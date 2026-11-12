"""Builder for the preference tab content."""

import shutil
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk
from autonomy import find_installed_apps, save_settings
from system_updates import (
    apt_upgrade_command,
    build_installed_app_inventory,
    display_package_name,
    estimate_remaining_seconds,
    flatpak_upgrade_command,
    parse_apt_upgradable,
    parse_flatpak_upgradable,
    parse_package_activity,
    parse_snap_installed,
    parse_snap_upgradable,
    run_inventory_query,
    snap_upgrade_command,
    run_streaming_command,
)
from ui_theme import fit_window_to_screen


class ComputerPreferencesTabMixin:
    def _build_computer_preferences_tab(self, context):
        card = getattr(context, 'card', None)
        computer_content = getattr(context, 'computer_content', None)
        description = getattr(context, 'description', None)
        item = getattr(context, 'item', None)
        memory_content = getattr(context, 'memory_content', None)
        window = getattr(context, 'window', None)
        computer_intro = card(
            computer_content, "Atualizações e manutenção",
            "Veja versões instaladas e disponíveis do APT e do Flatpak, quando instalado. Nenhum pacote é removido automaticamente.",
        )
        ttk.Label(
            computer_intro, text="A autenticação é solicitada pelo Linux quando necessária.", style="Hint.TLabel",
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
        package_progress = ttk.Progressbar(
            progress_card, mode="determinate", maximum=100, length=380,
        )
        package_progress.pack(fill="x", pady=(8, 0))
        package_progress.pack_forget()
        stage_status = tk.StringVar(value="")
        ttk.Label(
            progress_card, textvariable=stage_status, style="CardTitle.TLabel",
            wraplength=440,
        ).pack(anchor="w", pady=(8, 0))
        stage_list_frame = ttk.Frame(progress_card, style="Card.TFrame")
        stage_list = ttk.Treeview(
            stage_list_frame, columns=("stage", "state"), show="headings",
            height=4, style="Maintenance.Treeview",
        )
        stage_list.heading("stage", text="Etapa")
        stage_list.heading("state", text="Estado")
        stage_list.column("stage", width=340, minwidth=200, anchor="w")
        stage_list.column("state", width=120, minwidth=90, anchor="w")
        stage_list_scroll = ttk.Scrollbar(
            stage_list_frame, orient="vertical", command=stage_list.yview,
        )
        stage_list.configure(yscrollcommand=stage_list_scroll.set)
        stage_list.pack(side="left", fill="both", expand=True)
        stage_list_scroll.pack(side="right", fill="y")
        stage_rows = []
        timing_status = tk.StringVar(value="")
        ttk.Label(
            progress_card, textvariable=timing_status, style="Hint.TLabel",
            wraplength=440,
        ).pack(anchor="w", pady=(3, 0))
        activity_status = tk.StringVar(value="")
        ttk.Label(
            progress_card, textvariable=activity_status, style="Hint.TLabel",
            wraplength=440,
        ).pack(anchor="w", pady=(3, 0))
        package_activity = tk.StringVar(value="")
        ttk.Label(
            progress_card, textvariable=package_activity, style="CardTitle.TLabel",
            wraplength=440,
        ).pack(anchor="w", pady=(3, 0))
        live_packages_frame = ttk.Frame(progress_card, style="Card.TFrame")
        live_packages = ttk.Treeview(
            live_packages_frame, columns=("package", "state", "version"),
            show="headings", height=5, style="Maintenance.Treeview",
        )
        live_packages.heading("package", text="Programa ou pacote")
        live_packages.heading("state", text="Etapa")
        live_packages.heading("version", text="Versão")
        live_packages.column("package", width=220, minwidth=140, anchor="w")
        live_packages.column("state", width=110, minwidth=90, anchor="w")
        live_packages.column("version", width=140, minwidth=100, anchor="w")
        live_packages_scroll = ttk.Scrollbar(
            live_packages_frame, orient="vertical", command=live_packages.yview,
        )
        live_packages.configure(yscrollcommand=live_packages_scroll.set)
        live_packages.pack(side="left", fill="both", expand=True)
        live_packages_scroll.pack(side="right", fill="y")
        live_package_rows = {}
        maintenance_started_at = {"value": None}
        progress_clock = {"job": None}
        maintenance_buttons = []
        maintenance_details = {"text": ""}

        def format_duration(seconds):
            seconds = max(0, round(seconds))
            minutes, seconds = divmod(seconds, 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                return f"{hours}h {minutes:02}min"
            if minutes:
                return f"{minutes}min {seconds:02}s"
            return f"{seconds}s"

        def refresh_timing():
            progress_clock["job"] = None
            started_at = maintenance_started_at["value"]
            if started_at is None or not window.winfo_exists():
                return
            elapsed = time.monotonic() - started_at
            completed = sum(
                1 for row in live_package_rows.values()
                if row["state"] == "Atualizado"
            )
            total = len(live_package_rows)
            eta = estimate_remaining_seconds(elapsed, completed, total)
            eta_text = (
                f"Estimativa aproximada: {format_duration(eta)} restantes"
                if eta is not None else "Estimativa: calculando (depende dos downloads e da conexão)"
            )
            timing_status.set(
                f"Decorrido: {format_duration(elapsed)}  ·  {eta_text}"
            )
            progress_clock["job"] = window.after(1000, refresh_timing)

        def start_progress_clock():
            maintenance_started_at["value"] = time.monotonic()
            refresh_timing()

        def stop_progress_clock():
            maintenance_started_at["value"] = None
            if progress_clock["job"] is not None:
                try:
                    window.after_cancel(progress_clock["job"])
                except tk.TclError:
                    pass
                progress_clock["job"] = None

        def set_live_package(name, state, version=""):
            package_id = name
            name = display_package_name(name)
            existing = live_package_rows.get(name)
            if existing is None:
                item_id = live_packages.insert(
                    "", "end", values=(name, state, version or "—"),
                )
                live_package_rows[name] = {
                    "item_id": item_id, "state": state, "version": version,
                    "package_id": package_id,
                }
            else:
                existing.update(state=state, version=version or existing["version"])
                live_packages.item(
                    existing["item_id"],
                    values=(name, state, existing["version"] or "—"),
                )
            total = len(live_package_rows)
            completed = sum(
                1 for row in live_package_rows.values()
                if row["state"] == "Atualizado"
            )
            package_progress.configure(
                maximum=max(1, total), value=completed,
            )
            if total:
                activity_status.set(
                    f"{completed} de {total} pacote(s) em andamento ou concluído(s)"
                )

        def find_live_package_name(name):
            if name.startswith("Flatpak · "):
                return name
            display_name = display_package_name(name)
            if display_name in live_package_rows:
                return display_name
            for package_name in live_package_rows:
                if package_name.startswith("Flatpak · "):
                    continue
                row_package_id = live_package_rows[package_name]["package_id"]
                if row_package_id.split(":", 1)[0] == name.split(":", 1)[0]:
                    return package_name
            return display_name

        def show_progress_area():
            stage_list_frame.pack(
                fill="x", pady=(8, 0), before=details_button,
            )
            live_packages_frame.pack(
                fill="x", pady=(8, 0), before=details_button,
            )
            if not package_progress.winfo_manager():
                package_progress.pack(
                    fill="x", pady=(8, 0), before=stage_list_frame,
                )

        def prepare_live_packages(packages):
            live_package_rows.clear()
            for item_id in live_packages.get_children():
                live_packages.delete(item_id)
            package_progress.configure(maximum=1, value=0)
            for name, installed, candidate in packages:
                set_live_package(name, "Aguardando", f"{installed} → {candidate}")
            if not packages:
                activity_status.set("Identificando pacotes da operação…")

        def show_maintenance_details():
            if not maintenance_details["text"]:
                return
            details_window = self._set_nova_window_icon(tk.Toplevel(window))
            details_window.title("Detalhes da operação")
            details_window.transient(window)
            fit_window_to_screen(details_window, 620, 380, min_width=500, min_height=300)
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
            fit_window_to_screen(dialog, 500, 220, min_width=420, min_height=200)
            dialog.grab_set()
            dialog.focus_set()

        def show_package_review(
            title, description, packages, action_label=None, on_action=None,
            on_package_action=None,
        ):
            dialog = self._set_nova_window_icon(tk.Toplevel(window))
            dialog.title(title)
            dialog.transient(window)
            fit_window_to_screen(dialog, 620, 440, min_width=500, min_height=350)
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
            package_by_item = {}
            for package in packages:
                name, installed, candidate = package
                item_id = table.insert(
                    "", "end",
                    values=(display_package_name(name), installed, candidate),
                )
                package_by_item[item_id] = package
            if not packages:
                ttk.Label(
                    frame, text="Não há pacotes para mostrar.", style="Hint.TLabel",
                ).pack(anchor="w", pady=(8, 0))
            buttons = ttk.Frame(frame, style="Autonomy.TFrame")
            buttons.pack(fill="x", side="bottom", pady=(12, 0))
            ttk.Button(buttons, text="Fechar", style="Secondary.TButton", command=dialog.destroy).pack(side="right")
            selected_action = None
            if packages and on_package_action:
                selected_action = ttk.Button(
                    buttons, text="Atualizar selecionado", style="Primary.TButton",
                    state="disabled",
                )
                selected_action.pack(side="right", padx=(0, 8))

                def update_selected(_event=None):
                    selected = table.selection()
                    if not selected:
                        selected_action.configure(state="disabled")
                        return
                    package = package_by_item[selected[0]]
                    is_managed_package = package[0].startswith(
                        ("Flatpak · ", "Snap · "),
                    ) or not package[0].startswith("AppImage · ")
                    selected_action.configure(
                        state="normal" if is_managed_package else "disabled",
                        text=f"Atualizar {display_package_name(package[0])}",
                    )

                def update_package():
                    selected = table.selection()
                    if not selected:
                        return
                    package = package_by_item[selected[0]]
                    dialog.destroy()
                    on_package_action(package)

                selected_action.configure(command=update_package)
                table.bind("<<TreeviewSelect>>", update_selected)
            if packages and action_label and on_action:
                def do_action():
                    dialog.destroy()
                    on_action()

                ttk.Button(
                    buttons, text=action_label, style="Primary.TButton", command=do_action,
                ).pack(side="right", padx=(0, 8))
            table_frame.pack(fill="both", expand=True)
            dialog.grab_set()
            dialog.focus_set()

        def parse_removable_packages(output):
            packages = []
            for line in output.splitlines():
                fields = line.split()
                if len(fields) >= 2 and fields[0] in ("Remv", "Purg"):
                    version = fields[2].strip("[]") if len(fields) >= 3 else ""
                    packages.append((fields[1], version, "Será removido"))
            return packages

        def finish_maintenance(
            title, result, error, on_success=None, total_stages=0,
            expected_packages=(),
        ):
            if not window.winfo_exists():
                return
            stop_progress_clock()
            computer_progress.stop()
            computer_progress.pack_forget()
            for button in maintenance_buttons:
                button.configure(state="normal")
            stage_status.set(
                f"Etapas concluídas · {total_stages} de {total_stages}"
                if not error else "Operação encerrada com pendências"
            )
            package_activity.set("")
            result_details = "\n\n".join(
                f"Comando: {' '.join(command)}\n{output}"
                for command, output in result if output
            )
            maintenance_details["text"] = (result_details or error or "").strip()
            details_button.configure(state="normal" if maintenance_details["text"] else "disabled")

            def updates_from_results():
                apt_output = next(
                    (output for command, output in result
                     if command == ["apt", "list", "--upgradable"]),
                    "",
                )
                flatpak_updates = next(
                    (output for command, output in result
                     if command == [
                         "flatpak", "remote-ls", "--updates", "--columns=ref,version,commit",
                     ]),
                    "",
                )
                flatpak_installed = next(
                    (output for command, output in result
                     if command == ["flatpak", "list", "--columns=ref,version,active"]),
                    "",
                )
                snap_updates = next(
                    (output for command, output in result
                     if command == ["snap", "refresh", "--list"]),
                    "",
                )
                snap_installed = next(
                    (output for command, output in result
                     if command == ["snap", "list"]),
                    "",
                )
                snap_versions = parse_snap_installed(snap_installed)
                return (
                    parse_apt_upgradable(apt_output)
                    + parse_flatpak_upgradable(flatpak_updates, flatpak_installed)
                    + [
                        (f"Snap · {name}", snap_versions.get(name, "—"), candidate)
                        for name, candidate in parse_snap_upgradable(snap_updates).items()
                    ]
                )

            update_operations = (
                "Atualizar sistema", "Atualizar aplicativos selecionados",
            )
            if title in update_operations and not record_update_history(
                expected_packages, error,
            ):
                history_error = "Não foi possível salvar esta operação no histórico."
                maintenance_details["text"] = (
                    f"{maintenance_details['text']}\n\n{history_error}"
                ).strip()
                details_button.configure(state="normal")

            if error and title not in (
                "Verificar atualizações", "Atualizar sistema",
                "Atualizar aplicativos selecionados",
            ):
                computer_status_label.configure(style="ComputerStatusError.TLabel")
                computer_status.set(f"{title}: não foi concluído. Veja os detalhes para entender o erro.")
                return

            packages = updates_from_results() if title in (
                "Verificar atualizações", *update_operations,
            ) else []
            if title == "Atualizar aplicativos selecionados":
                expected_ids = {package[0] for package in expected_packages}

                def package_id_from_update(name):
                    if name.startswith("Flatpak · "):
                        return name.removeprefix("Flatpak · ").split(" (", 1)[0]
                    if name.startswith("Snap · "):
                        return name.removeprefix("Snap · ")
                    return name

                packages = [
                    package for package in packages
                    if (
                        package_id_from_update(package[0]) in expected_ids
                        or package_id_from_update(package[0]).split(":", 1)[0]
                        in expected_ids
                    )
                ]
            if title == "Verificar atualizações":
                activity_status.set(
                    f"{len(packages)} atualização(ões) encontrada(s)."
                )
            if title == "Atualizar sistema":
                pending = {name for name, _installed, _candidate in packages}
                verification_failed = bool(error)
                for name, row in tuple(live_package_rows.items()):
                    package_id = row["package_id"]
                    is_pending = package_id in pending or (
                        not name.startswith(("Flatpak · ", "Snap · "))
                        and any(
                            pending_name.split(":", 1)[0] == package_id.split(":", 1)[0]
                            for pending_name in pending
                            if not pending_name.startswith(("Flatpak · ", "Snap · "))
                        )
                    )
                    state = (
                        "Pendente" if is_pending else
                        "Não verificado" if verification_failed else
                        "Atualizado"
                    )
                    set_live_package(
                        name, state, row["version"],
                    )
                for name, installed, candidate in packages:
                    display_name = display_package_name(name)
                    if display_name not in live_package_rows:
                        set_live_package(
                            name, "Pendente", f"{installed} → {candidate}",
                        )
                updated_count = sum(
                    1 for row in live_package_rows.values()
                    if row["state"] == "Atualizado"
                )
                activity_status.set(
                    (
                        f"{updated_count} pacote(s) atualizado(s) · "
                        f"{len(packages)} ainda pendente(s)"
                    ) if not error else
                    f"Verificação final incompleta · {len(packages)} pendente(s)"
                )
            if error:
                computer_status_label.configure(style="ComputerStatusError.TLabel")
                if title == "Verificar atualizações":
                    computer_status.set(
                        f"Verificação parcial: {len(packages)} atualização(ões) listada(s). "
                        "Confira os detalhes das fontes indisponíveis."
                    )
                    show_package_review(
                        "Resultado parcial da verificação",
                        "Algumas fontes de pacotes não responderam. Confira os detalhes.",
                        packages,
                    )
                else:
                    computer_status.set(
                        f"Atualização parcial: {len(packages)} pacote(s) ainda pendente(s). "
                        "Confira os detalhes."
                    )
                    if packages:
                        show_package_review(
                            "Atualizações ainda pendentes",
                            "Algumas atualizações falharam ou continuam pendentes.",
                            packages,
                        )
                if title in update_operations:
                    load_installed_apps()
                return

            computer_status_label.configure(style="ComputerStatus.TLabel")
            if title == "Verificar atualizações":
                if packages:
                    summary = f"Há {len(packages)} atualização(ões) disponível(is)."
                else:
                    summary = "Sistema e programas estão atualizados."
            elif title == "Atualizar sistema":
                summary = (
                    f"Atualização concluída. Ainda há {len(packages)} item(ns) pendente(s)."
                    if packages else "Sistema e programas atualizados."
                )
            elif title == "Atualizar aplicativos selecionados":
                summary = (
                    f"Operação concluída; {len(packages)} atualização(ões) ainda pendente(s)."
                    if packages else "Aplicativos selecionados atualizados."
                )
            elif title == "Limpar cache do APT":
                summary = "Cache de pacotes limpo."
            else:
                summary = "Limpeza concluída."
            computer_status.set(summary)
            if title == "Verificar atualizações":
                action = (
                    (lambda: on_success(packages))
                    if on_success and packages else None
                )
                show_package_review(
                    "Atualizações disponíveis",
                    "Confira as versões instaladas e disponíveis antes de atualizar.",
                    packages, "Atualizar programas" if action else None, action,
                    on_package_action=(
                        (lambda package: update_selected_package(package))
                        if on_success else None
                    ),
                )
            elif title == "Atualizar sistema" and packages:
                show_package_review(
                    "Atualizações ainda pendentes",
                    "Algumas atualizações continuam pendentes. Nenhum pacote foi removido.",
                    packages,
                )
            elif on_success:
                on_success()
            if title in update_operations:
                load_installed_apps()

        def run_maintenance(
            title, commands, on_success=None, expected_packages=(),
        ):
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
            show_progress_area()
            prepare_live_packages(expected_packages)
            package_activity.set("")
            start_progress_clock()

            def describe_stage(command):
                if "apt-get" in command and "--only-upgrade" in command:
                    return "Atualizando os programas selecionados (APT)"
                if "apt-get" in command and "update" in command:
                    return "Atualizando o catálogo de pacotes APT"
                if "apt-get" in command and (
                    "upgrade" in command
                ):
                    return "Instalando atualizações do sistema (APT)"
                if "flatpak" in command and "appstream" in command:
                    return "Atualizando o catálogo do Flatpak"
                if "flatpak" in command and "update" in command:
                    return "Atualizando aplicativos e runtimes Flatpak"
                if "snap" in command and "refresh" in command:
                    return "Atualizando aplicativos Snap"
                if command[:3] == ["snap", "refresh", "--list"]:
                    return "Conferindo atualizações Snap restantes"
                if command[:3] == ["apt", "list", "--upgradable"]:
                    return "Conferindo atualizações APT restantes"
                if "remote-ls" in command:
                    return "Conferindo atualizações Flatpak restantes"
                if "flatpak" in command and "list" in command:
                    return "Lendo versões instaladas do Flatpak"
                return "Executando manutenção do sistema"

            stage_rows.clear()
            for item_id in stage_list.get_children():
                stage_list.delete(item_id)
            for index, command in enumerate(commands, start=1):
                item_id = stage_list.insert(
                    "", "end",
                    values=(f"{index}. {describe_stage(command)}", "Aguardando"),
                )
                stage_rows.append(item_id)

            def progress_update(
                stage, detail, package_event=None, completed_manager=None,
                stage_index=None, stage_state=None,
            ):
                if not window.winfo_exists():
                    return
                stage_status.set(stage)
                if stage_index is not None and 1 <= stage_index <= len(stage_rows):
                    item_id = stage_rows[stage_index - 1]
                    values = stage_list.item(item_id, "values")
                    stage_list.item(
                        item_id,
                        values=(values[0], stage_state or values[1]),
                    )
                if completed_manager:
                    for name, row in tuple(live_package_rows.items()):
                        belongs_to_manager = (
                            name.startswith("Flatpak · ")
                            if completed_manager == "flatpak" else
                            name.startswith("Snap · ")
                            if completed_manager == "snap" else
                            not name.startswith(("Flatpak · ", "Snap · "))
                        )
                        if belongs_to_manager:
                            set_live_package(name, "Atualizado", row["version"])
                if package_event:
                    name, state, version = package_event
                    display_name = find_live_package_name(name)
                    set_live_package(display_name, state, version)
                    version_text = f" · versão {version}" if version else ""
                    package_activity.set(f"{display_name}: {state.lower()}{version_text}")
                elif detail:
                    package_activity.set(detail)

            def worker():
                output = []
                errors = []
                failed_apt_update = False
                error = None
                try:
                    self.permission_manager.require("nova.core", "system.maintenance", confirmed=True)
                    for index, command in enumerate(commands, start=1):
                        if failed_apt_update and command[0] == "apt":
                            self.post_ui_callback(
                                progress_update,
                                f"Etapa {index} de {len(commands)} · ignorada",
                                "", stage_index=index,
                                stage_state="Ignorada (etapa anterior falhou)",
                            )
                            continue
                        label = describe_stage(command)
                        stage = f"Etapa {index} de {len(commands)} · {label}"
                        self.post_ui_callback(
                            progress_update, stage, "",
                            stage_index=index, stage_state="Em andamento",
                        )
                        command_lines = []

                        def receive_output(line):
                            command_lines.append(line)
                            activity = parse_package_activity(command, line)
                            if activity:
                                self.post_ui_callback(
                                    progress_update, stage, "", activity,
                                )

                        try:
                            return_code, details = run_streaming_command(
                                command,
                                env={**self._child_process_env(), "LC_ALL": "C"},
                                timeout=600,
                                on_output=receive_output,
                            )
                        except subprocess.TimeoutExpired as exc:
                            self.post_ui_callback(
                                progress_update, stage, "",
                                stage_index=index, stage_state="Interrompida",
                            )
                            details = exc.output or "".join(command_lines)
                            if isinstance(details, bytes):
                                details = details.decode("utf-8", errors="replace")
                            output.append((command, details.strip()))
                            error = "A operação ultrapassou o limite de 10 minutos."
                            break
                        except OSError:
                            self.post_ui_callback(
                                progress_update, stage, "",
                                stage_index=index, stage_state="Falhou",
                            )
                            raise
                        output.append((command, details.strip()))
                        if return_code == 0:
                            self.post_ui_callback(
                                progress_update, stage, "",
                                stage_index=index, stage_state="Concluída",
                            )
                            if "apt-get" in command and (
                                "upgrade" in command or "--only-upgrade" in command
                            ):
                                self.post_ui_callback(
                                    progress_update, stage, "",
                                    completed_manager="apt",
                                )
                            elif "flatpak" in command and "update" in command:
                                self.post_ui_callback(
                                    progress_update, stage, "",
                                    completed_manager="flatpak",
                                )
                            elif "snap" in command and "refresh" in command:
                                self.post_ui_callback(
                                    progress_update, stage, "",
                                    completed_manager="snap",
                                )
                        else:
                            self.post_ui_callback(
                                progress_update, stage, "",
                                stage_index=index, stage_state="Falhou",
                            )
                            message = details.strip() or (
                                f"O comando terminou com código {return_code}."
                            )
                            if title in (
                                "Verificar atualizações", "Atualizar sistema",
                                "Atualizar aplicativos selecionados",
                            ):
                                errors.append(f"{' '.join(command)}: {message}")
                                if command[:2] == ["pkexec", "apt-get"]:
                                    failed_apt_update = True
                                continue
                            error = message
                            break
                    if error is None and errors:
                        error = "\n\n".join(errors) or None
                except subprocess.TimeoutExpired:
                    error = "A operação demorou demais e foi interrompida."
                except OSError as exc:
                    error = f"Não consegui iniciar a ação: {exc}"
                finally:
                    self.system_maintenance_active = False
                self.post_ui_callback(
                    finish_maintenance, title, output, error, on_success,
                    len(commands), expected_packages,
                )

            threading.Thread(target=worker, daemon=True).start()

        def update_selected_package(package):
            name, _installed, _candidate = package
            if name.startswith("Flatpak · "):
                app_id = name.removeprefix("Flatpak · ").split(" (", 1)[0]
                update_command = flatpak_upgrade_command(app_id)
            elif name.startswith("Snap · "):
                snap_name = name.removeprefix("Snap · ")
                update_command = snap_upgrade_command(snap_name)
            else:
                update_command = apt_upgrade_command(name)
            commands = [update_command, ["apt", "list", "--upgradable"]]
            if shutil.which("flatpak"):
                commands.extend([
                    ["flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"],
                    ["flatpak", "list", "--columns=ref,version,active"],
                ])
            if shutil.which("snap"):
                commands.extend([
                    ["snap", "refresh", "--list"],
                    ["snap", "list"],
                ])
            run_maintenance(
                "Atualizar sistema", commands, expected_packages=[package],
            )

        def check_system_updates(for_upgrade=False, expected_packages=()):
            if for_upgrade:
                commands = [
                    [
                        "pkexec", "apt-get", "-o", "Dpkg::Use-Pty=0",
                        "upgrade", "--with-new-pkgs", "-y",
                    ],
                    ["apt", "list", "--upgradable"],
                ]
                if shutil.which("flatpak"):
                    commands.extend([
                        [
                            "flatpak", "update", "--noninteractive", "--assumeyes",
                            "--verbose",
                        ],
                        ["flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"],
                        ["flatpak", "list", "--columns=ref,version,active"],
                    ])
                if shutil.which("snap"):
                    commands.extend([
                        ["pkexec", "snap", "refresh"],
                        ["snap", "refresh", "--list"],
                        ["snap", "list"],
                    ])
                run_maintenance(
                    "Atualizar sistema", commands,
                    expected_packages=expected_packages,
                )
                return

            commands = [
                ["pkexec", "apt-get", "update"],
                ["apt", "list", "--upgradable"],
            ]
            if shutil.which("flatpak"):
                commands.extend([
                    ["flatpak", "update", "--appstream"],
                    ["flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"],
                    ["flatpak", "list", "--columns=ref,version,active"],
                ])
            if shutil.which("snap"):
                commands.extend([
                    ["snap", "refresh", "--list"],
                    ["snap", "list"],
                ])
            run_maintenance(
                "Verificar atualizações", commands,
                on_success=lambda packages: check_system_updates(
                    for_upgrade=True, expected_packages=packages,
                ),
            )

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

        apps_card = card(
            computer_content, "Aplicativos instalados",
            "Lista aplicativos com atalho no menu em ordem alfabética, com versão e origem quando identificadas.",
        )
        apps_controls = ttk.Frame(apps_card, style="Card.TFrame")
        apps_controls.pack(fill="x", pady=(6, 8))
        app_search = tk.StringVar()
        ttk.Label(
            apps_controls, text="Buscar:", style="Hint.TLabel",
        ).pack(side="left", padx=(0, 6))
        app_search_entry = ttk.Entry(
            apps_controls, textvariable=app_search,
        )
        app_search_entry.pack(side="left", fill="x", expand=True)
        inventory_status_banner = tk.StringVar(value="Pronto para consultar apps instalados.")
        inventory_banner_style = tk.StringVar(value="StatusBanner.TLabel")
        ttk.Label(
            apps_card,
            textvariable=inventory_status_banner,
            style="StatusBanner.TLabel",
            wraplength=460,
            justify="left",
        ).pack(anchor="w", pady=(0, 6))
        app_inventory_status = tk.StringVar(value="Selecione Recarregar lista para consultar.")
        ttk.Label(
            apps_card, textvariable=app_inventory_status, style="Hint.TLabel",
        ).pack(anchor="w", pady=(0, 6))
        inventory_empty_state = ttk.Label(
            apps_card,
            text="Nenhum aplicativo foi encontrado na consulta atual. Clique em Recarregar lista para tentar novamente.",
            style="PageHint.TLabel",
            wraplength=460,
        )
        inventory_error = tk.StringVar(value="")
        inventory_error_label = ttk.Label(
            apps_card,
            textvariable=inventory_error,
            foreground="#B42318",
            background="#F5F7FA",
            wraplength=460,
            justify="left",
        )
        app_filters = ttk.Frame(apps_card, style="Card.TFrame")
        app_filters.pack(fill="x", pady=(0, 8))
        source_filter = tk.StringVar(value="Todas as origens")
        ttk.Combobox(
            app_filters, textvariable=source_filter, state="readonly",
            values=(
                "Todas as origens", "APT/DEB", "Flatpak", "Snap",
                "AppImage", "Manual/outro",
            ), width=18,
        ).pack(side="left", padx=(0, 8))
        update_filter = tk.StringVar(value="Todos os estados")
        ttk.Combobox(
            app_filters, textvariable=update_filter, state="readonly",
            values=(
                "Todos os estados", "Com atualização",
                "Atualizados", "Verificação necessária",
                "Não gerenciados",
            ), width=22,
        ).pack(side="left")
        clear_filters_button = ttk.Button(
            app_filters,
            text="Limpar filtros",
            style="Secondary.TButton",
            command=lambda: (
                app_search.set(""),
                source_filter.set("Todas as origens"),
                update_filter.set("Todos os estados"),
            ),
        )
        clear_filters_button.pack(side="left", padx=(8, 0))

        def set_banner(style_name, text):
            inventory_status_banner.set(text)
            try:
                for widget in apps_card.winfo_children():
                    if getattr(widget, "cget", lambda *_: "")("textvariable") == inventory_status_banner:
                        widget.configure(style=style_name)
            except Exception:
                pass
        inventory_table_frame = ttk.Frame(apps_card, style="Card.TFrame", padding=4)
        inventory_table_frame.pack(fill="both", expand=True)
        inventory_table = ttk.Treeview(
            inventory_table_frame,
            columns=("name", "version", "candidate", "status", "origin", "package"),
            show="headings", height=12, style="Maintenance.Treeview",
            selectmode="extended",
        )
        for column, heading, width, minimum in (
            ("name", "Aplicativo", 190, 140),
            ("version", "Instalada", 120, 90),
            ("candidate", "Disponível", 120, 90),
            ("status", "Estado", 160, 120),
            ("origin", "Origem", 130, 100),
            ("package", "Pacote / ID", 170, 120),
        ):
            inventory_table.heading(
                column, text=heading,
                command=lambda selected=column: sort_inventory(selected),
            )
            inventory_table.column(
                column, width=width, minwidth=minimum, anchor="w",
            )
        inventory_scroll = ttk.Scrollbar(
            inventory_table_frame, orient="vertical", command=inventory_table.yview,
        )
        inventory_horizontal_scroll = ttk.Scrollbar(
            inventory_table_frame, orient="horizontal", command=inventory_table.xview,
        )
        inventory_table.configure(
            yscrollcommand=inventory_scroll.set,
            xscrollcommand=inventory_horizontal_scroll.set,
        )
        inventory_table.pack(side="left", fill="both", expand=True)
        inventory_scroll.pack(side="right", fill="y")
        inventory_horizontal_scroll.pack(side="bottom", fill="x")
        installed_apps_inventory = []
        app_by_item = {}
        inventory_sort = {"column": "name", "reverse": False}
        verified_at = {"value": ""}
        selected_app_details = tk.StringVar(
            value="Selecione um aplicativo para ver suas versões e detalhes.",
        )
        inventory_error_label.pack(anchor="w", pady=(0, 6))
        ttk.Label(
            apps_card, textvariable=selected_app_details, style="Hint.TLabel",
            wraplength=460, justify="left",
        ).pack(anchor="w", pady=(8, 0))
        inventory_actions = ttk.Frame(apps_card, style="Card.TFrame")
        inventory_actions.pack(fill="x", pady=(8, 0))
        update_selected_button = ttk.Button(
            inventory_actions, text="Atualizar selecionados",
            style="Primary.TButton", state="disabled",
        )
        update_selected_button.pack(side="right")

        def render_installed_apps(*_args):
            query = app_search.get().strip().casefold()
            selected_source = source_filter.get()
            selected_status = update_filter.get()
            for item_id in inventory_table.get_children():
                inventory_table.delete(item_id)
            app_by_item.clear()
            rows = [
                app for app in installed_apps_inventory
                if (
                    (not query or query in " ".join(
                        (
                            app["name"], app["version"], app["candidate_version"],
                            app["update_status"], app["origin"], app["package"],
                        )
                    ).casefold())
                    and (
                        selected_source == "Todas as origens"
                        or app["source"] == selected_source
                    )
                    and (
                        selected_status == "Todos os estados"
                        or (selected_status == "Com atualização"
                            and app["update_status"] == "Atualização disponível")
                        or (selected_status == "Atualizados"
                            and app["update_status"] == "Atualizado")
                        or (selected_status == "Verificação necessária"
                            and app["update_status"] == "Verificação necessária")
                        or (selected_status == "Não gerenciados"
                            and app["update_status"] == "Atualização não gerenciada")
                    )
                )
            ]
            column = inventory_sort["column"]
            sort_key = {
                "candidate": "candidate_version",
                "status": "update_status",
            }.get(column, column)
            rows.sort(
                key=lambda app: app[sort_key].casefold(),
                reverse=inventory_sort["reverse"],
            )
            for app in rows:
                item_id = inventory_table.insert(
                    "", "end",
                    values=(
                        app["name"], app["version"], app["candidate_version"],
                        app["update_status"], app["origin"], app["package"],
                    ),
                )
                app_by_item[item_id] = app
            if rows:
                inventory_empty_state.pack_forget()
                inventory_error.set("")
                inventory_table.pack(side="left", fill="both", expand=True)
            else:
                inventory_table.pack_forget()
                inventory_empty_state.pack(anchor="w", pady=(0, 8))
            app_inventory_status.set(
                f"{len(rows)} aplicativo(s) exibido(s) · "
                f"{len(installed_apps_inventory)} instalado(s)"
                + (f" · verificado em {verified_at['value']}" if verified_at["value"] else "")
            )
            if not rows:
                app_inventory_status.set(
                    "Nenhum aplicativo corresponde aos filtros atuais. "
                    "Ajuste a busca ou clique em Atualizar lista para consultar novamente."
                )
            update_selection_details()

        def sort_inventory(column):
            if inventory_sort["column"] == column:
                inventory_sort["reverse"] = not inventory_sort["reverse"]
            else:
                inventory_sort.update(column=column, reverse=False)
            render_installed_apps()

        def update_selection_details(_event=None):
            selected_apps = [
                app_by_item[item_id]
                for item_id in inventory_table.selection()
                if item_id in app_by_item
            ]
            eligible = [
                app for app in selected_apps
                if app["update_status"] == "Atualização disponível"
                and app["source"] in ("APT/DEB", "Flatpak", "Snap")
                and app["package"] != "—"
            ]
            update_selected_button.configure(
                state="normal" if eligible else "disabled",
                text=f"Atualizar selecionados ({len(eligible)})",
            )
            if not selected_apps:
                selected_app_details.set(
                    "Selecione um aplicativo para ver suas versões e detalhes."
                )
            elif len(selected_apps) == 1:
                app = selected_apps[0]
                selected_app_details.set(
                    f"{app['name']}  ·  instalada: {app['version']}  ·  "
                    f"disponível: {app['candidate_version']}  ·  "
                    f"{app['origin']}  ·  {app['update_status']}"
                )
            else:
                selected_app_details.set(
                    f"{len(selected_apps)} aplicativos selecionados; "
                    f"{len(eligible)} podem ser atualizados por seus gerenciadores."
                )

        app_search.trace_add("write", render_installed_apps)
        source_filter.trace_add("write", render_installed_apps)
        update_filter.trace_add("write", render_installed_apps)
        inventory_table.bind("<<TreeviewSelect>>", update_selection_details)
        refresh_apps_button = ttk.Button(
            apps_controls, text="Recarregar lista", style="Secondary.TButton",
        )
        refresh_apps_button.pack(side="right", padx=(8, 0))
        inventory_table_frame.pack(fill="both", expand=True)
        inventory_table.pack(side="left", fill="both", expand=True)
        inventory_scroll.pack(side="right", fill="y")
        inventory_horizontal_scroll.pack(side="bottom", fill="x")

        history_card = card(
            computer_content, "Histórico de atualizações",
            "Registro local das últimas operações iniciadas pela Nova.",
        )
        history_table = ttk.Treeview(
            history_card, columns=("when", "apps", "result"),
            show="headings", height=4, style="Maintenance.Treeview",
        )
        for column, heading, width in (
            ("when", "Data e hora", 150),
            ("apps", "Aplicativos", 250),
            ("result", "Resultado", 150),
        ):
            history_table.heading(column, text=heading)
            history_table.column(column, width=width, minwidth=100, anchor="w")
        history_table.pack(fill="x", pady=(8, 0))

        def render_update_history():
            for item_id in history_table.get_children():
                history_table.delete(item_id)
            history = self.settings.get("application_update_history", [])
            if not isinstance(history, list):
                history = []
            for event in history[:10]:
                if not isinstance(event, dict):
                    continue
                history_table.insert(
                    "", "end",
                    values=(
                        event.get("when", ""),
                        event.get("apps", ""),
                        event.get("result", ""),
                    ),
                )

        def record_update_history(expected_packages, error):
            names = sorted({
                display_package_name(package[0])
                .removeprefix("Flatpak · ").removeprefix("Snap · ")
                for package in expected_packages
            }, key=str.casefold)
            if not names:
                names = ["Atualização do sistema"]
            event = {
                "when": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
                "apps": ", ".join(names)[:240],
                "result": "Concluída" if not error else "Com pendências",
            }
            history = self.settings.get("application_update_history", [])
            if not isinstance(history, list):
                history = []
            updated = dict(self.settings)
            updated["application_update_history"] = [event, *history[:19]]
            if not save_settings(updated, getattr(self, "settings_path", None)):
                return False
            self.settings = updated
            render_update_history()
            return True

        render_update_history()

        def load_installed_apps():
            permission_notice = ""
            try:
                self._authorize_core_action("system.maintenance.read")
            except (PermissionError, OSError) as exc:
                permission_notice = (
                    "Acesso de leitura limitado; Nova continuará com a consulta local do sistema."
                )
                inventory_status_banner.set(permission_notice)
                if hasattr(self, "permission_manager"):
                    try:
                        self.permission_manager.require("nova.core", "system.maintenance.read")
                    except Exception:
                        pass
            if self.system_maintenance_active:
                messagebox.showinfo(
                    "Manutenção em andamento",
                    "Aguarde a ação atual terminar.",
                    parent=window,
                )
                return
            self.system_maintenance_active = True
            inventory_error.set("")
            refresh_apps_button.configure(state="disabled")
            inventory_status_banner.set("Consultando apps instalados e versões disponíveis…")
            app_inventory_status.set("Lendo aplicativos e versões instaladas…")
            inventory_empty_state.pack_forget()
            inventory_table.pack_forget()
            computer_progress.pack(
                fill="x", pady=(10, 0), before=details_button,
            )
            computer_progress.start(12)

            def worker():
                try:
                    try:
                        self.permission_manager.require(
                            "nova.core", "system.maintenance.read",
                        )
                    except Exception:
                        pass
                    apps = find_installed_apps()
                    desktop_files = [
                        app["desktop_file"] for app in apps
                        if app.get("desktop_file")
                    ]
                    package_owners = {}
                    package_versions = {}
                    source_errors = []
                    if desktop_files:
                        owners_output, owners_error = run_inventory_query(
                            ["dpkg-query", "-S", "--", *desktop_files],
                            timeout=60,
                            env={**self._child_process_env(), "LC_ALL": "C"},
                            allow_partial=True,
                        )
                        package_owners = parse_dpkg_query_owners(owners_output)
                        if owners_error:
                            source_errors.append(f"dpkg: {owners_error}")
                    packages_output, packages_error = run_inventory_query(
                        [
                            "dpkg-query", "-W", "-f=" +
                            "${binary:Package}\\t${Version}\\t${Status}\\n",
                        ],
                        timeout=60,
                        env={**self._child_process_env(), "LC_ALL": "C"},
                        allow_partial=True,
                    )
                    package_versions = parse_dpkg_query_packages(packages_output)
                    if packages_error:
                        source_errors.append(f"dpkg: {packages_error}")
                    flatpak_output = ""
                    flatpak_updates = ""
                    snap_output = ""
                    snap_updates = ""
                    apt_updates = []
                    checked_sources = set()
                    apt_output, apt_error = run_inventory_query(
                        ["apt", "list", "--upgradable"],
                        timeout=120,
                        env={**self._child_process_env(), "LC_ALL": "C"},
                    )
                    if not apt_error:
                        apt_updates = parse_apt_upgradable(apt_output)
                        checked_sources.add("APT/DEB")
                    else:
                        source_errors.append(f"APT: {apt_error}")
                    if shutil.which("flatpak"):
                        flatpak_output, flatpak_error = run_inventory_query(
                            [
                                "flatpak", "list",
                                "--columns=application,version,origin",
                            ],
                            timeout=60,
                            env={**self._child_process_env(), "LC_ALL": "C"},
                        )
                        if flatpak_error:
                            source_errors.append(f"Flatpak: {flatpak_error}")
                        flatpak_update_output, flatpak_update_error = run_inventory_query(
                            [
                                "flatpak", "remote-ls", "--updates",
                                "--columns=ref,version,commit",
                            ],
                            timeout=120,
                            env={**self._child_process_env(), "LC_ALL": "C"},
                        )
                        flatpak_updates = flatpak_update_output
                        if not flatpak_update_error:
                            checked_sources.add("Flatpak")
                        else:
                            source_errors.append(f"Flatpak: {flatpak_update_error}")
                    if shutil.which("snap"):
                        snap_output, snap_error = run_inventory_query(
                            ["snap", "list"], timeout=60,
                            env={**self._child_process_env(), "LC_ALL": "C"},
                        )
                        if snap_error:
                            source_errors.append(f"Snap: {snap_error}")
                        else:
                            snap_updates, snap_update_error = run_inventory_query(
                                ["snap", "refresh", "--list"],
                                timeout=120,
                                env={**self._child_process_env(), "LC_ALL": "C"},
                            )
                            if not snap_update_error:
                                checked_sources.add("Snap")
                            else:
                                source_errors.append(f"Snap: {snap_update_error}")
                    inventory = build_installed_app_inventory(
                        apps,
                        package_versions,
                        package_owners,
                        flatpak_output,
                        apt_upgradable=apt_updates,
                        flatpak_update_output=flatpak_updates,
                        snap_output=snap_output,
                        snap_update_output=snap_updates,
                        checked_sources=checked_sources,
                    )
                    error = "\n".join(source_errors) or None
                except (OSError, subprocess.SubprocessError) as exc:
                    inventory = []
                    error = str(exc)
                finally:
                    self.system_maintenance_active = False

                def finish_inventory():
                    if not window.winfo_exists():
                        return
                    computer_progress.stop()
                    computer_progress.pack_forget()
                    refresh_apps_button.configure(state="normal")
                    if error:
                        app_inventory_status.set(
                            "Inventário parcial: confira quais fontes não responderam. "
                            "Os itens sem consulta não são marcados como atualizados."
                        )
                        inventory_status_banner.set("Consulta concluída com pendências.")
                        inventory_error.set(
                            "Algumas fontes não responderam: " + error[:240]
                        )
                        maintenance_details["text"] = error
                        details_button.configure(state="normal")
                    else:
                        inventory_status_banner.set(
                            f"Consulta concluída · última atualização em {datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')}"
                        )
                        inventory_error.set("")
                    installed_apps_inventory[:] = inventory
                    verified_at["value"] = datetime.now().astimezone().strftime(
                        "%d/%m/%Y %H:%M",
                    )
                    inventory_sort.update(column="name", reverse=False)
                    render_installed_apps()

                self.post_ui_callback(finish_inventory)

            threading.Thread(target=worker, daemon=True).start()

        refresh_apps_button.configure(command=load_installed_apps)
        context.refresh_computer_inventory = load_installed_apps

        def update_inventory_selection():
            selected_apps = [
                app_by_item[item_id]
                for item_id in inventory_table.selection()
                if item_id in app_by_item
            ]
            selected_apps = [
                app for app in selected_apps
                if app["update_status"] == "Atualização disponível"
                and app["source"] in ("APT/DEB", "Flatpak", "Snap")
                and app["package"] != "—"
            ]
            if not selected_apps:
                return

            packages = [
                (app["package"], app["version"], app["candidate_version"])
                for app in selected_apps
            ]

            def start_selected_updates():
                apt_packages = [
                    app["package"] for app in selected_apps
                    if app["source"] == "APT/DEB"
                ]
                flatpak_apps = [
                    app["package"] for app in selected_apps
                    if app["source"] == "Flatpak"
                ]
                snap_packages = [
                    app["package"] for app in selected_apps
                    if app["source"] == "Snap"
                ]
                commands = []
                if apt_packages:
                    commands.append(apt_upgrade_command(apt_packages))
                if flatpak_apps:
                    commands.append(flatpak_upgrade_command(flatpak_apps))
                if snap_packages:
                    commands.append(snap_upgrade_command(snap_packages))
                commands.append(["apt", "list", "--upgradable"])
                if shutil.which("flatpak"):
                    commands.extend([
                        [
                            "flatpak", "remote-ls", "--updates",
                            "--columns=ref,version,commit",
                        ],
                        ["flatpak", "list", "--columns=ref,version,active"],
                    ])
                if shutil.which("snap"):
                    commands.extend([
                        ["snap", "refresh", "--list"],
                        ["snap", "list"],
                    ])
                run_maintenance(
                    "Atualizar aplicativos selecionados", commands,
                    expected_packages=packages,
                )

            show_package_review(
                "Confirmar atualizações",
                "Revise os aplicativos e as versões antes de iniciar. "
                "Cada item será atualizado pelo gerenciador que o instalou.",
                packages, "Atualizar selecionados", start_selected_updates,
            )

        update_selected_button.configure(command=update_inventory_selection)

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

        action = action_card(
            "Atualizações disponíveis",
            "Sincroniza o APT e compara as versões instaladas com as novas versões.",
        )
        add_maintenance_button(action, "Verificar", "Secondary.TButton", check_system_updates)
        action = action_card(
            "Atualizar programas",
            "Atualiza o sistema sem remover pacotes e instala dependências novas quando necessário.",
        )
        add_maintenance_button(
            action, "Atualizar", "Primary.TButton",
            check_system_updates,
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