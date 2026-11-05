"""Catálogo local de aplicativos e abertura restrita a launchers instalados."""

from pathlib import Path
import re
import subprocess
import time

from .base import Tool
from .results import ActionResult


_APP_DIRS = (Path("/usr/share/applications"),
             Path.home() / ".local/share/applications")
_APP_ID = re.compile(r"^[A-Za-z0-9_.-]{1,160}\.desktop$")
_GIO = Path("/usr/bin/gio")


def _launchable(path):
    try:
        if path.stat().st_size > 128_000:
            return False
        contents = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    if "[Desktop Entry]" not in contents:
        return False
    fields, in_entry = {}, False
    for line in contents.splitlines():
        if line.startswith("["):
            in_entry = line == "[Desktop Entry]"
        elif in_entry and "=" in line and not line.startswith(("#", " ", "\t")):
            key, value = line.split("=", 1)
            fields[key] = value
    return (fields.get("Type") == "Application"
            and fields.get("Hidden", "false").casefold() != "true"
            and fields.get("NoDisplay", "false").casefold() != "true")


def _desktop_file(app_id):
    if not isinstance(app_id, str) or not _APP_ID.fullmatch(app_id):
        raise ValueError("Identificador de aplicativo inválido")
    for directory in _APP_DIRS:
        candidate = directory / app_id
        if candidate.is_file() and not candidate.is_symlink() and _launchable(candidate):
            return candidate.resolve()
    raise FileNotFoundError("Aplicativo não encontrado no catálogo instalado")


class AppCatalogTool(Tool):
    name = "apps.list"
    description = "Lista aplicativos instalados disponíveis para abertura."

    def execute(self, arguments):
        if arguments:
            raise ValueError("O catálogo não aceita argumentos")
        rows = []
        for directory in _APP_DIRS:
            if not directory.is_dir():
                continue
            for item in directory.glob("*.desktop"):
                if item.is_file() and not item.is_symlink() and _launchable(item):
                    rows.append(item.name)
                    if len(rows) >= 300:
                        return ActionResult(True, f"{len(rows)} aplicativos encontrados.",
                                            {"apps": sorted(set(rows))})
        rows = sorted(set(rows))
        return ActionResult(True, f"{len(rows)} aplicativos encontrados.", {"apps": rows})


class AppLauncherTool(Tool):
    name = "apps.launch"
    description = "Solicita a abertura de um launcher .desktop conhecido."

    def execute(self, arguments):
        from .base import CancellationToken, ToolContext
        return self.execute_with_context(
            arguments, ToolContext(CancellationToken(), time.monotonic() + 10.0)
        )

    def execute_with_context(self, arguments, context):
        if not isinstance(arguments, dict) or set(arguments) != {"app_id"}:
            raise ValueError("Informe somente o app_id do catálogo")
        context.checkpoint()
        desktop_file = _desktop_file(arguments["app_id"])
        gio = _GIO
        if not gio.is_file():
            return ActionResult(False, "O lançador gráfico gio não está disponível.")
        process = subprocess.Popen(
            [str(gio), "launch", str(desktop_file)], shell=False,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            while process.poll() is None:
                try:
                    context.checkpoint()
                except Exception:
                    process.terminate()
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=0.5)
                    raise
                time.sleep(0.05)
        finally:
            if process.poll() is None:
                process.kill()
        if process.returncode:
            return ActionResult(False, "O aplicativo recusou a solicitação de abertura.")
        return ActionResult(True, "Solicitação de abertura enviada.",
                            {"app_id": arguments["app_id"]})


