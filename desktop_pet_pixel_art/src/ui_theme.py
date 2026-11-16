"""Nova Aurora design tokens and reusable Tk/ttk building blocks."""

from types import SimpleNamespace


# Keep named values in one place. Legacy aliases let older panels migrate gradually.
COLORS = {
    "background": "#111827",
    "background_secondary": "#151F30",
    "surface": "#1B273A",
    "surface_elevated": "#233249",
    "border": "#344258",
    "ink": "#F2F5FA",
    "muted": "#A8B4C7",
    "disabled": "#69778C",
    "purple": "#A78BFA",
    "cyan": "#72D6CE",
    "gold": "#F2BC75",
    "success": "#7CCCA4",
    "warning": "#F2BC75",
    "error": "#E77787",
    "info": "#79BDEB",
    "focus": "#C4B5FD",
    "track": "#303D52",
    "header_muted": "#A8B4C7",
    # Compatibility aliases for existing UI modules.
    "navy": "#151F30",
    "accent": "#A78BFA",
    "teal": "#72D6CE",
    "blue": "#79BDEB",
    "violet": "#A78BFA",
    "amber": "#F2BC75",
}

SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RADIUS = {"sm": 6, "md": 9, "lg": 12}  # Tk has no native corner radius; custom canvas only.
FONTS = {
    "eyebrow": ("TkDefaultFont", 8, "bold"),
    "title": ("TkDefaultFont", 16, "bold"),
    "section": ("TkDefaultFont", 11, "bold"),
    "body": ("TkDefaultFont", 10),
    "small": ("TkDefaultFont", 9),
    "tiny": ("TkDefaultFont", 8),
}


