"""Focused pages for the Meu Computador system center."""

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from computer_services import (
    analyze_directory, collect_network, collect_overview,
    collect_storage_overview, format_bytes,
)
from computer_diagnostics import (
    NetworkSampler, SystemHealthSampler,
    run_connectivity_diagnostics,
)
from computer_consultant import ActionHistoryStore, collect_computer_context
from computer_maintenance import (
    analyze_cleanup, collect_logs, delete_cleanup_items, inspect_disks,
)
from computer_backup import (
    create_backup, delete_backup, export_backup, list_backups,
    load_backup_directory, preview_restore, rename_backup,
    restore_backup, save_backup_directory,
)
from performance_monitor import CATEGORIES as PERFORMANCE_CATEGORIES, performance_context
from startup_manager import discover_startup_entries, set_startup_enabled
from ui_theme import COLORS, fit_window_to_screen, make_header


class ComputerCenterUIMixin:
    def show_computer_center(self, parent=None):
        parent = parent or self.root
        try:
            self._authorize_core_action("system.cpu.read")
            self._authorize_core_action("system.memory.read")
            self._authorize_core_action("system.disk.read")
        except (PermissionError, OSError) as exc:
            messagebox.showerror("Permissão necessária", str(exc), parent=parent)
            return
        window = self._set_nova_window_icon(tk.Toplevel(parent))
        window.title("Meu Computador · Central")
        window.configure(bg=COLORS["background"])
        window.transient(parent)
        fit_window_to_screen(window, 780, 700, min_width=600, min_height=480)
        self._activate_panel(window)
        make_header(window, "Meu Computador", "Informações reais para acompanhar e cuidar do sistema.",
                    eyebrow="NOVA  /  SISTEMA", back_command=lambda: self._panel_back(window))

        body = ttk.Frame(window, padding=(16, 10, 16, 16))
        body.pack(fill="both", expand=True)
        nav = ttk.Frame(body)
        nav.pack(fill="x", pady=(0, 12))
        content = ttk.Frame(body)
        content.pack(fill="both", expand=True)
        page_title = tk.StringVar(value="Visão geral")
        ttk.Label(content, textvariable=page_title, style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        status = tk.StringVar(value="Escolha uma seção para consultar.")
        ttk.Label(content, textvariable=status, style="PageHint.TLabel", wraplength=660).pack(anchor="w", pady=(0, 8))
        result = ttk.Frame(content)
        result.pack(fill="both", expand=True)
        cancel_event = threading.Event()
        state = {"closed": False, "busy": False, "job": None, "token": 0}
        results = queue.Queue()
        nav_buttons = []
        startup_items = {}
        startup_sort = {"column": "name", "reverse": False}
        storage_scan = {"directory": str(Path.home()),
                        "files": [], "sort": "size", "reverse": True}
        storage_directory_var = tk.StringVar(value=storage_scan["directory"])
        network_sampler = NetworkSampler()
        health_sampler = SystemHealthSampler()
        snapshots = {"network": None, "health": None}
        timers = {"network": None, "health": None}
        monitors = {"network": False, "health": False}
        network_interval = tk.StringVar(value="2")
        cleanup_items = []
        log_rows = []
        try:
            backup_directory = {"path": load_backup_directory()}
        except (OSError, ValueError):
            backup_directory = {"path": Path.home() / ".local/share/desktop_pet/backups"}
        backup_rows = {}
        performance_monitor = getattr(self, "performance_monitor", None)
        try:
            action_history = getattr(self, "computer_action_history", None) or ActionHistoryStore()
        except Exception:
            action_history = None
        performance_period = tk.StringVar(value="24 horas")
        performance_records = []
        alert_records = []
        consultant_action = {"id": None}

        def record_consultant_action(action_status, *, result="", error_code=None):
            if action_history is None:
                return None
            try:
                return action_history.record(
                    "consultor.computador", action_status, origin="Meu Computador",
                    result=result, error_code=error_code,
                )
            except Exception:
                status.set("O histórico de ações está indisponível; a consulta pode continuar.")
                return None

        def update_consultant_action(entry_id, action_status, *, result="", error_code=None):
            if action_history is None or entry_id is None:
                return
            try:
                action_history.update(entry_id, action_status, result=result, error_code=error_code)
            except Exception:
                status.set("Não foi possível atualizar o histórico local da ação.")

        def clear_result():
            for widget in result.winfo_children():
                widget.destroy()

        def add_metric(label, value, detail="", parent=result):
            card = ttk.Frame(parent, style="Card.TFrame", padding=12)
            card.pack(fill="x", pady=(0, 8))
            ttk.Label(card, text=label, style="Hint.TLabel").pack(anchor="w")
            ttk.Label(card, text=value, style="CardTitle.TLabel").pack(anchor="w", pady=(3, 0))
            if detail:
                ttk.Label(card, text=detail, style="Hint.TLabel", wraplength=630).pack(anchor="w", pady=(2, 0))
            return card

        def render_overview(data):
            add_metric("Processador", data["cpu_name"], f"Uso atual: {data['cpu_percent']:.0f}%")
            add_metric("Memória RAM", f"{format_bytes(data['memory_used'])} de {format_bytes(data['memory_total'])}",
                       f"{data['memory_percent']:.0f}% em uso")
            add_metric("Armazenamento da pasta pessoal", f"{format_bytes(data['disk_free'])} disponíveis",
                       f"{format_bytes(data['disk_used'])} usados de {format_bytes(data['disk_total'])} · {data['disk_percent']:.0f}%")
            add_metric("Sistema", data["system"], f"Computador: {data['hostname']}")
            temp = "Não disponível neste sistema" if data["temperature_c"] is None else f"{data['temperature_c']:.1f} °C"
            add_metric("Temperatura", temp, "Leitura dos sensores do sistema operacional")
            health = "Recursos em níveis usuais" if data["memory_percent"] < 85 and data["disk_percent"] < 90 else "Atenção: memória ou armazenamento próximos do limite"
            add_metric("Resumo", health, "Indicador baseado somente no uso atual de RAM e armazenamento.")

        def render_network(snapshot):
            snapshots["network"] = snapshot
            for item in snapshot["interfaces"]:
                address = ", ".join(item["addresses"]) or "Sem endereço IP"
                state_text = "Conectada" if item["connected"] else ("Ativa" if item["is_up"] else "Inativa")
                add_metric(f"{item['name']} · {item['type']}", state_text,
                           f"{address} · Gateway: {item['gateway'] or 'não identificado'} · "
                           f"{item['speed_mbps'] or '—'} Mbps")
            if not snapshot["interfaces"]:
                add_metric("Interfaces", "Nenhuma interface de rede encontrada")
            sent = snapshot["upload_bytes_per_second"]
            received = snapshot["download_bytes_per_second"]
            def rate(value):
                return "Aguardando amostra" if value is None else f"{format_bytes(value)}/s"
            add_metric("Tráfego atual", f"↑ {rate(sent)}   ↓ {rate(received)}",
                       f"Totais desde a inicialização: enviado {format_bytes(snapshot['bytes_sent'])} · recebido {format_bytes(snapshot['bytes_received'])}")
            add_metric("Estado da conexão", snapshot["connection_state"],
                       f"Internet: {snapshot['internet_state']} · DNS: {', '.join(snapshot['dns_servers']) or 'não identificado'}")
            chart = tk.Canvas(result, height=85, bg=COLORS["surface"], highlightthickness=0)
            chart.pack(fill="x", pady=(0, 6))
            history = snapshot["history"][-30:]
            peak = max([1.0] + [p[k] for p in history for k in ("upload", "download")])
            width = max(100, chart.winfo_width())
            for key, color in (("download", COLORS.get("accent", "#53c7b5")), ("upload", COLORS.get("primary", "#8b7cf6"))):
                points = []
                for i, point in enumerate(history):
                    x = 8 + i * max(1, (width - 16) / max(1, len(history) - 1))
                    y = 76 - point[key] / peak * 65
                    points.extend((x, y))
                if len(points) >= 4:
                    chart.create_line(*points, fill=color, width=2, smooth=True)
            actions = ttk.Frame(result); actions.pack(fill="x", pady=4)
            ttk.Label(actions, text="Amostra (s):").pack(side="left")
            ttk.Combobox(actions, textvariable=network_interval, values=("1", "2", "5", "10"), state="readonly", width=4).pack(side="left", padx=4)
            ttk.Button(actions, text="Verificar conexão", command=run_network_checks).pack(side="right")
            ttk.Label(result, text="Histórico temporário desta janela. A verificação externa só ocorre ao solicitar.", style="PageHint.TLabel").pack(anchor="w")

        def render_health(snapshot):
            snapshots["health"] = snapshot
            clear_result()
            add_metric("Processador", f"{snapshot['cpu_percent']:.0f}%", "Uso na amostra atual")
            add_metric("Memória", f"{snapshot['memory_percent']:.1f}% · {format_bytes(snapshot['memory_available'])} disponíveis", f"{format_bytes(snapshot['memory_used'])} de {format_bytes(snapshot['memory_total'])}")
            add_metric("Armazenamento", f"{snapshot['disk_percent']:.1f}% ocupado", f"{format_bytes(snapshot['disk_free'])} livres no volume pessoal")
            add_metric("Temperatura", "Não disponível" if snapshot["temperature_c"] is None else f"{snapshot['temperature_c']:.1f} °C", "Leitura mais alta entre sensores disponíveis")
            ttk.Label(result, text="Diagnósticos observados", style="CardTitle.TLabel").pack(anchor="w", pady=4)
            if snapshot["issues"]:
                for issue in snapshot["issues"]:
                    add_metric(f"{issue['severity']} · {issue['name']}", issue["evidence"], f"{issue['recommendation']} Limitação: {issue['limitation']}")
            else:
                ttk.Label(result, text="Nenhum indicador ultrapassou os limites de atenção nesta amostra.", style="PageHint.TLabel").pack(anchor="w")
            ttk.Label(result, text="Histórico recente", style="CardTitle.TLabel").pack(anchor="w", pady=(8, 2))
            history = snapshot["history"][-30:]
            chart = tk.Canvas(result, height=72, bg=COLORS["surface"], highlightthickness=0)
            chart.pack(fill="x")
            width = max(100, chart.winfo_width())
            for key, color in (("cpu_percent", COLORS["accent"]),
                               ("memory_percent", "#8B6FE8"),
                               ("disk_percent", "#D18B3C")):
                points = []
                for i, point in enumerate(history):
                    x = 8 + i * max(1, (width - 16) / max(1, len(history) - 1))
                    y = 66 - min(100, point[key]) / 100 * 56
                    points.extend((x, y))
                if len(points) >= 4:
                    chart.create_line(*points, fill=color, width=2, smooth=True)
            ttk.Label(result, text="CPU · RAM · armazenamento (escala 0–100%)", style="PageHint.TLabel").pack(anchor="w")
            ttk.Label(result, text=f"Processos (top uso) · {snapshot['inaccessible_processes']} sem acesso", style="CardTitle.TLabel").pack(anchor="w", pady=(8, 4))
            tree = ttk.Treeview(result, columns=("pid", "name", "cpu", "memory"), show="headings", height=7, style="Maintenance.Treeview")
            for col, title, width in (("pid", "PID", 65), ("name", "Processo", 260), ("cpu", "CPU", 80), ("memory", "Memória", 120)):
                tree.heading(col, text=title); tree.column(col, width=width, anchor="w")
            tree.pack(fill="both", expand=True)
            for p in snapshot["processes"]:
                cpu = "—" if p["cpu_percent"] is None else f"{p['cpu_percent']:.1f}%"
                tree.insert("", "end", values=(p["pid"], p["name"], cpu, format_bytes(p["memory_bytes"])))
            tree.bind("<<TreeviewSelect>>", lambda _e: show_process_detail(tree, snapshot))
            detail = tk.StringVar(value="Selecione um processo para ver detalhes.")
            ttk.Label(result, textvariable=detail, style="PageHint.TLabel").pack(anchor="w", pady=4)
            tree._detail_var = detail
            ttk.Label(result, text=f"Histórico em memória: {len(history)} amostra(s), limitado a 60.", style="PageHint.TLabel").pack(anchor="w")

        def render_disks(data):
            clear_result()
            if not data["devices"]:
                add_metric("Saúde dos discos", data["state"], data["reason"])
            for disk in data["devices"]:
                state_text = disk["smart_state"].capitalize()
                detail = (f"{disk['vendor'] or ''} {disk['model'] or disk['name']} · "
                          f"{format_bytes(disk['capacity_bytes'] or 0)} · "
                          f"Temperatura: {disk['temperature_c'] if disk['temperature_c'] is not None else 'não disponível'} °C")
                if disk["wear"]:
                    detail += f" · Desgaste ({disk['wear']['attribute']}): {disk['wear']['value']}"
                add_metric(f"{state_text} · {disk['path']}", detail.strip(), disk["detail"])
                for indicator in disk["indicators"]:
                    ttk.Label(result, text=f"• {indicator}", style="PageHint.TLabel").pack(anchor="w", padx=10)
            ttk.Button(result, text="Atualizar SMART", command=load_disks).pack(anchor="e", pady=6)
            ttk.Label(result, text="Consulta somente leitura. SMART pode exigir permissões adicionais; a Nova não as solicita nem executa reparos.", style="PageHint.TLabel", wraplength=640).pack(anchor="w")

        def render_logs(rows):
            clear_result(); log_rows[:] = rows
            controls = ttk.Frame(result); controls.pack(fill="x", pady=(0, 6))
            search = tk.StringVar(); severity = tk.StringVar(value="Todas")
            category = tk.StringVar(value="Todas")
            ttk.Entry(controls, textvariable=search).pack(side="left", fill="x", expand=True, padx=(0, 5))
            ttk.Combobox(controls, textvariable=category, values=("Todas", "Nova", "Sistema"), state="readonly", width=10).pack(side="left", padx=2)
            ttk.Combobox(controls, textvariable=severity, values=("Todas", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), state="readonly", width=12).pack(side="left", padx=2)
            ttk.Button(controls, text="Atualizar", command=load_logs).pack(side="left", padx=2)
            table = ttk.Treeview(result, columns=("date", "severity", "category", "source", "message"), show="headings", height=12, style="Maintenance.Treeview")
            for col, title, width in (("date", "Data", 145), ("severity", "Gravidade", 90), ("category", "Origem", 75), ("source", "Componente", 130), ("message", "Evento", 330)):
                table.heading(col, text=title, command=lambda c=col: sort_logs(table, c))
                table.column(col, width=width, minwidth=65, anchor="w")
            table.pack(fill="both", expand=True)
            detail = tk.StringVar(value=f"{len(rows)} registro(s) carregado(s); limite de 500.")
            ttk.Label(result, textvariable=detail, style="PageHint.TLabel", wraplength=650).pack(anchor="w", pady=5)
            visible = {}
            def refresh(*_):
                table.delete(*table.get_children()); visible.clear()
                needle = search.get().casefold().strip()
                filtered = [r for r in rows if (severity.get() == "Todas" or r["severity"] == severity.get()) and (category.get() == "Todas" or r["category"] == category.get()) and (not needle or needle in " ".join(str(v) for v in r.values()).casefold())]
                for i, row in enumerate(filtered):
                    iid = str(i); visible[iid] = row
                    table.insert("", "end", iid=iid, values=(row["date"], row["severity"], row["category"], row["source"], row["message"][:180]))
                detail.set(f"{len(filtered)} registro(s) · conteúdo sensível conhecido é ocultado · limite de 500.")
            def selected(_event=None):
                sel = table.selection()
                if sel:
                    row = visible.get(sel[0], {})
                    detail.set(f"{row.get('date','')} · {row.get('severity','')} · {row.get('source','')}\n{row.get('message','')}")
            table.bind("<<TreeviewSelect>>", selected)
            search.trace_add("write", refresh); category.trace_add("write", refresh); severity.trace_add("write", refresh)
            refresh()

        def sort_logs(table, column):
            values = [(table.set(iid, column), iid) for iid in table.get_children()]
            for _, iid in sorted(values, reverse=True): table.move(iid, "", "end")

        def render_cleanup(data):
            clear_result(); cleanup_items[:] = data["items"]
            note = "Análise limitada; alguns itens podem não ter sido verificados." if not data["complete"] else f"{len(cleanup_items)} item(ns) elegível(is)."
            add_metric("Limpeza Assistida", note, "Somente itens antigos sob ~/.cache e /tmp pertencentes ao usuário atual.")
            table = ttk.Treeview(result, columns=("select", "name", "category", "size", "path"), show="headings", selectmode="extended", height=12, style="Maintenance.Treeview")
            for col, title, width in (("select", "Revisar", 55), ("name", "Item", 130), ("category", "Categoria", 100), ("size", "Espaço", 90), ("path", "Localização / motivo", 380)):
                table.heading(col, text=title); table.column(col, width=width, anchor="w")
            table.pack(fill="both", expand=True)
            for i, item in enumerate(cleanup_items):
                table.insert("", "end", iid=str(i), values=("□", item["name"], item["category"], format_bytes(item["bytes"]), item["path"] + " · " + item["reason"]))
            actions = ttk.Frame(result); actions.pack(fill="x", pady=6)
            ttk.Button(actions, text="Cancelar análise", command=cancel_event.set).pack(side="left")
            ttk.Button(actions, text="Remover selecionados…", style="Primary.TButton", command=lambda: confirm_cleanup(table)).pack(side="right")
            ttk.Label(result, text="A remoção é permanente. Links simbólicos, arquivos pessoais fora das áreas permitidas e itens sem propriedade do usuário são recusados.", style="PageHint.TLabel", wraplength=640).pack(anchor="w")

        def confirm_cleanup(table):
            selected = table.selection()
            items = [cleanup_items[int(i)] for i in selected]
            if not items: status.set("Selecione um ou mais itens para remover."); return
            amount = sum(item["bytes"] for item in items)
            listing = "\n".join(f"• {item['path']} ({format_bytes(item['bytes'])})" for item in items[:8])
            if len(items) > 8: listing += f"\n… e mais {len(items)-8} item(ns)"
            if not messagebox.askyesno("Confirmar remoção permanente", f"Serão removidos {len(items)} item(ns), estimativa {format_bytes(amount)}.\n\n{listing}\n\nDeseja continuar?", parent=window): return
            try: self._authorize_core_action("file.delete", confirmed=True)
            except (PermissionError, OSError) as exc:
                messagebox.showerror("Permissão necessária", str(exc), parent=window); return
            paths = [item["path"] for item in items]
            start_worker("Limpeza", lambda _p: delete_cleanup_items(paths, cancel_event=cancel_event))

        def render_backups(rows):
            clear_result(); backup_rows.clear()
            actions = ttk.Frame(result); actions.pack(fill="x", pady=(0, 6))
            ttk.Label(actions, text=f"Pasta: {backup_directory['path']}", style="PageHint.TLabel").pack(side="left", fill="x", expand=True)
            ttk.Button(actions, text="Alterar pasta…", command=choose_backup_directory).pack(side="right")
            ttk.Button(result, text="Criar backup agora", style="Primary.TButton", command=create_backup_now).pack(anchor="e", pady=(0, 6))
            table = ttk.Treeview(result, columns=("label", "date", "size", "integrity"), show="headings", height=9, style="Maintenance.Treeview")
            for col, title, width in (("label", "Identificação", 200), ("date", "Data", 185), ("size", "Tamanho", 90), ("integrity", "Integridade", 190)):
                table.heading(col, text=title); table.column(col, width=width, anchor="w")
            table.pack(fill="both", expand=True)
            details = tk.StringVar(value="Selecione um backup para consultar o conteúdo permitido.")
            ttk.Label(result, textvariable=details, style="PageHint.TLabel", wraplength=650).pack(anchor="w", pady=6)
            row_by_id = {}
            for index, item in enumerate(rows):
                iid = str(index); row_by_id[iid] = item
                backup_rows[iid] = item
                table.insert("", "end", iid=iid, values=(item["label"], item["created_at"], format_bytes(item["size"]), item["integrity"]))
            def selected(_event=None):
                sel = table.selection()
                item = row_by_id.get(sel[0]) if sel else None
                if item:
                    content = ", ".join(entry["name"] + (" (ausente no momento do backup)" if not entry["present"] else f" · {format_bytes(entry['size'])}") for entry in item["contents"])
                    details.set(f"Conteúdo: {content or 'indisponível'}\nArquivo: {Path(item['path']).name}")
            table.bind("<<TreeviewSelect>>", selected)
            footer = ttk.Frame(result); footer.pack(fill="x", pady=(4, 0))
            ttk.Button(footer, text="Renomear", command=lambda: backup_action(table, "rename")).pack(side="left", padx=2)
            ttk.Button(footer, text="Exportar…", command=lambda: backup_action(table, "export")).pack(side="left", padx=2)
            ttk.Button(footer, text="Restaurar…", command=lambda: backup_action(table, "restore")).pack(side="left", padx=2)
            ttk.Button(footer, text="Excluir…", command=lambda: backup_action(table, "delete")).pack(side="right", padx=2)
            ttk.Button(footer, text="Atualizar lista", command=load_backups).pack(side="right", padx=2)
            if not rows:
                status.set("Ainda não há backups neste diretório.")

        def selected_backup(table):
            selection = table.selection()
            if not selection: return None
            return backup_rows.get(selection[0])

        def backup_action(table, action):
            item = selected_backup(table)
            if not item: status.set("Selecione um backup."); return
            if action == "rename":
                if not item["integrity"].startswith("Íntegro"): status.set("Backups inválidos não podem ser renomeados."); return
                try: self._authorize_core_action("file.write", confirmed=True)
                except (PermissionError, OSError) as exc: messagebox.showerror("Permissão necessária", str(exc), parent=window); return
                label = simpledialog.askstring("Renomear backup", "Nova identificação:", initialvalue=item["label"], parent=window)
                if label is None: return
                try: rename_backup(item["path"], backup_directory["path"], label)
                except (OSError, ValueError) as exc: messagebox.showerror("Não foi possível renomear", str(exc), parent=window); return
                load_backups(); return
            if action == "delete":
                if not messagebox.askyesno("Excluir backup", f"Excluir permanentemente {Path(item['path']).name}?", parent=window): return
                try: self._authorize_core_action("file.delete", confirmed=True)
                except (PermissionError, OSError) as exc: messagebox.showerror("Permissão necessária", str(exc), parent=window); return
                start_worker("Backup excluído", lambda _p: (delete_backup(item["path"], backup_directory["path"]), True)[1]); return
            if not item["integrity"].startswith("Íntegro"):
                status.set("Este backup não passou na verificação de integridade."); return
            if action == "export":
                try: self._authorize_core_action("file.write", confirmed=True)
                except (PermissionError, OSError) as exc: messagebox.showerror("Permissão necessária", str(exc), parent=window); return
                destination = filedialog.asksaveasfilename(parent=window, title="Exportar backup", initialfile=Path(item["path"]).name, defaultextension=".nova-backup.json", filetypes=(("Backup Nova", "*.nova-backup.json"),))
                if destination: start_worker("Backup exportado", lambda _p: export_backup(item["path"], backup_directory["path"], destination))
                return
            manager = getattr(self, "profile_manager", None)
            if manager is None: status.set("Gerenciador de perfil indisponível."); return
            try: preview = preview_restore(item["path"], backup_directory["path"], manager)
            except (OSError, ValueError) as exc: messagebox.showerror("Backup incompatível", str(exc), parent=window); return
            changes = [f"• {change['name']}: {change['action']}" for change in preview["changes"] if change["changed"]]
            if not changes: status.set("As configurações atuais já correspondem a este backup."); return
            prompt = (f"Restaurar ‘{preview['label']}’ modificará:\n" + "\n".join(changes) +
                      "\n\nUma cópia de segurança do estado atual será criada antes. Deseja continuar?")
            if not messagebox.askyesno("Confirmar restauração", prompt, parent=window): return
            try: self._authorize_core_action("file.write", confirmed=True)
            except (PermissionError, OSError) as exc: messagebox.showerror("Permissão necessária", str(exc), parent=window); return
            start_worker("Backup restaurado", lambda _p: restore_backup(item["path"], backup_directory["path"], manager))

        def create_backup_now():
            manager = getattr(self, "profile_manager", None)
            if manager is None: status.set("Gerenciador de perfil indisponível."); return
            try: self._authorize_core_action("file.read")
            except (PermissionError, OSError) as exc: messagebox.showerror("Permissão necessária", str(exc), parent=window); return
            try: self._authorize_core_action("file.write", confirmed=True)
            except (PermissionError, OSError) as exc: messagebox.showerror("Permissão necessária", str(exc), parent=window); return
            label = simpledialog.askstring("Criar backup", "Identificação do backup:", initialvalue="Backup manual", parent=window)
            if label is None: return
            start_worker("Backup criado", lambda _p: create_backup(manager, backup_directory["path"], label=label))

        def choose_backup_directory():
            chosen = filedialog.askdirectory(parent=window, initialdir=str(backup_directory["path"]), mustexist=False)
            if not chosen: return
            try: self._authorize_core_action("file.write", confirmed=True)
            except (PermissionError, OSError) as exc: messagebox.showerror("Permissão necessária", str(exc), parent=window); return
            try: backup_directory["path"] = save_backup_directory(chosen)
            except (OSError, ValueError) as exc: messagebox.showerror("Diretório inválido", str(exc), parent=window); return
            load_backups()

        def period_seconds():
            return {"1 hora": 3600, "6 horas": 21600, "24 horas": 86400,
                    "7 dias": 604800, "30 dias": 2592000}.get(performance_period.get(), 86400)

        def load_performance_history():
            if performance_monitor is None:
                status.set("Monitor de desempenho indisponível nesta sessão."); return
            page_title.set("Histórico de Desempenho"); clear_result()
            hours = period_seconds() / 3600
            def query(_progress):
                now = time.time(); span = period_seconds()
                current = performance_monitor.store.samples(since=now - span, until=now, limit=5000)
                previous = performance_monitor.store.samples(since=now - span * 2, until=now - span, limit=5000)
                return {"current": current, "previous": previous, "hours": hours}
            start_worker("Histórico de Desempenho", query)

        def render_performance_history(data):
            clear_result(); performance_records[:] = data["current"]
            samples = data["current"]; previous = data["previous"]
            controls = ttk.Frame(result); controls.pack(fill="x", pady=(0, 6))
            ttk.Combobox(controls, textvariable=performance_period,
                         values=("1 hora", "6 horas", "24 horas", "7 dias", "30 dias"),
                         state="readonly", width=13).pack(side="left")
            ttk.Button(controls, text="Atualizar", command=load_performance_history).pack(side="left", padx=5)
            enabled = tk.BooleanVar(value=performance_monitor.settings["enabled"])
            ttk.Checkbutton(controls, text="Coleta ativa", variable=enabled,
                            command=lambda: configure_monitor(enabled=enabled.get())).pack(side="left", padx=4)
            ttk.Label(controls, text="Intervalo (s)").pack(side="left", padx=(4, 1))
            interval = tk.StringVar(value=str(performance_monitor.settings["interval_seconds"]))
            ttk.Spinbox(controls, from_=60, to=3600, increment=60, width=6,
                        textvariable=interval).pack(side="left")
            ttk.Button(controls, text="Aplicar", command=lambda: apply_interval(interval)).pack(side="left", padx=3)
            ttk.Button(controls, text="Limpar histórico…", command=clear_performance_history).pack(side="right")
            if not samples:
                add_metric("Histórico vazio", "Ainda não há amostras para este período.",
                           f"A coleta é feita a cada {performance_monitor.settings['interval_seconds']} segundos quando está ativa.")
                return
            for metric, label, column, suffix in (("cpu", "CPU", "cpu", "%"), ("memory", "RAM", "memory", "%"), ("storage", "Armazenamento", "storage", "%"), ("temperature", "Temperatura", "temperature", " °C")):
                vals = [row[column] for row in samples if row[column] is not None]
                old = [row[column] for row in previous if row[column] is not None]
                latest = f"{vals[-1]:.1f}{suffix}" if vals else "Indisponível"
                peak = f" · pico {max(vals):.1f}{suffix}" if vals else ""
                comparison = f" · período anterior {sum(old)/len(old):.1f}{suffix}" if old else " · sem período anterior"
                add_metric(label, latest + peak, f"Média atual {sum(vals)/len(vals):.1f}{suffix}{comparison}" if vals else "Nenhuma leitura disponível.")
            chart = tk.Canvas(result, height=120, bg=COLORS["surface"], highlightthickness=0)
            chart.pack(fill="x", pady=4)
            width = max(100, chart.winfo_width()); plot = samples[-300:]
            for key, color in (("cpu", COLORS["accent"]), ("memory", "#8B6FE8"), ("storage", "#D18B3C"), ("temperature", "#D84B65")):
                pts = []
                for index, row in enumerate(plot):
                    if row[key] is None: continue
                    x = 8 + index * max(1, (width - 16) / max(1, len(plot) - 1))
                    scale = 110 if key == "temperature" else 100
                    y = 110 - min(scale, row[key]) / scale * 96
                    pts.extend((x, y))
                if len(pts) >= 4: chart.create_line(*pts, fill=color, width=2, smooth=True)
            ttk.Label(result, text="CPU · RAM · armazenamento (%) · temperatura (°C). O gráfico mostra até 300 amostras do período.", style="PageHint.TLabel").pack(anchor="w")
            net_up = [r["network_up"] for r in samples if r["network_up"] is not None]
            net_down = [r["network_down"] for r in samples if r["network_down"] is not None]
            add_metric("Rede", f"↑ {format_bytes(net_up[-1])}/s · ↓ {format_bytes(net_down[-1])}/s" if net_up and net_down else "Aguardando duas amostras", f"Picos: enviado {format_bytes(max(net_up)) if net_up else '—'}/s · recebido {format_bytes(max(net_down)) if net_down else '—'}/s")
            ttk.Label(result, text=f"{len(samples)} amostra(s) no período · retenção máxima de 30 dias.", style="PageHint.TLabel").pack(anchor="w")

        def configure_monitor(**changes):
            if performance_monitor is None: return
            try:
                self._authorize_core_action("file.write", confirmed=True)
                performance_monitor.configure(**changes)
                status.set("Configuração do monitor atualizada.")
            except (OSError, ValueError, PermissionError) as exc:
                messagebox.showerror("Não foi possível atualizar", str(exc), parent=window)

        def apply_interval(variable):
            try: value = int(variable.get())
            except ValueError:
                messagebox.showerror("Intervalo inválido", "Informe um número de segundos.", parent=window); return
            if not 60 <= value <= 3600:
                messagebox.showerror("Intervalo inválido", "O intervalo deve ser de 60 a 3600 segundos.", parent=window); return
            configure_monitor(interval_seconds=value)

        def clear_performance_history():
            if performance_monitor is None: return
            if not messagebox.askyesno("Limpar histórico", "Apagar amostras e alertas históricos?", parent=window): return
            try: self._authorize_core_action("file.delete", confirmed=True)
            except (PermissionError, OSError) as exc: messagebox.showerror("Permissão necessária", str(exc), parent=window); return
            start_worker("Histórico limpo", lambda _p: (performance_monitor.clear_history(), True)[1])

        def load_alerts():
            if performance_monitor is None:
                status.set("Monitor de alertas indisponível nesta sessão."); return
            page_title.set("Alertas"); clear_result()
            start_worker("Alertas", lambda _p: performance_monitor.store.alerts(limit=500))

        def render_action_history(rows):
            clear_result()
            table = ttk.Treeview(result, columns=("date", "action", "status", "origin", "result"), show="headings", height=14, style="Maintenance.Treeview")
            for col, title, width in (("date", "Data", 150), ("action", "Ação", 170), ("status", "Estado", 130), ("origin", "Origem", 100), ("result", "Resultado / erro", 260)):
                table.heading(col, text=title); table.column(col, width=width, anchor="w")
            table.pack(fill="both", expand=True)
            for row in rows:
                table.insert("", "end", values=(row["created_at"], row["action"], row["status"], row["origin"], row.get("error_code") or row["result"]))
            ttk.Label(result, text="Histórico local limitado a 500 entradas. Perguntas e argumentos não são armazenados.", style="PageHint.TLabel", wraplength=650).pack(anchor="w", pady=5)

        def load_action_history():
            page_title.set("Histórico de Ações"); clear_result()
            if action_history is None:
                status.set("O armazenamento do histórico está indisponível."); return
            def list_actions():
                rows = action_history.list()
                integration = getattr(self, "nova_integration", None)
                dispatcher = getattr(getattr(integration, "cognition", None), "dispatcher", None)
                existing_log = getattr(dispatcher, "action_log", None)
                if existing_log is not None and existing_log is not action_history:
                    state_map = {"succeeded": "Concluída", "failed": "Falhou",
                                 "cancelled": "Cancelada", "timeout": "Falhou"}
                    for entry in existing_log.entries():
                        rows.append({"created_at": entry.timestamp, "action": entry.action,
                                     "status": state_map.get(entry.outcome, "Falhou"),
                                     "origin": "Conversação", "result": "Registro da ação existente.",
                                     "error_code": entry.error_code})
                rows.sort(key=lambda row: row["created_at"], reverse=True)
                return rows[:200]
            start_worker("Histórico de Ações", lambda _p: list_actions())

        def render_consultant():
            clear_result()
            add_metric("Converse sobre seu computador", "A Nova usa observações atuais dos serviços do Meu Computador.", "A resposta segue pela conversa habitual da Nova e aparece no balão; não há um segundo histórico de chat.")
            ttk.Label(result, text="A coleta acontece sob demanda e a resposta usa a conversa habitual da Nova. Fontes indisponíveis serão identificadas como tal.", style="PageHint.TLabel", wraplength=640).pack(anchor="w", pady=(0, 8))
            ttk.Label(result, text="As observações relevantes acompanham apenas esta pergunta ao provedor configurado. O histórico de ações não guarda a pergunta nem os dados técnicos.", style="PageHint.TLabel", wraplength=640).pack(anchor="w", pady=(0, 8))
            hint = tk.StringVar(value="Pergunte sobre RAM, espaço, inicialização, rede, SMART, logs ou desempenho.")
            ttk.Label(result, textvariable=hint, style="PageHint.TLabel", wraplength=640).pack(anchor="w")
            controls = ttk.Frame(result); controls.pack(fill="x", pady=8)
            def send_question():
                ask = getattr(self, "_ask_question", None)
                if not callable(ask):
                    hint.set("A conversa da Nova não está disponível nesta sessão."); return
                text = ask()
                if state["closed"]:
                    return
                if not text:
                    return
                text = text.strip()
                if not text or len(text) > 2000:
                    hint.set("A pergunta deve ter até 2.000 caracteres."); return
                try:
                    self._authorize_core_action("ai.use")
                    lowered = text.casefold()
                    if any(term in lowered for term in ("lento", "travando", "processo", "consumindo", "consome", "maior uso", "diagnóstico", "diagnostico")):
                        self._authorize_core_action("system.process.read")
                    if any(term in lowered for term in ("aplicativo", "aplicativos", "programa", "inicializa", "iniciam", "startup", "atualização", "atualizações", "atualiza")):
                        self._authorize_core_action("system.app.read")
                    if any(term in lowered for term in ("rede", "conexão", "internet", "wi-fi", "wifi")):
                        self._authorize_core_action("network.access", confirmed=True)
                    if any(term in lowered for term in ("log", "erro", "falha", "serviço")):
                        self._authorize_core_action("system.maintenance.read")
                    if any(term in lowered for term in ("limpeza", "limpar", "cache", "temporário")):
                        self._authorize_core_action("file.read")
                except (PermissionError, OSError) as exc:
                    consultant_action["id"] = record_consultant_action(
                        "Aguardando autorização", result="Uma permissão necessária não foi concedida.",
                        error_code=type(exc).__name__,
                    )
                    hint.set(f"Permissão necessária para usar a conversa da Nova: {exc}"); return
                user_question = text
                consultant_action["id"] = record_consultant_action(
                    "Em andamento", result="Coletando fontes relevantes para a pergunta.",
                )
                start_worker("Contexto do Consultor", lambda _p: {
                    "question": user_question,
                    "action_id": consultant_action["id"],
                    "context": collect_computer_context(
                        user_question,
                        performance_store=(performance_monitor.store if performance_monitor else None),
                        system_monitor=getattr(self, "system_monitor", None),
                        cancel_event=cancel_event,
                    ),
                })
            ttk.Button(controls, text="Perguntar na conversa da Nova", style="Primary.TButton", command=send_question).pack(side="right")
            ttk.Button(controls, text="Cancelar coleta", command=cancel_event.set).pack(side="left")

        def render_alerts(rows):
            clear_result(); alert_records[:] = rows
            controls = ttk.Frame(result); controls.pack(fill="x", pady=(0, 6))
            category = tk.StringVar(value="Todas")
            severity = tk.StringVar(value="Todas")
            ttk.Combobox(controls, textvariable=category,
                         values=("Todas", *PERFORMANCE_CATEGORIES), state="readonly", width=17).pack(side="left")
            ttk.Combobox(controls, textvariable=severity,
                         values=("Todas", "Atenção", "Crítico"), state="readonly", width=12).pack(side="left", padx=5)
            ttk.Button(controls, text="Atualizar", command=load_alerts).pack(side="left")
            mute = tk.BooleanVar(value=False)
            ttk.Checkbutton(controls, text="Silenciar categoria", variable=mute,
                            command=lambda: toggle_alert_mute(category, mute)).pack(side="right")
            thresholds = performance_monitor.settings["thresholds"]
            limits = ttk.Frame(result); limits.pack(fill="x", pady=(0, 5))
            values = {}
            for name, caption in (("memory", "RAM %"), ("cpu", "CPU %"),
                                  ("storage", "Disco %"), ("temperature", "Temp °C")):
                ttk.Label(limits, text=caption).pack(side="left", padx=(2, 1))
                variable = tk.StringVar(value=str(round(thresholds[name])))
                ttk.Spinbox(limits, from_=1, to=100, width=4, textvariable=variable).pack(side="left", padx=(0, 4))
                values[name] = variable
            ttk.Label(limits, text="Confirmar (s)").pack(side="left", padx=(4, 1))
            confirmation = tk.StringVar(value=str(max(performance_monitor.settings["confirm_seconds"], performance_monitor.settings["cpu_confirm_seconds"])))
            ttk.Spinbox(limits, from_=60, to=86400, increment=60, width=6, textvariable=confirmation).pack(side="left", padx=(0, 4))
            ttk.Label(limits, text="Repetir (min)").pack(side="left", padx=(3, 1))
            repeat = tk.StringVar(value=str(performance_monitor.settings["repeat_minutes"]))
            ttk.Spinbox(limits, from_=1, to=1440, width=5, textvariable=repeat).pack(side="left", padx=(0, 4))
            def save_alert_limits():
                try:
                    threshold_values = {key: float(variable.get()) for key, variable in values.items()}
                    seconds = int(confirmation.get()); repeat_minutes = int(repeat.get())
                    if not 60 <= seconds <= 86400 or not 1 <= repeat_minutes <= 1440: raise ValueError("Os tempos estão fora dos limites permitidos.")
                    configure_monitor(thresholds=threshold_values, confirm_seconds=seconds,
                                      cpu_confirm_seconds=seconds,
                                      repeat_minutes=repeat_minutes)
                except ValueError as exc:
                    messagebox.showerror("Limites inválidos", str(exc), parent=window)
            ttk.Button(limits, text="Aplicar", command=save_alert_limits).pack(side="right", padx=2)
            current = tk.StringVar(value="Selecione uma categoria para consultar os controles de silêncio.")
            ttk.Label(result, textvariable=current, style="PageHint.TLabel").pack(anchor="w", pady=(0, 5))
            table = ttk.Treeview(result, columns=("date", "category", "severity", "title"), show="headings", height=11, style="Maintenance.Treeview")
            for col, title, width in (("date", "Data", 165), ("category", "Categoria", 120), ("severity", "Gravidade", 90), ("title", "Alerta", 330)):
                table.heading(col, text=title); table.column(col, width=width, anchor="w")
            table.pack(fill="both", expand=True)
            details = tk.StringVar(value=f"{len(rows)} alerta(s) armazenado(s).")
            ttk.Label(result, textvariable=details, style="PageHint.TLabel", wraplength=650).pack(anchor="w", pady=5)
            visible = {}
            def refresh(*_):
                table.delete(*table.get_children()); visible.clear()
                if category.get() != "Todas":
                    muted = category.get() in performance_monitor.settings["silenced_categories"]
                    mute.set(muted); current.set(f"{category.get()} · {'silenciada' if muted else 'ativa'}")
                filtered = [r for r in rows if (category.get() == "Todas" or r["category"] == category.get()) and (severity.get() == "Todas" or r["severity"] == severity.get())]
                for i, row in enumerate(filtered):
                    iid = str(i); visible[iid] = row
                    date = datetime.fromtimestamp(row["created_at"]).astimezone().strftime("%Y-%m-%d %H:%M")
                    table.insert("", "end", iid=iid, values=(date, row["category"], row["severity"], row["title"]))
                details.set(f"{len(filtered)} alerta(s) · ordenados do mais recente.")
            def show_detail(_event=None):
                sel = table.selection()
                row = visible.get(sel[0]) if sel else None
                if row:
                    date = datetime.fromtimestamp(row["created_at"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                    details.set(f"{row['description']}\nEvidência: {row['evidence']}\nRecomendação: {row['recommendation']}\nData: {date} · notificação enviada: {'sim' if row['notified'] else 'não'}")
            table.bind("<<TreeviewSelect>>", show_detail)
            category.trace_add("write", refresh); severity.trace_add("write", refresh); refresh()

        def toggle_alert_mute(category_var, mute_var):
            if performance_monitor is None or category_var.get() == "Todas":
                status.set("Escolha uma categoria específica para silenciar."); return
            muted = set(performance_monitor.settings["silenced_categories"])
            name = category_var.get()
            if mute_var.get(): muted.add(name)
            else: muted.discard(name)
            configure_monitor(silenced_categories=sorted(muted))

        def consultant_performance_context(hours=24):
            return performance_context(performance_monitor.store, hours=hours) if performance_monitor else {"schema": "nova-performance-context.v1", "samples": 0, "alerts": []}

        def show_process_detail(tree, snapshot):
            selected = tree.selection()
            if not selected: return
            pid = int(tree.item(selected[0], "values")[0])
            item = next((p for p in snapshot["processes"] if p["pid"] == pid), None)
            if item:
                tree._detail_var.set(f"{item['name']} · PID {pid} · usuário: {item['username'] or 'indisponível'} · RAM: {format_bytes(item['memory_bytes'])} ({item['memory_percent']:.1f}%)")

        def run_network_checks():
            snapshot = snapshots["network"]
            if not snapshot or state["busy"]: return
            monitors["network"] = False
            stop_timer("network")
            clear_result(); status.set("Executando verificações solicitadas…")
            start_worker("Diagnóstico de rede", lambda _p: run_connectivity_diagnostics(snapshot, cancel_event=cancel_event))

        def stop_timer(name):
            timer = timers[name]
            if timer is not None:
                try: window.after_cancel(timer)
                except tk.TclError: pass
                timers[name] = None

        def schedule_sample(name):
            stop_timer(name)
            if not monitors[name] or state["closed"]: return
            delay = max(1, int(network_interval.get() or 2)) if name == "network" else 5
            timers[name] = window.after(delay * 1000, lambda: sample_page(name))

        def sample_page(name):
            if state["busy"] or state["closed"] or not monitors[name]: return
            if name == "network":
                start_worker("Amostra de rede", lambda _p: network_sampler.sample())
            else:
                start_worker("Saúde do Sistema", lambda _p: health_sampler.sample(getattr(self, "system_monitor", None)))

        def set_busy(busy):
            state["busy"] = busy
            for button in nav_buttons:
                button.configure(state="disabled" if busy else "normal")

        def poll():
            state["job"] = None
            if state["closed"]:
                return
            final = None
            while True:
                try:
                    message = results.get_nowait()
                except queue.Empty:
                    break
                if message[0] != state["token"]:
                    continue
                _token, kind, section, value, error = message
                if kind == "progress":
                    if section == "Armazenamento":
                        status.set(
                            f"Analisando… {value['files']:,} arquivos · "
                            f"{value['directories']:,} pastas · "
                            f"{format_bytes(value['bytes'])} lidos"
                        )
                else:
                    final = (section, value, error)
            if final is None:
                if state["busy"]:
                    state["job"] = window.after(100, poll)
                return
            section, value, error = final
            set_busy(False)
            if error:
                if section == "Contexto do Consultor":
                    update_consultant_action(consultant_action["id"], "Falhou", result="Falha ao coletar o contexto local.", error_code="context_unavailable")
                status.set(f"Não foi possível consultar {section.lower()}: {error}")
                return
            if section == "Armazenamento":
                storage_scan["files"] = value["largest_files"]
                render_storage_result(value)
            elif section == "Inicialização":
                render_startup(value)
                status.set(f"{len(value)} entrada(s) encontrada(s).")
            elif section == "Visão geral":
                clear_result()
                render_overview(value)
                status.set("Informações atualizadas agora.")
            elif section == "Rede":
                clear_result()
                render_network(value)
                status.set("Monitoramento atualizado.")
                schedule_sample("network")
            elif section == "Amostra de rede":
                clear_result(); render_network(value)
                status.set("Monitoramento atualizado."); schedule_sample("network")
            elif section == "Diagnóstico de rede":
                clear_result()
                for check in value["checks"]:
                    add_metric(check["name"], check["state"], check["evidence"])
                status.set("Verificações concluídas; resultados não confirmam todo o percurso da rede.")
            elif section == "Saúde do Sistema":
                render_health(value)
                status.set("Amostra de saúde atualizada.")
                schedule_sample("health")
            elif section == "Saúde dos Discos":
                render_disks(value); status.set("Consulta SMART concluída.")
            elif section == "Central de Logs":
                render_logs(value); status.set(f"{len(value)} registro(s) disponível(is).")
            elif section == "Limpeza Assistida":
                render_cleanup(value); status.set("Análise concluída; nenhum item foi removido.")
            elif section == "Limpeza":
                render_cleanup({"items": [], "complete": True})
                status.set(f"Removidos: {len(value['removed'])} · falhas: {len(value['errors'])}" + (" · cancelada" if value["cancelled"] else ""))
                for error in value["errors"]:
                    ttk.Label(result, text=f"{error['path']}: {error['error']}", style="PageHint.TLabel", wraplength=650).pack(anchor="w")
            elif section == "Backups":
                render_backups(value); status.set(f"{len(value)} backup(s) listado(s).")
            elif section.startswith("Backup "):
                status.set({"Backup criado": "Backup criado e verificado.",
                            "Backup excluído": "Backup excluído.",
                            "Backup exportado": f"Backup exportado: {Path(value).name}",
                            "Backup restaurado": f"Configurações restauradas; cópia de segurança: {Path(value['safety_backup']).name}"}.get(section, "Operação concluída."))
                load_backups()
            elif section == "Histórico de Desempenho":
                render_performance_history(value)
                status.set(f"{len(value['current'])} amostra(s) no período selecionado.")
            elif section == "Alertas":
                render_alerts(value)
                status.set(f"{len(value)} alerta(s) carregado(s).")
            elif section == "Histórico limpo":
                status.set("Histórico e alertas apagados."); load_performance_history()
            elif section == "Contexto do Consultor":
                if value.get("context", {}).get("cancelled"):
                    update_consultant_action(value.get("action_id"), "Cancelada", result="Coleta cancelada pelo usuário.")
                    status.set("Consulta cancelada antes de enviar à conversa da Nova.")
                else:
                    submit = getattr(self, "ask_computer_consultant", None)
                    if callable(submit):
                        try:
                            submit(value["question"], value["context"], action_history_id=value.get("action_id"))
                            status.set("Pergunta enviada à conversa da Nova; a resposta aparecerá no balão habitual.")
                        except (PermissionError, RuntimeError, ValueError) as exc:
                            update_consultant_action(value.get("action_id"), "Falhou", result="A conversa não aceitou a pergunta.", error_code=type(exc).__name__)
                            status.set(f"A pergunta não foi enviada: {exc}")
                    else:
                        status.set("A conversa da Nova não está disponível neste momento.")
            elif section == "Histórico de Ações":
                render_action_history(value)
                status.set(f"{len(value)} ação(ões) recente(s).")
            elif section == "Armazenamento geral":
                render_storage_home(value)
                status.set("Escolha uma pasta para iniciar uma análise detalhada.")

        def start_worker(section, function, *, progress=False):
            if state["busy"] or state["closed"]:
                return
            state["token"] += 1
            token = state["token"]
            cancel_event.clear()
            set_busy(True)
            status.set("Consultando o sistema…")

            def report(metrics):
                results.put((token, "progress", section, metrics, None))

            def worker():
                try:
                    value = function(report if progress else None)
                    message = (token, "result", section, value, None)
                except Exception as exc:
                    message = (token, "result", section, None,
                               f"{type(exc).__name__}: {exc}")
                results.put(message)

            try:
                threading.Thread(target=worker, name="computer-center", daemon=True).start()
                state["job"] = window.after(100, poll)
            except (OSError, RuntimeError) as exc:
                set_busy(False)
                if section == "Contexto do Consultor":
                    update_consultant_action(consultant_action["id"], "Falhou", result="Não foi possível iniciar a coleta.", error_code=type(exc).__name__)
                status.set(f"Não foi possível iniciar a consulta: {exc}")

        def startup_filtered_rows(search, state_filter):
            needle = search.get().strip().casefold()
            wanted_state = state_filter.get()
            rows = [item for item in startup_items.values()
                    if (not needle or needle in " ".join((
                        item["name"], item["description"], item["path"],
                        item["kind"], item["command"],
                    )).casefold())
                    and (wanted_state == "Todos" or item["state"] == wanted_state)]
            column = startup_sort["column"]
            rows.sort(key=lambda item: item.get(column, "").casefold(),
                      reverse=startup_sort["reverse"])
            return rows

        def render_startup(entries):
            clear_result()
            startup_items.clear()
            for index, entry in enumerate(entries):
                startup_items[str(index)] = entry
            controls = ttk.Frame(result)
            controls.pack(fill="x", pady=(0, 8))
            search = tk.StringVar()
            search_entry = ttk.Entry(controls, textvariable=search)
            search_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
            filter_state = tk.StringVar(value="Todos")
            ttk.Combobox(controls, textvariable=filter_state,
                         values=("Todos", "Habilitado", "Desabilitado"),
                         state="readonly", width=16).pack(side="left")
            refresh = ttk.Button(controls, text="Atualizar lista",
                                 command=lambda: load_startup())
            refresh.pack(side="left", padx=(6, 0))
            columns = ("name", "description", "state", "kind")
            table = ttk.Treeview(result, columns=columns, show="headings",
                                 height=10, style="Maintenance.Treeview")
            for column, title, width in (
                ("name", "Aplicativo", 210), ("description", "Descrição", 245),
                ("state", "Estado", 110), ("kind", "Tipo", 90),
            ):
                table.heading(column, text=title,
                              command=lambda key=column: sort_startup(key, table, search, filter_state))
                table.column(column, width=width, minwidth=80, anchor="w")
            table.pack(fill="both", expand=True)
            details = tk.StringVar(value="Selecione uma entrada para consultar origem e comando.")
            ttk.Label(result, textvariable=details, style="PageHint.TLabel",
                      wraplength=650).pack(fill="x", pady=(8, 4))
            actions = ttk.Frame(result)
            actions.pack(fill="x")
            toggle = ttk.Button(actions, text="Habilitar / desabilitar", state="disabled")
            toggle.pack(side="right")
            visible = {}

            def refresh_rows(*_args):
                table.delete(*table.get_children())
                visible.clear()
                for key, item in enumerate(startup_filtered_rows(search, filter_state)):
                    iid = str(key)
                    table.insert("", "end", iid=iid,
                                 values=(item["name"], item["description"],
                                         item["state"], item["kind"]))
                    visible[iid] = item
                if not visible:
                    status.set("Nenhuma entrada corresponde à pesquisa ou ao filtro.")

            table._refresh_startup_rows = refresh_rows

            def select(_event=None):
                selected = table.selection()
                item = visible.get(selected[0]) if selected else None
                if item is None:
                    toggle.configure(state="disabled")
                    return
                info = f"{item['path']}\nTipo: {item['kind']} · Estado: {item['state']}"
                if item["command"]:
                    info += f"\nComando: {item['command']}"
                if item["error"]:
                    info += f"\nAtenção: {item['error']}"
                details.set(info)
                toggle.configure(
                    state="disabled" if item["error"] else "normal",
                    text="Desabilitar inicialização" if item["state"] == "Habilitado"
                    else "Habilitar inicialização",
                    command=lambda row=item: change_startup(row),
                )

            table.bind("<<TreeviewSelect>>", select)
            search.trace_add("write", refresh_rows)
            filter_state.trace_add("write", refresh_rows)
            refresh_rows()

        def sort_startup(column, table, search, filter_state):
            if startup_sort["column"] == column:
                startup_sort["reverse"] = not startup_sort["reverse"]
            else:
                startup_sort.update(column=column, reverse=False)
            table.selection_remove(table.selection())
            table._refresh_startup_rows()

        def load_startup():
            page_title.set("Gerenciador de inicialização")
            clear_result()
            start_worker("Inicialização", lambda _progress: discover_startup_entries())

        def change_startup(item):
            enabled = item["state"] != "Habilitado"
            action = "habilitar" if enabled else "desabilitar"
            prompt = (f"Deseja {action} {item['name']} na inicialização do usuário atual?\n\n"
                      "A configuração original será preservada em um backup quando houver um arquivo do usuário.")
            if not messagebox.askyesno("Confirmar alteração", prompt, parent=window):
                return
            try:
                self._authorize_core_action("system.maintenance", confirmed=True)
                outcome = set_startup_enabled(item, enabled)
                status.set(f"Inicialização atualizada: {outcome['path']}")
                load_startup()
            except (PermissionError, OSError, ValueError, FileNotFoundError) as exc:
                messagebox.showerror("Não foi possível alterar", str(exc), parent=window)

        def render_storage_home(data):
            clear_result()
            add_metric(data["path"],
                       f"{format_bytes(data['free'])} disponíveis de {format_bytes(data['total'])}",
                       f"{format_bytes(data['used'])} usados · {data['used'] / max(1, data['total']) * 100:.1f}%")
            ttk.Label(result, text="Volumes montados", style="CardTitle.TLabel").pack(anchor="w", pady=(4, 6))
            for volume in data["volumes"]:
                add_metric(volume["mountpoint"],
                           f"{format_bytes(volume['free'])} livres de {format_bytes(volume['total'])}",
                           f"{volume['device']} · {volume['filesystem']} · {volume['percent']:.1f}% usados")
            actions = ttk.Frame(result)
            actions.pack(fill="x", pady=(6, 8))
            ttk.Button(actions, text="Escolher pasta…", command=choose_storage_directory).pack(side="left")
            ttk.Label(actions, textvariable=storage_directory_var,
                      style="PageHint.TLabel").pack(side="left", padx=8)
            ttk.Button(actions, text="Analisar pasta", style="Primary.TButton",
                       command=start_storage_scan).pack(side="right")

        def choose_storage_directory():
            selected = filedialog.askdirectory(parent=window,
                                               initialdir=storage_scan["directory"],
                                               mustexist=True)
            if selected:
                storage_scan["directory"] = str(Path(selected).resolve())
                storage_directory_var.set(storage_scan["directory"])
                status.set(f"Pasta selecionada: {storage_scan['directory']}")

        def start_storage_scan(directory=None):
            if directory:
                storage_scan["directory"] = directory
                storage_directory_var.set(directory)
            selected = storage_scan["directory"]
            try:
                self._authorize_core_action("file.read")
            except (PermissionError, OSError) as exc:
                status.set(f"Permissão necessária para analisar esta pasta: {exc}")
                return
            page_title.set("Analisador de armazenamento")
            clear_result()
            progress = ttk.Progressbar(result, mode="indeterminate")
            progress.pack(fill="x", pady=(0, 8))
            progress.start(12)
            ttk.Button(result, text="Cancelar análise",
                       command=cancel_event.set).pack(anchor="e", pady=(0, 8))
            start_worker(
                "Armazenamento",
                lambda callback: analyze_directory(
                    selected, cancel_event=cancel_event,
                    progress_callback=callback,
                ), progress=True,
            )

        def render_storage_result(data):
            clear_result()
            status_text = ("Análise cancelada; resultados parciais." if data["cancelled"]
                           else "Análise parcial; alguns itens não puderam ser lidos." if not data["complete"]
                           else "Análise concluída.")
            status.set(status_text)
            add_metric(data["path"], format_bytes(data["bytes_scanned"]),
                       f"{data['files']:,} arquivos · {data['directories_count']:,} pastas · "
                       f"{data['inaccessible']} erro(s) de acesso")
            folder_card = ttk.Frame(result, style="Card.TFrame", padding=10)
            folder_card.pack(fill="both", expand=True, pady=(0, 8))
            ttk.Label(folder_card, text="Pastas · tamanhos somados", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 5))
            folder_tree = ttk.Treeview(folder_card, columns=("size", "files"),
                                       show="tree headings", height=7,
                                       style="Maintenance.Treeview")
            folder_tree.heading("#0", text="Pasta")
            folder_tree.heading("size", text="Tamanho")
            folder_tree.heading("files", text="Arquivos")
            folder_tree.column("#0", width=360, minwidth=180)
            folder_tree.column("size", width=110, anchor="e")
            folder_tree.column("files", width=90, anchor="e")
            folder_tree.pack(fill="both", expand=True)
            nodes = data["directories"]
            inserted = {".": "root"}
            item_paths = {"root": data["path"]}
            root_node = nodes.get(".", {})
            folder_tree.insert("", "end", iid="root",
                               text=root_node.get("name", Path(data["path"]).name),
                               values=(format_bytes(root_node.get("bytes", 0)),
                                       root_node.get("files", 0)))
            pending = [key for key in nodes if key != "."]
            pending.sort(key=lambda relative: (
                relative.count("/"), -nodes[relative]["bytes"],
                nodes[relative]["name"].casefold(),
            ))
            while pending:
                progressed = False
                for relative in pending[:]:
                    node = nodes[relative]
                    parent = inserted.get(node["parent"])
                    if parent is None:
                        continue
                    iid = f"dir-{len(inserted)}"
                    inserted[relative] = iid
                    item_paths[iid] = node["path"]
                    folder_tree.insert(parent, "end", iid=iid, text=node["name"],
                                       values=(format_bytes(node["bytes"]), node["files"]))
                    pending.remove(relative)
                    progressed = True
                if not progressed:
                    break
            folder_tree.item("root", open=True)
            files_card = ttk.Frame(result, style="Card.TFrame", padding=10)
            files_card.pack(fill="both", expand=True)
            ttk.Label(files_card, text="Maiores arquivos encontrados", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 5))
            filters = ttk.Frame(files_card)
            filters.pack(fill="x", pady=(0, 5))
            query = tk.StringVar()
            ttk.Entry(filters, textvariable=query).pack(side="left", fill="x", expand=True, padx=(0, 6))
            extensions = sorted({item["extension"] for item in data["largest_files"]})
            extension = tk.StringVar(value="Todas as extensões")
            ttk.Combobox(filters, textvariable=extension,
                         values=("Todas as extensões", *extensions),
                         state="readonly", width=22).pack(side="left")
            file_table = ttk.Treeview(files_card, columns=("name", "size", "extension", "path"),
                                      show="headings", height=6,
                                      style="Maintenance.Treeview")
            for column, label, width in (("name", "Arquivo", 180),
                                         ("size", "Tamanho", 100),
                                         ("extension", "Tipo", 110),
                                         ("path", "Localização", 390)):
                file_table.heading(column, text=label,
                                   command=lambda key=column: sort_files(key, file_table, query, extension))
                file_table.column(column, width=width, minwidth=90, anchor="w")
            file_table.pack(fill="both", expand=True)

            def refresh_files(*_args):
                file_table.delete(*file_table.get_children())
                for index, item in enumerate(filtered_file_rows(query, extension)):
                    file_table.insert("", "end", iid=str(index),
                                      values=(item["name"], format_bytes(item["bytes"]),
                                              item["extension"], item["path"]))

            query.trace_add("write", refresh_files)
            extension.trace_add("write", refresh_files)
            refresh_files()
            folder_tree.bind("<Double-1>", lambda _event: analyze_selected_folder(folder_tree, item_paths))
            ttk.Button(files_card, text="Analisar pasta selecionada",
                       command=lambda: analyze_selected_folder(folder_tree, item_paths)).pack(anchor="e", pady=(6, 0))
            if data["inaccessible"]:
                ttk.Label(files_card, text="Pastas ou arquivos sem permissão foram ignorados; a análise continuou.",
                          style="PageHint.TLabel", wraplength=630).pack(anchor="w", pady=(4, 0))

        def analyze_selected_folder(tree, item_paths):
            selected = tree.selection()
            if not selected:
                return
            selected_path = item_paths.get(selected[0], "")
            if selected_path:
                storage_scan["directory"] = selected_path
                storage_directory_var.set(selected_path)
                load_storage_home()

        def sort_files(column, table, query, extension):
            key = "size" if column == "size" else "name"
            if storage_scan["sort"] == key:
                storage_scan["reverse"] = not storage_scan["reverse"]
            else:
                storage_scan.update(sort=key, reverse=(key == "size"))
            table.delete(*table.get_children())
            for index, item in enumerate(filtered_file_rows(query, extension)):
                table.insert("", "end", iid=str(index),
                             values=(item["name"], format_bytes(item["bytes"]),
                                     item["extension"], item["path"]))

        def filtered_file_rows(query, extension):
            needle = query.get().casefold().strip()
            rows = [item for item in storage_scan["files"]
                    if (not needle or needle in item["name"].casefold()
                        or needle in item["path"].casefold())
                    and (extension.get() == "Todas as extensões"
                         or item["extension"] == extension.get())]
            rows.sort(key=(lambda item: item["bytes"])
                      if storage_scan["sort"] == "size"
                      else (lambda item: item["name"].casefold()),
                      reverse=storage_scan["reverse"])
            return rows

        def load_storage_home():
            page_title.set("Analisador de armazenamento")
            clear_result()
            start_worker("Armazenamento geral",
                         lambda _progress: collect_storage_overview(storage_scan["directory"]))

        def load_disks():
            page_title.set("Saúde dos Discos"); clear_result()
            start_worker("Saúde dos Discos", lambda _progress: inspect_disks())

        def load_logs():
            try: self._authorize_core_action("system.maintenance.read")
            except (PermissionError, OSError) as exc:
                status.set(f"Permissão necessária para consultar logs: {exc}"); return
            page_title.set("Central de Erros e Logs"); clear_result()
            start_worker("Central de Logs", lambda _progress: collect_logs())

        def load_cleanup():
            try: self._authorize_core_action("file.read")
            except (PermissionError, OSError) as exc:
                status.set(f"Permissão necessária para analisar arquivos: {exc}"); return
            page_title.set("Limpeza Assistida"); clear_result()
            ttk.Button(result, text="Cancelar análise", command=cancel_event.set).pack(anchor="e")
            start_worker("Limpeza Assistida", lambda _progress: analyze_cleanup(cancel_event=cancel_event))

        def load_backups():
            try: self._authorize_core_action("system.maintenance.read")
            except (PermissionError, OSError) as exc:
                status.set(f"Permissão necessária para consultar backups: {exc}"); return
            page_title.set("Backup e Restauração"); clear_result()
            start_worker("Backups", lambda _progress: list_backups(backup_directory["path"]))

        def open_page(section):
            if state["closed"] or state["busy"]:
                return
            monitors["network"] = monitors["health"] = False
            stop_timer("network"); stop_timer("health")
            if section == "Rede":
                try:
                    self._authorize_core_action("network.access", confirmed=True)
                except (PermissionError, OSError) as exc:
                    status.set(f"Permissão necessária para consultar a rede: {exc}")
                    return
            elif section == "Inicialização":
                try:
                    self._authorize_core_action("system.app.read")
                except (PermissionError, OSError) as exc:
                    status.set(f"Permissão necessária para consultar a inicialização: {exc}")
                    return
            if section == "Armazenamento":
                load_storage_home()
            elif section == "Inicialização":
                load_startup()
            elif section == "Rede":
                monitors["network"] = True
                page_title.set("Monitor de rede"); clear_result()
                start_worker("Rede", lambda _progress: network_sampler.sample())
            elif section == "Saúde do Sistema":
                try:
                    self._authorize_core_action("system.process.read")
                except (PermissionError, OSError) as exc:
                    status.set(f"Permissão necessária para consultar processos: {exc}")
                    return
                monitors["health"] = True
                page_title.set("Saúde do Sistema"); clear_result()
                start_worker("Saúde do Sistema", lambda _progress: health_sampler.sample(getattr(self, "system_monitor", None)))
            elif section == "Saúde dos Discos":
                load_disks()
            elif section == "Central de Logs":
                load_logs()
            elif section == "Limpeza Assistida":
                load_cleanup()
            elif section == "Backup":
                load_backups()
            elif section == "Histórico de Desempenho":
                load_performance_history()
            elif section == "Alertas":
                load_alerts()
            elif section == "Consultor Inteligente":
                page_title.set(section); render_consultant()
            elif section == "Histórico de Ações":
                load_action_history()
            else:
                page_title.set(section)
                clear_result()
                function = collect_overview
                start_worker(section, lambda _progress: function())

        apps_button = ttk.Button(
            nav, text="Biblioteca de Aplicativos · abrir inventário",
            command=lambda: self.open_autonomy_settings("computer"),
        )
        apps_button.grid(row=0, column=0, columnspan=3, sticky="ew", padx=2, pady=(0, 5))
        for index, section in enumerate(("Visão geral", "Inicialização", "Armazenamento", "Rede", "Saúde do Sistema", "Saúde dos Discos", "Central de Logs", "Limpeza Assistida", "Backup", "Histórico de Desempenho", "Alertas", "Consultor Inteligente", "Histórico de Ações")):
            button = ttk.Button(nav, text=section,
                                command=lambda name=section: open_page(name))
            button.grid(row=1 + index // 3, column=index % 3, sticky="ew", padx=2, pady=2)
            nav_buttons.append(button)
        for column in range(3): nav.columnconfigure(column, weight=1)

        def on_close():
            state["closed"] = True
            if consultant_action["id"]:
                update_consultant_action(consultant_action["id"], "Cancelada", result="Janela fechada durante a coleta.")
                consultant_action["id"] = None
            monitors["network"] = monitors["health"] = False
            stop_timer("network"); stop_timer("health")
            cancel_event.set()
            if state["job"] is not None:
                try:
                    window.after_cancel(state["job"])
                except tk.TclError:
                    pass
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", on_close)
        open_page("Visão geral")
        self.get_computer_consultant_context = lambda question="": collect_computer_context(
            question, performance_store=(performance_monitor.store if performance_monitor else None),
            system_monitor=getattr(self, "system_monitor", None),
        )
        self.get_performance_consultant_context = consultant_performance_context
        return window
