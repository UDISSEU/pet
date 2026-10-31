"""Persistência e regras simples de autonomia da Nova."""

import configparser
import json
import os
import shlex
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

SETTINGS_PATH = Path.home() / ".config" / "desktop_pet" / "settings.json"
DEFAULT_SETTINGS = {
    "mode": "companhia",
    "user_name": "",
    "quiet_start": "22:00",
    "quiet_end": "08:00",
    "memories": [],
    "reminders": [],
    "apps": [],
    "confirm_app_launch": True,
    "focus_minutes": 25,
    "break_minutes": 5,
    "routine_greeting": True,
    "routine_context": True,
    "last_context_date": "",
    "routine_idle_yawn": True,
    "routine_focus_celebration": True,
    "routine_note": True,
    "routine_surprise": True,
    "last_surprise_date": "",
    "last_note_at": 0,
    "routine_evening": True,
    "evening_time": "20:30",
    "last_evening_date": "",
    "ai_provider": "ollama",
    "online_ai_enabled": False,
    "allow_online_data": False,
    "confirm_free_tier": False,
    "ai_timeout": 30,
    "ollama_model": "llama3.2:1b",
    "gemini_model": "gemini-3.8-flash",
    "groq_model": "openai/gpt-oss-20b",
    "mistral_model": "mistral-small-latest",
}


def load_settings(path=SETTINGS_PATH):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    result = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        result.update(data)
    if not isinstance(result.get("user_name"), str):
        result["user_name"] = ""
    result["user_name"] = result["user_name"].strip()[:60]
    if not isinstance(result.get("memories"), list):
        result["memories"] = []
    memories = []
    seen_memories = set()
    for item in result["memories"]:
        if not isinstance(item, str) or not item.strip():
            continue
        memory = item.strip()
        normalized = memory.casefold()
        if normalized in seen_memories:
            continue
        seen_memories.add(normalized)
        memories.append(memory)
    result["memories"] = memories
    if not isinstance(result.get("reminders"), list):
        result["reminders"] = []
    result["reminders"] = [
        {"at": item["at"], "text": item["text"], "done": bool(item.get("done", False))}
        for item in result["reminders"]
        if isinstance(item, dict)
        and isinstance(item.get("at"), str)
        and valid_reminder_time(item["at"]) is not None
        and isinstance(item.get("text"), str)
        and item["text"].strip()
    ]
    if not isinstance(result.get("apps"), list):
        result["apps"] = []
    cleaned_apps = []
    for item in result["apps"]:
        if not (
            isinstance(item, dict)
            and isinstance(item.get("name"), str) and item["name"].strip()
            and isinstance(item.get("command"), str) and item["command"].strip()
        ):
            continue
        app = {"name": item["name"].strip(), "command": item["command"].strip()}
        desktop_file = item.get("desktop_file")
        if isinstance(desktop_file, str) and desktop_file.strip():
            app["desktop_file"] = desktop_file.strip()
        cleaned_apps.append(app)
    result["apps"] = cleaned_apps
    if result.get("mode") not in ("quietinha", "companhia", "proativa"):
        result["mode"] = "companhia"
    for key, default, minimum, maximum in (
        ("focus_minutes", 25, 5, 180),
        ("break_minutes", 5, 1, 60),
    ):
        try:
            value = int(result.get(key, default))
        except (TypeError, ValueError):
            value = default
        result[key] = min(maximum, max(minimum, value))
    for key in (
        "routine_greeting", "routine_context", "routine_idle_yawn",
        "routine_focus_celebration", "routine_note", "routine_surprise",
        "routine_evening",
    ):
        if not isinstance(result.get(key), bool):
            result[key] = False
    if not isinstance(result.get("last_surprise_date"), str):
        result["last_surprise_date"] = ""
    if not isinstance(result.get("last_context_date"), str):
        result["last_context_date"] = ""
    try:
        result["last_note_at"] = max(0, int(result.get("last_note_at", 0)))
    except (TypeError, ValueError):
        result["last_note_at"] = 0
    if not isinstance(result.get("confirm_app_launch"), bool):
        result["confirm_app_launch"] = True
    try:
        datetime.strptime(result.get("evening_time", "20:30"), "%H:%M")
    except (TypeError, ValueError):
        result["evening_time"] = "20:30"
    if not isinstance(result.get("last_evening_date"), str):
        result["last_evening_date"] = ""
    if result.get("ai_provider") not in ("ollama", "gemini", "groq", "mistral"):
        result["ai_provider"] = "ollama"
    for key in ("online_ai_enabled", "allow_online_data", "confirm_free_tier"):
        if not isinstance(result.get(key), bool):
            result[key] = False
    try:
        result["ai_timeout"] = min(30, max(5, int(result.get("ai_timeout", 30))))
    except (TypeError, ValueError):
        result["ai_timeout"] = 30
    for key, default in (
        ("ollama_model", "llama3.2:1b"),
        ("gemini_model", "gemini-3.8-flash"),
        ("groq_model", "openai/gpt-oss-20b"),
        ("mistral_model", "mistral-small-latest"),
    ):
        value = result.get(key)
        result[key] = value.strip()[:100] if isinstance(value, str) and value.strip() else default
    return result


