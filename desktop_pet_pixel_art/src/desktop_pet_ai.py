"""AI conversation and provider workers for the desktop pet."""

import logging
import queue
import random
import tkinter as tk
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
from nova_ai.personality.speech import pick_line
from providers.base_provider import ProviderError
from providers.provider_factory import create_provider


class DesktopPetAIMixin:
    def _ask_worker(self, history, memories=None, settings=None, user_name=""):
        event_bus = getattr(self, "event_bus", None)
        permissions = getattr(self, "permission_manager", None)
        request_settings = settings or self.settings
        cancel_event = getattr(self, "_ai_cancel", None)
        inference_lock = getattr(self, "_ai_inference_lock", None)
        if cancel_event is not None and cancel_event.is_set():
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
                permissions.require("nova.core", "ai.use")
            memory_enabled = request_settings.get("memory_enabled", True) is True
            if not memory_enabled:
                memories = []
            integration = getattr(self, "nova_integration", None)
            if integration is not None:
                question = next((item.get("content", "") for item in reversed(history)
                                 if item.get("role") == "user"), "")
                integration.learn_from_interaction(question, request_settings)
                memories = integration.build_context(
                    question,
                    memories,
                    enabled=memory_enabled,
                )
                request_settings["nova_personality_instructions"] = (
                    integration.personality_instructions(request_settings, question)
                )
            request_history = conversation_context_for_request(history, request_settings)
            answer = answer_request(
                request_history, memories=memories, settings=request_settings,
                user_name=user_name,
            )
        except Exception:
            logging.getLogger(__name__).exception("Falha inesperada no serviço de IA")
            answer = PROVIDER_FAILURE_MESSAGE
        finally:
            if inference_lock is not None:
                inference_lock.release()
        if cancel_event is not None and cancel_event.is_set():
            return
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
        self.history.append({
            "role": "assistant", "content": answer,
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        })
        self.history = self.history[-MAX_HISTORY_MESSAGES:]
        history_saved = (
            not conversation_history_is_enabled(self.settings)
            or save_history(self.history, self.history_path)
        )
        failed = answer == PROVIDER_FAILURE_MESSAGE
        self.state = "curious" if failed else "walk"
        self._show_idea_icon = True
        if failed:
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
