"""Shared visual tokens for Nova's desktop panels."""

from types import SimpleNamespace

COLORS = {
    "ink": "#18263A",
    "muted": "#718096",
    "background": "#F2F5F9",
    "surface": "#FFFFFF",
    "border": "#E2E8F0",
    "navy": "#17263B",
    "teal": "#75D8CC",
    "header_muted": "#B8C5D6",
    "accent": "#4386E8",
}


def make_header(parent, title, subtitle, *, eyebrow="NOVA  /  PAINEL", back_command=None):
    """Build the compact navy header shared by top-level panels."""
    import tkinter as tk

    colors = COLORS
    header = tk.Frame(parent, bg=colors["navy"], padx=18, pady=11)
    header.pack(fill="x")
    topline = tk.Frame(header, bg=colors["navy"])
    topline.pack(fill="x")
    tk.Label(
        topline, text=eyebrow, bg=colors["navy"], fg=colors["teal"],
        font=("TkDefaultFont", 8, "bold"), anchor="w",
    ).pack(side="left")
    if back_command:
        tk.Button(
            topline, text="← Voltar", command=back_command,
            relief="flat", bd=0, padx=9, pady=3, cursor="hand2",
            bg="#263B56", fg="#F7FAFC", activebackground="#344D6B",
            activeforeground="#FFFFFF", font=("TkDefaultFont", 9, "bold"),
        ).pack(side="right")
    tk.Label(
        header, text=title, bg=colors["navy"], fg="#F7FAFC",
        font=("TkDefaultFont", 15, "bold"), anchor="w",
    ).pack(anchor="w", pady=(3, 0))
    tk.Label(
        header, text=subtitle, bg=colors["navy"], fg=colors["header_muted"],
        font=("TkDefaultFont", 9), anchor="w",
    ).pack(anchor="w", pady=(1, 0))
    return header


class PanelNavigationMixin:
    """Small back stack for Nova's top-level windows."""

    def _activate_panel(self, window):
        if not hasattr(self, "_panel_history"):
            self._panel_history = []
        active = getattr(self, "_active_panel_window", None)
        if active is window:
            return
        if active is not None:
            try:
                if active.winfo_exists():
                    self._panel_history = [
                        item for item in self._panel_history if item is not active
                    ]
                    self._panel_history.append(active)
            except Exception:
                pass
        self._active_panel_window = window
        if not getattr(window, "_nova_navigation_bound", False):
            window._nova_navigation_bound = True
            window.bind("<Destroy>", lambda event, target=window: self._panel_destroyed(event, target), add="+")

    def _panel_destroyed(self, event, window):
        if event.widget is window and getattr(self, "_active_panel_window", None) is window:
            self._active_panel_window = None

    def _panel_back(self, window):
        if getattr(window, "_nova_back_in_progress", False):
            return
        window._nova_back_in_progress = True
        if getattr(self, "_active_panel_window", None) is window:
            self._active_panel_window = None
        try:
            if window.winfo_exists():
                window.destroy()
        except Exception:
            pass

        history = getattr(self, "_panel_history", [])
        while history:
            previous = history.pop()
            if callable(previous):
                previous()
                return
            try:
                if previous.winfo_exists():
                    previous.deiconify()
                    previous.lift()
                    previous.focus_set()
                    self._active_panel_window = previous
                    return
            except Exception:
                continue
        position = getattr(self, "_last_menu_position", None)
        if position is not None:
            self.show_menu(SimpleNamespace(x_root=position[0], y_root=position[1]))
