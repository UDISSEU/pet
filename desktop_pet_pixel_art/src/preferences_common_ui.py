"""Reusable widgets shared by the preference tab builders."""

import tkinter as tk
from tkinter import ttk
from ui_theme import COLORS, make_empty_state


def setup_list(parent, items, format_item, empty_text):
    empty_state = make_empty_state(parent, empty_text)
    empty_state.pack(fill="x", pady=(0, 8))
    list_frame = ttk.Frame(parent, style="Card.TFrame", padding=1)
    list_frame.pack(fill="both", expand=True)
    listing = tk.Listbox(
        list_frame, height=10, activestyle="none", relief="flat", bd=0,
        highlightthickness=0, selectforeground=COLORS["ink"],
        bg=COLORS["surface"], fg=COLORS["ink"], font=("TkDefaultFont", 10),
        selectbackground=COLORS["surface_elevated"], selectmode="browse",
    )
    list_scrollbar = ttk.Scrollbar(
        list_frame, orient="horizontal", command=listing.xview,
    )
    listing.configure(xscrollcommand=list_scrollbar.set)
    # Keep the paired widgets reachable by filtered list renderers. The helper
    # still returns its historical three values for existing callers.
    listing._nova_empty_state = empty_state
    listing._nova_list_frame = list_frame
    listing.pack(fill="both", expand=True, padx=8, pady=(7, 0))
    list_scrollbar.pack(fill="x", padx=8, pady=(0, 7))

    def refresh():
        listing.delete(0, "end")
        if not items:
            empty_state.pack(fill="x", pady=(0, 8))
            list_frame.pack_forget()
            return
        empty_state.pack_forget()
        list_frame.pack(fill="both", expand=True)
        for item in items:
            listing.insert("end", format_item(item))

    def remove_selected():
        selected = listing.curselection()
        if selected:
            del items[selected[0]]
            refresh()

    refresh()
    return listing, refresh, remove_selected


def render_filtered_list(listing, items, format_item, predicate):
    """Render filtered rows and keep the list/empty-state layout in sync."""
    visible = [item for item in items if predicate(item)]
    listing.delete(0, "end")
    for item in visible:
        listing.insert("end", format_item(item))
    empty_state = listing._nova_empty_state
    list_frame = listing._nova_list_frame
    if visible:
        empty_state.pack_forget()
        list_frame.pack(fill="both", expand=True)
    else:
        list_frame.pack_forget()
        empty_state.pack(fill="x", pady=(0, 8))
    return visible