def save_settings(settings, path=SETTINGS_PATH):
    temporary_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = stream.name
            json.dump(settings, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        return True
    except (OSError, TypeError, ValueError):
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        return False


def is_quiet_now(start, end, now=None):
    """Intervalo local [início, fim), inclusive quando cruza meia-noite."""
    try:
        start_time = datetime.strptime(start, "%H:%M").time()
        end_time = datetime.strptime(end, "%H:%M").time()
    except (TypeError, ValueError):
        return False
    if start_time == end_time:
        return False
    now_time = (now or datetime.now().astimezone()).time().replace(tzinfo=None)
    if start_time < end_time:
        return start_time <= now_time < end_time
    return now_time >= start_time or now_time < end_time


def valid_reminder_time(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def resolve_app_command(command):
    """Divide um comando sem shell e verifica se o executável está disponível."""
    try:
        argv = shlex.split(command)
    except (TypeError, ValueError) as exc:
        raise ValueError("Não consegui interpretar o comando. Confira as aspas.") from exc
    if not argv:
        raise ValueError("Informe o comando executável.")
    if any("\x00" in argument for argument in argv):
        raise ValueError("O comando contém um caractere inválido.")
    executable = os.path.expanduser(argv[0])
    if os.path.dirname(executable):
        available = os.path.isfile(executable) and os.access(executable, os.X_OK)
    else:
        available = shutil.which(executable) is not None
    if not available:
        raise ValueError(f"Não encontrei o executável '{argv[0]}'. Confira o nome ou caminho.")
    argv[0] = executable
    return argv


def find_installed_apps(search="", directories=None):
    """Return searchable Linux desktop apps from XDG application folders."""
    if directories is None:
        data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(os.pathsep)
        directories = [data_home / "applications", *(Path(item) / "applications" for item in data_dirs if item)]

    needle = search.casefold().strip()
    results = []
    seen_ids = set()
    for directory in directories:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for desktop_file in sorted(directory.rglob("*.desktop")):
            app_id = desktop_file.relative_to(directory).as_posix().replace("/", "-")
            if app_id in seen_ids:
                continue
            seen_ids.add(app_id)
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(desktop_file, encoding="utf-8")
                entry = parser["Desktop Entry"]
            except (OSError, UnicodeDecodeError, KeyError, configparser.Error):
                continue
            if entry.get("Type", "Application") != "Application":
                continue
            try:
                is_hidden = entry.getboolean("Hidden", fallback=False)
                is_internal = entry.getboolean("NoDisplay", fallback=False)
            except ValueError:
                continue
            if is_hidden or is_internal:
                continue
            name = entry.get("Name", "").strip()
            exec_value = entry.get("Exec", "").strip()
            if not name or not exec_value:
                continue
            try:
                argv = _desktop_exec_argv(exec_value, name, desktop_file)
                resolve_app_command(shlex.join(argv))
            except ValueError:
                continue
            generic_name = entry.get("GenericName", "").strip()
            searchable = f"{name} {generic_name}".casefold()
            if needle and needle not in searchable:
                continue
            results.append({
                "name": name,
                "command": shlex.join(argv),
                "generic_name": generic_name,
                "desktop_file": str(desktop_file),
            })
    return sorted(results, key=lambda item: item["name"].casefold())


def _desktop_exec_argv(exec_value, app_name, desktop_file):
    argv = shlex.split(exec_value)
    expanded = []
    for argument in argv:
        if argument == "%i":
            continue
        if argument in ("%f", "%F", "%u", "%U"):
            continue
        argument = argument.replace("%%", "\0")
        argument = argument.replace("%c", app_name).replace("%k", str(desktop_file))
        for code in ("%f", "%F", "%u", "%U", "%i"):
            argument = argument.replace(code, "")
        argument = argument.replace("\0", "%")
        if argument:
            expanded.append(argument)
    if not expanded:
        raise ValueError("empty desktop command")
    return expanded
