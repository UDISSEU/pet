"""Builder for the preference tab content."""

import tkinter as tk
from tkinter import ttk


class BehaviorPreferencesTabMixin:
    def _build_behavior_preferences_tabs(self, context):
        announce_charger = getattr(context, 'announce_charger', None)
        announce_usb = getattr(context, 'announce_usb', None)
        auto_sit = getattr(context, 'auto_sit', None)
        behavior_content = getattr(context, 'behavior_content', None)
        break_minutes = getattr(context, 'break_minutes', None)
        card = getattr(context, 'card', None)
        computer_content = getattr(context, 'computer_content', None)
        evening_time = getattr(context, 'evening_time', None)
        focus_goal = getattr(context, 'focus_goal', None)
        focus_minutes = getattr(context, 'focus_minutes', None)
        humor_labels = getattr(context, 'humor_labels', None)
        humor_style = getattr(context, 'humor_style', None)
        mode = getattr(context, 'mode', None)
        observe = getattr(context, 'observe', None)
        peekaboo = getattr(context, 'peekaboo', None)
        quiet_end = getattr(context, 'quiet_end', None)
        quiet_start = getattr(context, 'quiet_start', None)
        routine_break_tip = getattr(context, 'routine_break_tip', None)
        routine_content = getattr(context, 'routine_content', None)
        routine_context = getattr(context, 'routine_context', None)
        routine_dance = getattr(context, 'routine_dance', None)
        routine_evening = getattr(context, 'routine_evening', None)
        routine_focus_celebration = getattr(context, 'routine_focus_celebration', None)
        routine_greeting = getattr(context, 'routine_greeting', None)
        routine_idle_yawn = getattr(context, 'routine_idle_yawn', None)
        routine_note = getattr(context, 'routine_note', None)
        routine_surprise = getattr(context, 'routine_surprise', None)
        speech = getattr(context, 'speech', None)
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
            command=lambda: context.start_focus_from_settings(),
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

        context.focus_status = focus_status