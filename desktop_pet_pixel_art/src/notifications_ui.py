"""Notification history and category preferences window."""
import tkinter as tk
from tkinter import ttk

from notifications import NotificationCategory


class NotificationsUIMixin:
    def show_notifications(self):
        existing = getattr(self, "_notifications_window", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_set()
                    return existing
            except tk.TclError:
                pass
        window = self._set_nova_window_icon(tk.Toplevel(self.root))
        self._notifications_window = window
        window.title("Notificações da Nova")
        window.geometry("520x500")
        header = ttk.Frame(window, padding=14)
        header.pack(fill="x")
        ttk.Label(header, text=f"Notificações · {self.notification_manager.unread_count} não lidas",
                  style="Title.TLabel").pack(side="left")
        body = ttk.Frame(window, padding=(14, 0, 14, 14))
        body.pack(fill="both", expand=True)
        filters = ttk.Frame(body)
        filters.pack(fill="x", pady=(0, 8))
        category = tk.StringVar(value="Todas")
        options = ("Todas", *(item.value for item in NotificationCategory))
        ttk.Label(filters, text="Categoria:").pack(side="left")
        chooser = ttk.Combobox(filters, textvariable=category, values=options, state="readonly", width=18)
        chooser.pack(side="left", padx=6)
        enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(filters, text="Ativar categoria", variable=enabled).pack(side="left")
        listing = tk.Listbox(body, activestyle="none", bg="white", fg="#28334D",
                             relief="flat", font=("TkDefaultFont", 10))
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

        def set_category_enabled(*_args):
            if category.get() != "Todas":
                self.notification_manager.configure_category(category.get(), enabled.get())

        chooser.bind("<<ComboboxSelected>>", refill)
        enabled.trace_add("write", set_category_enabled)
        refill()
        actions = ttk.Frame(body)
        actions.pack(fill="x", pady=(10, 0))

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

        ttk.Button(actions, text="Marcar como lida",
                   command=lambda: update_and_reopen(self.notification_manager.mark_read)).pack(side="left")
        ttk.Button(actions, text="Descartar",
                   command=lambda: update_and_reopen(self.notification_manager.dismiss)).pack(side="left", padx=6)
        ttk.Button(actions, text="Limpar descartadas",
                   command=lambda: (self.notification_manager.clear_dismissible(), close_window(),
                                    self.show_notifications())).pack(side="left", padx=6)
        silent = tk.BooleanVar(value=self.notification_manager.silent)
        ttk.Checkbutton(actions, text="Modo silencioso", variable=silent,
                        command=lambda: self.notification_manager.set_silent(silent.get())).pack(side="right")
        return window