def apply_theme(root, *, style=None):
    """Install the shared Nova Aurora ttk styles on the UI thread."""
    from tkinter import ttk

    if style is None:
        style = ttk.Style(root)
    try:
        if "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    c = COLORS
    style.configure(".", background=c["background"], foreground=c["ink"],
                    font=FONTS["body"])
    style.configure("TFrame", background=c["background"])
    style.configure("Aurora.TFrame", background=c["background"])
    style.configure("Autonomy.TFrame", background=c["background"])
    style.configure("Card.TFrame", background=c["surface"])
    style.configure("Elevated.Card.TFrame", background=c["surface_elevated"])
    style.configure("TLabel", background=c["background"], foreground=c["ink"])
    style.configure("Title.TLabel", background=c["background"], foreground=c["ink"],
                    font=("TkDefaultFont", 14, "bold"))
    style.configure("Subtitle.TLabel", background=c["background"], foreground=c["muted"],
                    font=FONTS["small"])
    style.configure("CardTitle.TLabel", background=c["surface"], foreground=c["ink"],
                    font=("TkDefaultFont", 10, "bold"))
    style.configure("Hint.TLabel", background=c["surface"], foreground=c["muted"],
                    font=FONTS["small"])
    style.configure("Eyebrow.TLabel", background=c["background"], foreground=c["cyan"],
                    font=FONTS["eyebrow"])
    style.configure("Section.TLabel", background=c["background"], foreground=c["ink"],
                    font=FONTS["section"])
    style.configure("PageHint.TLabel", background=c["background"], foreground=c["muted"],
                    font=FONTS["small"])
    style.configure("Primary.TButton", padding=(14, 8), background=c["purple"],
                    foreground=c["background"], font=("TkDefaultFont", 9, "bold"))
    style.map("Primary.TButton", background=[("disabled", c["track"]),
                                              ("pressed", c["focus"]),
                                              ("active", c["focus"])],
              foreground=[("disabled", c["disabled"])])
    style.configure("Secondary.TButton", padding=(12, 8), background=c["surface_elevated"],
                    foreground=c["ink"])
    style.map("Secondary.TButton", background=[("pressed", c["border"]),
                                                ("active", c["border"])])
    style.configure("Quiet.TButton", padding=(8, 5), background=c["background_secondary"],
                    foreground=c["muted"])
    style.configure("Destructive.TButton", padding=(12, 8), background=c["error"],
                    foreground=c["background"])
    style.configure("Nav.TButton", padding=(7, 4), background=c["surface_elevated"],
                    foreground=c["ink"])
    style.map("Nav.TButton", background=[("active", c["border"])])
    style.configure("Nav.Active.TButton", padding=(7, 4), background=c["purple"],
                    foreground=c["background"], font=("TkDefaultFont", 9, "bold"))
    style.map("Nav.Active.TButton", background=[("active", c["focus"])])
    style.configure("TEntry", fieldbackground=c["surface_elevated"],
                    foreground=c["ink"], insertcolor=c["ink"], padding=6)
    style.configure("Autonomy.TEntry", fieldbackground=c["surface_elevated"],
                    foreground=c["ink"], padding=6)
    style.configure("TCombobox", fieldbackground=c["surface_elevated"],
                    foreground=c["ink"], padding=5, arrowcolor=c["cyan"])
    style.map("TCombobox", fieldbackground=[("readonly", c["surface_elevated"])],
              foreground=[("readonly", c["ink"])])
    style.configure("TabNav.TCombobox", fieldbackground=c["surface_elevated"],
                    foreground=c["ink"], padding=(10, 7),
                    font=("TkDefaultFont", 10, "bold"), arrowcolor=c["cyan"])
    style.map("TabNav.TCombobox", fieldbackground=[("readonly", c["surface_elevated"])],
              foreground=[("readonly", c["ink"])])
    style.configure("TCheckbutton", background=c["background"], foreground=c["ink"])
    style.map("TCheckbutton", background=[("active", c["background"])])
    style.configure("TNotebook", background=c["background"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(12, 8), background=c["surface"],
                    foreground=c["muted"])
    style.map("TNotebook.Tab", background=[("selected", c["surface_elevated"])],
              foreground=[("selected", c["ink"])])
    style.configure("Treeview", background=c["surface"], fieldbackground=c["surface"],
                    foreground=c["ink"], rowheight=30, borderwidth=0)
    style.map("Treeview", background=[("selected", c["surface_elevated"])],
              foreground=[("selected", c["ink"])])
    style.configure("Treeview.Heading", background=c["background_secondary"],
                    foreground=c["muted"], font=("TkDefaultFont", 9, "bold"), padding=7)
    style.map("Treeview.Heading", background=[("active", c["surface_elevated"])])
    style.configure("Horizontal.TProgressbar", troughcolor=c["track"],
                    background=c["cyan"], bordercolor=c["track"], lightcolor=c["cyan"],
                    darkcolor=c["cyan"])
    style.configure("TLabelframe", background=c["surface"], foreground=c["ink"],
                    bordercolor=c["border"], relief="flat", padding=8)
    style.configure("TLabelframe.Label", background=c["surface"], foreground=c["cyan"],
                    font=("TkDefaultFont", 9, "bold"))
    style.configure("TScrollbar", background=c["surface_elevated"], troughcolor=c["background"],
                    bordercolor=c["background"], arrowcolor=c["muted"])
    style.map("TScrollbar", background=[("active", c["border"])])
    style.configure("Status.Success.TLabel", background=c["surface"], foreground=c["success"])
    style.configure("Status.Warning.TLabel", background=c["surface"], foreground=c["warning"])
    style.configure("Status.Error.TLabel", background=c["surface"], foreground=c["error"])
    return style


def make_card(parent, *, padding=16, elevated=False, tk_widget=False):
    """Create a shared card surface for either ttk or classic Tk children."""
    if tk_widget:
        import tkinter as tk
        color = COLORS["surface_elevated"] if elevated else COLORS["surface"]
        return tk.Frame(parent, bg=color, padx=padding, pady=padding,
                        highlightbackground=COLORS["border"], highlightthickness=1)
    from tkinter import ttk
    return ttk.Frame(parent, style="Elevated.Card.TFrame" if elevated else "Card.TFrame",
                     padding=padding)


def make_aurora_mark(parent, *, size=34, background=None):
    """Draw Nova's small static orbital glyph; no image assets or animation needed."""
    import tkinter as tk
    background = background or COLORS["background_secondary"]
    mark = tk.Canvas(parent, width=size, height=size, bg=background,
                     highlightthickness=0, bd=0)
    inset = max(4, size * 0.18)
    mark.create_oval(inset, inset, size - inset, size - inset,
                     outline=COLORS["border"], width=1)
    mark.create_arc(inset + 1, inset + 1, size - inset - 1, size - inset - 1,
                    start=28, extent=138, style="arc", outline=COLORS["cyan"], width=2)
    mark.create_arc(inset + 1, inset + 1, size - inset - 1, size - inset - 1,
                    start=208, extent=112, style="arc", outline=COLORS["purple"], width=2)
    center = size / 2
    radius = max(2, size * 0.09)
    mark.create_oval(center - radius, center - radius, center + radius, center + radius,
                     fill=COLORS["gold"], outline="")
    return mark


def make_metric_card(parent, title, accent, *, padding=10, with_bar=True):
    """Build a compact overview metric card and return its live value widgets."""
    import tkinter as tk
    frame = make_card(parent, padding=padding, tk_widget=True)
    tk.Label(frame, text=title.upper(), bg=COLORS["surface"], fg=COLORS["muted"],
             font=FONTS["eyebrow"], anchor="w").pack(fill="x")
    value = tk.StringVar(master=frame, value="—")
    tk.Label(frame, textvariable=value, bg=COLORS["surface"], fg=COLORS["ink"],
             font=("TkDefaultFont", 18, "bold"), anchor="w").pack(fill="x", pady=(2, 0))
    detail = tk.StringVar(master=frame, value="Coletando dados")
    tk.Label(frame, textvariable=detail, bg=COLORS["surface"], fg=COLORS["muted"],
             font=FONTS["small"], anchor="w").pack(fill="x")
    bar = None
    if with_bar:
        bar = tk.Canvas(frame, height=5, bg=COLORS["track"], highlightthickness=0, bd=0)
        bar.pack(fill="x", pady=(8, 0))
    return frame, value, detail, bar, accent


def make_status_badge(parent, textvariable, *, background=None, foreground=None):
    """Create a compact badge for a live or persistent state."""
    import tkinter as tk
    return tk.Label(parent, textvariable=textvariable,
                    bg=background or COLORS["surface_elevated"],
                    fg=foreground or COLORS["cyan"],
                    font=FONTS["eyebrow"], padx=10, pady=6)


def make_empty_state(parent, title, description=None):
    """Present an empty list with a small identity marker and clear explanation."""
    import tkinter as tk
    frame = tk.Frame(parent, bg=COLORS["surface"], padx=16, pady=16)
    mark = make_aurora_mark(frame, size=28, background=COLORS["surface"])
    mark.pack(side="left", padx=(0, 12))
    copy = tk.Frame(frame, bg=COLORS["surface"])
    copy.pack(side="left", fill="x", expand=True)
    tk.Label(copy, text=title, bg=COLORS["surface"], fg=COLORS["ink"],
             font=("TkDefaultFont", 10, "bold"), anchor="w", justify="left",
             wraplength=390).pack(fill="x")
    if description:
        tk.Label(copy, text=description, bg=COLORS["surface"], fg=COLORS["muted"],
                 font=FONTS["small"], anchor="w", justify="left", wraplength=420).pack(
                     fill="x", pady=(3, 0))
    return frame


def make_section_heading(parent, title, subtitle=None):
    """Create a consistently spaced section heading and optional helper text."""
    from tkinter import ttk
    frame = ttk.Frame(parent, style="Aurora.TFrame")
    ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w")
    if subtitle:
        ttk.Label(frame, text=subtitle, style="PageHint.TLabel").pack(anchor="w", pady=(4, 0))
    return frame


def make_search_field(parent, variable=None, *, width=32):
    """Return a themed search row, its StringVar, and the keyboard-ready entry."""
    import tkinter as tk
    from tkinter import ttk
    row = ttk.Frame(parent, style="Aurora.TFrame")
    ttk.Label(row, text="⌕", foreground=COLORS["cyan"],
              style="PageHint.TLabel").pack(side="left", padx=(0, SPACING["sm"]))
    variable = variable or tk.StringVar(master=parent)
    entry = ttk.Entry(row, textvariable=variable, width=width)
    entry.pack(side="left", fill="x", expand=True)
    return row, variable, entry


def make_status_indicator(parent, text, level="info"):
    """Create a compact status message using a semantic state color."""
    from tkinter import ttk
    style_name = {
        "success": "Status.Success.TLabel",
        "warning": "Status.Warning.TLabel",
        "error": "Status.Error.TLabel",
    }.get(level, "PageHint.TLabel")
    return ttk.Label(parent, text=text, style=style_name, wraplength=480, padding=(8, 6))


def show_dialog(parent, title, message, *, actions=(("OK", True),), destructive=False):
    """Show a small modal Nova Aurora dialog and return the chosen action value."""
    import tkinter as tk
    from tkinter import ttk

    if not actions:
        raise ValueError("O diálogo precisa oferecer ao menos uma ação.")

    result = {"value": None}
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.transient(parent)
    dialog.configure(bg=COLORS["background"])
    dialog.resizable(False, False)
    header = tk.Frame(dialog, bg=COLORS["background_secondary"], padx=SPACING["lg"],
                      pady=SPACING["md"])
    header.pack(fill="x")
    tk.Label(header, text=title, bg=COLORS["background_secondary"], fg=COLORS["ink"],
             font=FONTS["section"], anchor="w", wraplength=420, justify="left").pack(fill="x")
    body = tk.Frame(dialog, bg=COLORS["background"], padx=SPACING["lg"], pady=SPACING["lg"])
    body.pack(fill="both", expand=True)
    tk.Label(body, text=message, bg=COLORS["background"], fg=COLORS["muted"],
             font=FONTS["body"], anchor="w", justify="left", wraplength=420).pack(fill="x")
    controls = ttk.Frame(body, style="Aurora.TFrame")
    controls.pack(fill="x", pady=(SPACING["lg"], 0))

    def choose(value):
        result["value"] = value
        dialog.destroy()

    for index, (label, value) in enumerate(actions):
        style = "Destructive.TButton" if destructive and index == len(actions) - 1 else (
            "Primary.TButton" if index == len(actions) - 1 else "Secondary.TButton"
        )
        ttk.Button(controls, text=label, style=style,
                   command=lambda selected=value: choose(selected)).pack(
                       side="right", padx=(SPACING["sm"], 0))
    dialog.protocol("WM_DELETE_WINDOW", lambda: choose(None))
    dialog.bind("<Escape>", lambda _event: choose(None))
    dialog.bind("<Return>", lambda _event: choose(actions[-1][1]))
    dialog.update_idletasks()
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - dialog.winfo_width()) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - dialog.winfo_height()) // 2)
    dialog.geometry(f"+{x}+{y}")
    dialog.grab_set()
    dialog.wait_window()
    return result["value"]


