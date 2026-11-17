"""Tkinter menu, calendar, and preferences UI for the desktop pet."""

import time
import tkinter as tk
from tkinter import ttk

from autonomy import save_settings
from calendar_view import open_calendar_window
from config import WIDTH
from dashboard_ui import DashboardUIMixin
from notifications_ui import NotificationsUIMixin
from permissions_ui import PermissionsUIMixin
from preferences_ui import PreferencesUIMixin
from ui_theme import COLORS, PanelNavigationMixin, make_aurora_mark, make_header


class DesktopPetUIMixin(PreferencesUIMixin, PanelNavigationMixin, DashboardUIMixin, NotificationsUIMixin, PermissionsUIMixin):
    def show_menu(self, event):
        self._last_user_activity_at = time.monotonic()
        self._last_menu_position = (event.x_root, event.y_root)
        if self._context_popup is not None:
            try:
                self._context_popup.destroy()
            except tk.TclError:
                pass

        popup = tk.Toplevel(self.root)
        self._context_popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg=COLORS["border"])
        self._activate_panel(popup)

        panel = tk.Frame(popup, bg=COLORS["background"], padx=7, pady=7,
                         highlightthickness=1, highlightbackground=COLORS["border"])
        panel.pack(fill="both", expand=True)
        title_bar = tk.Frame(panel, bg=COLORS["navy"], padx=9, pady=7)
        title_bar.pack(fill="x", padx=1, pady=(0, 6))
        make_aurora_mark(title_bar, size=24, background=COLORS["navy"]).pack(
            side="left", padx=(0, 7),
        )
        title_copy = tk.Frame(title_bar, bg=COLORS["navy"], cursor="fleur")
        title_copy.pack(side="left", fill="x", expand=True, padx=2, pady=1)
        title_label = tk.Label(
            title_copy, text="Painel Principal da Aurova", font=("TkDefaultFont", 10, "bold"),
            fg=COLORS["ink"], bg=COLORS["navy"], anchor="w", cursor="fleur",
        )
        title_label.pack(anchor="w")
        tk.Label(
            title_copy, text="Atalhos, rotina e preferências", font=("TkDefaultFont", 8),
            fg=COLORS["muted"], bg=COLORS["navy"], anchor="w", cursor="fleur",
        ).pack(anchor="w", pady=(1, 0))
        tk.Button(
            title_bar, text="×", command=lambda: close_popup(),
            relief="flat", bd=0, padx=5, pady=0, cursor="hand2",
            font=("TkDefaultFont", 11, "bold"), fg=COLORS["header_muted"],
            bg=COLORS["navy"], activebackground=COLORS["surface_elevated"],
        ).pack(side="right")

        drag_offset = {"x": 0, "y": 0}

        def start_popup_drag(drag_event):
            drag_offset["x"] = drag_event.x_root - popup.winfo_x()
            drag_offset["y"] = drag_event.y_root - popup.winfo_y()

        def move_popup(drag_event):
            screen_width = popup.winfo_screenwidth()
            screen_height = popup.winfo_screenheight()
            x = drag_event.x_root - drag_offset["x"]
            y = drag_event.y_root - drag_offset["y"]
            x = max(0, min(x, screen_width - popup.winfo_width()))
            y = max(0, min(y, screen_height - popup.winfo_height()))
            popup.geometry(f"+{x}+{y}")

        for drag_handle in (title_bar, title_copy, title_label):
            drag_handle.bind("<ButtonPress-1>", start_popup_drag)
            drag_handle.bind("<B1-Motion>", move_popup)

        def close_popup():
            if popup.winfo_exists():
                popup.destroy()
            if self._context_popup is popup:
                self._context_popup = None

        def hide_popup():
            if popup.winfo_exists():
                popup.withdraw()

        popup.bind("<Escape>", lambda _event: (close_popup(), "break")[1])

        action_grid = tk.Frame(panel, bg=COLORS["background"])
        action_grid.pack(fill="x", pady=(0, 2))
        action_grid.grid_columnconfigure(0, weight=1, uniform="menu_action")
        action_grid.grid_columnconfigure(1, weight=1, uniform="menu_action")

        def action_button(label, command, row, column, primary=False):
            bg = COLORS["accent"] if primary else COLORS["surface"]
            fg = COLORS["background"] if primary else COLORS["ink"]
            hover = COLORS["focus"] if primary else COLORS["border"]
            button = tk.Button(
                action_grid, text=label, anchor="w", command=lambda: (hide_popup(), command()),
                relief="flat", bd=0, padx=10, pady=7, cursor="hand2",
                bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                font=("TkDefaultFont", 9, "bold" if primary else "normal"),
            )
            button.grid(row=row, column=column, sticky="ew", padx=2, pady=2)
            return button

        action_button("✦  Conversar", self.ask_menu, 0, 0, primary=True)
        action_button("▦  Calendário", self.show_calendar, 0, 1)
        action_button("▤  Painel da Aurova", self.show_dashboard, 1, 0)
        action_button("♧  Notificações", self.show_notifications, 1, 1)
        action_button("⏱  Foco e rotina", lambda: self.open_autonomy_settings("routine"), 2, 0)
        action_button("⚙  Preferências", self.open_autonomy_settings, 2, 1)

        more = tk.Frame(panel, bg=COLORS["background"])
        expanded = {"value": False}

        def fit_popup_to_screen():
            popup.update_idletasks()
            screen_width = popup.winfo_screenwidth()
            screen_height = popup.winfo_screenheight()
            width = max(popup.winfo_width(), popup.winfo_reqwidth())
            height = max(popup.winfo_height(), popup.winfo_reqheight())
            x = max(0, min(popup.winfo_x(), screen_width - width))
            y = max(0, min(popup.winfo_y(), screen_height - height))
            popup.geometry(f"+{x}+{y}")

        def toggle_more():
            if expanded["value"]:
                more.pack_forget()
                more_button.configure(text="Mostrar mais  ▾")
            else:
                more.pack(fill="x", pady=(5, 0))
                more_button.configure(text="Mostrar menos  ▴")
            expanded["value"] = not expanded["value"]
            fit_popup_to_screen()

        more_button = tk.Button(
            panel, text="Mostrar mais  ▾", command=toggle_more, anchor="w",
            relief="flat", bd=0, padx=8, pady=5, cursor="hand2",
            bg=COLORS["surface_elevated"], fg=COLORS["muted"], activebackground=COLORS["border"],
        )
        more_button.pack(fill="x", pady=(4, 0))

        def section_label(parent, label):
            tk.Label(
                parent, text=label.upper(), anchor="w", padx=6, pady=4,
                bg=COLORS["background"], fg=COLORS["muted"],
                font=("TkDefaultFont", 8, "bold"),
            ).pack(fill="x", pady=(3, 0))

        def more_action(label, command):
            tk.Button(
                more, text=label, anchor="w",
                command=lambda: (hide_popup(), command()), relief="flat", bd=0,
                padx=8, pady=4, cursor="hand2", bg=COLORS["surface"], fg=COLORS["ink"],
                activebackground=COLORS["border"],
            ).pack(fill="x", pady=1)

        section_label(more, "Interação")
        more_action("Falar algo", self.say_something)
        more_action("Permissões", self.open_permissions)

        behavior_group = tk.Frame(more, bg=COLORS["background"])
        behavior_group.pack(fill="x", pady=(4, 0))
        behavior_section = tk.Frame(behavior_group, bg=COLORS["background"])
        behavior_expanded = {"value": False}

        def toggle_behavior():
            if behavior_expanded["value"]:
                behavior_section.pack_forget()
                behavior_button.configure(text="Comportamento  ▾")
            else:
                behavior_section.pack(fill="x", pady=(1, 2))
                behavior_button.configure(text="Comportamento  ▴")
            behavior_expanded["value"] = not behavior_expanded["value"]

        behavior_button = tk.Button(
            behavior_group, text="Comportamento  ▾", command=toggle_behavior, anchor="w",
            relief="flat", bd=0, padx=8, pady=5, cursor="hand2",
            bg=COLORS["surface_elevated"], fg=COLORS["muted"], activebackground=COLORS["border"],
        )
        behavior_button.pack(fill="x")

        def check_option(label, variable, command=None):
            tk.Checkbutton(
                behavior_section, text=label, variable=variable, command=command,
                anchor="w", padx=6, pady=2, bg=COLORS["background"], fg=COLORS["ink"],
                activebackground=COLORS["background"], selectcolor=COLORS["surface"],
                font=("TkDefaultFont", 8),
            ).pack(fill="x")

        check_option("Andar atrás das janelas", self.behind_var, self.toggle_behind_mode)
        check_option("Ficar parada aqui", self.stay_in_place_var, self.persist_preferences)
        check_option("Falas espontâneas", self.auto_speech_var, self.persist_preferences)
        check_option("Comentários sobre apps", self.observe_apps_var, self.persist_preferences)
        check_option("Sumir atrás das janelas", self.peekaboo_var, self.toggle_peekaboo)
        check_option("Sentar em janelas", self.auto_sit_var, self.toggle_auto_sit)
        section_label(more, "Manutenção")
        more_action("Diagnóstico do sistema", self.show_diagnostics)
        more_action("Esquecer conversa", self.forget_history)
        more_action("Apagar memórias salvas", self.forget_memories)
        more_action("Fechar Aurova", self.close_app)

        popup.update_idletasks()
        screen_w = popup.winfo_screenwidth()
        screen_h = popup.winfo_screenheight()
        x = min(event.x_root, max(0, screen_w - popup.winfo_reqwidth()))
        y = min(event.y_root, max(0, screen_h - popup.winfo_reqheight()))
        popup.geometry(f"+{x}+{y}")
        popup.focus_force()
        try:
            popup.attributes("-alpha", 0.0)

            def fade_in(step=0):
                if not popup.winfo_exists():
                    return
                alpha = min(1.0, (step + 1) / 7)
                try:
                    popup.attributes("-alpha", alpha)
                except tk.TclError:
                    return
                if alpha < 1.0:
                    popup.after(14, lambda: fade_in(step + 1))

            popup.after(14, fade_in)
        except tk.TclError:
            # Alguns gerenciadores de janelas não oferecem transparência gradual.
            pass
        return "break"

    def show_diagnostics(self):
        from diagnostics_ui import open_diagnostics_window

        return open_diagnostics_window(
            self.root,
            on_open_ai=lambda: self.open_autonomy_settings("ai"),
            on_back=lambda window: self._panel_back(window),
            on_open=self._activate_panel,
            memory_checker=(
                self.aurova_integration.memory_health
                if self.aurova_integration is not None else None
            ),
            integration_error=getattr(self, "_aurova_integration_error", None),
        )

    def show_calendar(self):
        return open_calendar_window(
            self.root, on_back=lambda window: self._panel_back(window),
            on_open=self._activate_panel,
        )

    def _question_dialog_geometry(self, dialog_width=420, dialog_height=280):
        gap = 8
        pet_left = int(round(self.x))
        pet_right = pet_left + WIDTH
        available_left = max(0, pet_left - gap)
        available_right = max(0, self.screen_w - pet_right - gap)
        width = min(dialog_width, max(1, self.screen_w - 32))
        if available_right >= width:
            x = pet_right + gap
        elif available_left >= width:
            x = pet_left - gap - width
        else:
            pet_center = (pet_left + pet_right) // 2
            x = pet_center - width // 2
            x = max(16, min(x, self.screen_w - width - 16))

        if width < 360:
            dialog_height = max(dialog_height, 280)
        height = min(dialog_height, self.screen_h)
        y = int(round(self.y + (self.cur_height - height) / 2))
        y = max(0, min(y, self.screen_h - height))
        return x, y, width, height

    def _ask_question(self):
        dialog = self._set_aurova_window_icon(tk.Toplevel(self.root))
        dialog.title("Perguntar à Aurova")
        dialog.configure(bg=COLORS["background"])
        dialog.transient(self.root)
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        x, y, width, height = self._question_dialog_geometry()
        dialog.geometry(f"{width}x{height}+{x}+{y}")

        result = {"question": None}
        background = COLORS["background"]
        content = tk.Frame(dialog, bg=background, padx=18, pady=16)
        content.pack(fill="both", expand=True)
        prompt_heading = tk.Frame(content, bg=background)
        prompt_heading.pack(fill="x")
        make_aurora_mark(prompt_heading, size=32, background=background).pack(
            side="left", padx=(0, 10),
        )
        prompt_copy = tk.Frame(prompt_heading, bg=background)
        prompt_copy.pack(side="left", fill="x", expand=True)
        tk.Label(
            prompt_copy, text="Converse com a Aurova",
            font=("TkDefaultFont", 13, "bold"), fg=COLORS["ink"], bg=background,
        ).pack(anchor="w")
        tk.Label(
            prompt_copy, text="Escreva sua pergunta abaixo",
            font=("TkDefaultFont", 9), fg=COLORS["muted"], bg=background,
        ).pack(anchor="w", pady=(3, 10))

        editor_border = tk.Frame(content, bg=COLORS["border"], padx=1, pady=1)
        editor_border.pack(fill="both", expand=True)
        answer = tk.Text(
            editor_border,
            height=4,
            wrap="word",
            undo=True,
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            font=("TkDefaultFont", 10),
            fg=COLORS["ink"],
            bg=COLORS["surface"],
            insertbackground=COLORS["cyan"],
        )
        answer.pack(fill="both", expand=True)

        buttons = tk.Frame(content, bg=background)
        buttons.pack(fill="x", pady=(12, 0))

        def finish():
            question = answer.get("1.0", "end-1c").strip()
            if not question:
                answer.focus_set()
                return
            result["question"] = question
            dialog.destroy()

        def cancel():
            dialog.destroy()

        cancel_button = ttk.Button(
            buttons,
            text="Cancelar",
            command=cancel,
            style="Quiet.TButton",
        )
        ask_button = ttk.Button(
            buttons,
            text="Perguntar",
            command=finish,
            style="Primary.TButton",
        )
        if width < 360:
            ask_button.pack(fill="x", pady=(0, 6))
            cancel_button.pack(fill="x")
        else:
            cancel_button.pack(side="right")
            ask_button.pack(side="right", padx=(0, 6))
        dialog.protocol("WM_DELETE_WINDOW", cancel)
        dialog.bind("<Control-Return>", lambda _event: finish())
        dialog.bind("<Escape>", lambda _event: cancel())
        dialog.grab_set()
        answer.focus_force()
        self.root.wait_window(dialog)
        return result["question"]

    def persist_preferences(self):
        self.settings.update(
            mode=self.settings.get("mode", "companhia"),
            behind=self.behind_var.get(),
            stay_in_place=self.stay_in_place_var.get(),
            auto_speech=self.auto_speech_var.get(),
            observe_apps=self.observe_apps_var.get(),
            peekaboo=self.peekaboo_var.get(),
            auto_sit=self.auto_sit_var.get(),
        )
        save_settings(self.settings, getattr(self, "settings_path", None))
