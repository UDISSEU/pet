#!/usr/bin/env python3
"""First-launch setup for Nova using only the system Python standard library."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request


APP_DIR = Path(__file__).resolve().parents[1]
VENV_DIR = APP_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
INSTALLER = APP_DIR / "install.sh"
APP_ENTRY = APP_DIR / "src" / "desktop_pet.py"
STATE_PATH = Path.home() / ".config" / "desktop_pet" / "installation_state.json"
DEFAULT_MODEL = "llama3.2:1b"
REQUIRED_IMPORTS = {
    "Pillow": "PIL",
    "OpenCV": "cv2",
    "NumPy": "numpy",
    "psutil": "psutil",
}
MODEL_NAME = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}(?::[A-Za-z0-9][A-Za-z0-9._-]{0,127})?\Z"
)


def system_prerequisites():
    """Return prerequisite results without installing or elevating privileges."""
    version_ok = sys.version_info >= (3, 10)
    try:
        import venv  # noqa: F401
        venv_ok = True
    except ImportError:
        venv_ok = False
    try:
        import tkinter  # noqa: F401
        tkinter_ok = True
    except ImportError:
        tkinter_ok = False
    return {
        "Python 3.10+": version_ok,
        "módulo venv": venv_ok,
        "Tkinter": tkinter_ok,
    }


def probe_dependencies(python_executable):
    """Import each runtime dependency in the target interpreter."""
    script = (
        "import importlib, json, sys\n"
        f"modules = {REQUIRED_IMPORTS!r}\n"
        "result = {}\n"
        "for label, module in modules.items():\n"
        " try:\n"
        "  importlib.import_module(module)\n"
        "  result[label] = True\n"
        " except Exception:\n"
        "  result[label] = False\n"
        "print(json.dumps(result))\n"
    )
    try:
        result = subprocess.run(
            [str(python_executable), "-c", script],
            cwd=APP_DIR,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return {name: False for name in REQUIRED_IMPORTS}
    if result.returncode:
        return {name: False for name in REQUIRED_IMPORTS}
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {name: False for name in REQUIRED_IMPORTS}
    return {
        name: report.get(name) is True
        for name in REQUIRED_IMPORTS
    }


def ollama_status(model=DEFAULT_MODEL, *, url="http://127.0.0.1:11434/api/tags"):
    """Check only the local Ollama endpoint and requested model."""
    if not MODEL_NAME.fullmatch(model):
        return "Nome de modelo inválido."
    try:
        with urllib.request.urlopen(url, timeout=1.5) as response:
            data = json.loads(response.read(1_000_001).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return "O serviço Ollama local não está respondendo."
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return "O Ollama respondeu em formato não reconhecido."
    expected = model if ":" in model else f"{model}:latest"
    if any(isinstance(row, dict) and row.get("name") == expected for row in models):
        return f"Ollama conectado; modelo {expected} está instalado."
    return f"Ollama conectado; modelo {expected} ainda não está instalado."


def _setup_completed():
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(state, dict) and state.get("setup_completed") is True


def _launch_application():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(APP_ENTRY)])


class SetupWindow:
    def __init__(self):
        import tkinter as tk
        from tkinter import messagebox, ttk

        self.tk = tk
        self.messagebox = messagebox
        self.ttk = ttk
        self.root = tk.Tk()
        self.root.title("Preparar a Nova")
        self.root.geometry("680x720")
        self.root.minsize(520, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.results = queue.Queue()
        self.status_results = queue.Queue()
        self._status_generation = 0
        self.process = None
        self.operation = None
        self.cancel_operation = threading.Event()
        self.closing = False
        self.dependency_results = probe_dependencies(VENV_PYTHON)
        self.model = tk.StringVar(value=self._configured_model())
        self._build()
        self._refresh_status()
        self.root.after(100, self._drain_results)

    def _configured_model(self):
        if not VENV_PYTHON.is_file():
            return DEFAULT_MODEL
        code = (
            "from autonomy import load_settings\n"
            "from nova_ai.profiles import UserProfileManager\n"
            "manager = UserProfileManager()\n"
            "print(load_settings(manager.settings_path()).get('ollama_model', "
            f"{DEFAULT_MODEL!r}))\n"
        )
        try:
            result = subprocess.run(
                [str(VENV_PYTHON), "-c", code],
                cwd=APP_DIR,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
                env=self._app_environment(),
            )
        except (OSError, subprocess.SubprocessError):
            return DEFAULT_MODEL
        value = result.stdout.strip()
        return value if result.returncode == 0 and MODEL_NAME.fullmatch(value) else DEFAULT_MODEL

    def _app_environment(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(APP_DIR / "src")
        return env

    def _build(self):
        tk, ttk = self.tk, self.ttk
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Preparação do ambiente", font=("TkDefaultFont", 18, "bold")).pack(
            anchor="w",
        )
        ttk.Label(
            frame,
            text=(
                "As dependências Python serão instaladas apenas no ambiente virtual "
                ".venv desta aplicação. Nenhum comando sudo ou alteração global será executado."
            ),
            wraplength=630,
            justify="left",
        ).pack(anchor="w", pady=(6, 12))

        system = ttk.LabelFrame(frame, text="Dependências do sistema", padding=10)
        system.pack(fill="x", pady=(0, 10))
        checks = system_prerequisites()
        for name, available in checks.items():
            value = "Encontrado" if available else "Ausente"
            ttk.Label(system, text=f"{name}: {value}").pack(anchor="w")
        self.system_help = ttk.Label(
            system,
            text=(
                "Instale manualmente, com autorização do sistema, os pacotes necessários. "
                "Debian/Ubuntu: sudo apt install python3-venv python3-tk. "
                "A Nova não executa sudo."
            ),
            wraplength=600,
            justify="left",
        )
        if not all(checks.values()):
            self.system_help.pack(anchor="w", pady=(6, 0))

        dependencies = ttk.LabelFrame(
            frame, text="Dependências Python (ambiente .venv)", padding=10
        )
        dependencies.pack(fill="x", pady=(0, 10))
        self.dependency_labels = {}
        for name in REQUIRED_IMPORTS:
            label = ttk.Label(dependencies)
            label.pack(anchor="w")
            self.dependency_labels[name] = label
        self.install_button = ttk.Button(
            dependencies,
            text="Instalar/reparar dependências",
            command=self.install_dependencies,
        )
        self.install_button.pack(anchor="e", pady=(8, 0))

        ollama = ttk.LabelFrame(frame, text="Ollama opcional — IA local", padding=10)
        ollama.pack(fill="x", pady=(0, 10))
        ttk.Label(
            ollama,
            text=(
                "A mascote funciona sem Ollama. A instalação do serviço é manual: "
                "abra ollama.com/download e siga as instruções oficiais. "
                "Para iniciar um serviço instalado, use `ollama serve` se ele não estiver "
                "sendo gerenciado pelo sistema."
            ),
            wraplength=600,
            justify="left",
        ).pack(anchor="w")
        ollama_buttons = ttk.Frame(ollama)
        ollama_buttons.pack(fill="x", pady=(6, 6))
        ttk.Button(
            ollama_buttons, text="Abrir instruções oficiais",
            command=self.open_ollama_guide,
        ).pack(side="left")
        ttk.Button(
            ollama_buttons, text="Testar serviço/modelo",
            command=self.test_ollama,
        ).pack(side="left", padx=(8, 0))
        model_row = ttk.Frame(ollama)
        model_row.pack(fill="x")
        ttk.Label(model_row, text="Modelo a baixar:").pack(side="left")
        ttk.Entry(model_row, textvariable=self.model).pack(
            side="left", fill="x", expand=True, padx=8,
        )
        self.pull_button = ttk.Button(
            model_row, text="Baixar modelo…", command=self.pull_model,
        )
        self.pull_button.pack(side="right")
        self.ollama_status = tk.StringVar(value="")
        ttk.Label(
            ollama, textvariable=self.ollama_status, wraplength=600, justify="left",
        ).pack(anchor="w", pady=(6, 0))

        log_frame = ttk.LabelFrame(frame, text="Progresso e diagnóstico", padding=6)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(log_frame, height=8, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x", pady=(8, 0))
        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(10, 0))
        ttk.Button(controls, text="Sair", command=self.close).pack(side="left")
        self.launch_button = ttk.Button(
            controls, text="Abrir a Nova", command=self.launch,
        )
        self.launch_button.pack(side="right")

    def _append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _refresh_status(self):
        for name, available in self.dependency_results.items():
            status = "OK" if available else "pendente"
            self.dependency_labels[name].configure(text=f"{name}: {status}")
        ready = all(self.dependency_results.values())
        system_ready = all(system_prerequisites().values())
        self.install_button.configure(
            state="normal" if system_ready and self.operation is None else "disabled"
        )
        self.launch_button.configure(
            state="normal" if ready and self.operation is None else "disabled"
        )
        self.pull_button.configure(
            state="normal" if ready and shutil.which("ollama") and self.operation is None
            else "disabled"
        )
        self._queue_ollama_status(self.model.get().strip())

    def _queue_ollama_status(self, model):
        self._status_generation += 1
        generation = self._status_generation
        self.ollama_status.set("Verificando o serviço Ollama local…")
        threading.Thread(
            target=self._check_ollama_status,
            args=(model, generation),
            daemon=True,
            name="nova-setup-ollama-check",
        ).start()

    def _check_ollama_status(self, model, generation):
        self.status_results.put((generation, ollama_status(model)))

    def install_dependencies(self):
        if not all(system_prerequisites().values()):
            self.messagebox.showerror(
                "Dependências do sistema",
                "Instale manualmente os componentes do sistema indicados acima e tente novamente. "
                "A Nova não solicita nem usa privilégios administrativos.",
                parent=self.root,
            )
            return
        if not self.messagebox.askyesno(
            "Confirmar instalação",
            "Criar ou atualizar o ambiente virtual local .venv e instalar requirements.txt? "
            "A instalação não modifica o Python global nem usa sudo.",
            parent=self.root,
        ):
            return
        if VENV_DIR.is_symlink():
            self.messagebox.showerror(
                "Ambiente inseguro",
                "O caminho .venv é um link simbólico. Nada foi alterado; verifique-o manualmente.",
                parent=self.root,
            )
            return
        self._start_process(
            "install",
            [str(INSTALLER), "--yes"],
            "Instalando dependências no ambiente virtual…",
        )

    def open_ollama_guide(self):
        import webbrowser

        try:
            if not webbrowser.open("https://ollama.com/download"):
                self._append_log("Não consegui abrir o navegador. Acesse https://ollama.com/download.")
        except OSError as exc:
            self._append_log(f"Não consegui abrir o navegador: {exc}")

    def test_ollama(self):
        model = self.model.get().strip()
        if not MODEL_NAME.fullmatch(model):
            self.ollama_status.set("Informe um nome de modelo válido.")
            return
        self._queue_ollama_status(model)

    def pull_model(self):
        model = self.model.get().strip()
        if not MODEL_NAME.fullmatch(model):
            self.ollama_status.set("Informe um nome de modelo válido.")
            return
        if not shutil.which("ollama"):
            self.ollama_status.set(
                "O comando ollama não foi encontrado. Instale o Ollama pelas instruções oficiais."
            )
            return
        confirmation = self.messagebox.askyesno(
            "Confirmar download do modelo",
            f"Baixar o modelo {model} do Ollama?\n\n"
            "O download requer internet e pode consumir dados e espaço em disco. "
            "Nenhum download começa sem esta confirmação.",
            parent=self.root,
        )
        if not confirmation:
            return
        self._start_process(
            "pull",
            ["ollama", "pull", model],
            f"Baixando {model}…",
        )

    def _start_process(self, operation, command, status):
        self.operation = operation
        self.cancel_operation = threading.Event()
        cancel_event = self.cancel_operation
        self._refresh_status()
        self.progress.start(12)
        self._append_log(status)
        self.results = queue.Queue()

        def run():
            try:
                self.process = subprocess.Popen(
                    command,
                    cwd=APP_DIR,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=self._app_environment(),
                )
                if operation == "pull" and cancel_event.is_set():
                    self.process.terminate()
                for line in self.process.stdout:
                    self.results.put(("line", line))
                return_code = self.process.wait()
                self.results.put(("finished", return_code))
            except OSError as exc:
                self.results.put(("error", str(exc)))

        threading.Thread(target=run, daemon=True, name=f"nova-setup-{operation}").start()

    def _drain_results(self):
        if self.closing:
            return
        while True:
            try:
                generation, status = self.status_results.get_nowait()
            except queue.Empty:
                break
            if generation == self._status_generation:
                self.ollama_status.set(status)
        while True:
            try:
                kind, value = self.results.get_nowait()
            except queue.Empty:
                break
            if kind == "line":
                self._append_log(value)
            elif kind == "error":
                self._finish_operation(False, value)
            elif kind == "finished":
                self._finish_operation(value == 0, f"Processo encerrado com código {value}.")
        self.root.after(100, self._drain_results)

    def _finish_operation(self, succeeded, message):
        operation = self.operation
        self.operation = None
        self.progress.stop()
        self._append_log(message)
        if operation == "install" and succeeded:
            self.dependency_results = probe_dependencies(VENV_PYTHON)
            if not all(self.dependency_results.values()):
                succeeded = False
                message = (
                    "A instalação terminou, mas uma ou mais dependências não puderam ser "
                    "importadas. Consulte o progresso e tente novamente."
                )
            elif not self._import_probe():
                succeeded = False
                message = (
                    "As bibliotecas foram instaladas, mas a importação da aplicação falhou. "
                    "Consulte o diagnóstico antes de tentar novamente."
                )
        elif operation == "pull" and succeeded:
            model = self.model.get().strip()
            if not self._save_model_preference(model):
                succeeded = False
                message = (
                    "O modelo foi baixado, mas não consegui salvar a preferência. "
                    "Selecione-o manualmente em Preferências > Inteligência artificial."
                )
        self._refresh_status()
        if not succeeded:
            self._append_log(message)
            self.ollama_status.set(message if operation == "pull" else self.ollama_status.get())

    def _import_probe(self):
        env = self._app_environment()
        try:
            result = subprocess.run(
                [
                    str(VENV_PYTHON), "-c",
                    "import desktop_pet, nova_ai.desktop_integration, "
                    "nova_ai.personality, providers.ollama_provider",
                ],
                cwd=APP_DIR,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._append_log(f"Verificação final falhou: {exc}")
            return False
        if result.returncode:
            self._append_log(result.stderr or "A aplicação não passou na verificação de importação.")
            return False
        self._append_log("Verificação final de importação: OK.")
        return True

    def _save_model_preference(self, model):
        code = (
            "import sys\n"
            "from autonomy import load_settings, save_settings\n"
            "from nova_ai.profiles import UserProfileManager\n"
            "manager = UserProfileManager()\n"
            "path = manager.settings_path()\n"
            "settings = load_settings(path)\n"
            "settings['ollama_model'] = sys.argv[1]\n"
            "raise SystemExit(0 if save_settings(settings, path) else 1)\n"
        )
        try:
            result = subprocess.run(
                [str(VENV_PYTHON), "-c", code, model],
                cwd=APP_DIR,
                env=self._app_environment(),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0

    def launch(self):
        if not all(self.dependency_results.values()):
            return
        if not self._import_probe():
            self.messagebox.showerror(
                "Verificação da aplicação",
                "A verificação final falhou. Corrija o problema antes de iniciar a Nova.",
                parent=self.root,
            )
            return
        try:
            subprocess.Popen(
                [str(VENV_PYTHON), str(APP_ENTRY)],
                cwd=APP_DIR,
                env=self._app_environment(),
            )
        except OSError as exc:
            self.messagebox.showerror(
                "Não foi possível iniciar",
                f"A Nova não foi iniciada: {exc}",
                parent=self.root,
            )
            return
        self.root.destroy()

    def close(self):
        if self.operation == "install":
            self.messagebox.showinfo(
                "Instalação em andamento",
                "Aguarde a instalação terminar antes de fechar esta janela.",
                parent=self.root,
            )
            return
        if self.operation == "pull" and not self.messagebox.askyesno(
            "Download em andamento",
            "Interromper o download do modelo e fechar a janela?",
            parent=self.root,
        ):
            return
        self.closing = True
        if self.operation == "pull":
            self.cancel_operation.set()
        process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    if VENV_DIR.is_symlink():
        print(
            f"O ambiente {VENV_DIR} é um link simbólico; verifique-o antes de iniciar.",
            file=sys.stderr,
        )
        return 1
    checks = system_prerequisites()
    if not checks["Python 3.10+"]:
        print("Python 3.10 ou superior é necessário.", file=sys.stderr)
        return 1
    if not checks["Tkinter"]:
        print(
            "A tela de preparação requer Tkinter. Instale-o manualmente "
            "(Debian/Ubuntu: sudo apt install python3-tk); nenhum sudo será executado.",
            file=sys.stderr,
        )
        return 1
    dependencies = probe_dependencies(VENV_PYTHON)
    if all(dependencies.values()) and _setup_completed():
        os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(APP_ENTRY)])
    SetupWindow().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
