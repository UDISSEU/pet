"""Builder for the preference tab content."""

import tkinter as tk
from tkinter import ttk
from autonomy import save_settings
from automations import AUTOMATIONS


class AutomationPreferencesTabMixin:
    def _build_automation_preferences_tab(self, context):
        automation_content = getattr(context, 'automation_content', None)
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