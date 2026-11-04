"""Reusable widgets shared by the preference tab builders."""

import tkinter as tk
from tkinter import ttk


def setup_list(parent, items, format_item, empty_text):
    ttk.Label(parent, text=empty_text, style="PageHint.TLabel").pack(
        anchor="w", pady=(0, 8)
    )
    list_frame = ttk.Frame(parent, style="Card.TFrame", padding=1)
    list_frame.pack(fill="both", expand=True)
    listing = tk.Listbox(
        list_frame, height=10, activestyle="none", relief="flat", bd=0,
        highlightthickness=0, selectforeground="#202B45",
        bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 10),
        selectbackground="#C7D2EE", selectmode="browse",
    )
    list_scrollbar = ttk.Scrollbar(
        list_frame, orient="horizontal", command=listing.xview,
    )
    listing.configure(xscrollcommand=list_scrollbar.set)
    listing.pack(fill="both", expand=True, padx=8, pady=(7, 0))
    list_scrollbar.pack(fill="x", padx=8, pady=(0, 7))

    def refresh():
        listing.delete(0, "end")
        for item in items:
            listing.insert("end", format_item(item))

    def remove_selected():
        selected = listing.curselection()
        if selected:
            del items[selected[0]]
            refresh()

    refresh()
    return listing, refresh, remove_selected
