"""Minimal permission review UI for core and registered local plugins."""
import tkinter as tk
from tkinter import messagebox, ttk

from permissions import SENSITIVE
from ui_theme import COLORS, make_header

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
        existing = getattr(self, "_permissions_window", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.deiconify()
                    existing.lift()
                    existing.focus_set()
                    return existing
            except tk.TclError:
                pass
        window = self._set_nova_window_icon(tk.Toplevel(self.root))
        self._permissions_window = window
        window.title("Permissões da Nova")
        window.geometry("560x640")
        window.minsize(500, 500)
        window.configure(bg=COLORS["background"])
        make_header(window, "Permissões", "Controle o que a Nova e cada habilidade podem acessar.",
                    eyebrow="NOVA  /  PRIVACIDADE")
        frame = tk.Frame(window, bg=COLORS["background"], padx=14, pady=12)
        frame.pack(fill="both", expand=True)
        notice = tk.Frame(frame, bg=COLORS["surface"], padx=11, pady=9,
                          highlightbackground=COLORS["border"], highlightthickness=1)
        notice.pack(fill="x", pady=(0, 10))
        tk.Label(notice, text="Acesso sob seu controle", bg=COLORS["surface"],
                 fg=COLORS["ink"], font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        tk.Label(notice, text="Revogações valem na próxima execução. Ações destrutivas continuam pedindo confirmação.",
                 bg=COLORS["surface"], fg=COLORS["muted"], font=("TkDefaultFont", 9),
                 wraplength=490, justify="left").pack(anchor="w", pady=(3, 0))
        list_frame = tk.Frame(frame, bg=COLORS["surface"], padx=10, pady=7,
                              highlightbackground=COLORS["border"], highlightthickness=1)
        list_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(list_frame, highlightthickness=0, bg=COLORS["surface"])
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        content = tk.Frame(canvas, bg=COLORS["surface"], padx=4)
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def add_owner(owner_id, owner_label, rows):
            tk.Label(content, text=owner_label, bg=COLORS["surface"], fg=COLORS["ink"],
                     font=("TkDefaultFont", 10, "bold"), anchor="w").pack(anchor="w", pady=(9, 4))
            for permission, label in rows:
                variable = tk.BooleanVar(value=self.permission_manager.allowed(owner_id, permission))
                def toggle(permission=permission, variable=variable, owner_id=owner_id,
                           owner_label=owner_label):
                    try:
                        if variable.get():
                            confirmed = permission not in SENSITIVE or messagebox.askyesno(
                                "Autorizar permissão", f"Autorizar {permission} para {owner_label}?", parent=window)
                            if not confirmed:
                                variable.set(False)
                                return
                            if not self.permission_manager.authorize(owner_id, permission, confirmed=True):
                                raise PermissionError("A permissão requer confirmação explícita.")
                        else:
                            self.permission_manager.revoke(owner_id, permission)
                    except (OSError, PermissionError) as exc:
                        messagebox.showerror("Não foi possível salvar", str(exc), parent=window)
                        variable.set(self.permission_manager.allowed(owner_id, permission))
                ttk.Checkbutton(content, text=label, variable=variable, command=toggle).pack(anchor="w", padx=8, pady=3)

        add_owner("nova.core", "Nova (recursos internos)", CORE_PERMISSIONS)
        for plugin_id in sorted(self.plugin_manager._plugins):
            plugin = self.plugin_manager._plugins[plugin_id]
            add_owner(plugin_id, f"Habilidade: {plugin.manifest.name} ({plugin_id})",
                      [(item, item) for item in plugin.manifest.permissions])

        def close_window():
            if getattr(self, "_permissions_window", None) is window:
                self._permissions_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_window)
        return window
