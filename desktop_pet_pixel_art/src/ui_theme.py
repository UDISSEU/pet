"""Shared visual tokens for Nova's desktop panels."""

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


def make_header(parent, title, subtitle, *, eyebrow="NOVA  /  PAINEL"):
    """Build the compact navy header shared by top-level panels."""
    import tkinter as tk

    colors = COLORS
    header = tk.Frame(parent, bg=colors["navy"], padx=18, pady=11)
    header.pack(fill="x")
    tk.Label(
        header, text=eyebrow, bg=colors["navy"], fg=colors["teal"],
        font=("TkDefaultFont", 8, "bold"), anchor="w",
    ).pack(anchor="w")
    tk.Label(
        header, text=title, bg=colors["navy"], fg="#F7FAFC",
        font=("TkDefaultFont", 15, "bold"), anchor="w",
    ).pack(anchor="w", pady=(3, 0))
    tk.Label(
        header, text=subtitle, bg=colors["navy"], fg=colors["header_muted"],
        font=("TkDefaultFont", 9), anchor="w",
    ).pack(anchor="w", pady=(1, 0))
    return header
