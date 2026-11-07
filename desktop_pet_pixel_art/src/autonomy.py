"""Persistência e regras simples de autonomia da Nova."""

import configparser
import fcntl
import json
import logging
import os
import shlex
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from json_persistence import (
    block_replacement,
    mark_valid,
    may_replace,
    preserve_corrupt_file,
)

logger = logging.getLogger(__name__)

SETTINGS_PATH = Path.home() / ".config" / "desktop_pet" / "settings.json"
LEGACY_REMOTE_AI_SETTINGS = (
    "online_ai_enabled",
    "allow_online_data",
    "confirm_free_tier",
    "gemini_model",
    "groq_model",
    "mistral_model",
)
DEFAULT_SETTINGS = {
    "mode": "companhia",
    "humor_style": "equilibrada",
    "announce_charger": True,
    "announce_usb": True,
    "spotify_client_id": "",
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
    "project_followup_days": 7,
    "adaptive_learning_enabled": False,
    "adaptive_learning_state": {
        "version": 1,
        "evidence": {
            "verbosity": {"concise": 0, "detailed": 0},
            "tone": {"formal": 0, "casual": 0},
            "humor": {"playful": 0, "restrained": 0},
            "support": {"encouraging": 0, "restrained": 0},
        },
        "last_observed": {},
    },
    "proactive_project_followups": {},
    "routine_idle_yawn": True,
    "routine_focus_celebration": True,
    "routine_note": True,
    "routine_surprise": True,
    "last_surprise_date": "",
    "last_note_at": 0,
    "routine_evening": True,
    "evening_time": "20:30",
    "last_evening_date": "",
    "routine_dance": True,
    "routine_break_tip": True,
    "last_seen_date": "",
    "interaction_count": 0,
    "ai_provider": "ollama",
    "ai_timeout": 30,
    "ollama_model": "llama3.2:1b",
    "ollama_num_ctx": 1024,
    "ollama_num_predict": 96,
    "ollama_num_threads": 1,
    "automations": {"enabled": {"laptop_status": True, "organize_downloads": True, "undo_downloads": True, "large_files": True, "duplicates": True, "trash_duplicates": True, "disk_summary": True, "empty_trash": True, "organize_screenshots": True, "pause_reminder": True, "low_battery_alert": True}, "last_run": {}, "activity": []},
}


