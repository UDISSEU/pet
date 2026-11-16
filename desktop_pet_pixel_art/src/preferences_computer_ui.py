"""Builder for the preference tab content."""

import shutil
import subprocess
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from autonomy import find_installed_apps, save_settings
from app_manager import (
    build_uninstall_command, build_update_all_commands, display_location,
    open_installed_application, preview_uninstall, resolve_icon_path,
)
from computer_services import format_bytes
from system_updates import (
    apt_upgrade_command,
    build_installed_app_inventory,
    display_package_name,
    estimate_remaining_seconds,
    flatpak_upgrade_command,
    InstalledAppInventoryStore,
    InventoryLoadState,
    parse_apt_upgradable,
    parse_flatpak_upgradable,
    parse_package_activity,
    parse_snap_installed,
    parse_snap_upgradable,
    query_installed_app_sources,
    merge_inventory_after_partial_failure,
    snap_upgrade_command,
    run_streaming_command,
)
from ui_theme import COLORS
from ui_theme import fit_window_to_screen
from computer_center_ui import ComputerCenterUIMixin


class ComputerPreferencesTabMixin(ComputerCenterUIMixin):
    def _build_computer_preferences_tab(self, context):
        card = getattr(context, 'card', None)
        computer_content = getattr(context, 'computer_content', None)
        description = getattr(context, 'description', None)
        item = getattr(context, 'item', None)
        memory_content = getattr(context, 'memory_content', None)
        window = getattr(context, 'window', None)
        center_card = ttk.Frame(computer_content, style="Card.TFrame", padding=14)
        center_card.pack(fill="x", pady=(0, 12))
        ttk.Label(center_card, text="Central do computador", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            center_card,
            text="Acompanhe processador, memória, armazenamento, temperatura e conexão em páginas organizadas.",
            style="Hint.TLabel", wraplength=420,
        ).pack(anchor="w", pady=(4, 10))
        ttk.Button(
            center_card, text="Abrir visão geral", style="Primary.TButton",
            command=lambda: self.show_computer_center(window),
        ).pack(anchor="e")
        computer_intro = card(
            computer_content, "Atualizações e manutenção",
            "Consulte versões e atualizações de APT/DEB, Flatpak e Snap. Nenhum pacote é alterado durante a consulta.",
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
            details_window.configure(bg=COLORS["background"])
            frame = ttk.Frame(details_window, style="Autonomy.TFrame", padding=14)
            frame.pack(fill="both", expand=True)
            output = tk.Text(frame, wrap="word", height=18, relief="flat", bd=0,
                             bg=COLORS["surface"], fg=COLORS["ink"], font=("TkFixedFont", 9))
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
            dialog.configure(bg=COLORS["background"])
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
            dialog.configure(bg=COLORS["background"])
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
            application_operation_titles = (*update_operations, "Desinstalar aplicativo")
            history_saved = True
            if title in update_operations:
                history_saved = record_update_history(expected_packages, error)
            elif title == "Desinstalar aplicativo":
                history_saved = record_application_operation(
                    "Desinstalação", expected_packages, error,
                )
            if not history_saved:
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
                if title in application_operation_titles:
                    load_installed_apps(force=True)
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
                    load_installed_apps(force=True)
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
            elif title == "Desinstalar aplicativo":
                summary = "Desinstalação concluída pelo gerenciador responsável."
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
            if title in application_operation_titles:
                load_installed_apps(force=True)

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
            "Inventário alfabético de aplicativos gráficos, incluindo pacotes e aplicativos Flatpak sem atalho no menu.",
        )
        apps_controls = ttk.Frame(apps_card, style="Card.TFrame")
        apps_controls.pack(fill="x", pady=(6, 8))
        app_search = tk.StringVar(value="")
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
        inventory_summary = tk.StringVar(value="Nenhuma consulta realizada.")
        ttk.Label(
            apps_card, textvariable=inventory_summary, style="Hint.TLabel",
            wraplength=460,
        ).pack(anchor="w", pady=(0, 6))
        inventory_empty_state = ttk.Label(
            apps_card,
            text="Nenhum aplicativo encontrado.",
            style="PageHint.TLabel",
            wraplength=460,
        )
        inventory_error = tk.StringVar(value="")
        inventory_error_label = ttk.Label(
            apps_card,
            textvariable=inventory_error,
            foreground=COLORS["error"],
            background=COLORS["surface"],
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
        category_filter = tk.StringVar(value="Todas as categorias")
        category_picker = ttk.Combobox(
            app_filters, textvariable=category_filter, state="readonly",
            values=("Todas as categorias", "Sem categoria"), width=19,
        )
        category_picker.pack(side="left", padx=(8, 0))
        clear_filters_button = ttk.Button(
            app_filters,
            text="Limpar filtros",
            style="Secondary.TButton",
            command=lambda: (
                app_search.set(""),
                source_filter.set("Todas as origens"),
                update_filter.set("Todos os estados"),
                category_filter.set("Todas as categorias"),
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
            show="tree headings", height=12, style="Maintenance.Treeview",
            selectmode="extended",
        )
        inventory_table.heading("#0", text="Ícone")
        inventory_table.column("#0", width=42, minwidth=34, stretch=False, anchor="center")
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
        inventory_state = InventoryLoadState()
        app_by_item = {}
        inventory_sort = {"column": "name", "reverse": False}
        settings_path = getattr(self, "settings_path", None)
        inventory_cache_path = (
            Path(settings_path).with_name("installed_apps_inventory.json")
            if settings_path
            else Path.home() / ".config" / "desktop_pet"
            / "installed_apps_inventory.json"
        )
        inventory_store = InstalledAppInventoryStore(inventory_cache_path)
        cached_snapshot = inventory_store.load()
        installed_apps_inventory.extend(cached_snapshot["apps"])
        category_value_options = ["Todas as categorias", "Sem categoria"]

        def refresh_category_values():
            categories = sorted({
                category.strip()
                for app in installed_apps_inventory
                for category in str(app.get("categories", "")).replace(";", ",").split(",")
                if category.strip()
            }, key=str.casefold)
            category_value_options[:] = ["Todas as categorias", "Sem categoria", *categories]
            category_picker.configure(values=tuple(category_value_options))
            if category_filter.get() not in category_value_options:
                category_filter.set("Todas as categorias")

        refresh_category_values()
        source_metadata = {"value": cached_snapshot["sources"]}

        def format_source_check_times(sources):
            return " · ".join(
                f"{source}: {datetime.fromisoformat(state['checked_at']).strftime('%d/%m %H:%M')}"
                + (" (precisa verificar)" if state["needs_verification"] else "")
                + (
                    f" · catálogo local {datetime.fromisoformat(state['metadata_updated_at']).strftime('%d/%m %H:%M')}"
                    + (" (pode estar desatualizado)" if state["metadata_stale"] else "")
                    if state["metadata_updated_at"] else ""
                )
                for source, state in sources.items()
                if state["checked_at"]
            )

        verified_at = {"value": format_source_check_times(cached_snapshot["sources"])}
        if installed_apps_inventory:
            inventory_status_banner.set(
                "Inventário salvo recuperado; os estados precisam de nova verificação.",
            )
            app_inventory_status.set(
                f"{len(installed_apps_inventory)} aplicativo(s) recuperado(s) "
                "do armazenamento local."
            )
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
        update_all_apps_button = ttk.Button(
            inventory_actions, text="Atualizar todos disponíveis",
            style="Secondary.TButton", state="disabled",
        )
        update_all_apps_button.pack(side="right", padx=(0, 8))
        open_selected_button = ttk.Button(
            inventory_actions, text="Abrir", style="Secondary.TButton", state="disabled",
        )
        open_selected_button.pack(side="left", padx=(0, 6))
        uninstall_selected_button = ttk.Button(
            inventory_actions, text="Desinstalar…", style="Secondary.TButton", state="disabled",
        )
        uninstall_selected_button.pack(side="left")
        app_icon_cache = {}
        checked_icon_names = set()

        def app_icon_image(app):
            icon_name = app.get("icon", "")
            if not icon_name or icon_name in checked_icon_names:
                return app_icon_cache.get(icon_name)
            if len(checked_icon_names) >= 128:
                return None
            checked_icon_names.add(icon_name)
            path = resolve_icon_path(app)
            if path is None:
                return None
            try:
                from PIL import Image, ImageTk
                with Image.open(path) as image:
                    image = image.convert("RGBA")
                    image.thumbnail((24, 24), Image.Resampling.LANCZOS)
                    icon = ImageTk.PhotoImage(image, master=inventory_table)
                app_icon_cache[icon_name] = icon
                return icon
            except (OSError, ValueError, tk.TclError):
                return None

        def render_installed_apps(*_args):
            query = app_search.get().strip().casefold()
            selected_source = source_filter.get()
            selected_status = update_filter.get()
            selected_category = category_filter.get()
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
                            app.get("description", ""),
                            app.get("categories", ""),
                            app.get("location", ""),
                            app.get("desktop_file", ""),
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
                    and (
                        selected_category == "Todas as categorias"
                        or (selected_category == "Sem categoria" and not app.get("categories"))
                        or selected_category in {
                            category.strip()
                            for category in str(app.get("categories", "")).replace(";", ",").split(",")
                        }
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
                row_options = {
                    "values": (
                        app["name"], app["version"], app["candidate_version"],
                        app["update_status"], app["origin"], app["package"],
                    ),
                }
                icon = app_icon_image(app)
                if icon is not None:
                    row_options["image"] = icon
                item_id = inventory_table.insert("", "end", **row_options)
                app_by_item[item_id] = app
            if rows:
                inventory_empty_state.pack_forget()
                inventory_table.pack(side="left", fill="both", expand=True)
            else:
                inventory_table.pack_forget()
                if installed_apps_inventory:
                    inventory_empty_state.configure(
                        text="Nenhum aplicativo corresponde aos filtros atuais.",
                    )
                    inventory_empty_state.pack(anchor="w", pady=(0, 8))
                elif inventory_error.get():
                    inventory_empty_state.pack_forget()
                else:
                    inventory_empty_state.configure(
                        text="Nenhum aplicativo encontrado nas fontes consultadas.",
                    )
                    inventory_empty_state.pack(anchor="w", pady=(0, 8))
            counts = {
                "Atualizado": 0,
                "Atualização disponível": 0,
                "Verificação necessária": 0,
                "Atualização não gerenciada": 0,
            }
            for app in installed_apps_inventory:
                counts[app["update_status"]] = counts.get(app["update_status"], 0) + 1
            inventory_summary.set(
                f"Total: {len(installed_apps_inventory)} · "
                f"atualizados: {counts['Atualizado']} · "
                f"desatualizados: {counts['Atualização disponível']} · "
                f"aguardando verificação: {counts['Verificação necessária']} · "
                f"não gerenciados: {counts['Atualização não gerenciada']}"
            )
            app_inventory_status.set(
                f"{len(rows)} aplicativo(s) exibido(s) · "
                f"{len(installed_apps_inventory)} instalado(s)"
                + (f" · verificado em {verified_at['value']}" if verified_at["value"] else "")
            )
            if not rows and inventory_error.get():
                app_inventory_status.set(
                    "Nenhum resultado novo; consulte os detalhes da falha. "
                    "Os dados anteriores foram preservados."
                )
            elif not rows:
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
            available = [
                app for app in installed_apps_inventory
                if app["update_status"] == "Atualização disponível"
                and app["source"] in ("APT/DEB", "Flatpak", "Snap")
                and app["package"] != "—"
            ]
            update_all_apps_button.configure(
                state="normal" if available and not self.system_maintenance_active else "disabled",
                text=f"Atualizar todos disponíveis ({len(available)})",
            )
            can_open = len(selected_apps) == 1 and (
                selected_apps[0]["source"] == "AppImage"
                or selected_apps[0].get("shortcut_state") == "available"
            )
            open_selected_button.configure(state="normal" if can_open else "disabled")
            managed = len(selected_apps) == 1 and selected_apps[0]["source"] in (
                "APT/DEB", "Flatpak", "Snap",
            ) and selected_apps[0]["package"] != "—"
            can_review_manual = len(selected_apps) == 1 and selected_apps[0]["source"] in (
                "AppImage", "Manual/outro",
            )
            uninstall_selected_button.configure(
                state="normal" if (managed or can_review_manual) and not self.system_maintenance_active else "disabled",
                text="Desinstalar…" if managed else "Revisar remoção",
            )
            if not selected_apps:
                selected_app_details.set(
                    "Selecione um aplicativo para ver suas versões e detalhes."
                )
            elif len(selected_apps) == 1:
                app = selected_apps[0]
                location = display_location(app)
                categories = app.get("categories", "") or "Não informada"
                description = app.get("description") or "Sem descrição fornecida pelo aplicativo."
                shortcut = {
                    "available": "disponível", "broken": "quebrado", "absent": "ausente",
                }.get(app.get("shortcut_state"), "não identificado")
                details = (
                    f"{app['name']}\n{description}\n"
                    f"Instalada: {app['version']} · disponível: {app['candidate_version']}\n"
                    f"Origem: {app['origin']} · categoria: {categories}\n"
                    f"Estado: {app['update_status']} · atalho: {shortcut}"
                )
                if app.get("desktop_file") and not app["desktop_file"].startswith("appstream:"):
                    details += f" · arquivo: {app['desktop_file']}"
                details += f"\nExecutável/localização: {location}"
                if app["source"] == "AppImage":
                    try:
                        path = Path(app["package"])
                        if path.is_file() and not path.is_symlink():
                            details += f" · arquivo {format_bytes(path.stat().st_size)}"
                    except OSError:
                        pass
                duplicate_sources = sorted({
                    other["origin"] for other in installed_apps_inventory
                    if other is not app and other["name"].casefold() == app["name"].casefold()
                }, key=str.casefold)
                if duplicate_sources:
                    details += "\nPossível duplicata com: " + ", ".join(duplicate_sources)
                if app["source"] in ("APT/DEB", "Flatpak", "Snap"):
                    details += "\nTamanho instalado: não consultado nesta versão."
                selected_app_details.set(details)
            else:
                selected_app_details.set(
                    f"{len(selected_apps)} aplicativos selecionados; "
                    f"{len(eligible)} podem ser atualizados por seus gerenciadores."
                )

        app_search.trace_add("write", render_installed_apps)
        source_filter.trace_add("write", render_installed_apps)
        update_filter.trace_add("write", render_installed_apps)
        category_filter.trace_add("write", render_installed_apps)
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
            computer_content, "Histórico de operações",
            "Atualizações e remoções iniciadas pela Nova; dados pessoais não são registrados.",
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

        def record_application_operation(operation, expected_packages, error):
            names = sorted({
                str(package[0]).removeprefix("Flatpak · ").removeprefix("Snap · ")
                for package in expected_packages if package
            }, key=str.casefold)
            if not names:
                names = ["Aplicativos selecionados"]
            event = {
                "when": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
                "apps": f"{operation}: {', '.join(names)}"[:240],
                "result": "Concluída" if not error else "Com falhas",
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
        render_installed_apps()

        def load_installed_apps(*, force=False):
            if not inventory_state.begin(force=force):
                return
            try:
                self._authorize_core_action("system.maintenance.read")
            except (PermissionError, OSError) as exc:
                inventory_state.finish()
                inventory_status_banner.set("Permissão necessária para consultar o inventário.")
                inventory_error.set(f"Não foi possível consultar os aplicativos: {exc}")
                return
            if self.system_maintenance_active:
                inventory_state.finish()
                inventory_status_banner.set("Aguarde a manutenção atual terminar.")
                app_inventory_status.set(
                    "A consulta será iniciada quando não houver manutenção em andamento.",
                )
                return
            self.system_maintenance_active = True
            inventory_error.set("")
            refresh_apps_button.configure(state="disabled")
            inventory_status_banner.set("Consultando apps instalados e versões disponíveis…")
            app_inventory_status.set("Lendo aplicativos e versões instaladas…")
            if not installed_apps_inventory:
                inventory_empty_state.configure(
                    text="Consultando fontes; a lista será exibida quando a consulta terminar.",
                )
                inventory_empty_state.pack(anchor="w", pady=(0, 8))
            computer_progress.pack(
                fill="x", pady=(10, 0), before=details_button,
            )
            computer_progress.start(12)

            def worker():
                inventory = []
                error = None
                completed = False
                commit_inventory = False
                previous_inventory = list(installed_apps_inventory)
                sources = None
                saved_snapshot = None

                def preserve_previous_inventory():
                    failed_sources = {"APT/DEB", "Flatpak", "Snap"}
                    return merge_inventory_after_partial_failure(
                        previous_inventory,
                        [
                            app for app in previous_inventory
                            if app["source"] not in failed_sources
                        ],
                        failed_sources,
                    )

                try:
                    self.permission_manager.require(
                        "nova.core", "system.maintenance.read",
                    )
                    source_errors = []
                    launcher_discovery_complete = True
                    try:
                        apps = find_installed_apps()
                    except OSError as exc:
                        apps = []
                        launcher_discovery_complete = False
                        source_errors.append(f"Atalhos do sistema: {exc}")
                    sources = query_installed_app_sources(
                        apps,
                        env={**self._child_process_env(), "LC_ALL": "C"},
                        cancel_event=inventory_state.cancel_event,
                    )
                    source_errors.extend(sources["errors"])
                    if not launcher_discovery_complete:
                        sources["inventory_complete_sources"].discard("APT/DEB")
                        sources["source_results"]["APT/DEB"][
                            "inventory_complete"
                        ] = False
                    inventory = build_installed_app_inventory(
                        apps,
                        sources["package_versions"],
                        sources["package_owners"],
                        sources["flatpak_output"],
                        apt_upgradable=sources["apt_upgradable"],
                        flatpak_update_output=sources["flatpak_update_output"],
                        snap_output=sources["snap_output"],
                        snap_update_output=sources["snap_update_output"],
                        checked_sources=sources["checked_sources"],
                        apt_owners_checked=sources["apt_owners_checked"],
                        apt_applications=sources["apt_applications"],
                        snap_applications=sources["snap_applications"],
                    )
                    failed_sources = (
                        set(sources["source_results"])
                        - sources["inventory_complete_sources"]
                    )
                    inventory = merge_inventory_after_partial_failure(
                        previous_inventory, inventory, failed_sources,
                    )
                    commit_inventory = bool(
                        sources["inventory_complete_sources"]
                        or any(
                            app["source"] in failed_sources
                            for app in previous_inventory
                        )
                        or any(
                            app["source"] in ("AppImage", "Manual/outro")
                            for app in inventory
                        )
                    )
                    error = "\n".join(source_errors) or None
                    completed = True
                except (PermissionError, OSError, subprocess.SubprocessError, ValueError) as exc:
                    inventory = preserve_previous_inventory()
                    commit_inventory = bool(previous_inventory)
                    error = str(exc)
                except Exception as exc:
                    inventory = preserve_previous_inventory()
                    commit_inventory = bool(previous_inventory)
                    error = f"Falha ao montar o inventário ({type(exc).__name__}): {exc}"
                finally:
                    if commit_inventory:
                        source_results = (
                            sources["source_results"] if sources else {
                                source: {
                                    "inventory_complete": False,
                                    "updates_complete": False,
                                }
                                for source in ("APT/DEB", "Flatpak", "Snap")
                            }
                        )
                        try:
                            saved_snapshot = inventory_store.save(
                                inventory,
                                source_results,
                                previous_sources=source_metadata["value"],
                            )
                        except (OSError, TypeError, ValueError) as exc:
                            persistence_error = (
                                "Não foi possível salvar o inventário local: "
                                f"{exc}"
                            )
                            error = "\n".join(
                                filter(None, (error, persistence_error)),
                            )
                    self.system_maintenance_active = False
                    inventory_state.finish(completed=completed)

                if inventory_state.closed:
                    return

                def finish_inventory():
                    try:
                        window_exists = window.winfo_exists()
                    except tk.TclError:
                        window_exists = False
                    if inventory_state.closed or not window_exists:
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
                        inventory_error.set("Detalhes das falhas:\n" + error)
                        maintenance_details["text"] = error
                        details_button.configure(state="normal")
                        if (
                            sources
                            and not sources["inventory_complete_sources"]
                            and not commit_inventory
                        ):
                            inventory_status_banner.set(
                                "Falha nas fontes de pacotes; inventário anterior preservado.",
                            )
                    else:
                        inventory_status_banner.set(
                            f"Consulta concluída · última atualização em {datetime.now().astimezone().strftime('%d/%m/%Y %H:%M')}"
                        )
                        inventory_error.set("")
                    if commit_inventory:
                        installed_apps_inventory[:] = (
                            saved_snapshot["apps"] if saved_snapshot else inventory
                        )
                        refresh_category_values()
                        if saved_snapshot:
                            source_metadata["value"] = saved_snapshot["sources"]
                            verified_at["value"] = format_source_check_times(
                                saved_snapshot["sources"],
                            )
                        inventory_sort.update(column="name", reverse=False)
                    render_installed_apps()

                self.post_ui_callback(finish_inventory)

            try:
                threading.Thread(target=worker, daemon=True).start()
            except (OSError, RuntimeError) as exc:
                self.system_maintenance_active = False
                inventory_state.finish()
                computer_progress.stop()
                computer_progress.pack_forget()
                refresh_apps_button.configure(state="normal")
                inventory_status_banner.set("Não foi possível iniciar a consulta.")
                inventory_error.set(f"Erro ao iniciar o inventário: {exc}")

        refresh_apps_button.configure(
            command=lambda: load_installed_apps(force=True),
        )
        context.refresh_computer_inventory = load_installed_apps
        window.bind(
            "<Destroy>",
            lambda event: inventory_state.close() if event.widget is window else None,
            add="+",
        )

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
                commands = build_update_all_commands(selected_apps)
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

        def update_all_available_apps():
            apps = [
                app for app in installed_apps_inventory
                if app["update_status"] == "Atualização disponível"
                and app["source"] in ("APT/DEB", "Flatpak", "Snap")
                and app["package"] != "—"
            ]
            if not apps or self.system_maintenance_active:
                return
            packages = [
                (app["package"], app["version"], app["candidate_version"])
                for app in apps
            ]

            def start_updates():
                try:
                    commands = build_update_all_commands(apps)
                except ValueError as exc:
                    messagebox.showerror("Atualização indisponível", str(exc), parent=window)
                    return
                commands.append(["apt", "list", "--upgradable"])
                if shutil.which("flatpak"):
                    commands.extend([
                        ["flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"],
                        ["flatpak", "list", "--columns=ref,version,active"],
                    ])
                if shutil.which("snap"):
                    commands.extend([["snap", "refresh", "--list"], ["snap", "list"]])
                run_maintenance(
                    "Atualizar aplicativos selecionados", commands,
                    expected_packages=packages,
                )

            show_package_review(
                "Confirmar atualização dos aplicativos",
                "A Nova atualizará somente estes aplicativos pelos gerenciadores de origem. "
                "Dependências necessárias podem ser atualizadas pelo próprio gerenciador.",
                packages, "Atualizar todos", start_updates,
            )

        update_all_apps_button.configure(command=update_all_available_apps)

        def open_selected_application():
            selected = [
                app_by_item[item_id] for item_id in inventory_table.selection()
                if item_id in app_by_item
            ]
            if len(selected) != 1:
                return
            app = selected[0]
            try:
                self._authorize_core_action("system.app.launch", confirmed=True)
                self.permission_manager.require(
                    "nova.core", "system.app.launch", confirmed=True,
                )
            except (PermissionError, OSError) as exc:
                messagebox.showerror("Permissão necessária", str(exc), parent=window)
                return
            computer_status.set(f"Abrindo {app['name']}…")

            def worker():
                try:
                    self.permission_manager.require(
                        "nova.core", "system.app.launch", confirmed=True,
                    )
                    open_installed_application(
                        app, env=self._child_process_env(),
                    )
                    result = None
                except Exception as exc:
                    result = f"Não foi possível abrir {app['name']}: {type(exc).__name__}."

                def finish_open():
                    try:
                        if not window.winfo_exists():
                            return
                    except tk.TclError:
                        return
                    if result:
                        computer_status_label.configure(style="ComputerStatusError.TLabel")
                        computer_status.set(result)
                    else:
                        computer_status_label.configure(style="ComputerStatus.TLabel")
                        computer_status.set(f"Abertura de {app['name']} solicitada.")

                self.post_ui_callback(finish_open)

            try:
                threading.Thread(target=worker, name="nova-open-installed-app", daemon=True).start()
            except (OSError, RuntimeError) as exc:
                computer_status.set(f"Não foi possível iniciar a abertura: {exc}")

        open_selected_button.configure(command=open_selected_application)

        def request_uninstall_selected():
            selected = [
                app_by_item[item_id] for item_id in inventory_table.selection()
                if item_id in app_by_item
            ]
            if len(selected) != 1:
                return
            app = selected[0]
            if app["source"] not in ("APT/DEB", "Flatpak", "Snap"):
                shortcut = app.get("desktop_file") or "Nenhum atalho identificado"
                location = display_location(app)
                messagebox.showinfo(
                    "Revisar remoção manual",
                    f"Origem: {app['source']}\nLocalização: {location}\nAtalho: {shortcut}\n\n"
                    "Os dados associados não podem ser identificados com segurança. "
                    "A Nova não apagará o executável, atalho nem configurações automaticamente. "
                    "Faça a remoção manual após revisar esses locais; nenhum arquivo será alterado agora.",
                    parent=window,
                )
                return
            try:
                self._authorize_core_action("system.maintenance.read")
                self.permission_manager.require("nova.core", "system.maintenance.read")
            except (PermissionError, OSError) as exc:
                messagebox.showerror("Permissão necessária", str(exc), parent=window)
                return
            if self.system_maintenance_active:
                messagebox.showinfo("Manutenção em andamento", "Aguarde a ação atual terminar.", parent=window)
                return
            self.system_maintenance_active = True
            computer_status.set(f"Preparando prévia de remoção para {app['name']}…")
            for button in maintenance_buttons:
                button.configure(state="disabled")

            def worker():
                try:
                    self.permission_manager.require("nova.core", "system.maintenance.read")
                    preview = preview_uninstall(
                        app, env={**self._child_process_env(), "LC_ALL": "C"},
                    )
                    error = None
                except Exception as exc:
                    preview = None
                    error = f"Não foi possível simular a remoção ({type(exc).__name__}): {exc}"
                finally:
                    self.system_maintenance_active = False

                def finish_preview():
                    try:
                        if not window.winfo_exists():
                            return
                    except tk.TclError:
                        return
                    for button in maintenance_buttons:
                        button.configure(state="normal")
                    if error:
                        computer_status_label.configure(style="ComputerStatusError.TLabel")
                        computer_status.set(error)
                        return
                    removal_rows = [
                        (name, "Instalado", "Será removido")
                        for name in preview["packages"]
                    ]
                    if not removal_rows:
                        removal_rows = [(app["package"], app["version"], "Será removido")]
                    expected = [(app["package"], app["version"], app["candidate_version"])]

                    def confirm_removal():
                        try:
                            command = build_uninstall_command(app)
                        except ValueError as exc:
                            messagebox.showerror("Remoção indisponível", str(exc), parent=window)
                            return
                        run_maintenance(
                            "Desinstalar aplicativo", [command],
                            expected_packages=expected,
                        )

                    show_package_review(
                        f"Confirmar remoção · {app['name']}",
                        f"Origem: {preview['manager']}. {preview['personal_data']} "
                        f"{preview['details'][:500]}",
                        removal_rows, "Desinstalar aplicativo", confirm_removal,
                    )

                self.post_ui_callback(finish_preview)

            try:
                threading.Thread(target=worker, name="nova-preview-app-removal", daemon=True).start()
            except (OSError, RuntimeError) as exc:
                self.system_maintenance_active = False
                for button in maintenance_buttons:
                    button.configure(state="normal")
                computer_status.set(f"Não foi possível iniciar a prévia: {exc}")

        uninstall_selected_button.configure(command=request_uninstall_selected)

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
