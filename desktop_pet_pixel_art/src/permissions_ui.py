"""Minimal permission review UI for core and registered local plugins."""
import tkinter as tk
from tkinter import messagebox, ttk

from permissions import SENSITIVE

CORE_PERMISSIONS = (
    ("file.read", "Ler arquivos selecionados"),
    ("file.write", "Gravar arquivos"),
    ("file.move", "Mover arquivos"),
    ("file.delete", "Excluir arquivos"),
    ("file.organize", "Organizar Downloads e capturas"),
    ("system.cpu.read", "Ler uso de CPU"),
    ("system.memory.read", "Ler uso de memória"),
    ("system.disk.read", "Ler uso de disco"),
    ("system.process.read", "Ler processos"),
    ("system.app.launch", "Abrir aplicativos"),
    ("system.maintenance.read", "Consultar atualizações e pacotes"),
    ("system.maintenance", "Alterar pacotes e cache do sistema"),
    ("spotify.control", "Controlar Spotify"),
    ("ai.use", "Usar inteligência artificial"),
    ("network.access", "Acessar a rede"),
    ("notification.create", "Criar notificações"),
    ("pet.animation.control", "Controlar animações"),
)


class PermissionsUIMixin:
    def open_permissions(self):
        window = self._set_nova_window_icon(tk.Toplevel(self.root))
        window.title("Permissões da Nova")
        window.geometry("520x600")
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Permissões", style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Permissões revogadas bloqueiam a próxima execução. Ações destrutivas ainda pedem confirmação.",
                  style="Subtitle.TLabel", wraplength=470).pack(anchor="w", pady=(5, 12))
        canvas = tk.Canvas(frame, highlightthickness=0, bg="#F5F6FA")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, padding=4)
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def add_owner(owner, rows):
            ttk.Label(content, text=owner, style="Title.TLabel").pack(anchor="w", pady=(9, 4))
            for permission, label in rows:
                variable = tk.BooleanVar(value=self.permission_manager.allowed(owner, permission))
                def toggle(permission=permission, variable=variable):
                    try:
                        if variable.get():
                            confirmed = permission not in SENSITIVE or messagebox.askyesno(
                                "Autorizar permissão", f"Autorizar {permission} para {owner}?", parent=window)
                            if not confirmed:
                                variable.set(False)
                                return
                            if not self.permission_manager.authorize(owner, permission, confirmed=True):
                                raise PermissionError("A permissão requer confirmação explícita.")
                        else:
                            self.permission_manager.revoke(owner, permission)
                    except (OSError, PermissionError) as exc:
                        messagebox.showerror("Não foi possível salvar", str(exc), parent=window)
                        variable.set(self.permission_manager.allowed(owner, permission))
                ttk.Checkbutton(content, text=label, variable=variable, command=toggle).pack(anchor="w", padx=10, pady=2)

        add_owner("Nova (recursos internos)", CORE_PERMISSIONS)
        for plugin_id in sorted(self.plugin_manager._plugins):
            plugin = self.plugin_manager._plugins[plugin_id]
            add_owner(f"Habilidade: {plugin.manifest.name} ({plugin_id})",
                      [(item, item) for item in plugin.manifest.permissions])
