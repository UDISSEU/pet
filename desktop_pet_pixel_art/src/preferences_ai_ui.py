"""Builder for the preference tab content."""

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from autonomy import save_settings
from providers.ollama_provider import OllamaProvider
from spotify_control import spotify_connected as spotify_token_connected


class AIPreferencesTabMixin:
    def _build_ai_preferences_tab(self, context):
        ai_content = getattr(context, 'ai_content', None)
        ai_timeout = getattr(context, 'ai_timeout', None)
        card = getattr(context, 'card', None)
        ollama_model = getattr(context, 'ollama_model', None)
        ollama_num_ctx = getattr(context, 'ollama_num_ctx', None)
        ollama_num_predict = getattr(context, 'ollama_num_predict', None)
        ollama_num_threads = getattr(context, 'ollama_num_threads', None)
        spotify_client_id = getattr(context, 'spotify_client_id', None)
        window = getattr(context, 'window', None)
        ai_provider_card = card(
            ai_content, "Inferência local — Ollama",
            "A conversa usa somente o Ollama instalado neste computador. Sem o serviço ou o modelo, a Nova continua disponível para animações, rotinas, memórias e recursos locais.",
        )
        ttk.Label(
            ai_provider_card,
            text="A Nova não inicia o serviço nem baixa modelos automaticamente. O download só começa após sua confirmação.",
            style="Hint.TLabel", wraplength=400,
        ).pack(anchor="w", pady=(5, 8))
        pull_row = ttk.Frame(ai_provider_card, style="Card.TFrame")
        pull_row.pack(fill="x", pady=(0, 8))
        pull_status = tk.StringVar(value="")
        pull_state = {"running": False, "cancel_event": None}
        pull_button = ttk.Button(
            pull_row, text="Baixar modelo configurado", style="Secondary.TButton",
        )
        pull_button.pack(side="left")
        cancel_pull_button = ttk.Button(
            pull_row, text="Cancelar", style="Secondary.TButton", state="disabled",
        )
        cancel_pull_button.pack(side="left", padx=(6, 0))
        ttk.Label(pull_row, textvariable=pull_status, style="Hint.TLabel", wraplength=265).pack(
            side="left", fill="x", expand=True, padx=(8, 0),
        )
        pull_progress = ttk.Progressbar(ai_provider_card, mode="indeterminate")
        pull_progress.pack(fill="x", pady=(0, 8))

        def set_pull_status(text):
            try:
                if window.winfo_exists():
                    pull_status.set(text)
            except tk.TclError:
                return

        def finish_pull(result):
            pull_state["running"] = False
            pull_state["cancel_event"] = None
            try:
                if not window.winfo_exists():
                    return
                pull_progress.stop()
                pull_button.configure(state="normal")
                cancel_pull_button.configure(state="disabled")
                pull_status.set(result)
            except tk.TclError:
                return

        def update_pull_progress(status):
            message = status.get("status")
            completed = status.get("completed")
            total = status.get("total")
            if (
                isinstance(message, str)
                and isinstance(completed, int)
                and not isinstance(completed, bool)
                and completed >= 0
                and isinstance(total, int)
                and not isinstance(total, bool)
                and total > 0
            ):
                text = f"{message}: {completed * 100 // total}%"
            elif isinstance(message, str) and message:
                text = message[:160]
            else:
                text = "Baixando modelo…"
            set_pull_status(text)

        def pull_selected_model():
            if pull_state["running"]:
                return
            model = ollama_model.get().strip()
            try:
                OllamaProvider.validate_model_name(model)
                timeout_value = int(ai_timeout.get())
            except (TypeError, ValueError):
                pull_status.set("Informe um modelo válido e confira o timeout.")
                return
            if not 5 <= timeout_value <= 30:
                pull_status.set("Informe um timeout entre 5 e 30 segundos.")
                return
            confirmed = messagebox.askyesno(
                "Confirmar download do modelo",
                f"Baixar ou atualizar o modelo Ollama “{model}”?\n\n"
                "Isso exige conexão com a internet e pode consumir bastante dados e espaço em disco. "
                "Em computadores com pouca memória, prefira um modelo pequeno como o padrão 1B. "
                "O download não será iniciado se você escolher Não.",
                parent=window,
            )
            if not confirmed:
                return
            provider_settings = dict(self.settings)
            provider_settings.update(
                ai_provider="ollama",
                ai_timeout=timeout_value,
                ollama_model=model,
            )
            cancel_event = threading.Event()
            pull_state["running"] = True
            pull_state["cancel_event"] = cancel_event
            pull_button.configure(state="disabled")
            cancel_pull_button.configure(state="normal")
            pull_status.set("Conectando ao serviço Ollama local…")
            pull_progress.start(12)
            threading.Thread(
                target=self._ollama_pull_worker,
                args=(
                    provider_settings,
                    lambda status: self.post_ui_callback(update_pull_progress, status),
                    lambda result: self.post_ui_callback(finish_pull, result),
                    cancel_event,
                ),
                daemon=True,
                name="nova-ollama-model-pull",
            ).start()

        def cancel_model_pull():
            cancel_event = pull_state["cancel_event"]
            if cancel_event is None:
                return
            cancel_event.set()
            cancel_pull_button.configure(state="disabled")
            pull_status.set("Cancelando o download…")

        pull_button.configure(command=pull_selected_model)
        cancel_pull_button.configure(command=cancel_model_pull)

        test_row = ttk.Frame(ai_provider_card, style="Card.TFrame")
        test_row.pack(fill="x", pady=(0, 8))
        test_status = tk.StringVar(value="")
        test_button_state = {"running": False}
        test_button = ttk.Button(
            test_row, text="Testar conexão Ollama", style="Secondary.TButton",
        )
        test_button.pack(side="left")
        ttk.Label(test_row, textvariable=test_status, style="Hint.TLabel", wraplength=265).pack(
            side="left", fill="x", expand=True, padx=(8, 0),
        )

        def test_selected_provider():
            if test_button_state["running"]:
                return
            try:
                timeout_value = int(ai_timeout.get())
                local_limits = {
                    "ollama_num_ctx": int(ollama_num_ctx.get()),
                    "ollama_num_predict": int(ollama_num_predict.get()),
                    "ollama_num_threads": int(ollama_num_threads.get()),
                }
            except ValueError:
                test_status.set("Confira timeout e limites locais numéricos.")
                return
            if not 5 <= timeout_value <= 30:
                test_status.set("Informe um timeout entre 5 e 30 segundos.")
                return
            if not (512 <= local_limits["ollama_num_ctx"] <= 2048
                    and 16 <= local_limits["ollama_num_predict"] <= 256
                    and 1 <= local_limits["ollama_num_threads"] <= 2):
                test_status.set("Contexto: 512–2048; resposta: 16–256; threads: 1–2.")
                return
            provider_settings = dict(self.settings)
            provider_settings.update(
                ai_provider="ollama",
                ai_timeout=timeout_value,
                ollama_model=ollama_model.get().strip(),
                **local_limits,
            )
            test_button_state["running"] = True
            test_button.configure(state="disabled")
            test_status.set("Testando…")
            threading.Thread(
                target=self._provider_test_worker,
                args=("ollama", provider_settings, window, test_status, test_button, test_button_state),
                daemon=True,
            ).start()

        test_button.configure(command=test_selected_provider)
        ttk.Label(ai_provider_card, text="Modelo Ollama", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ollama_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Contexto Ollama (512–2048 tokens)", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ollama_num_ctx, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Resposta Ollama (16–256 tokens)", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ollama_num_predict, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Threads CPU Ollama (1–2; padrão 1)", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ollama_num_threads, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Timeout (5–30 segundos)", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ai_timeout, style="Autonomy.TEntry").pack(fill="x", pady=(2, 0))

        spotify_card = card(
            ai_content,
            "Spotify",
            "Para tocar uma música pelo nome, conecte sua conta: a Nova pesquisa pela API e envia a faixa ao player local. Para tocar playlist sem conectar a API, use o link dela. Adicionar faixas a playlists exige um app Spotify Developer Mode; o dono desse app precisa de Premium. Cadastre o Redirect URI http://127.0.0.1:8765/callback. A Nova usa PKCE e não pede Client Secret.",
        )
        ttk.Label(spotify_card, text="Client ID do app Spotify", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(
            spotify_card, textvariable=spotify_client_id, style="Autonomy.TEntry"
        ).pack(fill="x", pady=(3, 7))
        spotify_status = tk.StringVar(
            value=("Conta conectada." if spotify_token_connected(
                self.settings.get("spotify_client_id", "")
            ) else "Ainda não conectado.")
        )
        spotify_connect_button = ttk.Button(
            spotify_card, text="Conectar conta Spotify", style="Secondary.TButton",
        )
        spotify_connect_button.pack(anchor="w", pady=(0, 5))
        ttk.Label(
            spotify_card, textvariable=spotify_status, style="Hint.TLabel",
            wraplength=400,
        ).pack(anchor="w")
        self._spotify_status_var = spotify_status
        self._spotify_connect_button = spotify_connect_button

        def connect_spotify_account():
            client_id = spotify_client_id.get().strip()
            if not client_id:
                spotify_status.set("Cole o Client ID do seu app Spotify acima.")
                return
            updated = dict(self.settings)
            updated["spotify_client_id"] = client_id
            if not save_settings(updated, getattr(self, "settings_path", None)):
                spotify_status.set("Não consegui salvar as preferências.")
                return
            self.settings = updated
            spotify_connect_button.configure(state="disabled")
            spotify_status.set("Abrindo o Spotify para autorização…")
            threading.Thread(
                target=self._spotify_connect_worker,
                args=(client_id,), daemon=True,
            ).start()

        spotify_connect_button.configure(command=connect_spotify_account)
