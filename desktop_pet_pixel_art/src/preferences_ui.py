"""Preferences window and tab navigation for the desktop pet."""

import time
import tkinter as tk
from tkinter import messagebox, ttk
from autonomy import save_settings
from ui_theme import COLORS, make_header
from types import SimpleNamespace
from preferences_automation_ui import AutomationPreferencesTabMixin
from preferences_ai_ui import AIPreferencesTabMixin
from preferences_behavior_ui import BehaviorPreferencesTabMixin
from preferences_computer_ui import ComputerPreferencesTabMixin
from preferences_memory_ui import MemoryPreferencesTabMixin
from preferences_apps_ui import AppsPreferencesTabMixin


class PreferencesUIMixin(
    AutomationPreferencesTabMixin, AIPreferencesTabMixin,
    BehaviorPreferencesTabMixin, ComputerPreferencesTabMixin,
    MemoryPreferencesTabMixin, AppsPreferencesTabMixin,
):
    def open_autonomy_settings(self, selected_tab="behavior"):
        window = self._set_nova_window_icon(tk.Toplevel(self.root))
        window.title("Preferências da Nova")
        window.transient(self.root)
        window.attributes("-topmost", True)
        window.geometry("560x600")
        window.minsize(520, 550)
        window.configure(bg=COLORS["background"])
        self._activate_panel(window)
        make_header(
            window, "Preferências", "Personalize comportamento, rotina, memória e integrações.",
            eyebrow="NOVA  /  CONFIGURAÇÕES",
            back_command=lambda: self._panel_back(window),
        )

        style = ttk.Style(window)
        style.configure("Autonomy.TFrame", background=COLORS["background"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("Title.TLabel", background=COLORS["background"], foreground=COLORS["ink"], font=("TkDefaultFont", 14, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["background"], foreground=COLORS["muted"], font=("TkDefaultFont", 9))
        style.configure("CardTitle.TLabel", background=COLORS["surface"], foreground=COLORS["ink"], font=("TkDefaultFont", 10, "bold"))
        style.configure("Hint.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=("TkDefaultFont", 9))
        style.configure("PageHint.TLabel", background=COLORS["background"], foreground=COLORS["muted"], font=("TkDefaultFont", 9))
        style.configure("ComputerStatus.TLabel", background=COLORS["surface"], foreground=COLORS["ink"], font=("TkDefaultFont", 10, "bold"))
        style.configure("ComputerStatusError.TLabel", background=COLORS["surface"], foreground="#B42318", font=("TkDefaultFont", 10, "bold"))
        style.configure("ModeHint.TLabel", background=COLORS["surface"], foreground=COLORS["muted"], font=("TkDefaultFont", 8))
        style.configure("Primary.TButton", padding=(14, 8), font=("TkDefaultFont", 9, "bold"))
        style.configure("Secondary.TButton", padding=(12, 8))
        style.configure("Nav.TButton", padding=(4, 2))
        style.configure(
            "TabNav.TLabel", background=COLORS["background"], foreground=COLORS["ink"],
            font=("TkDefaultFont", 11, "bold"),
        )
        style.configure(
            "Maintenance.Treeview", background=COLORS["surface"], fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"], rowheight=28, borderwidth=0,
        )
        style.configure(
            "Maintenance.Treeview.Heading", background=COLORS["background"],
            foreground=COLORS["ink"], font=("TkDefaultFont", 9, "bold"),
        )
        style.configure(
            "History.Treeview", background=COLORS["surface"], fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"], rowheight=27, borderwidth=0,
        )
        style.configure(
            "History.Treeview.Heading", background=COLORS["background"],
            foreground=COLORS["ink"], font=("TkDefaultFont", 9, "bold"),
        )
        style.configure("Autonomy.TEntry", fieldbackground="#EDF0F5", foreground="#26344A", padding=4)

        outer = ttk.Frame(window, style="Autonomy.TFrame", padding=(16, 12, 16, 12))
        outer.pack(fill="both", expand=True)

        notebook = ttk.Frame(outer, style="Autonomy.TFrame")
        tab_navigation = ttk.Frame(outer, style="Autonomy.TFrame")
        tab_navigation.pack(fill="x", pady=(0, 6))
        tab_pages = []
        history_refresh_callback = {"callback": None}
        active_tab_index = 0
        active_tab_name = tk.StringVar(value="Comportamento")

        def select_tab(target):
            nonlocal active_tab_index
            if isinstance(target, int):
                index = target % len(tab_pages)
            else:
                index = next(i for i, (_name, page) in enumerate(tab_pages) if page is target)
            active_tab_index = index
            for i, (name, page) in enumerate(tab_pages):
                if i == index:
                    page.pack(fill="both", expand=True)
                    active_tab_name.set(name)
                    if name == "Histórico" and history_refresh_callback["callback"]:
                        history_refresh_callback["callback"]()
                else:
                    page.pack_forget()

        def register_tab(page, name):
            tab_pages.append((name, page))
            if len(tab_pages) == 1:
                select_tab(0)

        def move_tab(direction):
            select_tab(active_tab_index + direction)

        ttk.Button(
            tab_navigation, text="◀", width=2, style="Nav.TButton",
            command=lambda: move_tab(-1),
        ).pack(side="left")
        ttk.Label(
            tab_navigation, textvariable=active_tab_name, style="TabNav.TLabel",
        ).pack(side="left", expand=True, padx=8)
        ttk.Button(
            tab_navigation, text="▶", width=2, style="Nav.TButton",
            command=lambda: move_tab(1),
        ).pack(side="right")
        notebook.pack(fill="both", expand=True)
        def scrollable_tab():
            tab = ttk.Frame(notebook, style="Autonomy.TFrame")
            canvas = tk.Canvas(
                tab, bg=COLORS["background"], bd=0, highlightthickness=0,
                yscrollincrement=24,
            )
            scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            content = ttk.Frame(canvas, style="Autonomy.TFrame", padding=14)
            content_window = canvas.create_window((0, 0), window=content, anchor="nw")
            content.bind(
                "<Configure>",
                lambda _event, target=canvas: target.configure(scrollregion=target.bbox("all")),
            )
            canvas.bind(
                "<Configure>",
                lambda event, target=canvas, item=content_window:
                    target.itemconfigure(item, width=event.width),
            )

            def scroll_wheel(event, target=canvas):
                widget = event.widget
                while widget is not None:
                    if widget is target:
                        if getattr(event, "num", None) == 4:
                            target.yview_scroll(-3, "units")
                        elif getattr(event, "num", None) == 5:
                            target.yview_scroll(3, "units")
                        else:
                            delta = int(-event.delta / 120) if abs(event.delta) >= 120 else int(-event.delta)
                            if delta:
                                target.yview_scroll(delta * 3, "units")
                        return "break"
                    widget = getattr(widget, "master", None)
                return None

            canvas.bind_all("<MouseWheel>", scroll_wheel, add="+")
            canvas.bind_all("<Button-4>", scroll_wheel, add="+")
            canvas.bind_all("<Button-5>", scroll_wheel, add="+")
            return tab, content

        behavior_tab, behavior_content = scrollable_tab()
        routine_tab, routine_content = scrollable_tab()
        memory_tab, memory_content = scrollable_tab()
        history_tab, history_content = scrollable_tab()
        reminder_tab, reminder_content = scrollable_tab()
        apps_tab, apps_content = scrollable_tab()
        computer_tab, computer_content = scrollable_tab()
        automation_tab, automation_content = scrollable_tab()
        ai_tab, ai_content = scrollable_tab()
        register_tab(behavior_tab, "Comportamento")
        register_tab(routine_tab, "Foco e rotina")
        register_tab(memory_tab, "Memórias")
        register_tab(history_tab, "Histórico")
        register_tab(reminder_tab, "Lembretes")
        register_tab(apps_tab, "Aplicativos")
        register_tab(computer_tab, "Meu Computador")
        register_tab(automation_tab, "Automações")
        register_tab(ai_tab, "Inteligência artificial")

        context = SimpleNamespace(**locals())
        self._build_automation_preferences_tab(context)

        mode = tk.StringVar(value=self.settings.get("mode", "companhia"))
        quiet_start = tk.StringVar(value=self.settings.get("quiet_start", "22:00"))
        quiet_end = tk.StringVar(value=self.settings.get("quiet_end", "08:00"))
        focus_goal = tk.StringVar()
        focus_minutes = tk.StringVar(value=str(self.settings.get("focus_minutes", 25)))
        break_minutes = tk.StringVar(value=str(self.settings.get("break_minutes", 5)))
        routine_greeting = tk.BooleanVar(value=self.settings.get("routine_greeting", True))
        routine_context = tk.BooleanVar(value=self.settings.get("routine_context", True))
        routine_idle_yawn = tk.BooleanVar(value=self.settings.get("routine_idle_yawn", True))
        routine_focus_celebration = tk.BooleanVar(value=self.settings.get("routine_focus_celebration", True))
        routine_note = tk.BooleanVar(value=self.settings.get("routine_note", True))
        routine_surprise = tk.BooleanVar(value=self.settings.get("routine_surprise", True))
        routine_evening = tk.BooleanVar(value=self.settings.get("routine_evening", True))
        routine_dance = tk.BooleanVar(value=self.settings.get("routine_dance", True))
        routine_break_tip = tk.BooleanVar(value=self.settings.get("routine_break_tip", True))
        evening_time = tk.StringVar(value=self.settings.get("evening_time", "20:30"))
        speech = tk.BooleanVar(value=self.auto_speech_var.get())
        observe = tk.BooleanVar(value=self.observe_apps_var.get())
        announce_charger = tk.BooleanVar(value=self.settings.get("announce_charger", True))
        announce_usb = tk.BooleanVar(value=self.settings.get("announce_usb", True))
        humor_labels = {
            "tranquila": "Mais tranquila",
            "equilibrada": "Equilibrada",
            "brincalhona": "Mais brincalhona",
        }
        humor_style = tk.StringVar(
            value=humor_labels.get(
                self.settings.get("humor_style", "equilibrada"), "Equilibrada"
            )
        )
        auto_sit = tk.BooleanVar(value=self.auto_sit_var.get())
        peekaboo = tk.BooleanVar(value=self.peekaboo_var.get())
        confirm_app_launch = tk.BooleanVar(
            value=self.settings.get("confirm_app_launch", True)
        )
        ai_provider = tk.StringVar(value=self.settings.get("ai_provider", "ollama"))
        online_ai_enabled = tk.BooleanVar(value=self.settings.get("online_ai_enabled", False))
        allow_online_data = tk.BooleanVar(value=self.settings.get("allow_online_data", False))
        confirm_free_tier = tk.BooleanVar(value=self.settings.get("confirm_free_tier", False))
        ai_timeout = tk.StringVar(value=str(self.settings.get("ai_timeout", 30)))
        ollama_model = tk.StringVar(value=self.settings.get("ollama_model", "llama3.2:1b"))
        ollama_num_ctx = tk.StringVar(value=str(self.settings.get("ollama_num_ctx", 1024)))
        ollama_num_predict = tk.StringVar(value=str(self.settings.get("ollama_num_predict", 96)))
        ollama_num_threads = tk.StringVar(value=str(self.settings.get("ollama_num_threads", 1)))
        gemini_model = tk.StringVar(value=self.settings.get("gemini_model", "gemini-3.8-flash"))
        groq_model = tk.StringVar(value=self.settings.get("groq_model", "openai/gpt-oss-20b"))
        mistral_model = tk.StringVar(value=self.settings.get("mistral_model", "mistral-small-latest"))
        spotify_client_id = tk.StringVar(value=self.settings.get("spotify_client_id", ""))
        memory_items = list(self.settings.get("memories", []))
        reminder_items = list(self.settings.get("reminders", []))
        app_items = list(self.settings.get("apps", []))

        def card(parent, title, hint=None):
            frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
            frame.pack(fill="x", pady=(0, 12))
            ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
            if hint:
                ttk.Label(frame, text=hint, style="Hint.TLabel", wraplength=360).pack(anchor="w", pady=(3, 8))
            return frame

        context.__dict__.update(locals())
        self._build_ai_preferences_tab(context)

        self._build_behavior_preferences_tabs(context)
        self._build_computer_preferences_tab(context)

        self._build_memory_preferences_tabs(context)

        self._build_reminders_and_apps_preferences_tabs(context)
        def start_focus_from_settings():
            if self.focus_mode != "idle" or self.ai_request_active or self.dragging:
                context.focus_status.set("Não consigo iniciar outra sessão enquanto estou ocupada.")
                return
            try:
                duration = int(focus_minutes.get())
                pause = int(break_minutes.get())
            except ValueError:
                select_tab(routine_tab)
                messagebox.showerror("Duração inválida", "Informe durações em minutos.", parent=window)
                return
            if not 5 <= duration <= 180 or not 1 <= pause <= 60:
                select_tab(routine_tab)
                messagebox.showerror("Duração inválida", "Foco: 5–180 minutos. Pausa: 1–60 minutos.", parent=window)
                return
            save_and_close((focus_goal.get(), duration, pause))

        context.start_focus_from_settings = start_focus_from_settings

        footer = ttk.Frame(outer, style="Autonomy.TFrame")
        footer.pack(fill="x", pady=(14, 0))

        def save_and_close(focus_params=None):
            try:
                for value in (quiet_start.get(), quiet_end.get()):
                    time.strptime(value, "%H:%M")
            except ValueError:
                select_tab(behavior_tab)
                messagebox.showerror("Horário inválido", "Use HH:MM nos horários de silêncio.", parent=window)
                return
            try:
                duration = int(focus_minutes.get())
                pause = int(break_minutes.get())
                time.strptime(evening_time.get(), "%H:%M")
            except ValueError:
                select_tab(routine_tab)
                messagebox.showerror("Valor inválido", "Confira as durações e use HH:MM no horário de encerramento.", parent=window)
                return
            if not 5 <= duration <= 180 or not 1 <= pause <= 60:
                select_tab(routine_tab)
                messagebox.showerror("Duração inválida", "Foco: 5–180 minutos. Pausa: 1–60 minutos.", parent=window)
                return
            try:
                timeout_value = int(ai_timeout.get())
            except ValueError:
                select_tab(ai_tab)
                messagebox.showerror("Timeout inválido", "Informe um número entre 5 e 30 segundos.", parent=window)
                return
            if not 5 <= timeout_value <= 30:
                select_tab(ai_tab)
                messagebox.showerror("Timeout inválido", "Informe um número entre 5 e 30 segundos.", parent=window)
                return
            try:
                local_limits = {
                    "ollama_num_ctx": int(ollama_num_ctx.get()),
                    "ollama_num_predict": int(ollama_num_predict.get()),
                    "ollama_num_threads": int(ollama_num_threads.get()),
                }
            except ValueError:
                select_tab(ai_tab)
                messagebox.showerror("Limites locais inválidos", "Use números válidos para contexto, resposta e threads.", parent=window)
                return
            if not (512 <= local_limits["ollama_num_ctx"] <= 2048
                    and 16 <= local_limits["ollama_num_predict"] <= 256
                    and 1 <= local_limits["ollama_num_threads"] <= 2):
                select_tab(ai_tab)
                messagebox.showerror("Limites locais inválidos", "Contexto: 512–2048 tokens; resposta: 16–256; threads: 1–2.", parent=window)
                return
            updated = dict(self.settings)
            updated_automations = dict(updated.get("automations", {}))
            updated_automation_enabled = dict(updated_automations.get("enabled", {}))
            updated_automation_enabled["pause_reminder"] = routine_break_tip.get()
            updated_automations["enabled"] = updated_automation_enabled
            updated["automations"] = updated_automations
            updated.update(
                mode=mode.get(), quiet_start=quiet_start.get(), quiet_end=quiet_end.get(),
                humor_style={label: key for key, label in humor_labels.items()}[
                    humor_style.get()
                ],
                memories=memory_items, reminders=reminder_items, apps=app_items,
                confirm_app_launch=confirm_app_launch.get(),
                auto_speech=speech.get(), observe_apps=observe.get(), auto_sit=auto_sit.get(),
                announce_charger=announce_charger.get(), announce_usb=announce_usb.get(),
                peekaboo=peekaboo.get(),
                focus_minutes=duration, break_minutes=pause,
                routine_greeting=routine_greeting.get(),
                routine_context=routine_context.get(),
                routine_idle_yawn=routine_idle_yawn.get(),
                routine_focus_celebration=routine_focus_celebration.get(),
                routine_note=routine_note.get(),
                routine_surprise=routine_surprise.get(),
                routine_evening=routine_evening.get(), evening_time=evening_time.get(),
                routine_dance=routine_dance.get(),
                routine_break_tip=routine_break_tip.get(),
                ai_provider=ai_provider.get(), online_ai_enabled=online_ai_enabled.get(),
                allow_online_data=allow_online_data.get(),
                confirm_free_tier=confirm_free_tier.get(), ai_timeout=timeout_value,
                ollama_model=ollama_model.get().strip(),
                **local_limits,
                gemini_model=gemini_model.get().strip(), groq_model=groq_model.get().strip(),
                mistral_model=mistral_model.get().strip(),
                spotify_client_id=spotify_client_id.get().strip(),
            )
            if not save_settings(updated):
                messagebox.showerror("Erro ao salvar", "Não consegui salvar as preferências.", parent=window)
                return
            self.settings = updated
            self.auto_speech_var.set(speech.get())
            self.observe_apps_var.set(observe.get())
            self.auto_sit_var.set(auto_sit.get())
            self.peekaboo_var.set(peekaboo.get())
            window.destroy()
            if routine_greeting.get() and not self._routine_greeted:
                self.root.after(500, self.show_start_greeting)
            if routine_context.get():
                self.root.after(1000, self.show_context_greeting)
            if focus_params:
                self.start_focus(*focus_params)
            else:
                self.show_bubble("Preferências atualizadas.", duration=2500)

        ttk.Button(footer, text="Cancelar", style="Secondary.TButton", command=window.destroy).pack(side="right")
        ttk.Button(footer, text="Salvar alterações", style="Primary.TButton", command=save_and_close).pack(side="right", padx=(0, 8))
        if selected_tab == "routine":
            select_tab(routine_tab)
        elif selected_tab == "memory":
            select_tab(memory_tab)
        elif selected_tab == "reminder":
            select_tab(reminder_tab)
        elif selected_tab == "apps":
            select_tab(apps_tab)
        elif selected_tab == "computer":
            select_tab(computer_tab)
        elif selected_tab == "automation":
            select_tab(automation_tab)
        elif selected_tab == "ai":
            select_tab(ai_tab)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.bind("<Control-Return>", lambda _event: save_and_close())
