"""Small first-access welcome screen that never installs or downloads models."""

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from environment_check import check_environment, format_disk_space, format_memory
from installation_state import InstallationStateStore


def run_first_access_if_needed(icon_path=None, *, state_store=None):
    store = state_store or InstallationStateStore()
    if store.load()["setup_completed"]:
        return True
    report = check_environment()
    if not _show_welcome_window(icon_path, report):
        return False
    store.complete_first_run(report.to_installation_state())
    return True


def _show_welcome_window(icon_path=None, report=None):
    report = report or check_environment()
    window = tk.Tk()
    window.title("Bem-vinda à Nova")
    window.resizable(True, True)
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    window_width = max(320, min(760, screen_width - 32))
    window_height = max(260, min(720, screen_height - 48))
    window.minsize(min(480, window_width), min(380, window_height))
    window.geometry(f"{window_width}x{window_height}")
    try:
        window.attributes("-topmost", True)
    except tk.TclError:
        pass

    result = {"continue": False}
    container = ttk.Frame(window, padding=16)
    container.pack(fill="both", expand=True)
    scroll_area = ttk.Frame(container)
    container.columnconfigure(0, weight=1)
    container.rowconfigure(0, weight=1)
    scroll_area.grid(row=0, column=0, sticky="nsew")
    canvas = tk.Canvas(scroll_area, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(scroll_area, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    content = ttk.Frame(canvas, padding=(8, 8, 16, 18))
    content_window = canvas.create_window((0, 0), window=content, anchor="nw")

    def update_scroll_region(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def resize_content(event):
        canvas.itemconfigure(content_window, width=event.width)

    content.bind("<Configure>", update_scroll_region)
    canvas.bind("<Configure>", resize_content)

    image_path = Path(icon_path) if icon_path is not None else None
    if image_path is not None and image_path.is_file():
        try:
            with Image.open(image_path) as source:
                image = source.convert("RGBA")
                image.thumbnail((96, 96), Image.Resampling.LANCZOS)
            window.nova_image = ImageTk.PhotoImage(image)
            ttk.Label(content, image=window.nova_image).pack(pady=(0, 8))
        except (OSError, tk.TclError, ValueError):
            pass

    ttk.Label(
        content, text="Oi! Eu sou a Nova",
        font=("TkDefaultFont", 19, "bold"),
    ).pack(pady=(0, 6))
    intro = ttk.Label(
        content,
        text=(
            "Que bom ter você por aqui. A Nova pode continuar funcionando sem o Ollama; "
            "a conversa por IA só fica disponível quando o serviço local e um modelo já "
            "estiverem prontos."
        ),
        justify="left",
        wraplength=640,
    )
    intro.pack(fill="x", pady=(0, 10))
    privacy = ttk.Label(
        content,
        text=(
            "Nenhum modelo será baixado nesta tela. A instalação ou o download de um "
            "modelo só acontecerá depois de uma confirmação explícita."
        ),
        justify="left",
        wraplength=640,
    )
    privacy.pack(fill="x", pady=(0, 8))
    ttk.Label(
        content, text="Suas preferências, perfis e memórias existentes não serão apagados.",
        justify="left", wraplength=640,
    ).pack(fill="x", pady=(0, 14))

    checks = ttk.LabelFrame(content, text="VERIFICAÇÃO DO COMPUTADOR", padding=(14, 10))
    checks.pack(fill="x")
    ollama_descriptions = {
        "ready": f"Ollama disponível; modelo {report.selected_model} encontrado.",
        "model_missing": f"Ollama disponível; falta o modelo {report.selected_model}.",
        "installed_not_running": "Ollama instalado, mas o serviço não está respondendo.",
        "not_installed": "Ollama não encontrado; a Nova pode continuar sem IA.",
        "unavailable": "O serviço respondeu em formato não reconhecido.",
    }
    dependency_status = (
        "Todas as dependências principais foram encontradas."
        if all(report.dependencies.values())
        else "Faltam dependências; execute ./install.sh antes de continuar."
    )
    rows = (
        ("Python", f"{report.python_version} — " + (
            "compatível" if report.python_supported else "requer Python 3.10 ou superior"
        )),
        ("Dependências", dependency_status),
        ("Ollama", ollama_descriptions.get(report.ollama_status, "Estado não reconhecido.")),
        ("Personalidade", "Módulos disponíveis." if report.personality_status == "available"
         else "Módulos não encontrados."),
        ("Recursos gráficos",
         f"{report.graphics_available}/{report.graphics_total} animações encontradas."),
        ("Memória SQLite", {
            "ready": "Banco de memória existente legível.",
            "not_created": "Banco será criado/reutilizado pela aplicação ao iniciar.",
            "corrupt": "Banco de memória com erro de integridade; os dados serão preservados.",
            "unsafe": "Banco de memória usa um link simbólico; verifique o diagnóstico.",
            "unavailable": "Banco de memória não pôde ser verificado.",
            "unrecognized": "Arquivo SQLite existente não foi reconhecido como banco da Nova.",
            "profile_registry_invalid":
                "Registro de perfis precisa de atenção; nada será apagado.",
        }.get(report.database_status, "Estado não reconhecido.")),
        ("Armazenamento", format_disk_space(report.free_disk_bytes)),
        ("Hardware", f"{format_memory(report.memory_total_bytes)} · "
         f"{report.cpu_count or 'CPU não detectada'} núcleos lógicos"),
    )
    status_labels = []
    for label, value in rows:
        row = ttk.Frame(checks)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=label, font=("TkDefaultFont", 9, "bold")).pack(
            anchor="nw", side="left", padx=(0, 8),
        )
        value_label = ttk.Label(row, text=value, wraplength=590, justify="left")
        value_label.pack(anchor="w", fill="x", expand=True)
        status_labels.append(value_label)

    def update_wrapping(event):
        text_width = max(220, event.width - 80)
        intro.configure(wraplength=text_width)
        privacy.configure(wraplength=text_width)
        for label in status_labels:
            label.configure(wraplength=text_width)

    content.bind("<Configure>", update_wrapping, add="+")

    footer = ttk.Frame(container, padding=(0, 12, 0, 0))
    footer.grid(row=1, column=0, sticky="ew")
    separator = ttk.Separator(footer, orient="horizontal")
    separator.pack(fill="x", pady=(0, 12))
    button_row = ttk.Frame(footer)
    button_row.pack(fill="x")

    def finish(continue_to_app):
        result["continue"] = continue_to_app
        window.destroy()

    continue_button = tk.Button(
        button_row,
        text="Continuar sem baixar modelos",
        command=lambda: finish(True),
        background="#2864D7",
        foreground="#FFFFFF",
        activebackground="#1D4FAF",
        activeforeground="#FFFFFF",
        disabledforeground="#E6EAF0",
        highlightbackground="#2864D7",
        highlightcolor="#17469E",
        highlightthickness=2,
        borderwidth=0,
        relief="flat",
        padx=18,
        pady=11,
        font=("TkDefaultFont", 10, "bold"),
        cursor="hand2",
    )
    exit_button = tk.Button(
        button_row,
        text="Sair",
        command=lambda: finish(False),
        background="#E8EDF4",
        foreground="#24364B",
        activebackground="#D4DDE9",
        activeforeground="#18263A",
        highlightbackground="#AAB8C8",
        highlightcolor="#64748B",
        highlightthickness=1,
        borderwidth=1,
        relief="solid",
        padx=16,
        pady=10,
        font=("TkDefaultFont", 10),
        cursor="hand2",
    )
    if not report.can_continue:
        continue_button.configure(state="disabled")
        ttk.Label(
            footer,
            text="Corrija Python/dependências com ./install.sh para continuar.",
            wraplength=420,
            justify="left",
        ).pack(fill="x", pady=(0, 8))

    def arrange_buttons(event=None):
        width = event.width if event is not None else window.winfo_width()
        continue_button.grid_forget()
        exit_button.grid_forget()
        if width < 520:
            continue_button.grid(row=0, column=0, sticky="ew", pady=(0, 8))
            exit_button.grid(row=1, column=0, sticky="ew")
            button_row.columnconfigure(0, weight=1)
        else:
            exit_button.grid(row=0, column=0, sticky="w")
            continue_button.grid(row=0, column=1, sticky="e")
            button_row.columnconfigure(0, weight=1)
            button_row.columnconfigure(1, weight=0)

    button_row.bind("<Configure>", arrange_buttons)

    def scroll_content(event):
        if event.delta:
            canvas.yview_scroll(-int(event.delta / 120), "units")

    canvas.bind("<MouseWheel>", scroll_content)

    window.protocol("WM_DELETE_WINDOW", lambda: finish(False))
    window.bind("<Return>", lambda _event: continue_button.invoke())
    window.bind("<Escape>", lambda _event: finish(False))
    window.update_idletasks()
    arrange_buttons()
    x = max(0, (screen_width - window.winfo_width()) // 2)
    y = max(0, (screen_height - window.winfo_height()) // 2)
    window.geometry(f"+{x}+{y}")
    continue_button.focus_set()
    window.mainloop()
    return result["continue"]
