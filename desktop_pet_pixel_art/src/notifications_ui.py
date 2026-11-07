"""Notification history and category preferences window."""
import tkinter as tk
from tkinter import ttk

from notifications import NotificationCategory
from ui_theme import COLORS, fit_window_to_screen, make_header


class NotificationsUIMixin:
    def show_notifications(self):
        existing = getattr(self, "_notifications_window", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_set()
                    self._activate_panel(existing)
                    return existing
            except tk.TclError:
                pass
        window = self._set_nova_window_icon(tk.Toplevel(self.root))
        self._notifications_window = window
        self._activate_panel(window)
        window.title("Notificações da Nova")
        fit_window_to_screen(
            window, 560, 540, min_width=500, min_height=380, vertical_margin=16,
        )
        window.configure(bg=COLORS["background"])
        make_header(window, "Notificações", "Acompanhe avisos e ajuste como a Nova se comunica.",
                    eyebrow="NOVA  /  CENTRAL DE AVISOS",
                    back_command=lambda: self._panel_back(window))
        body = tk.Frame(window, bg=COLORS["background"], padx=14, pady=8)
        body.pack(fill="both", expand=True)
        filters = tk.Frame(body, bg=COLORS["surface"], padx=10, pady=5,
                            highlightbackground=COLORS["border"], highlightthickness=1)
        filters.pack(fill="x", pady=(0, 8))
        category = tk.StringVar(value="Todas")
        options = ("Todas", *(item.value for item in NotificationCategory))
        tk.Label(filters, text="Categoria", bg=COLORS["surface"], fg=COLORS["muted"],
                 font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0, sticky="w")
        chooser = ttk.Combobox(filters, textvariable=category, values=options, state="readonly", width=18)
        chooser.grid(row=0, column=1, sticky="ew", padx=6)
        unread_badge = tk.Label(
            filters, text=f"{self.notification_manager.unread_count} não lidas",
            bg=COLORS["surface"], fg=COLORS["muted"],
            font=("TkDefaultFont", 9, "bold"), anchor="e",
        )
        unread_badge.grid(row=0, column=2, sticky="e")
        enabled = tk.BooleanVar(value=True)
        enabled_control = ttk.Checkbutton(filters, text="Ativar categoria", variable=enabled)
        enabled_control.grid(row=1, column=0, sticky="w", pady=(5, 0))
        filters.grid_columnconfigure(1, weight=1)
        silent = tk.BooleanVar(value=self.notification_manager.silent)
        ttk.Checkbutton(
            filters, text="Modo silencioso", variable=silent,
            command=lambda: self.notification_manager.set_silent(silent.get()),
        ).grid(row=1, column=1, sticky="w", pady=(5, 0))
        list_card = tk.Frame(body, bg=COLORS["surface"], padx=7, pady=7,
                             highlightbackground=COLORS["border"], highlightthickness=1)
        listing = tk.Listbox(list_card, activestyle="none", bg=COLORS["surface"], fg=COLORS["ink"],
                             selectbackground="#DCE9FA", selectforeground=COLORS["ink"],
                             relief="flat", borderwidth=0, font=("TkDefaultFont", 10),
                             highlightthickness=0, selectmode="browse")
        listing.pack(fill="both", expand=True)
        active = []

        def refill(*_args):
            nonlocal active
            selected_category = category.get()
            active = self.notification_manager.filtered(
                None if selected_category == "Todas" else selected_category
            )
            listing.delete(0, "end")
            for item in active:
                listing.insert("end", f"{'●' if not item.read else '○'} [{item.category.value}] {item.title} — {item.message}")
            enabled.set(True if selected_category == "Todas" else
                        self.notification_manager.categories.get(selected_category, True))
            unread_badge.configure(text=f"{self.notification_manager.unread_count} não lidas")

        def set_category_enabled(*_args):
            if category.get() != "Todas":
                self.notification_manager.configure_category(category.get(), enabled.get())

        chooser.bind("<<ComboboxSelected>>", refill)
        enabled.trace_add("write", set_category_enabled)
        refill()
        actions = ttk.Frame(body)
        actions.pack(fill="x", side="bottom", pady=(10, 0))
        action_buttons = ttk.Frame(actions)
        action_buttons.pack(fill="x")

        def selected():
            selection = listing.curselection()
            return active[selection[0]] if selection else None

        def update_and_reopen(action):
            item = selected()
            if item:
                action(item.notification_id)
                close_window()
                self.show_notifications()

        def close_window():
            if getattr(self, "_notifications_window", None) is window:
                self._notifications_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_window)

        mark_read_button = ttk.Button(
            action_buttons, text="Marcar como lida",
            command=lambda: update_and_reopen(self.notification_manager.mark_read),
        )
        dismiss_button = ttk.Button(
            action_buttons, text="Descartar",
            command=lambda: update_and_reopen(self.notification_manager.dismiss),
        )
        clear_button = ttk.Button(
            action_buttons, text="Limpar descartadas",
            command=lambda: (self.notification_manager.clear_dismissible(), close_window(),
                             self.show_notifications()),
        )

        def arrange_action_buttons(event):
            for button in (mark_read_button, dismiss_button, clear_button):
                button.pack_forget()
                button.grid_forget()
            if event.width < 400:
                action_buttons.columnconfigure(0, weight=1, uniform="notification_action")
                action_buttons.columnconfigure(1, weight=1, uniform="notification_action")
                mark_read_button.grid(row=0, column=0, sticky="ew", padx=(0, 3), pady=(0, 4))
                dismiss_button.grid(row=0, column=1, sticky="ew", padx=(3, 0), pady=(0, 4))
                clear_button.grid(row=1, column=0, columnspan=2, sticky="ew")
            else:
                mark_read_button.pack(side="left")
                dismiss_button.pack(side="left", padx=6)
                clear_button.pack(side="left", padx=6)

        action_buttons.bind("<Configure>", arrange_action_buttons)
        list_card.pack(fill="both", expand=True)
        return window
