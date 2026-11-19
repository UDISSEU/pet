"""AI conversation and provider workers for the desktop pet."""

import logging
import json
import queue
import random
import threading
import tkinter as tk
from tkinter import ttk
import time
from datetime import datetime

from ai.request_handler import (
    PROVIDER_FAILURE_MESSAGE,
    answer_request,
    conversation_context_for_request,
    conversation_history_is_enabled,
)
from config import MAX_HISTORY_MESSAGES
from event_bus import Event, EventType
from ollama_client import save_history
from aurova_ai.personality.speech import pick_line
from providers.base_provider import ProviderError
from providers.provider_factory import create_provider


class DesktopPetAIMixin:
    def _start_ai_progress(self, cancel_event):
        if not hasattr(self, "root") or getattr(self, "_closing", False):
            return
        try:
            dialog = self._set_aurova_window_icon(tk.Toplevel(self.root))
            dialog.title("Aurova · Respondendo")
            dialog.transient(self.root)
            dialog.resizable(False, False)
            ttk.Label(dialog, text="Aurova está pensando…", padding=(16, 14)).pack(fill="x")
            button = ttk.Button(dialog, text="Cancelar resposta")

            def request_cancel():
                cancel_event.set()
                button.configure(state="disabled", text="Cancelamento solicitado…")

            button.configure(command=request_cancel)
            button.pack(anchor="e", padx=12, pady=(0, 12))
            dialog.protocol("WM_DELETE_WINDOW", request_cancel)
            self._ai_progress_dialog = dialog
            self._ai_progress_cancel_button = button
        except (tk.TclError, AttributeError):
            logging.getLogger(__name__).debug("Janela de cancelamento indisponível")

    def _close_ai_progress(self):
        dialog = getattr(self, "_ai_progress_dialog", None)
        self._ai_progress_dialog = None
        self._ai_progress_cancel_button = None
        if dialog is not None:
            try:
                if dialog.winfo_exists():
                    dialog.destroy()
            except tk.TclError:
                pass

    def _operational_confirmation(self, call, cancel_event, permissions=(), timeout_seconds=90):
        completed = threading.Event()
        decision = {"value": "cancel"}
        try:
            queued = self.post_ui_callback(self._safe_show_operational_confirmation, call,
                                           decision, completed, permissions, timeout_seconds,
                                           cancel_event)
        except Exception:
            logging.getLogger(__name__).exception("Não foi possível agendar confirmação operacional")
            return "cancel"
        if not queued:
            return "cancel"
        deadline = time.monotonic() + max(0, min(float(timeout_seconds), 120))
        while not completed.wait(0.1):
            if cancel_event is not None and cancel_event.is_set():
                return "cancel"
            if getattr(self, "_closing", False):
                return "cancel"
            if time.monotonic() >= deadline:
                return "cancel"
        return decision["value"]

    def _safe_show_operational_confirmation(self, call, decision, completed,
                                            permissions=(), timeout_seconds=90,
                                            cancel_event=None):
        try:
            self._show_operational_confirmation(call, decision, completed,
                                                permissions, timeout_seconds, cancel_event)
        except Exception:
            logging.getLogger(__name__).exception("Falha ao abrir confirmação operacional")
            decision["value"] = "cancel"
            completed.set()

    def _show_operational_confirmation(self, call, decision, completed, permissions=(),
                                       timeout_seconds=90, cancel_event=None):
        """Render a call-specific authorization prompt on Tk's main thread."""
        if self._closing:
            completed.set()
            return
        integration = getattr(self, "aurova_integration", None)
        try:
            definition = integration.cognition.dispatcher.registry.get(call.name)
            description = definition.tool.description
            impact = json.dumps(call.arguments, ensure_ascii=False, indent=2)[:1400]
            reversible = "Reversível" if call.name in {"files.organize_downloads", "files.organize.undo"} else "Reversibilidade não garantida"
            risk = ("Consulta somente leitura; dados ficam sujeitos às permissões da ferramenta."
                    if definition.read_only else
                    "A ação altera dados ou estado e pode ter efeitos persistentes.")
        except Exception:
            description, impact, reversible, risk = "Ação operacional", "Detalhes indisponíveis", "Risco não determinado", "Não aprove se os detalhes não forem claros."
        dialog = self._set_aurova_window_icon(tk.Toplevel(self.root))
        dialog.title("Aurova · Confirmar ação")
        dialog.transient(self.root)
        dialog.resizable(False, False)
        pending_after_ids = []

        def schedule_dialog_callback(delay_ms, callback):
            after_id = dialog.after(delay_ms, callback)
            pending_after_ids.append(after_id)

        ttk.Label(dialog, text=f"Aurova solicita autorização para: {call.name}", padding=(14, 12, 14, 4)).pack(anchor="w")
        ttk.Label(dialog, text=description, wraplength=440, padding=(14, 2, 14, 6)).pack(anchor="w")
        permission_text = ("\nPermissões que serão concedidas: " + ", ".join(permissions)
                           if permissions else "")
        ttk.Label(dialog, text=f"Informações afetadas:\n{impact}\n\nImpacto: {risk}\n{reversible}{permission_text}\nA ação será revalidada pelo dispatcher.", wraplength=440, justify="left", padding=14).pack(anchor="w")
        buttons = ttk.Frame(dialog, padding=(10, 0, 10, 12))
        buttons.pack(fill="x")
        def finish(value):
            if completed.is_set():
                return
            decision["value"] = value
            completed.set()
            if getattr(self, "_active_operational_confirmation_finish", None) is finish:
                self._active_operational_confirmation_finish = None
            for after_id in pending_after_ids:
                try:
                    dialog.after_cancel(after_id)
                except tk.TclError:
                    pass
            pending_after_ids.clear()
            try:
                dialog.destroy()
            except tk.TclError:
                pass
        self._active_operational_confirmation_finish = finish
        ttk.Button(buttons, text="Aprovar", command=lambda: finish("approve")).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Negar", command=lambda: finish("deny")).pack(side="right", padx=6)
        ttk.Button(buttons, text="Cancelar", command=lambda: finish("cancel")).pack(side="right", padx=6)
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish("cancel"))
        schedule_dialog_callback(
            max(1, int(max(0, min(float(timeout_seconds), 120)) * 1000)),
            lambda: finish("cancel"),
        )
        if cancel_event is not None:
            def poll_request_cancellation():
                try:
                    if not dialog.winfo_exists() or completed.is_set():
                        return
                    if cancel_event.is_set():
                        finish("cancel")
                    else:
                        schedule_dialog_callback(50, poll_request_cancellation)
                except tk.TclError:
                    decision["value"] = "cancel"
                    completed.set()
            schedule_dialog_callback(50, poll_request_cancellation)

    def _cancel_operational_confirmation(self):
        finish = getattr(self, "_active_operational_confirmation_finish", None)
        if callable(finish):
            finish("cancel")

    def _ask_worker(self, history, memories=None, settings=None, user_name="", *, computer_context=None, cancel_event=None):
        event_bus = getattr(self, "event_bus", None)
        permissions = getattr(self, "permission_manager", None)
        request_settings = settings or self.settings
        cancel_event = cancel_event or getattr(self, "_ai_cancel", None)
        inference_lock = getattr(self, "_ai_inference_lock", None)
        if cancel_event is not None and cancel_event.is_set():
            if getattr(self, "_closing", False):
                return
            answer = "Solicitação cancelada; nenhuma ferramenta foi executada."
            if event_bus is not None:
                event_bus.post(Event(EventType.AI_RESPONSE_RECEIVED, {"answer": answer}))
            elif hasattr(self, "_ai_results"):
                self._ai_results.put(answer)
            return
        acquired = inference_lock.acquire(blocking=False) if inference_lock is not None else True
        if not acquired:
            self.post_ui_callback(
                self._show_answer,
                "Já estou respondendo a outra pergunta. Tente novamente em instantes.",
            )
            return
        if event_bus is not None:
            event_bus.post(Event(EventType.AI_REQUEST_STARTED, {}))
        try:
            if permissions is not None:
                self._authorize_core_action("ai.use")
                permissions.require("aurova.core", "ai.use")
            memory_enabled = request_settings.get("memory_enabled", True) is True
            if not memory_enabled:
                memories = []
            integration = getattr(self, "aurova_integration", None)
            if integration is not None:
                question = next((item.get("content", "") for item in reversed(history)
                                 if item.get("role") == "user"), "")
                integration.learn_from_interaction(question, request_settings)
                memories = integration.build_context(
                    question,
                    memories,
                    enabled=memory_enabled,
                )
                request_settings["aurova_personality_instructions"] = (
                    integration.personality_instructions(request_settings, question)
                )
            if computer_context is not None:
                from computer_consultant import consultant_context_memory
                memories = list(memories or ())
                memories.append(consultant_context_memory(computer_context))
                guardrails = (
                    "Nesta pergunta, responda sobre o computador usando os dados locais fornecidos. "
                    "Separe observações explícitas de hipóteses, explique limitações e diga claramente "
                    "quando faltarem dados. Não invente valores. Sugira passos seguros; não solicite "
                    "nem execute ações administrativas ou destrutivas sem autorização explícita. "
                    "Mantenha a personalidade acolhedora da Aurova."
                )
                base_personality = str(request_settings.get("aurova_personality_instructions", ""))
                request_settings["aurova_personality_instructions"] = (
                    base_personality[:max(0, 4_000 - len(guardrails) - 2)]
                    + "\n\n" + guardrails
                )
            request_history = conversation_context_for_request(history, request_settings)
            from aurova_ai.operational_loop import classify_request, run_operational_loop
            request_text = next((item.get("content", "") for item in reversed(request_history)
                                 if item.get("role") == "user"), "")
            classification = classify_request(
                request_text,
                cognitive_classifier=(integration.cognition.classifier if integration is not None else None),
            )
            category = classification.category
            if category == "unsupported":
                answer = (
                    "Essa capacidade não está disponível na Aurova. Posso conversar e usar apenas "
                    "as ferramentas locais que aparecem no catálogo autorizado."
                )
            elif (category == "conversation" or category == "ambiguous"
                  or classification.requires_clarification
                  or integration is None or integration.cognition.dispatcher is None):
                if category == "ambiguous" or classification.requires_clarification:
                    current = str(request_settings.get("aurova_personality_instructions", ""))
                    request_settings["aurova_personality_instructions"] = (
                        current[:3_000] + "\n\nO pedido operacional está ambíguo ou incompleto. "
                        "Faça uma pergunta curta de esclarecimento e não solicite ferramentas nesta resposta."
                    )
                answer = answer_request(
                    request_history, memories=memories, settings=request_settings,
                    user_name=user_name, cancel_event=cancel_event,
                )
            else:
                from ai.ai_core import AICore
                core = AICore(settings=request_settings)
                messages, prompt = core.prepare_request(
                    request_history, memories=memories, user_name=user_name,
                )
                prompt += (
                    "\n\nA solicitação foi classificada como consulta ou tarefa. Use somente as ferramentas "
                    "listadas quando forem necessárias. Tool calls são propostas; não afirme conclusão "
                    "sem resultado bem-sucedido do dispatcher. Na continuação, mensagens role=tool são "
                    "os resultados efetivos: use os valores exatamente como retornados, nunca substitua "
                    "o resultado pelos argumentos da chamada e não invente valores ausentes. Se o estado "
                    "indicar falha ou o conteúdo disser que não há dados, informe isso claramente."
                )
                answer = run_operational_loop(
                    router=core.router, messages=messages, system_prompt=prompt,
                    tools=integration.operational_tool_schemas(),
                    dispatcher=integration.cognition.dispatcher,
                    confirm=lambda call, **kwargs: self._operational_confirmation(
                        call, cancel_event, kwargs.get("permissions", ()),
                        kwargs.get("timeout_seconds", 90)),
                    permission_manager=permissions,
                    cancel_event=cancel_event,
                )
        except ProviderError as exc:
            from providers.base_provider import ProviderCancelled
            if isinstance(exc, ProviderCancelled) or (cancel_event is not None and cancel_event.is_set()):
                answer = "Solicitação cancelada durante a inferência; nenhuma nova ferramenta foi executada."
            else:
                logging.getLogger(__name__).info("Consulta de IA não concluída (%s)", type(exc).__name__)
                answer = PROVIDER_FAILURE_MESSAGE
        except Exception:
            logging.getLogger(__name__).exception("Falha inesperada no serviço de IA")
            answer = PROVIDER_FAILURE_MESSAGE
        finally:
            if inference_lock is not None:
                inference_lock.release()
        if cancel_event is not None and cancel_event.is_set():
            answer = "Solicitação cancelada; nenhuma nova ferramenta foi executada."
        if event_bus is not None:
            if answer == PROVIDER_FAILURE_MESSAGE:
                event_bus.post(Event(EventType.AI_REQUEST_FAILED, {"error": answer}))
            event_bus.post(Event(EventType.AI_RESPONSE_RECEIVED, {"answer": answer}))
        elif hasattr(self, "_ai_results"):
            self._ai_results.put(answer)

    def _provider_test_worker(
        self, provider_name, settings, window, status_var, button, button_state
    ):
        try:
            provider = create_provider(provider_name, settings)
            result = provider.test_connection(timeout=min(15, settings.get("ai_timeout", 10)))
        except ProviderError as exc:
            result = str(exc)
        except Exception:
            logging.getLogger(__name__).exception("Falha inesperada no teste do provedor de IA")
            result = "O teste de conexão falhou por um erro inesperado."
        self._provider_test_results.put((window, status_var, button, result, button_state))

    def _ollama_pull_worker(self, settings, on_progress, on_complete, cancel_event):
        try:
            provider = create_provider("ollama", settings)
            result = provider.pull_model(
                on_progress=on_progress,
                cancel_event=cancel_event,
            )
        except ProviderError as exc:
            result = str(exc)
        except Exception:
            logging.getLogger(__name__).exception("Falha inesperada ao baixar modelo Ollama")
            result = "O download do modelo falhou por um erro inesperado."
        on_complete(result)

    def _drain_provider_test_results(self):
        try:
            window, status_var, button, result, button_state = self._provider_test_results.get_nowait()
        except queue.Empty:
            return
        button_state["running"] = False
        try:
            if window.winfo_exists():
                status_var.set(result)
                button.configure(state="normal")
        except tk.TclError:
            pass

    def _drain_ai_results(self):
        """Compatibility hook; worker responses arrive through EventBus."""

    def _show_answer(self, answer):
        if self._closing:
            return
        self.ai_request_active = False
        self._close_ai_progress()
        self.history.append({
            "role": "assistant", "content": answer,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        history_saved = (
            not conversation_history_is_enabled(self.settings)
            or save_history(self.history, self.history_path)
        )
        failed = (answer == PROVIDER_FAILURE_MESSAGE
                  or answer.startswith(("Já estou respondendo a outra pergunta",
                                        "Tive um problema ao consultar a IA")))
        action_id = getattr(self, "_pending_computer_action_id", None)
        if action_id is not None:
            history_store = getattr(self, "computer_action_history", None)
            if history_store is not None:
                try:
                    history_store.update(
                        action_id, "Falhou" if failed else "Concluída",
                        result="O provedor não respondeu." if failed else "Resposta enviada à conversa da Aurova.",
                        error_code=("conversation_busy" if answer.startswith("Já estou respondendo")
                                    else "provider_unavailable") if failed else None,
                    )
                except Exception:
                    logging.getLogger(__name__).exception("Não foi possível atualizar o histórico do consultor")
            self._pending_computer_action_id = None
        focus_mode = getattr(self, "focus_mode", "idle")
        if focus_mode == "focus":
            self.state = "focused"
        elif focus_mode == "break":
            self.state = "sitting"
        else:
            self.state = "curious" if failed else "walk"
        self._show_idea_icon = True
        if failed and focus_mode == "idle":
            answer = pick_line(
                "oops", name=self.settings.get("user_name", ""),
                rng=random, history=self._speech_history,
            )
            self._schedule_pose_callback(3500, "curious", self.finish_curious)
        words = max(len(answer.split()), 1)
        duration = min(max(6000, words * 400), 30000)
        if history_saved:
            self.show_bubble(answer, duration=duration)
        else:
            self.show_bubble(
                f"{answer}\n\nNão consegui salvar o histórico.",
                duration=duration,
            )