def load_settings(path=SETTINGS_PATH):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        mark_valid(path)
        data = {}
    except OSError as exc:
        block_replacement(path, type(exc).__name__)
        data = {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        preserve_corrupt_file(path, type(exc).__name__)
        data = {}
    else:
        if not isinstance(data, dict):
            preserve_corrupt_file(path, "raiz JSON não é um objeto")
            data = {}
        else:
            mark_valid(path)
    result = dict(DEFAULT_SETTINGS)
    if isinstance(data, dict):
        result.update(data)
    automation_data = data.get("automations", {}) if isinstance(data, dict) else {}
    defaults_automations = DEFAULT_SETTINGS["automations"]
    if not isinstance(automation_data, dict):
        automation_data = {}
    enabled = automation_data.get("enabled", {})
    last_run = automation_data.get("last_run", {})
    activity = automation_data.get("activity", [])
    if not isinstance(enabled, dict):
        enabled = {}
    if not isinstance(last_run, dict):
        last_run = {}
    if not isinstance(activity, list):
        activity = []
    result["automations"] = {
        "enabled": {key: enabled.get(key, value) if isinstance(enabled.get(key, value), bool) else value for key, value in defaults_automations["enabled"].items()},
        "last_run": {key: value for key, value in last_run.items() if key in defaults_automations["enabled"] and isinstance(value, str)},
        "activity": [item for item in activity if isinstance(item, dict) and item.get("id") in defaults_automations["enabled"] and isinstance(item.get("summary"), str) and isinstance(item.get("timestamp"), str)][:10],
    }
    if not isinstance(result.get("user_name"), str):
        result["user_name"] = ""
    result["user_name"] = result["user_name"].strip()[:60]
    if not isinstance(result.get("adaptive_learning_enabled"), bool):
        result["adaptive_learning_enabled"] = False
    from nova_ai.personality.preference_learner import PreferenceLearner
    result["adaptive_learning_state"] = PreferenceLearner.normalize_state(
        result.get("adaptive_learning_state")
    )
    followups = result.get("proactive_project_followups")
    if not isinstance(followups, dict):
        followups = {}
    result["proactive_project_followups"] = {
        memory_id: observed_at
        for memory_id, observed_at in list(followups.items())[:100]
        if isinstance(memory_id, str)
        and len(memory_id) == 32
        and all(character in "0123456789abcdef" for character in memory_id)
        and isinstance(observed_at, str)
        and _valid_iso_timestamp(observed_at)
    }
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
    if result.get("humor_style") not in ("tranquila", "equilibrada", "brincalhona"):
        result["humor_style"] = "equilibrada"
    for key in ("announce_charger", "announce_usb"):
        if not isinstance(result.get(key), bool):
            result[key] = True
    try:
        followup_days = result.get("project_followup_days", 7)
        if isinstance(followup_days, bool):
            raise ValueError
        result["project_followup_days"] = min(30, max(1, int(followup_days)))
    except (TypeError, ValueError):
        result["project_followup_days"] = 7
    if not isinstance(result.get("spotify_client_id"), str):
        result["spotify_client_id"] = ""
    result["spotify_client_id"] = result["spotify_client_id"].strip()[:128]
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
        "routine_evening", "routine_dance", "routine_break_tip",
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
    if not isinstance(result.get("last_seen_date"), str):
        result["last_seen_date"] = ""
    else:
        try:
            datetime.strptime(result["last_seen_date"], "%Y-%m-%d")
        except ValueError:
            result["last_seen_date"] = ""
    try:
        interaction_count = result.get("interaction_count", 0)
        if isinstance(interaction_count, bool):
            raise ValueError("interaction_count não pode ser booleano")
        result["interaction_count"] = min(
            2_147_483_647, max(0, int(interaction_count))
        )
    except (TypeError, ValueError):
        result["interaction_count"] = 0
    result["ai_provider"] = "ollama"
    for key in LEGACY_REMOTE_AI_SETTINGS:
        result.pop(key, None)
    try:
        result["ai_timeout"] = min(30, max(5, int(result.get("ai_timeout", 30))))
    except (TypeError, ValueError):
        result["ai_timeout"] = 30
    for key, default, minimum, maximum in (
        ("ollama_num_ctx", 1024, 512, 2048),
        ("ollama_num_predict", 96, 16, 256),
        ("ollama_num_threads", 1, 1, 2),
    ):
        try:
            value = result.get(key, default)
            if isinstance(value, bool):
                raise ValueError
            result[key] = min(maximum, max(minimum, int(value)))
        except (TypeError, ValueError):
            result[key] = default
    for key, default in (("ollama_model", "llama3.2:1b"),):
        value = result.get(key)
        result[key] = value.strip()[:100] if isinstance(value, str) and value.strip() else default
    return result


def _valid_iso_timestamp(value):
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def save_settings(settings, path=SETTINGS_PATH):
    path = Path(path) if path is not None else SETTINGS_PATH
    if not may_replace(path):
        logger.error("Gravação das configurações bloqueada para preservar %s", path.name)
        return False
    temporary_path = None
    lock_fd = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = path.with_name(f".{path.name}.lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        payload = dict(settings)
        payload["ai_provider"] = "ollama"
        for key in LEGACY_REMOTE_AI_SETTINGS:
            payload.pop(key, None)
        user_name = payload.get("user_name")
        if not isinstance(user_name, str) or not user_name.strip():
            try:
                saved_settings = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                saved_settings = {}
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                if isinstance(exc, (UnicodeDecodeError, json.JSONDecodeError)):
                    backup = preserve_corrupt_file(path, type(exc).__name__)
                    if backup is not None:
                        saved_settings = {}
                    else:
                        logger.error(
                            "Não foi possível preservar as configurações atuais (%s); gravação cancelada",
                            type(exc).__name__,
                        )
                        return False
                else:
                    logger.error(
                        "Não foi possível preservar as configurações atuais (%s); gravação cancelada",
                        type(exc).__name__,
                    )
                    return False
            if isinstance(saved_settings, dict):
                saved_name = saved_settings.get("user_name")
                if isinstance(saved_name, str) and saved_name.strip():
                    payload["user_name"] = saved_name

        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = stream.name
            json.dump(payload, stream, ensure_ascii=False, indent=2)
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
    finally:
        if lock_fd is not None:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


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
        directories = [
            data_home / "applications",
            *(Path(item) / "applications" for item in data_dirs if item),
            Path.home() / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"),
            Path("/var/lib/snapd/desktop/applications"),
        ]

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
