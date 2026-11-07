"""Janela mensal simples do calendário local da Nova."""

import calendar
from datetime import date
import tkinter as tk
from ui_theme import COLORS, fit_window_to_screen, make_header

MONTH_NAMES = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)
WEEKDAY_NAMES = ("Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom")


def open_calendar_window(parent, *, on_back=None, on_open=None):
    today = date.today()
    shown_month = {"year": today.year, "month": today.month}

    window = tk.Toplevel(parent)
    window.title("Calendário")
    window.transient(parent)
    window.attributes("-topmost", True)
    window.configure(bg=COLORS["background"])

    make_header(
        window, "Calendário", "Consulte as datas sem sair da Nova.",
        eyebrow="NOVA  /  ORGANIZAÇÃO",
        back_command=(lambda: on_back(window)) if on_back else window.destroy,
    )
    if on_open:
        on_open(window)
    content = tk.Frame(window, padx=14, pady=12, bg=COLORS["background"])
    content.pack(fill="both", expand=True)
    header = tk.Frame(content, bg=COLORS["background"])
    header.pack(fill="x", pady=(0, 10))
    month_title = tk.Label(header, font=("TkDefaultFont", 12, "bold"),
                           bg=COLORS["background"], fg=COLORS["ink"])
    header.grid_columnconfigure(1, weight=1)
    month_title.grid(row=0, column=1, sticky="ew")
    days_frame = tk.Frame(content, bg=COLORS["background"])
    days_frame.pack()

    def shift_month(offset):
        month = shown_month["month"] + offset
        year = shown_month["year"]
        if month < 1:
            month, year = 12, year - 1
        elif month > 12:
            month, year = 1, year + 1
        shown_month.update(year=year, month=month)
        draw_month()

    tk.Button(header, text="‹", width=3, command=lambda: shift_month(-1)).grid(row=0, column=0)
    tk.Button(header, text="›", width=3, command=lambda: shift_month(1)).grid(row=0, column=2)

    def draw_month():
        month_title.configure(
            text=f"{MONTH_NAMES[shown_month['month'] - 1]} {shown_month['year']}"
        )
        for child in days_frame.winfo_children():
            child.destroy()

        for column, weekday in enumerate(WEEKDAY_NAMES):
            tk.Label(
                days_frame,
                text=weekday,
                width=4,
                fg=COLORS["muted"], bg=COLORS["background"],
                font=("TkDefaultFont", 9, "bold"),
            ).grid(row=0, column=column, pady=(0, 4))

        month_rows = calendar.Calendar(firstweekday=calendar.MONDAY).monthdayscalendar(
            shown_month["year"], shown_month["month"]
        )
        for row, week in enumerate(month_rows, start=1):
            for column, day in enumerate(week):
                is_today = (
                    day == today.day
                    and shown_month["month"] == today.month
                    and shown_month["year"] == today.year
                )
                tk.Label(
                    days_frame,
                    text=str(day) if day else "",
                    width=4,
                    padx=2,
                    pady=5,
                    bg=COLORS["accent"] if is_today else COLORS["surface"],
                    fg="white" if is_today else COLORS["ink"],
                    font=("TkDefaultFont", 10, "bold" if is_today else "normal"),
                ).grid(row=row, column=column, padx=1, pady=1)

    draw_month()
    fit_window_to_screen(window, 420, 420, min_width=360, min_height=380)
    return window