def make_header(parent, title, subtitle, *, eyebrow="NOVA  /  PAINEL", back_command=None):
    """Build the compact Nova Aurora header shared by top-level panels."""
    import tkinter as tk

    c = COLORS
    header = tk.Frame(parent, bg=c["background_secondary"], padx=SPACING["lg"], pady=SPACING["md"])
    header.pack(fill="x")
    topline = tk.Frame(header, bg=c["background_secondary"])
    topline.pack(fill="x")
    tk.Label(topline, text=eyebrow, bg=c["background_secondary"], fg=c["cyan"],
             font=FONTS["eyebrow"], anchor="w").pack(side="left")
    if back_command:
        tk.Button(topline, text="← Voltar", command=back_command, relief="flat", bd=0,
                  padx=9, pady=3, cursor="hand2", bg=c["surface_elevated"], fg=c["ink"],
                  activebackground=c["border"], activeforeground=c["ink"],
                  font=FONTS["small"]).pack(side="right")
    title_row = tk.Frame(header, bg=c["background_secondary"])
    title_row.pack(fill="x", pady=(6, 0))
    make_aurora_mark(title_row, size=36, background=c["background_secondary"]).pack(
        side="left", padx=(0, SPACING["md"]), pady=(1, 0))
    copy = tk.Frame(title_row, bg=c["background_secondary"])
    copy.pack(side="left", fill="x", expand=True)
    tk.Label(copy, text=title, bg=c["background_secondary"], fg=c["ink"],
             font=FONTS["title"], anchor="w").pack(anchor="w")
    tk.Label(copy, text=subtitle, bg=c["background_secondary"], fg=c["muted"],
             font=FONTS["small"], anchor="w").pack(anchor="w", pady=(1, 0))
    return header


def fit_window_to_screen(
    window, width, height, *, min_width=480, min_height=360, vertical_margin=48,
):
    """Size and center a resizable panel without exceeding the available display."""
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    width = max(320, min(width, screen_width - 32))
    height = max(240, min(height, screen_height - vertical_margin))
    window.resizable(True, True)
    window.minsize(min(min_width, width), min(min_height, height))
    window.geometry(f"{width}x{height}")
    window.update_idletasks()
    x = max(0, (screen_width - window.winfo_width()) // 2)
    y = max(0, (screen_height - window.winfo_height()) // 2)
    window.geometry(f"+{x}+{y}")


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
                    self._panel_history = [item for item in self._panel_history if item is not active]
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
