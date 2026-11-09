"""Local, read-only installation diagnostics for the desktop application."""

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk

from environment_check import check_environment, format_disk_space, format_memory
from ui_theme import fit_window_to_screen, make_header

logger = logging.getLogger(__name__)


def diagnostic_recommendations(report, memory_health=None):
    guidance = []
    missing_dependencies = [
        name for name, available in report.dependencies.items() if not available
    ]
    if not report.python_supported:
        guidance.append("Use Python 3.10 ou superior e execute ./install.sh novamente.")
    if missing_dependencies:
        guidance.append(
            "Feche a Nova e execute ./install.sh para preparar as dependências: "
            + ", ".join(missing_dependencies)
            + "."
        )
    if report.ollama_status == "not_installed":
        guidance.append(
            "Para usar conversa por IA, instale o Ollama em https://ollama.com/download "
            "e inicie o serviço manualmente. A Nova não instala serviços do sistema."
        )
    elif report.ollama_status == "installed_not_running":
        guidance.append(
            "O executável Ollama existe, mas o serviço local não respondeu. "
            "Inicie-o pelo gerenciador de serviços ou pelas instruções da sua instalação."
        )
    elif report.ollama_status == "model_missing":
        guidance.append(
            "O modelo configurado não foi encontrado. Abra Preferências > Inteligência "
            "artificial para baixá-lo; o download exige confirmação."
        )
    elif report.ollama_status == "unavailable":
        guidance.append(
            "Não foi possível validar o serviço Ollama local. Confira o endereço local "
            "e o formato da resposta; nenhum serviço remoto foi consultado."
        )
    if report.database_status in ("corrupt", "unrecognized", "unsafe", "unavailable",
                                  "profile_registry_invalid"):
        guidance.append(
            "A memória existente precisa de atenção. A Nova preservou os dados e não "
            "tentará recriar nem apagar o banco automaticamente."
        )
    if memory_health is not None and memory_health.get("status") != "healthy":
        guidance.append(
            "A verificação do SQLite encontrou um estado degradado. Preserve os backups "
            "e investigue o banco antes de restaurar ou remover arquivos."
        )
    if report.graphics_status != "ready":
        guidance.append(
            "Alguns assets de animação estão ausentes. Verifique os arquivos da instalação "
            "antes de substituí-los."
        )
    if report.personality_status != "available":
        guidance.append(
            "Os módulos de personalidade não foram encontrados. Verifique ou reinstale "
            "os arquivos da aplicação."
        )
    if not guidance:
        guidance.append("As verificações locais estão em ordem; nenhuma ação de reparo é necessária.")
    return tuple(guidance)


