"""Tkinter menu, calendar, and preferences UI for the desktop pet."""

import re
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from autonomy import find_installed_apps, resolve_app_command, save_settings, valid_reminder_time
from automations import AUTOMATIONS
from calendar_view import open_calendar_window
from dashboard_ui import DashboardUIMixin
from notifications_ui import NotificationsUIMixin
from permissions_ui import PermissionsUIMixin
from ollama_client import save_history
from spotify_control import spotify_connected as spotify_token_connected


class DesktopPetUIMixin(DashboardUIMixin, NotificationsUIMixin, PermissionsUIMixin):
    def show_menu(self, event):
        self._last_user_activity_at = time.monotonic()
        if self._context_popup is not None:
            try:
                self._context_popup.destroy()
            except tk.TclError:
                pass

        popup = tk.Toplevel(self.root)
        self._context_popup = popup
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#D8DEEA")
        popup.bind("<Escape>", lambda _event: popup.destroy())
        popup.bind("<FocusOut>", lambda _event: popup.after_idle(
            lambda: popup.destroy() if popup.winfo_exists() and
            popup.focus_displayof() is None else None
        ))

        panel = tk.Frame(popup, bg="#F5F6FA", padx=6, pady=6,
                         highlightthickness=1, highlightbackground="#D8DEEA")
        panel.pack(fill="both", expand=True)
        title_bar = tk.Frame(panel, bg="#F5F6FA")
        title_bar.pack(fill="x", padx=3, pady=(0, 3))
        title_label = tk.Label(
            title_bar, text="Nova", font=("TkDefaultFont", 10, "bold"),
            fg="#202B45", bg="#F5F6FA", anchor="w", cursor="fleur",
        )
        title_label.pack(side="left", fill="x", expand=True, padx=2, pady=2)
        tk.Button(
            title_bar, text="×", command=lambda: popup.destroy(),
            relief="flat", bd=0, padx=5, pady=0, cursor="hand2",
            font=("TkDefaultFont", 11, "bold"), fg="#68738A",
            bg="#F5F6FA", activebackground="#E7EAF1",
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

        action_grid = tk.Frame(panel, bg="#F5F6FA")
        action_grid.pack(fill="x", pady=(0, 2))
        action_grid.grid_columnconfigure(0, weight=1, uniform="menu_action")
        action_grid.grid_columnconfigure(1, weight=1, uniform="menu_action")

        def action_button(label, command, row, column, primary=False):
            bg = "#5269C8" if primary else "#FFFFFF"
            fg = "#FFFFFF" if primary else "#28334D"
            hover = "#4056B2" if primary else "#E9EDF5"
            button = tk.Button(
                action_grid, text=label, anchor="w", command=lambda: (close_popup(), command()),
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

        more = tk.Frame(panel, bg="#F5F6FA")
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
            bg="#E9EDF5", fg="#536078", activebackground="#DDE3EF",
        )
        more_button.pack(fill="x", pady=(4, 0))

        def section_label(parent, label):
            tk.Label(
                parent, text=label.upper(), anchor="w", padx=6, pady=4,
                bg="#F5F6FA", fg="#758099",
                font=("TkDefaultFont", 8, "bold"),
            ).pack(fill="x", pady=(3, 0))

        def more_action(label, command):
            tk.Button(
                more, text=label, anchor="w",
                command=lambda: (close_popup(), command()), relief="flat", bd=0,
                padx=8, pady=4, cursor="hand2", bg="#FFFFFF", fg="#28334D",
                activebackground="#E9EDF5",
            ).pack(fill="x", pady=1)

        section_label(more, "Interação")
        more_action("Falar algo", self.say_something)
        more_action("Permissões", self.open_permissions)

        behavior_group = tk.Frame(more, bg="#F5F6FA")
        behavior_group.pack(fill="x", pady=(4, 0))
        behavior_section = tk.Frame(behavior_group, bg="#F5F6FA")
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
            bg="#E9EDF5", fg="#536078", activebackground="#DDE3EF",
        )
        behavior_button.pack(fill="x")

        def check_option(label, variable, command=None):
            tk.Checkbutton(
                behavior_section, text=label, variable=variable, command=command,
                anchor="w", padx=6, pady=2, bg="#F5F6FA", fg="#39445C",
                activebackground="#F5F6FA", selectcolor="#FFFFFF",
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
        open_calendar_window(self.root)
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
        save_settings(self.settings)
    def open_autonomy_settings(self, selected_tab="behavior"):
        window = self._set_nova_window_icon(tk.Toplevel(self.root))
        window.title("Preferências da Nova")
        window.transient(self.root)
        window.attributes("-topmost", True)
        window.geometry("560x600")
        window.minsize(520, 550)
        window.configure(bg="#E3E8F0")

        style = ttk.Style(window)
        style.configure("Autonomy.TFrame", background="#E3E8F0")
        style.configure("Card.TFrame", background="#F5F7FA")
        style.configure("Title.TLabel", background="#E3E8F0", foreground="#202B45", font=("TkDefaultFont", 14, "bold"))
        style.configure("Subtitle.TLabel", background="#E3E8F0", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("CardTitle.TLabel", background="#F5F7FA", foreground="#26344A", font=("TkDefaultFont", 10, "bold"))
        style.configure("Hint.TLabel", background="#F5F7FA", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("PageHint.TLabel", background="#E3E8F0", foreground="#58667C", font=("TkDefaultFont", 9))
        style.configure("ComputerStatus.TLabel", background="#F5F7FA", foreground="#26344A", font=("TkDefaultFont", 10, "bold"))
        style.configure("ComputerStatusError.TLabel", background="#F5F7FA", foreground="#B42318", font=("TkDefaultFont", 10, "bold"))
        style.configure("ModeHint.TLabel", background="#F5F7FA", foreground="#58667C", font=("TkDefaultFont", 8))
        style.configure("Primary.TButton", padding=(14, 8), font=("TkDefaultFont", 9, "bold"))
        style.configure("Secondary.TButton", padding=(12, 8))
        style.configure("Nav.TButton", padding=(4, 2))
        style.configure(
            "TabNav.TLabel", background="#E3E8F0", foreground="#202B45",
            font=("TkDefaultFont", 11, "bold"),
        )
        style.configure(
            "Maintenance.Treeview", background="#F5F7FA", fieldbackground="#F5F7FA",
            foreground="#26344A", rowheight=28, borderwidth=0,
        )
        style.configure(
            "Maintenance.Treeview.Heading", background="#E3E8F0",
            foreground="#26344A", font=("TkDefaultFont", 9, "bold"),
        )
        style.configure(
            "History.Treeview", background="#F5F7FA", fieldbackground="#F5F7FA",
            foreground="#26344A", rowheight=27, borderwidth=0,
        )
        style.configure(
            "History.Treeview.Heading", background="#E3E8F0",
            foreground="#26344A", font=("TkDefaultFont", 9, "bold"),
        )
        style.configure("Autonomy.TEntry", fieldbackground="#EDF0F5", foreground="#26344A", padding=4)

        outer = ttk.Frame(window, style="Autonomy.TFrame", padding=(22, 18, 22, 14))
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Preferências da Nova", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Ajuste o ritmo, a rotina e o que ela pode lembrar ou fazer.",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 14))

        notebook = ttk.Frame(outer, style="Autonomy.TFrame")
        tab_navigation = ttk.Frame(outer, style="Autonomy.TFrame")
        tab_navigation.pack(fill="x", pady=(0, 6))
        tab_pages = []
        history_refresh_callback = {"callback": None}
        active_tab_index = 0
        active_tab_name = tk.StringVar(value="Comportamento")

        def select_tab(target):
            nonlocal active_tab_index
            if isinstance(target, int):
                index = target % len(tab_pages)
            else:
                index = next(i for i, (_name, page) in enumerate(tab_pages) if page is target)
            active_tab_index = index
            for i, (name, page) in enumerate(tab_pages):
                if i == index:
                    page.pack(fill="both", expand=True)
                    active_tab_name.set(name)
                    if name == "Histórico" and history_refresh_callback["callback"]:
                        history_refresh_callback["callback"]()
                else:
                    page.pack_forget()

        def register_tab(page, name):
            tab_pages.append((name, page))
            if len(tab_pages) == 1:
                select_tab(0)

        def move_tab(direction):
            select_tab(active_tab_index + direction)

        ttk.Button(
            tab_navigation, text="◀", width=2, style="Nav.TButton",
            command=lambda: move_tab(-1),
        ).pack(side="left")
        ttk.Label(
            tab_navigation, textvariable=active_tab_name, style="TabNav.TLabel",
        ).pack(side="left", expand=True, padx=8)
        ttk.Button(
            tab_navigation, text="▶", width=2, style="Nav.TButton",
            command=lambda: move_tab(1),
        ).pack(side="right")
        notebook.pack(fill="both", expand=True)
        def scrollable_tab():
            tab = ttk.Frame(notebook, style="Autonomy.TFrame")
            canvas = tk.Canvas(
                tab, bg="#E3E8F0", bd=0, highlightthickness=0,
                yscrollincrement=24,
            )
            scrollbar = ttk.Scrollbar(tab, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scrollbar.set)
            canvas.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            content = ttk.Frame(canvas, style="Autonomy.TFrame", padding=14)
            content_window = canvas.create_window((0, 0), window=content, anchor="nw")
            content.bind(
                "<Configure>",
                lambda _event, target=canvas: target.configure(scrollregion=target.bbox("all")),
            )
            canvas.bind(
                "<Configure>",
                lambda event, target=canvas, item=content_window:
                    target.itemconfigure(item, width=event.width),
            )

            def scroll_wheel(event, target=canvas):
                widget = event.widget
                while widget is not None:
                    if widget is target:
                        if getattr(event, "num", None) == 4:
                            target.yview_scroll(-3, "units")
                        elif getattr(event, "num", None) == 5:
                            target.yview_scroll(3, "units")
                        else:
                            delta = int(-event.delta / 120) if abs(event.delta) >= 120 else int(-event.delta)
                            if delta:
                                target.yview_scroll(delta * 3, "units")
                        return "break"
                    widget = getattr(widget, "master", None)
                return None

            canvas.bind_all("<MouseWheel>", scroll_wheel, add="+")
            canvas.bind_all("<Button-4>", scroll_wheel, add="+")
            canvas.bind_all("<Button-5>", scroll_wheel, add="+")
            return tab, content

        behavior_tab, behavior_content = scrollable_tab()
        routine_tab, routine_content = scrollable_tab()
        memory_tab, memory_content = scrollable_tab()
        history_tab, history_content = scrollable_tab()
        reminder_tab, reminder_content = scrollable_tab()
        apps_tab, apps_content = scrollable_tab()
        computer_tab, computer_content = scrollable_tab()
        automation_tab, automation_content = scrollable_tab()
        ai_tab, ai_content = scrollable_tab()
        register_tab(behavior_tab, "Comportamento")
        register_tab(routine_tab, "Foco e rotina")
        register_tab(memory_tab, "Memórias")
        register_tab(history_tab, "Histórico")
        register_tab(reminder_tab, "Lembretes")
        register_tab(apps_tab, "Aplicativos")
        register_tab(computer_tab, "Meu Computador")
        register_tab(automation_tab, "Automações")
        register_tab(ai_tab, "Inteligência artificial")

        ttk.Label(automation_content, text="Automações", style="Title.TLabel").pack(anchor="w")
        ttk.Label(automation_content, text="Acompanhe seu notebook e cuide dos arquivos com ações locais e controladas.", style="Subtitle.TLabel", wraplength=465).pack(anchor="w", pady=(3, 12))
        automation_settings = self.settings.setdefault("automations", {"enabled": {}, "last_run": {}, "activity": []})
        automation_settings.setdefault("enabled", {})
        automation_settings.setdefault("last_run", {})
        automation_settings.setdefault("activity", [])
        self._automation_status_labels = {}
        self._automation_metric_vars = {}
        self._automation_metric_bars = {}
        self._automation_action_buttons = {}

        status_auto = next(item for item in AUTOMATIONS if item["id"] == "laptop_status")
        status_card = ttk.Frame(automation_content, style="Card.TFrame", padding=13)
        status_card.pack(fill="x", pady=(0, 9))
        status_header = ttk.Frame(status_card, style="Card.TFrame")
        status_header.pack(fill="x")
        status_title_frame = ttk.Frame(status_header, style="Card.TFrame")
        status_title_frame.pack(side="left", fill="x", expand=True)
        ttk.Label(status_title_frame, text="Visão geral do notebook", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(status_title_frame, text="Leitura local · não envia dados para a IA", style="Hint.TLabel").pack(anchor="w", pady=(2, 0))
        status_enabled = tk.BooleanVar(value=automation_settings["enabled"].get("laptop_status", True))
        def toggle_status_automation():
            self.settings["automations"]["enabled"]["laptop_status"] = status_enabled.get()
            save_settings(self.settings)
        ttk.Checkbutton(status_header, text="Ativada", variable=status_enabled, command=toggle_status_automation).pack(side="right", padx=(6, 0))

        metric_grid = ttk.Frame(status_card, style="Card.TFrame")
        metric_grid.pack(fill="x", pady=(12, 4))
        metric_specs = (("cpu", "CPU"), ("memory", "Memória"), ("disk", "Disco"), ("battery", "Bateria"))
        for index, (key, label) in enumerate(metric_specs):
            tile = ttk.Frame(metric_grid, style="Card.TFrame", padding=(8, 5))
            tile.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 5) if index % 2 == 0 else (5, 0), pady=3)
            metric_grid.columnconfigure(index % 2, weight=1)
            ttk.Label(tile, text=label, style="Hint.TLabel").pack(anchor="w")
            value_var = tk.StringVar(value="Aguardando leitura")
            self._automation_metric_vars[key] = value_var
            ttk.Label(tile, textvariable=value_var, style="CardTitle.TLabel").pack(anchor="w", pady=(1, 3))
            bar_var = tk.DoubleVar(value=0)
            self._automation_metric_bars[key] = bar_var
            ttk.Progressbar(tile, variable=bar_var, maximum=100, mode="determinate").pack(fill="x")

        device_info = tk.StringVar(value="Atualize para consultar tempo ligado e processos com maior uso de memória.")
        ttk.Label(status_card, textvariable=device_info, style="Hint.TLabel", wraplength=445, justify="left").pack(anchor="w", pady=(5, 7))
        self._automation_device_info_var = device_info
        status_actions = ttk.Frame(status_card, style="Card.TFrame")
        status_actions.pack(fill="x")
        status_button = ttk.Button(status_actions, text="Atualizar status", style="Primary.TButton", command=lambda: self._request_automation(status_auto))
        status_button.pack(side="left")
        self._automation_action_buttons["laptop_status"] = status_button
        self._automation_status_labels["laptop_status"] = ttk.Label(status_actions, text=automation_settings["last_run"].get("laptop_status", "Ainda não consultado"), style="Hint.TLabel", wraplength=255)
        self._automation_status_labels["laptop_status"].pack(side="left", padx=(10, 0), fill="x", expand=True)

        files_card = ttk.Frame(automation_content, style="Card.TFrame", padding=13)
        files_card.pack(fill="x", pady=5)
        ttk.Label(files_card, text="Arquivos e organização", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(files_card, text="Organize Downloads por tipo. A Nova mostra a lista e pede sua confirmação antes de mover qualquer arquivo.", style="Hint.TLabel", wraplength=450, justify="left").pack(anchor="w", pady=(3, 9))
        organize_auto = next(item for item in AUTOMATIONS if item["id"] == "organize_downloads")
        undo_auto = next(item for item in AUTOMATIONS if item["id"] == "undo_downloads")
        for item, button_text in ((organize_auto, "Pré-visualizar e organizar"), (undo_auto, "Desfazer última organização")):
            row = ttk.Frame(files_card, style="Card.TFrame")
            row.pack(fill="x", pady=3)
            enabled_var = tk.BooleanVar(value=automation_settings["enabled"].get(item["id"], True))
            def toggle_file_automation(automation=item, variable=enabled_var):
                self.settings["automations"]["enabled"][automation["id"]] = variable.get()
                save_settings(self.settings)
            ttk.Checkbutton(row, text="Ativada", variable=enabled_var, command=toggle_file_automation).pack(side="left")
            action_button = ttk.Button(row, text=button_text, style="Primary.TButton" if item["id"] == "organize_downloads" else "Secondary.TButton", command=lambda automation=item: self._request_automation(automation))
            action_button.pack(side="right")
            self._automation_action_buttons[item["id"]] = action_button
            last = automation_settings["last_run"].get(item["id"], "Ainda não executada")
            status_label = ttk.Label(files_card, text=last, style="Hint.TLabel", wraplength=445)
            status_label.pack(anchor="w", pady=(0, 5))
            self._automation_status_labels[item["id"]] = status_label

        def add_automation_row(parent, item, button_text="Executar", button_style="Primary.TButton"):
            row = ttk.Frame(parent, style="Card.TFrame")
            row.pack(fill="x", pady=4)
            enabled_var = tk.BooleanVar(value=automation_settings["enabled"].get(item["id"], True))
            def toggle_item(automation=item, variable=enabled_var):
                self.settings["automations"]["enabled"][automation["id"]] = variable.get()
                save_settings(self.settings)
            ttk.Checkbutton(row, text="Ativada", variable=enabled_var, command=toggle_item).pack(side="left")
            ttk.Label(row, text=item["name"], style="CardTitle.TLabel").pack(side="left", padx=(5, 0), fill="x", expand=True)
            button = ttk.Button(row, text=button_text, style=button_style, command=lambda automation=item: self._request_automation(automation))
            button.pack(side="right")
            self._automation_action_buttons[item["id"]] = button
            status_label = ttk.Label(parent, text=automation_settings["last_run"].get(item["id"], item["description"]), style="Hint.TLabel", wraplength=445)
            status_label.pack(anchor="w", padx=(7, 0), pady=(0, 3))
            self._automation_status_labels[item["id"]] = status_label

        insights_card = ttk.Frame(automation_content, style="Card.TFrame", padding=13)
        insights_card.pack(fill="x", pady=5)
        ttk.Label(insights_card, text="Análise de espaço", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(insights_card, text="Investigue o que ocupa espaço antes de decidir o que fazer.", style="Hint.TLabel", wraplength=450).pack(anchor="w", pady=(3, 7))
        add_automation_row(insights_card, next(item for item in AUTOMATIONS if item["id"] == "large_files"), "Maiores arquivos", "Secondary.TButton")
        add_automation_row(insights_card, next(item for item in AUTOMATIONS if item["id"] == "duplicates"), "Buscar duplicados", "Secondary.TButton")
        add_automation_row(insights_card, next(item for item in AUTOMATIONS if item["id"] == "trash_duplicates"), "Mover cópias", "Secondary.TButton")
        add_automation_row(insights_card, next(item for item in AUTOMATIONS if item["id"] == "disk_summary"), "Resumo de espaço", "Secondary.TButton")

        cleanup_card = ttk.Frame(automation_content, style="Card.TFrame", padding=13)
        cleanup_card.pack(fill="x", pady=5)
        ttk.Label(cleanup_card, text="Limpeza controlada", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(cleanup_card, text="A Lixeira só é esvaziada depois da sua confirmação. As capturas podem ser restauradas com Desfazer última organização.", style="Hint.TLabel", wraplength=450).pack(anchor="w", pady=(3, 7))
        add_automation_row(cleanup_card, next(item for item in AUTOMATIONS if item["id"] == "empty_trash"), "Revisar e esvaziar", "Secondary.TButton")
        add_automation_row(cleanup_card, next(item for item in AUTOMATIONS if item["id"] == "organize_screenshots"), "Prévia e confirmação")

        wellbeing_card = ttk.Frame(automation_content, style="Card.TFrame", padding=13)
        wellbeing_card.pack(fill="x", pady=5)
        ttk.Label(wellbeing_card, text="Bem-estar e bateria", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(wellbeing_card, text="Os avisos aguardam o fim do foco e respeitam o horário silencioso.", style="Hint.TLabel", wraplength=450).pack(anchor="w", pady=(3, 6))
        pause_enabled = tk.BooleanVar(value=automation_settings["enabled"].get("pause_reminder", True) and self.settings.get("routine_break_tip", True))
        def toggle_pause():
            self.settings["automations"]["enabled"]["pause_reminder"] = pause_enabled.get()
            self.settings["routine_break_tip"] = pause_enabled.get()
            save_settings(self.settings)
        ttk.Checkbutton(wellbeing_card, text="Lembrete de pausa saudável", variable=pause_enabled, command=toggle_pause).pack(anchor="w", pady=2)
        self._automation_status_labels["pause_reminder"] = ttk.Label(wellbeing_card, text=automation_settings["last_run"].get("pause_reminder", "Sugestão após 50 minutos de atividade."), style="Hint.TLabel", wraplength=445)
        self._automation_status_labels["pause_reminder"].pack(anchor="w", padx=(24, 0), pady=(0, 3))
        battery_enabled = tk.BooleanVar(value=automation_settings["enabled"].get("low_battery_alert", True))
        def toggle_battery_alert():
            self.settings["automations"]["enabled"]["low_battery_alert"] = battery_enabled.get()
            save_settings(self.settings)
        ttk.Checkbutton(wellbeing_card, text="Avisar quando a bateria chegar a 20%", variable=battery_enabled, command=toggle_battery_alert).pack(anchor="w", pady=2)
        self._automation_status_labels["low_battery_alert"] = ttk.Label(wellbeing_card, text=automation_settings["last_run"].get("low_battery_alert", "Verificação periódica enquanto a Nova estiver aberta."), style="Hint.TLabel", wraplength=445)
        self._automation_status_labels["low_battery_alert"].pack(anchor="w", padx=(24, 0), pady=(0, 3))

        activity_card = ttk.Frame(automation_content, style="Card.TFrame", padding=13)
        activity_card.pack(fill="x", pady=5)
        ttk.Label(activity_card, text="Atividade recente", style="CardTitle.TLabel").pack(anchor="w")
        activity_var = tk.StringVar(value="Nenhuma automação executada nesta sessão ainda.")
        self._automation_activity_var = activity_var
        ttk.Label(activity_card, textvariable=activity_var, style="Hint.TLabel", wraplength=450, justify="left").pack(anchor="w", pady=(5, 0))
        self._refresh_automation_activity()

        safety_card = ttk.Frame(automation_content, style="Card.TFrame", padding=13)
        safety_card.pack(fill="x", pady=(5, 0))
        ttk.Label(safety_card, text="Como a Nova protege suas ações", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(safety_card, text="As automações ficam em uma lista local fixa. Análises não alteram arquivos. Organizar Downloads ou capturas mostra a prévia e permite desfazer; esvaziar a Lixeira pede confirmação porque remove itens definitivamente. A Nova não segue links simbólicos, não substitui arquivos existentes e a IA não inicia automações.", style="Hint.TLabel", wraplength=450, justify="left").pack(anchor="w", pady=(4, 0))

        mode = tk.StringVar(value=self.settings.get("mode", "companhia"))
        quiet_start = tk.StringVar(value=self.settings.get("quiet_start", "22:00"))
        quiet_end = tk.StringVar(value=self.settings.get("quiet_end", "08:00"))
        focus_goal = tk.StringVar()
        focus_minutes = tk.StringVar(value=str(self.settings.get("focus_minutes", 25)))
        break_minutes = tk.StringVar(value=str(self.settings.get("break_minutes", 5)))
        routine_greeting = tk.BooleanVar(value=self.settings.get("routine_greeting", True))
        routine_context = tk.BooleanVar(value=self.settings.get("routine_context", True))
        routine_idle_yawn = tk.BooleanVar(value=self.settings.get("routine_idle_yawn", True))
        routine_focus_celebration = tk.BooleanVar(value=self.settings.get("routine_focus_celebration", True))
        routine_note = tk.BooleanVar(value=self.settings.get("routine_note", True))
        routine_surprise = tk.BooleanVar(value=self.settings.get("routine_surprise", True))
        routine_evening = tk.BooleanVar(value=self.settings.get("routine_evening", True))
        routine_dance = tk.BooleanVar(value=self.settings.get("routine_dance", True))
        routine_break_tip = tk.BooleanVar(value=self.settings.get("routine_break_tip", True))
        evening_time = tk.StringVar(value=self.settings.get("evening_time", "20:30"))
        speech = tk.BooleanVar(value=self.auto_speech_var.get())
        observe = tk.BooleanVar(value=self.observe_apps_var.get())
        announce_charger = tk.BooleanVar(value=self.settings.get("announce_charger", True))
        announce_usb = tk.BooleanVar(value=self.settings.get("announce_usb", True))
        humor_labels = {
            "tranquila": "Mais tranquila",
            "equilibrada": "Equilibrada",
            "brincalhona": "Mais brincalhona",
        }
        humor_style = tk.StringVar(
            value=humor_labels.get(
                self.settings.get("humor_style", "equilibrada"), "Equilibrada"
            )
        )
        auto_sit = tk.BooleanVar(value=self.auto_sit_var.get())
        peekaboo = tk.BooleanVar(value=self.peekaboo_var.get())
        confirm_app_launch = tk.BooleanVar(
            value=self.settings.get("confirm_app_launch", True)
        )
        ai_provider = tk.StringVar(value=self.settings.get("ai_provider", "ollama"))
        online_ai_enabled = tk.BooleanVar(value=self.settings.get("online_ai_enabled", False))
        allow_online_data = tk.BooleanVar(value=self.settings.get("allow_online_data", False))
        confirm_free_tier = tk.BooleanVar(value=self.settings.get("confirm_free_tier", False))
        ai_timeout = tk.StringVar(value=str(self.settings.get("ai_timeout", 30)))
        ollama_model = tk.StringVar(value=self.settings.get("ollama_model", "llama3.2:1b"))
        gemini_model = tk.StringVar(value=self.settings.get("gemini_model", "gemini-3.8-flash"))
        groq_model = tk.StringVar(value=self.settings.get("groq_model", "openai/gpt-oss-20b"))
        mistral_model = tk.StringVar(value=self.settings.get("mistral_model", "mistral-small-latest"))
        spotify_client_id = tk.StringVar(value=self.settings.get("spotify_client_id", ""))
        memory_items = list(self.settings.get("memories", []))
        reminder_items = list(self.settings.get("reminders", []))
        app_items = list(self.settings.get("apps", []))

        def card(parent, title, hint=None):
            frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
            frame.pack(fill="x", pady=(0, 12))
            ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
            if hint:
                ttk.Label(frame, text=hint, style="Hint.TLabel", wraplength=360).pack(anchor="w", pady=(3, 8))
            return frame

        ai_provider_card = card(
            ai_content, "Provedor de conversa",
            "A Nova começa usando o Ollama local. Provedores online só recebem o histórico recente e memórias relacionadas depois que você habilitar o uso e autorizar o envio.",
        )
        ttk.Label(ai_provider_card, text="Provedor", style="Hint.TLabel").pack(anchor="w")
        ttk.Combobox(
            ai_provider_card, textvariable=ai_provider,
            values=("ollama", "gemini", "groq", "mistral"), state="readonly",
        ).pack(fill="x", pady=(3, 8))
        ttk.Checkbutton(
            ai_provider_card, text="Ativar provedor online selecionado",
            variable=online_ai_enabled,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            ai_provider_card,
            text="Autorizo enviar histórico recente e memórias relacionadas\nà pergunta ao provedor online",
            variable=allow_online_data,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            ai_provider_card,
            text="Confirmei no painel que minha chave usa modalidade gratuita\ne que a cobrança está desabilitada",
            variable=confirm_free_tier,
        ).pack(anchor="w", pady=2)
        ttk.Label(
            ai_provider_card,
            text="O teste verifica a chave e a disponibilidade do modelo sem enviar conversas. Chaves (nunca gravadas nas preferências): GEMINI_API_KEY, GROQ_API_KEY ou MISTRAL_API_KEY; o lançador também lê as três do cofre do sistema. Confira privacidade, limites e cobrança no painel do provedor.",
            style="Hint.TLabel", wraplength=400,
        ).pack(anchor="w", pady=(5, 8))
        test_row = ttk.Frame(ai_provider_card, style="Card.TFrame")
        test_row.pack(fill="x", pady=(0, 8))
        test_status = tk.StringVar(value="")
        test_button_state = {"running": False}
        test_button = ttk.Button(
            test_row, text="Testar conexão", style="Secondary.TButton",
        )
        test_button.pack(side="left")
        ttk.Label(test_row, textvariable=test_status, style="Hint.TLabel", wraplength=265).pack(
            side="left", fill="x", expand=True, padx=(8, 0),
        )

        def test_selected_provider():
            if test_button_state["running"]:
                return
            try:
                timeout_value = int(ai_timeout.get())
            except ValueError:
                test_status.set("Informe um timeout entre 5 e 30 segundos.")
                return
            if not 5 <= timeout_value <= 30:
                test_status.set("Informe um timeout entre 5 e 30 segundos.")
                return
            provider_name = ai_provider.get()
            provider_settings = dict(self.settings)
            provider_settings.update(
                ai_provider=provider_name,
                ai_timeout=timeout_value,
                ollama_model=ollama_model.get().strip(),
                gemini_model=gemini_model.get().strip(),
                groq_model=groq_model.get().strip(),
                mistral_model=mistral_model.get().strip(),
            )
            test_button_state["running"] = True
            test_button.configure(state="disabled")
            test_status.set("Testando…")
            threading.Thread(
                target=self._provider_test_worker,
                args=(provider_name, provider_settings, window, test_status, test_button, test_button_state),
                daemon=True,
            ).start()

        test_button.configure(command=test_selected_provider)
        ttk.Label(ai_provider_card, text="Modelo Ollama", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ollama_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Modelo Gemini", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=gemini_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Modelo Groq", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=groq_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Modelo Mistral", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=mistral_model, style="Autonomy.TEntry").pack(fill="x", pady=(2, 6))
        ttk.Label(ai_provider_card, text="Timeout (5–30 segundos)", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(ai_provider_card, textvariable=ai_timeout, style="Autonomy.TEntry").pack(fill="x", pady=(2, 0))

        spotify_card = card(
            ai_content,
            "Spotify",
            "Para tocar uma música pelo nome, conecte sua conta: a Nova pesquisa pela API e envia a faixa ao player local. Para tocar playlist sem conectar a API, use o link dela. Adicionar faixas a playlists exige um app Spotify Developer Mode; o dono desse app precisa de Premium. Cadastre o Redirect URI http://127.0.0.1:8765/callback. A Nova usa PKCE e não pede Client Secret.",
        )
        ttk.Label(spotify_card, text="Client ID do app Spotify", style="Hint.TLabel").pack(anchor="w")
        ttk.Entry(
            spotify_card, textvariable=spotify_client_id, style="Autonomy.TEntry"
        ).pack(fill="x", pady=(3, 7))
        spotify_status = tk.StringVar(
            value=("Conta conectada." if spotify_token_connected(
                self.settings.get("spotify_client_id", "")
            ) else "Ainda não conectado.")
        )
        spotify_connect_button = ttk.Button(
            spotify_card, text="Conectar conta Spotify", style="Secondary.TButton",
        )
        spotify_connect_button.pack(anchor="w", pady=(0, 5))
        ttk.Label(
            spotify_card, textvariable=spotify_status, style="Hint.TLabel",
            wraplength=400,
        ).pack(anchor="w")
        self._spotify_status_var = spotify_status
        self._spotify_connect_button = spotify_connect_button

        def connect_spotify_account():
            client_id = spotify_client_id.get().strip()
            if not client_id:
                spotify_status.set("Cole o Client ID do seu app Spotify acima.")
                return
            updated = dict(self.settings)
            updated["spotify_client_id"] = client_id
            if not save_settings(updated):
                spotify_status.set("Não consegui salvar as preferências.")
                return
            self.settings = updated
            spotify_connect_button.configure(state="disabled")
            spotify_status.set("Abrindo o Spotify para autorização…")
            threading.Thread(
                target=self._spotify_connect_worker,
                args=(client_id,), daemon=True,
            ).start()

        spotify_connect_button.configure(command=connect_spotify_account)

        mode_card = card(behavior_content, "Como a Nova deve se comportar?", "Você pode personalizar as opções abaixo depois de escolher um modo.")
        mode_row = ttk.Frame(mode_card, style="Card.TFrame")
        mode_row.pack(fill="x", pady=(2, 0))
        modes = (
            ("quietinha", "Quietinha", "Fica mais discreta"),
            ("companhia", "Companhia", "Interage de vez em quando"),
            ("proativa", "Proativa", "Toma mais iniciativas"),
        )
        def choose_mode(value):
            presets = {
                "quietinha": (False, False, False, False),
                "companhia": (True, True, True, False),
                "proativa": (True, True, True, True),
            }
            speech.set(presets[value][0])
            observe.set(presets[value][1])
            auto_sit.set(presets[value][2])
            peekaboo.set(presets[value][3])

        for column, (value, label, description) in enumerate(modes):
            option = ttk.Frame(mode_row, style="Card.TFrame", padding=(0, 2))
            option.grid(row=0, column=column, sticky="w", padx=(0, 18))
            ttk.Radiobutton(
                option, text=label, value=value, variable=mode,
                command=lambda selected=value: choose_mode(selected),
            ).pack(anchor="w")
            ttk.Label(option, text=description, style="ModeHint.TLabel").pack(anchor="w", padx=(22, 0))

        behavior_card = card(behavior_content, "Iniciativas", "As iniciativas automáticas respeitam o horário de silêncio.")
        ttk.Checkbutton(behavior_card, text="Falas espontâneas", variable=speech).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Comentários sobre o app ativo", variable=observe).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Avisar quando conectar o carregador", variable=announce_charger).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Avisar quando um pendrive entrar", variable=announce_usb).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Sentar em janelas", variable=auto_sit).pack(anchor="w", pady=3)
        ttk.Checkbutton(behavior_card, text="Brincar de sumir atrás das janelas", variable=peekaboo).pack(anchor="w", pady=3)
        humor_row = ttk.Frame(behavior_card, style="Card.TFrame")
        humor_row.pack(fill="x", pady=(8, 2))
        ttk.Label(humor_row, text="Tom das respostas", style="CardTitle.TLabel").pack(side="left")
        ttk.Combobox(
            humor_row, textvariable=humor_style, state="readonly", width=20,
            values=tuple(humor_labels.values()),
        ).pack(side="right")
        ttk.Label(
            behavior_card,
            text="Controla a frequência das brincadeiras nas respostas da IA.",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(1, 2))

        quiet_card = card(behavior_content, "Horário de silêncio", "A Nova pausa falas, observações e lembretes durante esse período.")
        quiet_row = ttk.Frame(quiet_card, style="Card.TFrame")
        quiet_row.pack(anchor="w")
        ttk.Label(quiet_row, text="Das").pack(side="left")
        ttk.Entry(quiet_row, textvariable=quiet_start, width=8, justify="center", style="Autonomy.TEntry").pack(side="left", padx=(8, 16), ipady=4)
        ttk.Label(quiet_row, text="às").pack(side="left")
        ttk.Entry(quiet_row, textvariable=quiet_end, width=8, justify="center", style="Autonomy.TEntry").pack(side="left", padx=8, ipady=4)
        ttk.Label(quiet_row, text="HH:MM").pack(side="left", padx=(4, 0))

        focus_card = card(
            routine_content,
            "Sessão de foco",
            "Escolha no que vai trabalhar. A Nova fica quieta até a pausa e usa a animação de descanso.",
        )
        ttk.Label(focus_card, text="Sua prioridade", style="CardTitle.TLabel").pack(anchor="w", pady=(2, 3))
        ttk.Entry(focus_card, textvariable=focus_goal, style="Autonomy.TEntry").pack(fill="x", ipady=5)
        duration_row = ttk.Frame(focus_card, style="Card.TFrame")
        duration_row.pack(fill="x", pady=(12, 4))
        ttk.Label(duration_row, text="Foco (min)").pack(side="left")
        ttk.Spinbox(duration_row, from_=5, to=180, increment=5, textvariable=focus_minutes, width=7).pack(side="left", padx=(8, 18), ipady=3)
        ttk.Label(duration_row, text="Pausa (min)").pack(side="left")
        ttk.Spinbox(duration_row, from_=1, to=60, increment=1, textvariable=break_minutes, width=7).pack(side="left", padx=8, ipady=3)
        if self.focus_mode == "focus":
            focus_status_text = f"Foco em andamento: {self.focus_goal}"
        elif self.focus_mode == "break":
            focus_status_text = "Você está no intervalo. A Nova também está descansando."
        else:
            focus_status_text = "Ao terminar, ela avisa para você fazer uma pausa."
        focus_status = tk.StringVar(value=focus_status_text)
        ttk.Label(focus_card, textvariable=focus_status, style="Hint.TLabel", wraplength=360).pack(anchor="w", pady=(6, 8))
        focus_actions = ttk.Frame(focus_card, style="Card.TFrame")
        focus_actions.pack(fill="x")
        ttk.Button(
            focus_actions, text="Iniciar foco", style="Primary.TButton",
            command=lambda: start_focus_from_settings(),
        ).pack(side="left")
        ttk.Button(
            focus_actions, text="Encerrar sessão", style="Secondary.TButton",
            command=self.stop_focus,
        ).pack(side="left", padx=(8, 0))

        routine_card = card(
            routine_content,
            "Pequenas rotinas",
            "As mensagens aparecem apenas enquanto a Nova estiver aberta e fora do horário de silêncio.",
        )
        ttk.Checkbutton(
            routine_card, text="Dar boas-vindas quando eu iniciar a Nova",
            variable=routine_greeting,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Comentário de bom dia, boa tarde ou boa noite",
            variable=routine_context,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Bocejar depois de 5 minutos sem interação",
            variable=routine_idle_yawn,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Comemorar ao concluir uma sessão de foco",
            variable=routine_focus_celebration,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Recadinho ocasional (intervalo mínimo de 30 minutos)",
            variable=routine_note,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Uma surpresa aleatória por dia (fala e aceno)",
            variable=routine_surprise,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Dancinha espontânea (somente companhia/proativa)",
            variable=routine_dance,
        ).pack(anchor="w", pady=4)
        ttk.Checkbutton(
            routine_card, text="Lembrete de pausa saudável a cada 50 minutos",
            variable=routine_break_tip,
        ).pack(anchor="w", pady=4)
        evening_row = ttk.Frame(routine_card, style="Card.TFrame")
        evening_row.pack(fill="x", pady=(5, 0))
        ttk.Checkbutton(
            evening_row, text="Lembrar de encerrar o dia às",
            variable=routine_evening,
        ).pack(side="left")
        ttk.Entry(evening_row, textvariable=evening_time, width=8, justify="center", style="Autonomy.TEntry").pack(side="left", padx=8, ipady=3)
        ttk.Label(evening_row, text="(HH:MM)", style="Hint.TLabel").pack(side="left")

        computer_intro = card(
            computer_content, "Cuidados com o sistema",
            "Atualizações e limpezas usam o APT. O Linux solicitará autenticação quando necessário.",
        )
        ttk.Label(
            computer_intro, text="Escolha uma ação para começar.", style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        progress_card = ttk.Frame(computer_content, style="Card.TFrame", padding=14)
        progress_card.pack(fill="x", pady=(0, 12))
        computer_status = tk.StringVar(value="Tudo pronto.")
        computer_status_label = ttk.Label(
            progress_card, textvariable=computer_status, style="ComputerStatus.TLabel",
            wraplength=360,
        )
        computer_status_label.pack(anchor="w")
        computer_progress = ttk.Progressbar(progress_card, mode="indeterminate", length=380)
        computer_progress.pack(fill="x", pady=(10, 0))
        computer_progress.stop()
        computer_progress.pack_forget()
        maintenance_buttons = []
        maintenance_details = {"text": ""}

        def show_maintenance_details():
            if not maintenance_details["text"]:
                return
            details_window = self._set_nova_window_icon(tk.Toplevel(window))
            details_window.title("Detalhes da operação")
            details_window.transient(window)
            details_window.geometry("620x380")
            details_window.configure(bg="#E3E8F0")
            frame = ttk.Frame(details_window, style="Autonomy.TFrame", padding=14)
            frame.pack(fill="both", expand=True)
            output = tk.Text(frame, wrap="word", height=18, relief="flat", bd=0,
                             bg="#F5F7FA", fg="#344054", font=("TkFixedFont", 9))
            scrollbar = ttk.Scrollbar(frame, orient="vertical", command=output.yview)
            output.configure(yscrollcommand=scrollbar.set)
            output.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            output.insert("1.0", maintenance_details["text"])
            output.configure(state="disabled")

        details_button = ttk.Button(
            progress_card, text="Ver detalhes", style="Secondary.TButton",
            command=show_maintenance_details, state="disabled",
        )
        details_button.pack(anchor="e", pady=(8, 0))

        def show_maintenance_confirmation(title, description, confirm_label, on_confirm):
            dialog = self._set_nova_window_icon(tk.Toplevel(window))
            dialog.title(title)
            dialog.transient(window)
            dialog.resizable(False, False)
            dialog.configure(bg="#E3E8F0")
            frame = ttk.Frame(dialog, style="Autonomy.TFrame", padding=20)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text=title, style="Title.TLabel").pack(anchor="w")
            ttk.Label(frame, text=description, style="Subtitle.TLabel", wraplength=420).pack(anchor="w", pady=(8, 18))
            actions = ttk.Frame(frame, style="Autonomy.TFrame")
            actions.pack(fill="x")
            ttk.Button(actions, text="Cancelar", style="Secondary.TButton", command=dialog.destroy).pack(side="right")

            def confirm():
                dialog.destroy()
                on_confirm()

            ttk.Button(
                actions, text=confirm_label, style="Primary.TButton", command=confirm,
            ).pack(side="right", padx=(0, 8))
            dialog.geometry("500x220")
            dialog.grab_set()
            dialog.focus_set()

        def show_package_review(title, description, packages, action_label=None, on_action=None):
            dialog = self._set_nova_window_icon(tk.Toplevel(window))
            dialog.title(title)
            dialog.transient(window)
            dialog.geometry("620x440")
            dialog.minsize(500, 350)
            dialog.configure(bg="#E3E8F0")
            frame = ttk.Frame(dialog, style="Autonomy.TFrame", padding=16)
            frame.pack(fill="both", expand=True)
            ttk.Label(frame, text=title, style="Title.TLabel").pack(anchor="w")
            count = len(packages)
            count_text = f"{count} pacote(s)" if count else "Nenhum pacote"
            ttk.Label(
                frame, text=f"{description}  {count_text}.", style="Subtitle.TLabel",
                wraplength=440,
            ).pack(anchor="w", pady=(4, 12))
            table_frame = ttk.Frame(frame, style="Card.TFrame", padding=4)
            table_frame.pack(fill="both", expand=True)
            columns = ("package", "current", "action")
            table = ttk.Treeview(
                table_frame, columns=columns, show="headings", height=12,
                style="Maintenance.Treeview",
            )
            table.heading("package", text="Pacote")
            table.heading("current", text="Versão instalada")
            table.heading("action", text="Ação / nova versão")
            table.column("package", width=200, minwidth=120, anchor="w")
            table.column("current", width=130, minwidth=90, anchor="w")
            table.column("action", width=200, minwidth=100, anchor="w")
            scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=table.yview)
            horizontal_scrollbar = ttk.Scrollbar(
                table_frame, orient="horizontal", command=table.xview,
            )
            table.configure(
                yscrollcommand=scrollbar.set,
                xscrollcommand=horizontal_scrollbar.set,
            )
            table.pack(side="left", fill="both", expand=True)
            scrollbar.pack(side="right", fill="y")
            horizontal_scrollbar.pack(side="bottom", fill="x")
            for package in packages:
                table.insert("", "end", values=package)
            if not packages:
                ttk.Label(
                    frame, text="Não há pacotes para mostrar.", style="Hint.TLabel",
                ).pack(anchor="w", pady=(8, 0))
            buttons = ttk.Frame(frame, style="Autonomy.TFrame")
            buttons.pack(fill="x", pady=(12, 0))
            ttk.Button(buttons, text="Fechar", style="Secondary.TButton", command=dialog.destroy).pack(side="right")
            if packages and action_label and on_action:
                def do_action():
                    dialog.destroy()
                    on_action()

                ttk.Button(
                    buttons, text=action_label, style="Primary.TButton", command=do_action,
                ).pack(side="right", padx=(0, 8))
            dialog.grab_set()
            dialog.focus_set()

        def parse_upgradable_packages(output):
            packages = []
            for line in output.splitlines():
                if "upgradable" not in line.lower() or "/" not in line:
                    continue
                fields = line.split()
                if len(fields) < 2:
                    continue
                name = fields[0].split("/", 1)[0]
                candidate = fields[1]
                installed = ""
                match = re.search(r"\[upgradable from: ([^\]]+)\]", line)
                if match:
                    installed = match.group(1)
                packages.append((name, installed, candidate))
            return packages

        def parse_removable_packages(output):
            packages = []
            for line in output.splitlines():
                fields = line.split()
                if len(fields) >= 2 and fields[0] in ("Remv", "Purg"):
                    version = fields[2].strip("[]") if len(fields) >= 3 else ""
                    packages.append((fields[1], version, "Será removido"))
            return packages

        def finish_maintenance(title, result, error, on_success=None):
            if not window.winfo_exists():
                return
            computer_progress.stop()
            computer_progress.pack_forget()
            for button in maintenance_buttons:
                button.configure(state="normal")
            maintenance_details["text"] = (result or error or "").strip()
            details_button.configure(state="normal" if maintenance_details["text"] else "disabled")
            if error:
                computer_status_label.configure(style="ComputerStatusError.TLabel")
                computer_status.set(f"{title}: não foi concluído. Veja os detalhes para entender o erro.")
                return
            computer_status_label.configure(style="ComputerStatus.TLabel")
            if title == "Verificar atualizações":
                packages = parse_upgradable_packages(result)
                if packages:
                    summary = f"Há {len(packages)} atualização(ões) disponível(is)."
                else:
                    summary = "Seu sistema está atualizado."
            elif title == "Atualizar sistema":
                summary = "Atualização concluída."
            elif title == "Limpar cache do APT":
                summary = "Cache de pacotes limpo."
            else:
                summary = "Limpeza concluída."
            computer_status.set(summary)
            if title == "Verificar atualizações":
                action = on_success or None
                show_package_review(
                    "Atualizações disponíveis", "Veja as versões encontradas pelo APT.",
                    packages, "Atualizar pacotes" if action else None, action,
                )
            elif on_success:
                on_success()

        def run_maintenance(title, commands, on_success=None):
            try:
                self._authorize_core_action("system.maintenance", confirmed=True)
            except (PermissionError, OSError) as exc:
                messagebox.showerror("Permissão necessária", str(exc), parent=window)
                return
            if self.system_maintenance_active:
                messagebox.showinfo("Manutenção em andamento", "Aguarde a ação atual terminar.", parent=window)
                return
            self.system_maintenance_active = True
            maintenance_details["text"] = ""
            details_button.configure(state="disabled")
            computer_status_label.configure(style="ComputerStatus.TLabel")
            computer_status.set(f"{title} em andamento. O Linux pode solicitar autenticação.")
            for button in maintenance_buttons:
                button.configure(state="disabled")
            computer_progress.pack(fill="x", pady=(10, 0), before=details_button)
            computer_progress.start(12)

            def worker():
                output = []
                error = None
                try:
                    self.permission_manager.require("nova.core", "system.maintenance", confirmed=True)
                    for command in commands:
                        completed = subprocess.run(
                            command, capture_output=True, text=True, timeout=600,
                            check=False, env=self._child_process_env(),
                        )
                        details = (completed.stdout or "") + (completed.stderr or "")
                        if details.strip():
                            output.append(details.strip())
                        if completed.returncode != 0:
                            error = details.strip() or f"O comando terminou com código {completed.returncode}."
                            break
                except subprocess.TimeoutExpired:
                    error = "A operação demorou demais e foi interrompida."
                except OSError as exc:
                    error = f"Não consegui iniciar a ação: {exc}"
                finally:
                    self.system_maintenance_active = False
                self.post_ui_callback(
                    finish_maintenance, title, "\n\n".join(output), error, on_success,
                )

            threading.Thread(target=worker, daemon=True).start()

        def check_system_updates(for_upgrade=False):
            followup = None
            if for_upgrade:
                followup = lambda: run_maintenance(
                    "Atualizar sistema", [["pkexec", "apt-get", "upgrade", "-y"]],
                )
            run_maintenance("Verificar atualizações", [
                ["pkexec", "apt-get", "update"],
                ["apt", "list", "--upgradable"],
            ], on_success=followup)

        def add_maintenance_button(parent, text, style_name, command):
            button = ttk.Button(parent, text=text, style=style_name, command=command)
            button.pack(side="right", padx=(12, 0))
            maintenance_buttons.append(button)
            return button

        def action_card(title, description):
            action = ttk.Frame(computer_content, style="Card.TFrame", padding=(14, 11))
            action.pack(fill="x", pady=(0, 9))
            text_frame = ttk.Frame(action, style="Card.TFrame")
            text_frame.pack(side="left", fill="x", expand=True)
            ttk.Label(text_frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
            ttk.Label(text_frame, text=description, style="Hint.TLabel", wraplength=280).pack(anchor="w", pady=(3, 0))
            return action

        def preview_autoremove():
            try:
                self._authorize_core_action("system.maintenance.read")
            except (PermissionError, OSError) as exc:
                messagebox.showerror("Permissão necessária", str(exc), parent=window)
                return
            if self.system_maintenance_active:
                messagebox.showinfo("Manutenção em andamento", "Aguarde a ação atual terminar.", parent=window)
                return
            self.system_maintenance_active = True
            computer_status.set("Conferindo a prévia de remoção…")
            details_button.configure(state="disabled")
            for button in maintenance_buttons:
                button.configure(state="disabled")
            computer_progress.pack(fill="x", pady=(10, 0), before=details_button)
            computer_progress.start(12)

            def worker():
                try:
                    self.permission_manager.require("nova.core", "system.maintenance.read")
                    result = subprocess.run(
                        ["apt-get", "-s", "autoremove"], capture_output=True,
                        text=True, timeout=120, check=False,
                        env=self._child_process_env(),
                    )
                    details = (result.stdout or "") + (result.stderr or "")
                    error = details.strip() if result.returncode else None
                except (OSError, subprocess.TimeoutExpired) as exc:
                    details = ""
                    error = f"Não consegui verificar a lista: {exc}"
                self.system_maintenance_active = False

                def show_preview():
                    if not window.winfo_exists():
                        return
                    computer_progress.stop()
                    computer_progress.pack_forget()
                    for button in maintenance_buttons:
                        button.configure(state="normal")
                    if error:
                        maintenance_details["text"] = error
                        details_button.configure(state="normal")
                        computer_status_label.configure(style="ComputerStatusError.TLabel")
                        computer_status.set("Não consegui preparar a prévia. Veja os detalhes.")
                        return
                    preview_text = details.strip() or "O APT não listou pacotes para remover."
                    maintenance_details["text"] = preview_text
                    details_button.configure(state="normal")
                    packages = parse_removable_packages(preview_text)
                    computer_status.set(f"Prévia pronta: {len(packages)} pacote(s) para revisar.")
                    show_package_review(
                        "Pacotes não utilizados", "O APT marcou estes pacotes para remoção.",
                        packages, "Remover pacotes" if packages else None,
                        lambda: run_maintenance(
                            "Remover pacotes não utilizados",
                            [["pkexec", "apt-get", "autoremove", "-y"]],
                        ),
                    )

                self.post_ui_callback(show_preview)

            threading.Thread(target=worker, daemon=True).start()

        action = action_card("Atualizações disponíveis", "Atualiza a lista do APT e informa quais pacotes têm versões novas.")
        add_maintenance_button(action, "Verificar", "Secondary.TButton", check_system_updates)
        action = action_card("Atualizar programas", "Instala atualizações disponíveis sem remover pacotes.")
        add_maintenance_button(
            action, "Atualizar", "Primary.TButton",
            lambda: check_system_updates(for_upgrade=True),
        )
        action = action_card("Pacotes não utilizados", "Mostra primeiro a prévia do que o APT pretende remover.")
        add_maintenance_button(action, "Revisar", "Secondary.TButton", preview_autoremove)
        action = action_card("Cache de downloads", "Apaga arquivos de instalação .deb já baixados pelo APT.")
        add_maintenance_button(
            action, "Limpar cache", "Secondary.TButton",
            lambda: show_maintenance_confirmation(
                "Limpar cache de downloads",
                "Serão apagados os arquivos .deb já baixados pelo APT. Isso não remove programas instalados.",
                "Limpar cache",
                lambda: run_maintenance("Limpar cache do APT", [["pkexec", "apt-get", "clean"]]),
            ),
        )

        def setup_list(parent, items, format_item, empty_text):
            ttk.Label(parent, text=empty_text, style="PageHint.TLabel").pack(anchor="w", pady=(0, 8))
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

        protected_memory_card = card(
            memory_content, "Memórias essenciais protegidas",
            "Essas informações são controladas pelo código e não podem ser removidas pela lista de memórias.",
        )
        ttk.Label(
            protected_memory_card, text="Nome da assistente: Nova · protegido",
            style="CardTitle.TLabel",
        ).pack(anchor="w", pady=(2, 4))
        user_name_display = tk.StringVar(
            value=(f"Seu nome: {self.settings['user_name']} · protegido"
                   if self.settings.get("user_name") else "Seu nome ainda não foi informado.")
        )
        self._user_name_display_var = user_name_display
        ttk.Label(
            protected_memory_card, textvariable=user_name_display, style="CardTitle.TLabel",
        ).pack(anchor="w")
        if not self.settings.get("user_name"):
            ttk.Button(
                protected_memory_card, text="Informar meu nome", style="Secondary.TButton",
                command=self.ask_user_name,
            ).pack(anchor="w", pady=(8, 0))

        memory_card = card(memory_content, "O que a Nova deve lembrar?", "Só use informações que você queira manter. Elas entram no contexto da IA local.")
        memory_entry = tk.StringVar()
        memory_form = ttk.Frame(memory_card, style="Card.TFrame")
        memory_form.pack(fill="x")
        memory_input = ttk.Entry(memory_form, textvariable=memory_entry, style="Autonomy.TEntry")
        memory_input.pack(side="left", fill="x", expand=True, ipady=5)
        memory_list, refresh_memories, remove_memory = setup_list(
            memory_content, memory_items, lambda item: item,
            "Suas memórias ficam neste computador e você pode removê-las quando quiser.",
        )
        def add_memory():
            value = memory_entry.get().strip()
            if value:
                memory_items.append(value)
                memory_entry.set("")
                refresh_memories()
        ttk.Button(memory_form, text="Adicionar", style="Primary.TButton", command=add_memory).pack(side="left", padx=(8, 0))
        memory_input.bind("<Return>", lambda _event: add_memory())
        ttk.Button(memory_content, text="Remover selecionada", style="Secondary.TButton", command=remove_memory).pack(anchor="e", pady=(10, 0))

        history_card = card(
            history_content, "Histórico de conversa",
            "Veja as mensagens salvas, quando foram registradas e apague uma mensagem ou todo o histórico.",
        )
        history_status = tk.StringVar(value="")
        ttk.Label(history_card, textvariable=history_status, style="Hint.TLabel").pack(anchor="w")
        history_list_frame = ttk.Frame(history_content, style="Card.TFrame", padding=4)
        history_list_frame.pack(fill="both", expand=True, pady=(0, 10))
        history_view = tk.Text(
            history_list_frame, height=10, wrap="word", relief="flat", bd=0,
            padx=10, pady=8, spacing1=2, spacing3=5,
            bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 9),
            cursor="arrow", takefocus=True,
        )
        history_scrollbar = ttk.Scrollbar(
            history_list_frame, orient="vertical", command=history_view.yview,
        )
        history_view.configure(yscrollcommand=history_scrollbar.set)
        history_view.pack(side="left", fill="both", expand=True)
        history_scrollbar.pack(side="right", fill="y")
        history_view.tag_configure(
            "history_header", foreground="#26344A", font=("TkDefaultFont", 9, "bold"),
        )
        history_view.tag_configure("history_selected", background="#DFE6FA")
        history_entries = []
        selected_history = {"index": None}

        def scroll_history(event):
            if getattr(event, "num", None) == 4:
                history_view.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                history_view.yview_scroll(3, "units")
            elif event.delta:
                amount = int(-event.delta / 120) if abs(event.delta) >= 120 else int(-event.delta)
                if amount:
                    history_view.yview_scroll(amount * 3, "units")
            return "break"

        history_view.bind("<MouseWheel>", scroll_history)
        history_view.bind("<Button-4>", scroll_history)
        history_view.bind("<Button-5>", scroll_history)

        ttk.Label(history_content, text="Mensagem selecionada", style="CardTitle.TLabel").pack(anchor="w", pady=(2, 5))
        history_detail_frame = ttk.Frame(history_content, style="Card.TFrame", padding=1)
        history_detail_frame.pack(fill="x", pady=(0, 10))
        history_detail = tk.Text(
            history_detail_frame, height=5, wrap="word", relief="flat", bd=0,
            bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 9),
        )
        history_detail_scrollbar = ttk.Scrollbar(
            history_detail_frame, orient="vertical", command=history_detail.yview,
        )
        history_detail.configure(yscrollcommand=history_detail_scrollbar.set)
        history_detail.pack(side="left", fill="both", expand=True)
        history_detail_scrollbar.pack(side="right", fill="y")
        history_detail.configure(state="disabled")

        def show_selected_history_message(index=None):
            if index is not None:
                selected_history["index"] = index
            index = selected_history["index"]
            content = ""
            if index is not None:
                try:
                    item = self.history[index]
                    stamp = item.get("timestamp")
                    if isinstance(stamp, str):
                        try:
                            local_time = datetime.fromisoformat(stamp).astimezone()
                            when = local_time.strftime("%d/%m/%Y às %H:%M:%S")
                        except ValueError:
                            when = "Data/hora não registrada"
                    else:
                        when = "Data/hora não registrada"
                    who = "Você" if item.get("role") == "user" else "Nova"
                    content = f"{who} · {when}\n\n{item.get('content', '')}"
                except (IndexError, ValueError):
                    pass
            history_detail.configure(state="normal")
            history_detail.delete("1.0", "end")
            history_detail.insert("1.0", content)
            history_detail.configure(state="disabled")

        def select_history_message(event):
            line = int(history_view.index(f"@{event.x},{event.y}").split(".")[0])
            for first_line, last_line, index, start, end in history_entries:
                if first_line <= line <= last_line:
                    selected_history["index"] = index
                    history_view.tag_remove("history_selected", "1.0", "end")
                    history_view.tag_add("history_selected", start, end)
                    show_selected_history_message(index)
                    break
            return "break"

        history_view.bind("<Button-1>", select_history_message)

        def refresh_history():
            history_view.configure(state="normal")
            history_view.delete("1.0", "end")
            history_entries.clear()
            for index in range(len(self.history) - 1, -1, -1):
                item = self.history[index]
                if not isinstance(item, dict):
                    continue
                stamp = item.get("timestamp")
                try:
                    when = datetime.fromisoformat(stamp).astimezone().strftime("%d/%m/%Y %H:%M")
                except (TypeError, ValueError):
                    when = "Sem data/hora"
                who = "Você" if item.get("role") == "user" else "Nova"
                message = item.get("content", "")
                if not isinstance(message, str):
                    message = str(message)
                message = message.strip() or "(mensagem vazia)"
                start = history_view.index("end-1c")
                first_line = int(start.split(".")[0])
                history_view.insert("end", f"{who} · {when}\n", "history_header")
                history_view.insert("end", f"{message}\n\n")
                end = history_view.index("end-1c")
                last_line = int(end.split(".")[0])
                history_entries.append((first_line, last_line, index, start, end))
            history_view.configure(state="disabled")
            selected_history["index"] = None
            history_status.set(f"{len(self.history)} mensagem(ns) salvas neste computador.")
            show_selected_history_message()

        def delete_history_message():
            if self.ai_request_active:
                messagebox.showinfo("Conversa em andamento", "Aguarde a resposta terminar antes de apagar mensagens.", parent=window)
                return
            index = selected_history["index"]
            if index is None:
                messagebox.showinfo("Selecione uma mensagem", "Escolha uma mensagem na lista para apagá-la.", parent=window)
                return
            removed = self.history.pop(index)
            if not save_history(self.history):
                self.history.insert(index, removed)
                messagebox.showerror("Erro ao salvar", "Não consegui apagar a mensagem do arquivo de histórico.", parent=window)
                return
            refresh_history()

        def clear_conversation_history():
            if self.ai_request_active:
                messagebox.showinfo("Conversa em andamento", "Aguarde a resposta terminar antes de apagar o histórico.", parent=window)
                return
            if not self.history:
                return
            if not messagebox.askyesno("Apagar histórico", "Apagar todas as mensagens salvas?", parent=window):
                return
            previous = self.history
            self.history = []
            if not save_history(self.history):
                self.history = previous
                messagebox.showerror("Erro ao salvar", "Não consegui apagar o arquivo de histórico.", parent=window)
            else:
                refresh_history()

        history_actions = ttk.Frame(history_content, style="Autonomy.TFrame")
        history_actions.pack(fill="x")
        ttk.Button(
            history_actions, text="Apagar mensagem selecionada", style="Secondary.TButton",
            command=delete_history_message,
        ).pack(side="left")
        ttk.Button(
            history_actions, text="Apagar todo o histórico", style="Secondary.TButton",
            command=clear_conversation_history,
        ).pack(side="right")
        history_refresh_callback["callback"] = refresh_history
        refresh_history()

        reminder_card = card(reminder_content, "Criar lembrete", "A data e hora seguem o relógio local deste computador.")
        reminder_form = ttk.Frame(reminder_card, style="Card.TFrame")
        reminder_form.pack(fill="x")
        reminder_date = tk.StringVar()
        reminder_time = tk.StringVar()
        reminder_text = tk.StringVar()
        ttk.Label(reminder_form, text="Data").grid(row=0, column=0, sticky="w")
        ttk.Entry(reminder_form, textvariable=reminder_date, width=14, style="Autonomy.TEntry").grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(3, 8), ipady=4)
        ttk.Label(reminder_form, text="Hora").grid(row=0, column=1, sticky="w")
        ttk.Entry(reminder_form, textvariable=reminder_time, width=9, style="Autonomy.TEntry").grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(3, 8), ipady=4)
        ttk.Label(reminder_form, text="Lembrete").grid(row=0, column=2, sticky="w")
        ttk.Entry(reminder_form, textvariable=reminder_text, style="Autonomy.TEntry").grid(row=1, column=2, sticky="ew", pady=(3, 8), ipady=4)
        reminder_form.columnconfigure(2, weight=1)
        reminder_list, refresh_reminders, remove_reminder = setup_list(
            reminder_content, reminder_items,
            lambda item: f"{item.get('at', '')[:16].replace('T', ' ')}   ·   {item.get('text', '')}",
            "Quando vencer, a Nova mostra o lembrete em um balão.",
        )
        def add_reminder():
            value = f"{reminder_date.get().strip()}T{reminder_time.get().strip()}"
            parsed = valid_reminder_time(value)
            text = reminder_text.get().strip()
            if not parsed or not text:
                messagebox.showerror("Confira o lembrete", "Informe uma data AAAA-MM-DD, horário HH:MM e texto.", parent=window)
                return
            reminder_items.append({"at": parsed.isoformat(timespec="minutes"), "text": text, "done": False})
            reminder_date.set("")
            reminder_time.set("")
            reminder_text.set("")
            refresh_reminders()
        ttk.Button(reminder_form, text="Adicionar", style="Primary.TButton", command=add_reminder).grid(row=2, column=0, columnspan=3, sticky="e")
        ttk.Button(reminder_content, text="Remover selecionado", style="Secondary.TButton", command=remove_reminder).pack(anchor="e", pady=(10, 0))

        app_card = card(
            apps_content,
            "Permitir que a Nova abra um app",
            "Cadastre apenas apps que você reconhece. Você pode escolher se a Nova confirma cada abertura.",
        )
        ttk.Checkbutton(
            app_card,
            text="Perguntar antes de abrir um app",
            variable=confirm_app_launch,
        ).pack(anchor="w", pady=(0, 10))
        picker_row = ttk.Frame(app_card, style="Card.TFrame")
        picker_row.pack(fill="x", pady=(0, 10))
        app_picker_button = ttk.Button(
            picker_row, text="Buscar app instalado…", style="Secondary.TButton"
        )
        app_picker_button.pack(side="left")
        ttk.Label(
            picker_row, text="ou preencha os dados manualmente abaixo",
            style="Hint.TLabel",
        ).pack(side="left", padx=(10, 0))
        app_form = ttk.Frame(app_card, style="Card.TFrame")
        app_form.pack(fill="x")
        app_name = tk.StringVar()
        app_command = tk.StringVar()
        app_desktop_file = tk.StringVar()
        ttk.Label(app_form, text="Nome").grid(row=0, column=0, sticky="w")
        ttk.Entry(app_form, textvariable=app_name, width=18, style="Autonomy.TEntry").grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(3, 7), ipady=4)
        ttk.Label(app_form, text="Comando executável").grid(row=0, column=1, sticky="w")
        app_command_input = ttk.Entry(app_form, textvariable=app_command, style="Autonomy.TEntry")
        app_command_input.grid(row=1, column=1, sticky="ew", pady=(3, 7), ipady=4)
        app_command_input.bind("<KeyRelease>", lambda _event: app_desktop_file.set(""))
        app_form.columnconfigure(1, weight=1)
        ttk.Label(
            app_form,
            text="Exemplos: firefox --new-window  ·  code .  ·  /usr/bin/gimp",
            style="Hint.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))
        app_error = tk.StringVar()
        app_error_label = ttk.Label(
            app_form, textvariable=app_error, foreground="#B42318",
            background="#F5F7FA", wraplength=360,
        )
        app_error_label.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 5))
        app_buttons = ttk.Frame(app_form, style="Card.TFrame")
        app_buttons.grid(row=4, column=0, columnspan=2, sticky="ew")
        editing_app = {"index": None}
        app_list, refresh_apps, remove_app = setup_list(
            apps_content, app_items,
            lambda item: f"{item.get('name', '')}   ·   {item.get('command', '')}",
            "Selecione um app para editar ou remover. As alterações são salvas na hora.",
        )
        def clear_app_form():
            editing_app["index"] = None
            app_name.set("")
            app_command.set("")
            app_desktop_file.set("")
            app_error.set("")
            app_error_label.configure(foreground="#B42318")
            save_app_button.configure(text="Adicionar app")
            remove_app_button.configure(state="disabled")
            app_list.selection_clear(0, "end")

        def select_app(_event=None):
            selected = app_list.curselection()
            if not selected:
                return
            index = selected[0]
            editing_app["index"] = index
            app_name.set(app_items[index]["name"])
            app_command.set(app_items[index]["command"])
            app_desktop_file.set(app_items[index].get("desktop_file", ""))
            app_error.set("")
            save_app_button.configure(text="Salvar edição")
            remove_app_button.configure(state="normal")

        def open_app_picker():
            picker = self._set_nova_window_icon(tk.Toplevel(window))
            picker.title("Selecionar aplicativo instalado")
            picker.transient(window)
            picker.attributes("-topmost", True)
            picker.geometry("460x500")
            picker.minsize(380, 360)
            picker.configure(bg="#E3E8F0")
            content = ttk.Frame(picker, style="Autonomy.TFrame", padding=18)
            content.pack(fill="both", expand=True)
            ttk.Label(content, text="Selecionar aplicativo", style="Title.TLabel").pack(anchor="w")
            ttk.Label(
                content,
                text="Pesquise entre os aplicativos instalados neste computador.",
                style="Subtitle.TLabel",
            ).pack(anchor="w", pady=(3, 12))
            query = tk.StringVar()
            search_entry = ttk.Entry(content, textvariable=query, style="Autonomy.TEntry")
            search_entry.pack(fill="x", ipady=5, pady=(0, 10))
            result_frame = ttk.Frame(content, style="Card.TFrame", padding=1)
            result_frame.pack(fill="both", expand=True)
            result_list = tk.Listbox(
                result_frame, activestyle="none", relief="flat", bd=0,
                highlightthickness=0, selectforeground="#202B45",
                bg="#F5F7FA", fg="#344054", font=("TkDefaultFont", 10),
                selectbackground="#C7D2EE", selectmode="browse",
            )
            scrollbar = ttk.Scrollbar(result_frame, orient="vertical", command=result_list.yview)
            horizontal_scrollbar = ttk.Scrollbar(
                result_frame, orient="horizontal", command=result_list.xview,
            )
            result_list.configure(
                yscrollcommand=scrollbar.set,
                xscrollcommand=horizontal_scrollbar.set,
            )
            result_list.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=7)
            scrollbar.pack(side="right", fill="y", padx=(0, 5), pady=7)
            horizontal_scrollbar.pack(side="bottom", fill="x", padx=8, pady=(0, 7))
            feedback = tk.StringVar()
            ttk.Label(content, textvariable=feedback, style="PageHint.TLabel").pack(anchor="w", pady=(8, 0))
            installed_apps = find_installed_apps()
            visible_apps = []

            def filter_results(*_args):
                needle = query.get().casefold().strip()
                visible_apps.clear()
                visible_apps.extend(
                    item for item in installed_apps
                    if not needle or needle in f"{item['name']} {item['generic_name']}".casefold()
                )
                result_list.delete(0, "end")
                for item in visible_apps:
                    suffix = f"  ·  {item['generic_name']}" if item["generic_name"] else ""
                    result_list.insert("end", item["name"] + suffix)
                if visible_apps:
                    feedback.set(f"{len(visible_apps)} aplicativo(s) encontrado(s).")
                else:
                    feedback.set("Nenhum app encontrado. Você ainda pode preencher o formulário manualmente.")

            def use_selected_app(_event=None):
                selected = result_list.curselection()
                if not selected:
                    feedback.set("Selecione um aplicativo da lista.")
                    return
                app = visible_apps[selected[0]]
                app_name.set(app["name"])
                app_command.set(app["command"])
                app_desktop_file.set(app.get("desktop_file", ""))
                app_error.set("")
                editing_app["index"] = None
                save_app_button.configure(text="Adicionar app")
                remove_app_button.configure(state="disabled")
                app_list.selection_clear(0, "end")
                picker.destroy()

            query.trace_add("write", filter_results)
            filter_results()
            result_list.bind("<Double-Button-1>", use_selected_app)
            picker_buttons = ttk.Frame(content, style="Autonomy.TFrame")
            picker_buttons.pack(fill="x", pady=(12, 0))
            ttk.Button(picker_buttons, text="Cancelar", style="Secondary.TButton", command=picker.destroy).pack(side="right")
            ttk.Button(picker_buttons, text="Usar selecionado", style="Primary.TButton", command=use_selected_app).pack(side="right", padx=(0, 8))
            picker.bind("<Return>", use_selected_app)
            picker.bind("<Escape>", lambda _event: picker.destroy())
            search_entry.focus_set()

        app_picker_button.configure(command=open_app_picker)

        def validate_app_form():
            name = app_name.get().strip()
            command = app_command.get().strip()
            try:
                argv = resolve_app_command(command)
            except ValueError as exc:
                app_error_label.configure(foreground="#B42318")
                app_error.set(str(exc))
                return None
            if not name:
                app_error_label.configure(foreground="#B42318")
                app_error.set("Informe um nome para identificar este aplicativo.")
                return None
            for index, item in enumerate(app_items):
                if index != editing_app["index"] and item["name"].casefold() == name.casefold():
                    app_error_label.configure(foreground="#B42318")
                    app_error.set("Já existe um app com esse nome. Escolha outro nome.")
                    return None
            app_error_label.configure(foreground="#B42318")
            app_error.set("")
            return name, command, argv, app_desktop_file.get().strip()

        def persist_app_items():
            updated = dict(self.settings)
            updated["apps"] = [dict(item) for item in app_items]
            if not save_settings(updated):
                app_error_label.configure(foreground="#B42318")
                app_error.set("Não consegui salvar os apps. Confira as permissões e tente novamente.")
                return False
            self.settings = updated
            return True

        def save_app():
            values = validate_app_form()
            if not values:
                return
            name, command, _argv, desktop_file = values
            index = editing_app["index"]
            previous_items = [dict(item) for item in app_items]
            saved_app = {"name": name, "command": command}
            if desktop_file:
                saved_app["desktop_file"] = desktop_file
            if index is None:
                app_items.append(saved_app)
            else:
                app_items[index] = saved_app
            refresh_apps()
            if not persist_app_items():
                app_items[:] = previous_items
                refresh_apps()
                clear_app_form()
                return
            clear_app_form()

        def test_app_command():
            values = validate_app_form()
            if not values:
                return
            name, command, argv, desktop_file = values
            try:
                self._launch_app(
                    {"name": name, "command": command, "desktop_file": desktop_file},
                    question="",
                )
            except (OSError, ValueError, subprocess.SubprocessError):
                app_error_label.configure(foreground="#B42318")
                app_error.set("Não consegui iniciar esse aplicativo agora.")
                self._show_oops()
                return
            app_error_label.configure(foreground="#287247")
            app_error.set(f"Comando enviado ao sistema para abrir {name}.")

        def remove_selected_app():
            previous_items = [dict(item) for item in app_items]
            remove_app()
            if previous_items == app_items:
                return
            if not persist_app_items():
                app_items[:] = previous_items
                refresh_apps()
                clear_app_form()
                return
            clear_app_form()

        app_list.bind("<<ListboxSelect>>", select_app)
        save_app_button = ttk.Button(app_buttons, text="Adicionar app", style="Primary.TButton", command=save_app)
        save_app_button.pack(side="right")
        ttk.Button(app_buttons, text="Testar comando", style="Secondary.TButton", command=test_app_command).pack(side="right", padx=(0, 8))
        ttk.Button(app_buttons, text="Novo app", style="Secondary.TButton", command=clear_app_form).pack(side="left")
        remove_app_button = ttk.Button(
            app_buttons,
            text="Remover app",
            style="Secondary.TButton",
            command=remove_selected_app,
            state="disabled",
        )
        remove_app_button.pack(side="left", padx=(8, 0))

        def start_focus_from_settings():
            if self.focus_mode != "idle" or self.ai_request_active or self.dragging:
                focus_status.set("Não consigo iniciar outra sessão enquanto estou ocupada.")
                return
            try:
                duration = int(focus_minutes.get())
                pause = int(break_minutes.get())
            except ValueError:
                select_tab(routine_tab)
                messagebox.showerror("Duração inválida", "Informe durações em minutos.", parent=window)
                return
            if not 5 <= duration <= 180 or not 1 <= pause <= 60:
                select_tab(routine_tab)
                messagebox.showerror("Duração inválida", "Foco: 5–180 minutos. Pausa: 1–60 minutos.", parent=window)
                return
            save_and_close((focus_goal.get(), duration, pause))

        footer = ttk.Frame(outer, style="Autonomy.TFrame")
        footer.pack(fill="x", pady=(14, 0))

        def save_and_close(focus_params=None):
            try:
                for value in (quiet_start.get(), quiet_end.get()):
                    time.strptime(value, "%H:%M")
            except ValueError:
                select_tab(behavior_tab)
                messagebox.showerror("Horário inválido", "Use HH:MM nos horários de silêncio.", parent=window)
                return
            try:
                duration = int(focus_minutes.get())
                pause = int(break_minutes.get())
                time.strptime(evening_time.get(), "%H:%M")
            except ValueError:
                select_tab(routine_tab)
                messagebox.showerror("Valor inválido", "Confira as durações e use HH:MM no horário de encerramento.", parent=window)
                return
            if not 5 <= duration <= 180 or not 1 <= pause <= 60:
                select_tab(routine_tab)
                messagebox.showerror("Duração inválida", "Foco: 5–180 minutos. Pausa: 1–60 minutos.", parent=window)
                return
            try:
                timeout_value = int(ai_timeout.get())
            except ValueError:
                select_tab(ai_tab)
                messagebox.showerror("Timeout inválido", "Informe um número entre 5 e 30 segundos.", parent=window)
                return
            if not 5 <= timeout_value <= 30:
                select_tab(ai_tab)
                messagebox.showerror("Timeout inválido", "Informe um número entre 5 e 30 segundos.", parent=window)
                return
            updated = dict(self.settings)
            updated_automations = dict(updated.get("automations", {}))
            updated_automation_enabled = dict(updated_automations.get("enabled", {}))
            updated_automation_enabled["pause_reminder"] = routine_break_tip.get()
            updated_automations["enabled"] = updated_automation_enabled
            updated["automations"] = updated_automations
            updated.update(
                mode=mode.get(), quiet_start=quiet_start.get(), quiet_end=quiet_end.get(),
                humor_style={label: key for key, label in humor_labels.items()}[
                    humor_style.get()
                ],
                memories=memory_items, reminders=reminder_items, apps=app_items,
                confirm_app_launch=confirm_app_launch.get(),
                auto_speech=speech.get(), observe_apps=observe.get(), auto_sit=auto_sit.get(),
                announce_charger=announce_charger.get(), announce_usb=announce_usb.get(),
                peekaboo=peekaboo.get(),
                focus_minutes=duration, break_minutes=pause,
                routine_greeting=routine_greeting.get(),
                routine_context=routine_context.get(),
                routine_idle_yawn=routine_idle_yawn.get(),
                routine_focus_celebration=routine_focus_celebration.get(),
                routine_note=routine_note.get(),
                routine_surprise=routine_surprise.get(),
                routine_evening=routine_evening.get(), evening_time=evening_time.get(),
                routine_dance=routine_dance.get(),
                routine_break_tip=routine_break_tip.get(),
                ai_provider=ai_provider.get(), online_ai_enabled=online_ai_enabled.get(),
                allow_online_data=allow_online_data.get(),
                confirm_free_tier=confirm_free_tier.get(), ai_timeout=timeout_value,
                ollama_model=ollama_model.get().strip(),
                gemini_model=gemini_model.get().strip(), groq_model=groq_model.get().strip(),
                mistral_model=mistral_model.get().strip(),
                spotify_client_id=spotify_client_id.get().strip(),
            )
            if not save_settings(updated):
                messagebox.showerror("Erro ao salvar", "Não consegui salvar as preferências.", parent=window)
                return
            self.settings = updated
            self.auto_speech_var.set(speech.get())
            self.observe_apps_var.set(observe.get())
            self.auto_sit_var.set(auto_sit.get())
            self.peekaboo_var.set(peekaboo.get())
            window.destroy()
            if routine_greeting.get() and not self._routine_greeted:
                self.root.after(500, self.show_start_greeting)
            if routine_context.get():
                self.root.after(1000, self.show_context_greeting)
            if focus_params:
                self.start_focus(*focus_params)
            else:
                self.show_bubble("Preferências atualizadas.", duration=2500)

        ttk.Button(footer, text="Cancelar", style="Secondary.TButton", command=window.destroy).pack(side="right")
        ttk.Button(footer, text="Salvar alterações", style="Primary.TButton", command=save_and_close).pack(side="right", padx=(0, 8))
        if selected_tab == "routine":
            select_tab(routine_tab)
        elif selected_tab == "memory":
            select_tab(memory_tab)
        elif selected_tab == "reminder":
            select_tab(reminder_tab)
        elif selected_tab == "apps":
            select_tab(apps_tab)
        elif selected_tab == "computer":
            select_tab(computer_tab)
        elif selected_tab == "automation":
            select_tab(automation_tab)
        elif selected_tab == "ai":
            select_tab(ai_tab)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.bind("<Control-Return>", lambda _event: save_and_close())
