"""Dashboard window; all widget updates run through Tk's main-thread timer."""
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk


class DashboardUIMixin:
    def show_dashboard(self):
        existing = getattr(self, "_dashboard_window", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_set()
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
        window.title("Painel da Nova")
        window.geometry("500x510")
        style = ttk.Style(window)
        style.configure("Dashboard.Title.TLabel", font=("TkDefaultFont", 14, "bold"), foreground="#202B45")
        ttk.Label(window, text="Painel da Nova", style="Dashboard.Title.TLabel").pack(anchor="w", padx=18, pady=(16, 8))
        status = ttk.Label(window, text="Coletando métricas…", justify="left", wraplength=460)
        status.pack(fill="both", expand=True, anchor="nw", padx=18, pady=10)
        controls = ttk.Frame(window, padding=(18, 0, 18, 12))
        controls.pack(fill="x")
        interval = tk.StringVar(value=str(self.settings.get("dashboard_interval", 5)))
        paused = tk.BooleanVar(value=False)
        ttk.Label(controls, text="Atualizar (s):").pack(side="left")
        chooser = ttk.Combobox(controls, textvariable=interval, values=("2", "5", "10", "30"),
                               state="readonly", width=5)
        chooser.pack(side="left", padx=5)
        ttk.Checkbutton(controls, text="Pausar", variable=paused).pack(side="left")
        results = queue.Queue()
        state = {"busy": False, "closed": False}

        def collect():
            state["busy"] = True
            def worker():
                try:
                    results.put(self.system_monitor.collect(extra=self._dashboard_snapshot()))
                except Exception:
                    results.put({"error": "metrics_unavailable", **self._dashboard_snapshot()})
            threading.Thread(target=worker, name="nova-dashboard-metrics", daemon=True).start()

        def refresh():
            if state["closed"]:
                return
            try:
                metrics = results.get_nowait()
                state["busy"] = False
                if "error" in metrics:
                    text = "CPU/RAM/disco/processo: indisponíveis no momento.\n"
                else:
                    text = (f"CPU: {metrics['cpu_percent']:.0f}%\nRAM: {metrics['memory_percent']:.0f}% "
                            f"({metrics['memory_used'] // (1024**2)} / {metrics['memory_total'] // (1024**2)} MB)\n"
                            f"Disco pessoal: {metrics['disk_percent']:.0f}% usado · "
                            f"{metrics['disk_free'] // (1024**3)} GB livres\n"
                            f"Memória da Nova: {metrics['process_memory'] // (1024**2)} MB\n"
                            f"Threads: {metrics['threads']}\nTempo aberto: {metrics['uptime_seconds'] // 60} min\n")
                text += (f"Estado: {metrics.get('pet_state', self.state)} · animação: {metrics.get('animation', 'idle')}\n"
                         f"IA: {metrics.get('ai_provider', 'ollama')} · {metrics.get('ai_status', 'idle')}\n"
                         f"Spotify configurado: {'sim' if metrics.get('integrations', {}).get('spotify') else 'não'}\n"
                         f"Plugins: {metrics.get('plugins', {}).get('installed', 0)} instalados, "
                         f"{metrics.get('plugins', {}).get('active', 0)} ativos\n"
                         f"Tarefas em execução: {metrics.get('tasks_running', 0)}\n"
                         f"Erros recentes: {len(metrics.get('recent_errors', []))}\n"
                         f"Notificações não lidas: {self.notification_manager.unread_count}")
                status.configure(text=text)
            except queue.Empty:
                pass
            try:
                delay = max(2, min(30, int(interval.get()))) * 1000
            except ValueError:
                delay = 5000
            if not paused.get() and not state["busy"]:
                collect()
            window.after(delay, refresh)

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
            if getattr(self, "_dashboard_window", None) is window:
                self._dashboard_window = None
            window.destroy()
        window.protocol("WM_DELETE_WINDOW", on_close)
        refresh()
        return window
