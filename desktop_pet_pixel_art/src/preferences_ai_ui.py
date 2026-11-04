"""Builder for the preference tab content."""

import threading
import tkinter as tk
from tkinter import ttk
from autonomy import save_settings
from spotify_control import spotify_connected as spotify_token_connected


class AIPreferencesTabMixin:
    def _build_ai_preferences_tab(self, context):
        ai_content = getattr(context, 'ai_content', None)
        ai_provider = getattr(context, 'ai_provider', None)
        ai_timeout = getattr(context, 'ai_timeout', None)
        allow_online_data = getattr(context, 'allow_online_data', None)
        card = getattr(context, 'card', None)
        confirm_free_tier = getattr(context, 'confirm_free_tier', None)
        gemini_model = getattr(context, 'gemini_model', None)
        groq_model = getattr(context, 'groq_model', None)
        mistral_model = getattr(context, 'mistral_model', None)
        ollama_model = getattr(context, 'ollama_model', None)
        online_ai_enabled = getattr(context, 'online_ai_enabled', None)
        spotify_client_id = getattr(context, 'spotify_client_id', None)
        window = getattr(context, 'window', None)
        ai_provider_card = card(
            ai_content, "Provedor de conversa",
            "A Nova começa usando o Ollama local. Provedores online só recebem o histórico recente e memórias relacionadas depois que você habilitar o uso e autorizar o envio.",
        )
        ttk.Label(ai_provider_card, text="Provedor", style="Hint.TLabel").pack(anchor="w")
        ttk.Combobox(
            ai_provider_card, textvariable=ai_provider,
            values=("ollama", "gemini", "groq", "mistral"), state="readonly",
        ).pack(fill="x", pady=(3, 8))
        ttk.Checkbutton(
            ai_provider_card, text="Ativar provedor online selecionado",
            variable=online_ai_enabled,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            ai_provider_card,
            text="Autorizo enviar histórico recente e memórias relacionadas\nà pergunta ao provedor online",
            variable=allow_online_data,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            ai_provider_card,
            text="Confirmei no painel que minha chave usa modalidade gratuita\ne que a cobrança está desabilitada",
            variable=confirm_free_tier,
        ).pack(anchor="w", pady=2)
        ttk.Label(
            ai_provider_card,
            text="O teste verifica a chave e a disponibilidade do modelo sem enviar conversas. Chaves (nunca gravadas nas preferências): GEMINI_API_KEY, GROQ_API_KEY ou MISTRAL_API_KEY; o lançador também lê as três do cofre do sistema. Confira privacidade, limites e cobrança no painel do provedor.",
            style="Hint.TLabel", wraplength=400,
        ).pack(anchor="w", pady=(5, 8))
        test_row = ttk.Frame(ai_provider_card, style="Card.TFrame")
        test_row.pack(fill="x", pady=(0, 8))
        test_status = tk.StringVar(value="")
        test_button_state = {"running": False}
        test_button = ttk.Button(
            test_row, text="Testar conexão", style="Secondary.TButton",
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
            except ValueError:
                test_status.set("Informe um timeout entre 5 e 30 segundos.")
                return
            if not 5 <= timeout_value <= 30:
                test_status.set("Informe um timeout entre 5 e 30 segundos.")
                return
            provider_name = ai_provider.get()
            provider_settings = dict(self.settings)
            provider_settings.update(
                ai_provider=provider_name,
                ai_timeout=timeout_value,
                ollama_model=ollama_model.get().strip(),
                gemini_model=gemini_model.get().strip(),
                groq_model=groq_model.get().strip(),
                mistral_model=mistral_model.get().strip(),
            )
            test_button_state["running"] = True
            test_button.configure(state="disabled")
            test_status.set("Testando…")
            threading.Thread(
                target=self._provider_test_worker,
                args=(provider_name, provider_settings, window, test_status, test_button, test_button_state),
                daemon=True,
            ).start()

        test_button.configure(command=test_selected_provider)
        ttk.Label(ai_provider_card, text="Modelo Ollama", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ollama_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Modelo Gemini", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=gemini_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Modelo Groq", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=groq_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Modelo Mistral", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=mistral_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
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
            if not save_settings(updated):
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