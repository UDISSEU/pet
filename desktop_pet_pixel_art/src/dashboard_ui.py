"""Compact Nova dashboard with background metric collection."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from ui_theme import fit_window_to_screen


class DashboardUIMixin:
    def show_dashboard(self):
        existing = getattr(self, "_dashboard_window", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_set()
                    self._activate_panel(existing)
                    return existing
            except tk.TclError:
                pass
        try:
            self._authorize_core_action("system.cpu.read")
            self._authorize_core_action("system.memory.read")
            self._authorize_core_action("system.disk.read")
        except (PermissionError, OSError) as exc:
            messagebox.showerror("Permissão necessária", str(exc), parent=self.root)
            return

        window = self._set_nova_window_icon(tk.Toplevel(self.root))
        self._dashboard_window = window
        self._activate_panel(window)
        window.title("Painel da Nova")
        fit_window_to_screen(window, 580, 570, min_width=520, min_height=440)
        window.configure(bg="#F2F5F9")

        colors = {
            "ink": "#18263A",
            "muted": "#718096",
            "surface": "#FFFFFF",
            "border": "#E2E8F0",
            "track": "#E9EEF4",
            "teal": "#18A999",
            "blue": "#4386E8",
            "violet": "#8A6FE8",
            "amber": "#E6A23C",
        }
        small_font = ("TkDefaultFont", 8)

        header = tk.Frame(window, bg="#17263B", padx=18, pady=11)
        header.pack(fill="x")
        title_stack = tk.Frame(header, bg="#17263B")
        title_stack.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_stack, text="NOVA  /  MONITORAMENTO", bg="#17263B", fg="#75D8CC",
            font=("TkDefaultFont", 8, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_stack, text="Painel da Nova", bg="#17263B", fg="#F7FAFC",
            font=("TkDefaultFont", 16, "bold"), anchor="w",
        ).pack(anchor="w", pady=(3, 0))
        tk.Label(
            title_stack, text="Recursos e atividade em tempo real", bg="#17263B",
            fg="#B8C5D6", font=small_font, anchor="w",
        ).pack(anchor="w", pady=(1, 0))

        badge_var = tk.StringVar(value="●  AO VIVO")
        badge = tk.Label(
            header, textvariable=badge_var, bg="#21423F", fg="#8DE1D4",
            font=("TkDefaultFont", 8, "bold"), padx=10, pady=6,
        )
        badge.pack(side="right", anchor="n", padx=(8, 0), pady=3)
        back_button = tk.Button(
            header, text="← Voltar", command=lambda: self._panel_back(window),
            relief="flat", bd=0, padx=9, pady=5, cursor="hand2",
            bg="#263B56", fg="#F7FAFC", activebackground="#344D6B",
            activeforeground="#FFFFFF", font=("TkDefaultFont", 9, "bold"),
        )
        back_button.pack(side="right", anchor="n", padx=(0, 6), pady=3)

        body = tk.Frame(window, bg="#F2F5F9")
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, bg="#F2F5F9", bd=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        content = tk.Frame(canvas, bg="#F2F5F9", padx=14, pady=8)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(content_window, width=event.width),
        )

        def section_title(parent, text):
            tk.Label(
                parent, text=text.upper(), bg="#F2F5F9", fg=colors["muted"],
                font=("TkDefaultFont", 8, "bold"), anchor="w",
            ).pack(fill="x", pady=(0, 4))

        def make_surface(parent, padding=11):
            return tk.Frame(
                parent, bg=colors["surface"], padx=padding, pady=padding,
                highlightbackground=colors["border"], highlightthickness=1,
            )

        state_card = make_surface(content, padding=7)
        state_card.pack(fill="x", pady=(0, 8))
        state_dot = tk.Label(
            state_card, text="●", bg=colors["surface"], fg=colors["teal"],
            font=("TkDefaultFont", 12),
        )
        state_dot.pack(side="left", padx=(0, 8))
        pet_state_var = tk.StringVar(value="Estado: aguardando dados")
        tk.Label(
            state_card, textvariable=pet_state_var, bg=colors["surface"],
            fg=colors["ink"], font=("TkDefaultFont", 10, "bold"),
        ).pack(side="left")
        animation_var = tk.StringVar(value="Animação —")
        tk.Label(
            state_card, textvariable=animation_var, bg=colors["surface"],
            fg=colors["muted"], font=small_font,
        ).pack(side="right", padx=(8, 2))

        section_title(content, "Resumo do sistema")
        metrics_grid = tk.Frame(content, bg="#F2F5F9")
        metrics_grid.pack(fill="x", pady=(0, 8))
        metrics_grid.columnconfigure(0, weight=1, uniform="metric")
        metrics_grid.columnconfigure(1, weight=1, uniform="metric")

        def metric_card(row, column, title, accent, with_bar=True):
            card = make_surface(metrics_grid, padding=8)
            card.grid(row=row, column=column, sticky="nsew",
                      padx=(0, 6) if column == 0 else (6, 0),
                      pady=(0, 8) if row == 0 else (0, 0))
            tk.Label(
                card, text=title.upper(), bg=colors["surface"], fg=colors["muted"],
                font=("TkDefaultFont", 8, "bold"), anchor="w",
            ).pack(fill="x")
            value = tk.StringVar(value="—")
            tk.Label(
                card, textvariable=value, bg=colors["surface"], fg=colors["ink"],
                font=("TkDefaultFont", 18, "bold"), anchor="w",
            ).pack(fill="x", pady=(1, 0))
            detail = tk.StringVar(value="Coletando dados")
            tk.Label(
                card, textvariable=detail, bg=colors["surface"], fg=colors["muted"],
                font=small_font, anchor="w",
            ).pack(fill="x")
            bar = None
            if with_bar:
                bar = tk.Canvas(card, height=5, bg=colors["surface"],
                                highlightthickness=0, bd=0)
                bar.pack(fill="x", pady=(5, 0))
            return value, detail, bar, accent

        cpu = metric_card(0, 0, "Processador", colors["teal"])
        memory = metric_card(0, 1, "Memória RAM", colors["blue"])
        disk = metric_card(1, 0, "Disco", colors["violet"])
        nova_memory = metric_card(1, 1, "Memória da Nova", colors["amber"], with_bar=False)

        def update_bar(canvas, percent, color):
            if canvas is None:
                return
            ratio = max(0.0, min(100.0, float(percent))) / 100.0
            canvas._dashboard_progress = (percent, color)
            width = max(1, canvas.winfo_width())
            height = max(1, canvas.winfo_height())
            canvas.delete("all")
            canvas.create_rectangle(0, 0, width, height, fill=colors["track"], outline="")
            if ratio:
                canvas.create_rectangle(0, 0, width * ratio, height,
                                        fill=color, outline="")

        for metric in (cpu, memory, disk):
            bar = metric[2]
            bar._dashboard_progress = (0, metric[3])
            bar.bind(
                "<Configure>",
                lambda _event, target=bar: update_bar(
                    target, *target._dashboard_progress
                ),
            )

        details_row = tk.Frame(content, bg="#F2F5F9")
        details_row.pack(fill="x", pady=(0, 6))
        details_row.columnconfigure(0, weight=1, uniform="details")
        details_row.columnconfigure(1, weight=1, uniform="details")

        activity_card = make_surface(details_row, padding=8)
        activity_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        service_card = make_surface(details_row, padding=8)
        service_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        for parent, heading in ((activity_card, "ROTINA"), (service_card, "SERVIÇOS")):
            tk.Label(parent, text=heading, bg=colors["surface"], fg=colors["muted"],
                     font=("TkDefaultFont", 8, "bold"), anchor="w").pack(fill="x")
        activity_var = tk.StringVar(value="Aguardando atividade")
        activity_detail_var = tk.StringVar(value="")
        tk.Label(activity_card, textvariable=activity_var, bg=colors["surface"],
                 fg=colors["ink"], font=("TkDefaultFont", 9, "bold"),
                 anchor="w").pack(fill="x", pady=(4, 1))
        tk.Label(activity_card, textvariable=activity_detail_var,
                 bg=colors["surface"], fg=colors["muted"], font=small_font,
                 anchor="w").pack(fill="x")

        services_var = tk.StringVar(value="IA —")
        services_detail_var = tk.StringVar(value="Spotify —")
        tk.Label(service_card, textvariable=services_var, bg=colors["surface"],
                 fg=colors["ink"], font=("TkDefaultFont", 9, "bold"),
                 anchor="w").pack(fill="x", pady=(4, 1))
        tk.Label(service_card, textvariable=services_detail_var,
                 bg=colors["surface"], fg=colors["muted"], font=small_font,
                 anchor="w").pack(fill="x")

        controls = tk.Frame(window, bg="#F2F5F9", padx=14, pady=8)
        controls.pack(fill="x", side="bottom")
        tk.Label(controls, text="Atualizar a cada", bg="#F2F5F9",
                 fg=colors["muted"], font=small_font).pack(side="left")
        interval = tk.StringVar(value=str(self.settings.get("dashboard_interval", 5)))
        chooser = ttk.Combobox(
            controls, textvariable=interval, values=("2", "5", "10", "30"),
            state="readonly", width=4,
        )
        chooser.pack(side="left", padx=(7, 4))
        tk.Label(controls, text="seg", bg="#F2F5F9", fg=colors["muted"],
                 font=small_font).pack(side="left")
        paused = tk.BooleanVar(value=False)
        ttk.Checkbutton(controls, text="Pausar", variable=paused).pack(side="right")

        results = queue.Queue(maxsize=1)
        state = {"busy": False, "closed": False}

        def collect():
            if state["busy"] or state["closed"]:
                return
            state["busy"] = True

            def worker():
                try:
                    result = self.system_monitor.collect(extra=self._dashboard_snapshot())
                except Exception:
                    result = {"error": "metrics_unavailable"}
                try:
                    results.put_nowait(result)
                except queue.Full:
                    pass

            threading.Thread(target=worker, name="nova-dashboard-metrics", daemon=True).start()

        def render(metrics):
            if "error" in metrics:
                for metric in (cpu, memory, disk):
                    metric[0].set("Indisponível")
                    metric[1].set("Métrica temporariamente indisponível")
                    update_bar(metric[2], 0, metric[3])
                nova_memory[0].set("—")
                nova_memory[1].set("Aguardando dados")
            else:
                cpu_percent = metrics.get("cpu_percent", 0)
                memory_percent = metrics.get("memory_percent", 0)
                disk_percent = metrics.get("disk_percent", 0)
                cpu[0].set(f"CPU: {cpu_percent:.0f}%")
                cpu[1].set("Uso geral do processador")
                memory[0].set(f"{memory_percent:.0f}%")
                memory[1].set(
                    f"{metrics.get('memory_used', 0) / (1024 ** 3):.1f} / "
                    f"{metrics.get('memory_total', 0) / (1024 ** 3):.1f} GB usados"
                )
                disk[0].set(f"{disk_percent:.0f}%")
                disk[1].set(f"{metrics.get('disk_free', 0) // (1024 ** 3)} GB livres")
                nova_memory[0].set(f"{metrics.get('process_memory', 0) // (1024 ** 2)} MB")
                nova_memory[1].set(
                    f"{metrics.get('threads', 0)} threads · "
                    f"{metrics.get('uptime_seconds', 0) // 60} min aberta"
                )
                update_bar(cpu[2], cpu_percent, cpu[3])
                update_bar(memory[2], memory_percent, memory[3])
                update_bar(disk[2], disk_percent, disk[3])

            pet_state = metrics.get("pet_state", getattr(self, "state", "idle"))
            animation = metrics.get("animation", "idle")
            pet_state_var.set(f"Nova está {pet_state}")
            animation_var.set(f"Animação  {animation}")
            active_plugins = metrics.get("plugins", {}).get("active", 0)
            task_count = metrics.get("tasks_running", 0)
            errors = len(metrics.get("recent_errors", []))
            unread = getattr(self.notification_manager, "unread_count", 0)
            activity_var.set(f"{task_count} tarefas · {active_plugins} plugins ativos")
            activity_detail_var.set(f"{errors} erros · {unread} notificações não lidas")
            ai_status = metrics.get("ai_status", "idle")
            spotify = metrics.get("integrations", {}).get("spotify", False)
            services_var.set(f"IA  Ollama · {ai_status}")
            services_detail_var.set(
                f"Spotify  {'conectado' if spotify else 'não configurado'}"
            )

        def refresh():
            if state["closed"]:
                return
            try:
                metrics = results.get_nowait()
            except queue.Empty:
                pass
            else:
                state["busy"] = False
                render(metrics)

            is_paused = paused.get()
            badge_var.set("Ⅱ  PAUSADO" if is_paused else "●  AO VIVO")
            badge.configure(
                bg="#39485C" if is_paused else "#21423F",
                fg="#D2D9E2" if is_paused else "#8DE1D4",
            )
            try:
                delay = max(2, min(30, int(interval.get()))) * 1000
            except ValueError:
                delay = 5000
            if not is_paused and not state["busy"]:
                collect()
            state["after_id"] = window.after(delay, refresh)

        def save_interval(_event=None):
            try:
                value = max(2, min(30, int(interval.get())))
            except ValueError:
                value = 5
            self.settings["dashboard_interval"] = value
            self.persist_preferences()

        chooser.bind("<<ComboboxSelected>>", save_interval)

        def on_close():
            state["closed"] = True
            after_id = state.get("after_id")
            if after_id is not None:
                try:
                    window.after_cancel(after_id)
                except tk.TclError:
                    pass
            if getattr(self, "_dashboard_window", None) is window:
                self._dashboard_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", on_close)
        refresh()
        return window
