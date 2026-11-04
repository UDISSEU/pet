"""Builder for the preference tab content."""

import re
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk


class ComputerPreferencesTabMixin:
    def _build_computer_preferences_tab(self, context):
        card = getattr(context, 'card', None)
        computer_content = getattr(context, 'computer_content', None)
        description = getattr(context, 'description', None)
        item = getattr(context, 'item', None)
        memory_content = getattr(context, 'memory_content', None)
        window = getattr(context, 'window', None)
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