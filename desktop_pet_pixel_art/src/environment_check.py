"""Read-only checks for the local runtime, Ollama, and character assets."""

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import urllib.error
from urllib.parse import urlsplit
import urllib.request

from config import MOVEMENT_VIDEOS, OLLAMA_MODEL, OLLAMA_URL, resolve_movement_path
from nova_ai.memory.memory_storage import APPLICATION_ID, SCHEMA_VERSION


_REQUIRED_MODULES = {
    "Pillow": "PIL",
    "OpenCV": "cv2",
    "NumPy": "numpy",
    "psutil": "psutil",
}
_PROFILE_ID = re.compile(r"[a-f0-9]{32}\Z")
_PROFILE_REGISTRY_VERSION = 1
_MAX_PROFILES = 50


@dataclass(frozen=True)
class EnvironmentReport:
    python_version: str
    python_supported: bool
    dependencies: dict
    ollama_status: str
    selected_model: str
    database_status: str
    personality_status: str
    graphics_status: str
    graphics_available: int
    graphics_total: int
    free_disk_bytes: int | None
    memory_total_bytes: int | None
    cpu_count: int | None

    @property
    def can_continue(self):
        return self.python_supported and all(self.dependencies.values())

    def to_installation_state(self):
        return {
            "dependencies_verified": dict(self.dependencies),
            "ollama_status": self.ollama_status,
            "selected_model": self.selected_model,
            "database_status": self.database_status,
            "personality_status": self.personality_status,
            "graphics_status": self.graphics_status,
        }


def check_environment(*, home=None, model=OLLAMA_MODEL, url=OLLAMA_URL):
    """Inspect local installation state; never install, start, or download anything."""
    home = Path(home) if home is not None else Path.home()
    python = sys.version_info
    version = f"{python.major}.{python.minor}.{python.micro}"
    dependencies = {
        label: _module_available(module)
        for label, module in _REQUIRED_MODULES.items()
    }
    ollama_status = _check_ollama(model, url)
    graphics_available = sum(
        resolve_movement_path(filename).is_file()
        for filename in MOVEMENT_VIDEOS.values()
    )
    graphics_status = (
        "ready" if graphics_available == len(MOVEMENT_VIDEOS)
        else "partial" if graphics_available
        else "missing"
    )
    database_status = _check_existing_database(home)
    personality_status = (
        "available"
        if _module_available("nova_ai.personality.personality_engine")
        else "missing"
    )
    try:
        free_disk_bytes = shutil.disk_usage(home).free
    except OSError:
        free_disk_bytes = None
    memory_total_bytes = _physical_memory_bytes()

    return EnvironmentReport(
        python_version=version,
        python_supported=(python.major, python.minor) >= (3, 10),
        dependencies=dependencies,
        ollama_status=ollama_status,
        selected_model=model,
        database_status=database_status,
        personality_status=personality_status,
        graphics_status=graphics_status,
        graphics_available=graphics_available,
        graphics_total=len(MOVEMENT_VIDEOS),
        free_disk_bytes=free_disk_bytes,
        memory_total_bytes=memory_total_bytes,
        cpu_count=os.cpu_count(),
    )


def _module_available(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _check_ollama(model, url):
    executable_found = shutil.which("ollama") is not None
    endpoint = urlsplit(url)
    if endpoint.hostname not in ("localhost", "127.0.0.1", "::1"):
        return "unavailable"
    tags_url = url.rsplit("/api/", 1)[0] + "/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=1.5) as response:
            payload = response.read(1_000_001)
        if len(payload) > 1_000_000:
            return "unavailable"
        data = json.loads(payload.decode("utf-8"))
    except (
        urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError,
    ):
        return "installed_not_running" if executable_found else "not_installed"

    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return "unavailable"
    wanted = model if ":" in model else f"{model}:latest"
    if any(isinstance(item, dict) and item.get("name") == wanted for item in models):
        return "ready"
    return "model_missing"


def _check_existing_database(home):
    base_dir = home / ".config" / "desktop_pet"
    if base_dir.is_symlink():
        return "unsafe"
    if not base_dir.exists():
        return "not_created"
    registry = base_dir / "user_profiles.json"
    if registry.is_symlink():
        return "unsafe"
    if not registry.exists():
        profile_id = "legacy"
    else:
        try:
            data = json.loads(registry.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            return "unavailable"
        except json.JSONDecodeError:
            return "profile_registry_invalid"
        if not isinstance(data, dict) or data.get("version") != _PROFILE_REGISTRY_VERSION:
            return "profile_registry_invalid"
        rows = data.get("profiles")
        active_id = data.get("active_profile_id")
        if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_PROFILES:
            return "profile_registry_invalid"
        profile_ids = set()
        has_legacy = False
        for row in rows:
            if not isinstance(row, dict):
                return "profile_registry_invalid"
            row_id = row.get("profile_id")
            name = row.get("name")
            if (
                not isinstance(row_id, str)
                or (row_id != "legacy" and not _PROFILE_ID.fullmatch(row_id))
                or row_id in profile_ids
                or not isinstance(name, str)
                or not name.strip()
                or len(name) > 60
            ):
                return "profile_registry_invalid"
            profile_ids.add(row_id)
            has_legacy |= row_id == "legacy"
        if not has_legacy or not isinstance(active_id, str) or active_id not in profile_ids:
            return "profile_registry_invalid"
        profile_id = active_id

    if profile_id == "legacy":
        database = base_dir / "nova_memory.sqlite3"
    else:
        profiles_dir = base_dir / "profiles"
        if profiles_dir.is_symlink():
            return "unsafe"
        profile_dir = profiles_dir / profile_id
        if profile_dir.is_symlink():
            return "unsafe"
        database = profile_dir / "nova_memory.sqlite3"
    if database.is_symlink():
        return "unsafe"
    if not database.exists():
        return "not_created"
    if database.parent.is_symlink():
        return "unsafe"
    try:
        uri = f"{database.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=1.0) as connection:
            integrity = connection.execute("PRAGMA quick_check").fetchone()
            application_id = connection.execute("PRAGMA application_id").fetchone()[0]
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if integrity is None or integrity[0] != "ok":
                return "corrupt"
            if application_id != APPLICATION_ID or schema_version not in (
                0, 1, SCHEMA_VERSION,
            ):
                return "unrecognized"
            return "ready"
    except (OSError, sqlite3.DatabaseError, ValueError):
        return "unavailable"


def format_disk_space(free_bytes):
    if free_bytes is None:
        return "não foi possível verificar"
    gib = free_bytes / (1024 ** 3)
    return f"{gib:.1f} GiB livres"


def _physical_memory_bytes():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None


def format_memory(memory_bytes):
    if memory_bytes is None:
        return "não foi possível verificar"
    gib = memory_bytes / (1024 ** 3)
    return f"{gib:.1f} GiB RAM"