def open_diagnostics_window(
    parent, *, on_open_ai=None, on_back=None, on_open=None,
    checker=check_environment,
    memory_checker=None,
):
    window = tk.Toplevel(parent)
    window.title("Diagnóstico da Nova")
    window.transient(parent)
    fit_window_to_screen(window, 600, 570, min_width=500, min_height=420)
    if on_open is not None:
        on_open(window)

    make_header(
        window, "Diagnóstico local",
        "Verifique os componentes e a instalação da Nova.",
        eyebrow="NOVA  /  DIAGNÓSTICO",
        back_command=(
            (lambda: on_back(window)) if on_back is not None else window.destroy
        ),
    )

    content = ttk.Frame(window, padding=18)
    content.pack(fill="both", expand=True)
    ttk.Label(
        content,
        text=(
            "Esta verificação é somente leitura: não inicia serviços, instala pacotes, "
            "altera memórias nem baixa modelos."
        ),
        wraplength=540,
    ).pack(anchor="w", pady=(0, 12))

    results = ttk.LabelFrame(content, text="Estado", padding=10)
    results.pack(fill="x")
    status_text = tk.StringVar(value="Aguardando verificação…")
    ttk.Label(results, textvariable=status_text, justify="left", wraplength=530).pack(
        anchor="w",
    )
    guidance = ttk.LabelFrame(content, text="Próximas ações", padding=10)
    guidance.pack(fill="both", expand=True, pady=(12, 0))
    guidance_text_widget = tk.Text(
        guidance, wrap="word", height=12, relief="flat", state="disabled",
    )
    guidance_scrollbar = ttk.Scrollbar(
        guidance, orient="vertical", command=guidance_text_widget.yview,
    )
    guidance_text_widget.configure(yscrollcommand=guidance_scrollbar.set)
    guidance_scrollbar.pack(side="right", fill="y")
    guidance_text_widget.pack(side="left", fill="both", expand=True)

    actions = ttk.Frame(content)
    actions.pack(fill="x", pady=(14, 0))
    result_queue = queue.Queue()
    checking = {"active": False}
    pending_poll = {"after_id": None}
    recheck = ttk.Button(actions, text="Verificar novamente")
    recheck.pack(side="left")
    ai_button = ttk.Button(
        actions, text="Preferências de IA", command=on_open_ai or (lambda: None),
    )
    if on_open_ai is not None:
        ai_button.pack(side="left", padx=(8, 0))
    ttk.Button(actions, text="Fechar", command=window.destroy).pack(side="right")

    def render(report, memory_health=None):
        dependency_line = ", ".join(
            f"{name}: {'OK' if available else 'ausente'}"
            for name, available in report.dependencies.items()
        )
        status_text.set(
            f"Python {report.python_version}: "
            f"{'compatível' if report.python_supported else 'incompatível'}\n"
            f"Dependências: {dependency_line}\n"
            f"Ollama: {report.ollama_status}; modelo: {report.selected_model}\n"
            f"Memória: {report.database_status}; personalidade: {report.personality_status}\n"
            f"Animações: {report.graphics_available}/{report.graphics_total} "
            f"({report.graphics_status})\n"
            f"Hardware: {format_memory(report.memory_total_bytes)}, "
            f"{report.cpu_count or 'CPU desconhecida'} CPUs lógicas, "
            f"{format_disk_space(report.free_disk_bytes)}"
        )
        if memory_health is not None:
            status_text.set(
                status_text.get() + "\nSQLite local: "
                f"{memory_health.get('status', 'indisponível')}; "
                f"integridade: {memory_health.get('integrity_check', 'desconhecida')}; "
                f"{memory_health.get('database_size_bytes', 0)} bytes"
            )
        guidance_text_widget.configure(state="normal")
        guidance_text_widget.delete("1.0", "end")
        guidance_text_widget.insert(
            "1.0",
            "\n\n".join(
                f"• {item}" for item in diagnostic_recommendations(report, memory_health)
            ),
        )
        guidance_text_widget.configure(state="disabled")
        has_ollama_issue = report.ollama_status == "model_missing"
        if on_open_ai is not None:
            ai_button.configure(state="normal" if has_ollama_issue else "disabled")

    def poll_results():
        pending_poll["after_id"] = None
        if not window.winfo_exists():
            return
        try:
            report, memory_health, error = result_queue.get_nowait()
        except queue.Empty:
            if checking["active"]:
                pending_poll["after_id"] = window.after(100, poll_results)
            return
        checking["active"] = False
        recheck.configure(state="normal")
        if error is not None:
            status_text.set("Não foi possível concluir o diagnóstico local.")
            guidance_text_widget.configure(state="normal")
            guidance_text_widget.delete("1.0", "end")
            guidance_text_widget.insert("1.0", "Tente novamente. Nenhuma alteração foi feita.")
            guidance_text_widget.configure(state="disabled")
        else:
            render(report, memory_health)

    def cancel_pending_poll(event):
        if event.widget is not window or pending_poll["after_id"] is None:
            return
        try:
            window.after_cancel(pending_poll["after_id"])
        except tk.TclError:
            pass
        pending_poll["after_id"] = None

    def start_check():
        if checking["active"]:
            return
        checking["active"] = True
        recheck.configure(state="disabled")
        status_text.set("Verificando componentes locais…")
        guidance_text_widget.configure(state="normal")
        guidance_text_widget.delete("1.0", "end")
        guidance_text_widget.configure(state="disabled")

        def worker():
            try:
                report = checker()
            except Exception:
                logger.exception("Falha ao verificar o ambiente da Nova")
                result_queue.put((None, None, True))
                return
            memory_health = None
            if memory_checker is not None:
                try:
                    memory_health = memory_checker()
                except Exception:
                    logger.exception("Falha ao verificar a saúde do SQLite da Nova")
                    memory_health = {"status": "unavailable"}
            result_queue.put((report, memory_health, None))

        threading.Thread(
            target=worker, daemon=True, name="nova-environment-diagnostic",
        ).start()
        pending_poll["after_id"] = window.after(100, poll_results)

    recheck.configure(command=start_check)

    def close_on_escape(event):
        if event.keysym == "Escape":
            window.destroy()
            return "break"
        return None

    window.bind("<Escape>", close_on_escape)
    window.bind("<Destroy>", cancel_pending_poll, add="+")
    start_check()
    return window
