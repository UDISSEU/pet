"""Tkinter menu, calendar, and preferences UI for the desktop pet."""

import time
import tkinter as tk

from autonomy import save_settings
from calendar_view import open_calendar_window
from dashboard_ui import DashboardUIMixin
from notifications_ui import NotificationsUIMixin
from permissions_ui import PermissionsUIMixin
from preferences_ui import PreferencesUIMixin
from ui_theme import COLORS, PanelNavigationMixin, make_header


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
        title_label = tk.Label(
            title_bar, text="Painel Principal da Nova", font=("TkDefaultFont", 10, "bold"),
            fg="#F7FAFC", bg=COLORS["navy"], anchor="w", cursor="fleur",
        )
        title_label.pack(side="left", fill="x", expand=True, padx=2, pady=2)
        tk.Button(
            title_bar, text="×", command=lambda: close_popup(),
            relief="flat", bd=0, padx=5, pady=0, cursor="hand2",
            font=("TkDefaultFont", 11, "bold"), fg=COLORS["header_muted"],
            bg=COLORS["navy"], activebackground="#263B56",
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

        for drag_handle in (title_bar, title_label):
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
            fg = "#FFFFFF" if primary else COLORS["ink"]
            hover = "#3473CF" if primary else "#E6EDF5"
            button = tk.Button(
                action_grid, text=label, anchor="w", command=lambda: (hide_popup(), command()),
                relief="flat", bd=0, padx=8, pady=5, cursor="hand2",
                bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
                font=("TkDefaultFont", 9, "bold" if primary else "normal"),
            )
            button.grid(row=row, column=column, sticky="ew", padx=2, pady=2)
            return button

        action_button("✦  Conversar", self.ask_menu, 0, 0, primary=True)
        action_button("▦  Calendário", self.show_calendar, 0, 1)
        action_button("▤  Painel da Nova", self.show_dashboard, 1, 0)
        action_button("♧  Notificações", self.show_notifications, 1, 1)
        action_button("⏱  Foco e rotina", lambda: self.open_autonomy_settings("routine"), 2, 0)
        action_button("⚙  Preferências", self.open_autonomy_settings, 2, 1)

        more = tk.Frame(panel, bg=COLORS["background"])
        expanded = {"value": False}

        def toggle_more():
            if expanded["value"]:
                more.pack_forget()
                more_button.configure(text="Mostrar mais  ▾")
            else:
                more.pack(fill="x", pady=(5, 0))
                more_button.configure(text="Mostrar menos  ▴")
            expanded["value"] = not expanded["value"]

        more_button = tk.Button(
            panel, text="Mostrar mais  ▾", command=toggle_more, anchor="w",
            relief="flat", bd=0, padx=8, pady=5, cursor="hand2",
            bg="#E5EBF3", fg=COLORS["muted"], activebackground="#D9E2EE",
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
                activebackground="#E6EDF5",
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
            bg="#E5EBF3", fg=COLORS["muted"], activebackground="#D9E2EE",
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
        more_action("Esquecer conversa", self.forget_history)
        more_action("Apagar memórias salvas", self.forget_memories)
        more_action("Fechar Nova", self.close_app)

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
    def show_calendar(self):
        return open_calendar_window(
            self.root, on_back=lambda window: self._panel_back(window),
            on_open=self._activate_panel,
        )
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
