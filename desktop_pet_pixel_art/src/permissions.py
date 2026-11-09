"""Persistent, deny-by-default plugin permissions."""
import json
import os
from pathlib import Path
import tempfile
import threading

from json_persistence import block_replacement, mark_valid, may_replace, preserve_corrupt_file

DEFAULT_PERMISSION_PATH = Path.home() / ".config" / "desktop_pet" / "permissions.json"
KNOWN_PERMISSIONS = {
    "file.read", "file.write", "file.move", "file.delete", "file.organize",
    "system.clock.read", "system.cpu.read", "system.memory.read", "system.disk.read",
    "system.process.read", "system.app.read", "system.app.launch", "system.maintenance.read",
    "system.maintenance", "spotify.control", "ai.use", "network.access",
    "notification.create", "pet.animation.control", "task.create",
    "reminder.read", "reminder.write",
}
SENSITIVE = {
    "file.write", "file.move", "file.delete", "file.organize",
    "system.app.launch", "system.maintenance", "spotify.control", "network.access",
    "reminder.write",
}


def _validated_data(data):
    if not isinstance(data, dict) or set(data) - {"grants", "history"}:
        raise ValueError("raiz de permissões inválida")

    grants = data.get("grants", {})
    history = data.get("history", [])
    if not isinstance(grants, dict) or not isinstance(history, list):
        raise ValueError("estrutura de permissões inválida")

    for plugin_id, permissions in grants.items():
        if not isinstance(plugin_id, str) or not plugin_id.strip() or len(plugin_id) > 64:
            raise ValueError("identificador de plugin inválido")
        if not isinstance(permissions, dict):
            raise ValueError("concessões de plugin inválidas")
        for permission, granted in permissions.items():
            if permission not in KNOWN_PERMISSIONS or type(granted) is not bool:
                raise ValueError("concessão desconhecida ou inválida")

    for item in history:
        if (not isinstance(item, dict)
                or set(item) != {"plugin", "permission", "granted"}
                or not isinstance(item["plugin"], str)
                or not item["plugin"].strip()
                or len(item["plugin"]) > 64
                or not isinstance(item["permission"], str)
                or item["permission"] not in KNOWN_PERMISSIONS
                or type(item["granted"]) is not bool):
            raise ValueError("entrada de histórico inválida")

    return grants, history


class PermissionManager:
    def __init__(self, path=DEFAULT_PERMISSION_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._grants = {}
        self._history = []
        self._ensure_safe_path()
        self._load()

    def _ensure_safe_path(self):
        if self.path.is_symlink():
            raise OSError("O arquivo de permissões não pode ser um link simbólico")
        if self.path.parent.exists() and self.path.parent.is_symlink():
            raise OSError("O diretório de permissões não pode ser um link simbólico")

    def _load(self):
        try:
            contents = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            mark_valid(self.path)
            return
        except OSError as exc:
            block_replacement(self.path, type(exc).__name__)
            return
        except UnicodeDecodeError as exc:
            preserve_corrupt_file(self.path, type(exc).__name__)
            return

        try:
            data = json.loads(contents)
            grants, history = _validated_data(data)
        except (json.JSONDecodeError, ValueError) as exc:
            preserve_corrupt_file(self.path, type(exc).__name__)
            return

        mark_valid(self.path)
        self._grants = grants
        self._history = history

    def allowed(self, plugin_id, permission):
        with self._lock:
            plugin = self._grants.get(str(plugin_id), {})
            return bool(plugin.get(permission, False)) if isinstance(plugin, dict) else False

    def has_decision(self, plugin_id, permission):
        with self._lock:
            return any(item.get("plugin") == str(plugin_id)
                       and item.get("permission") == str(permission)
                       for item in self._history)

    def permissions_for(self, plugin_id):
        with self._lock:
            row = self._grants.get(str(plugin_id), {})
            return dict(row) if isinstance(row, dict) else {}

    def authorize(self, plugin_id, permission, *, confirmed=False):
        if not isinstance(plugin_id, str) or not plugin_id.strip() or len(plugin_id) > 64:
            raise ValueError("Identificador de plugin inválido.")
        if not isinstance(permission, str) or permission not in KNOWN_PERMISSIONS:
            raise ValueError("Permissão desconhecida.")
        if permission in SENSITIVE and not confirmed:
            return False
        with self._lock:
            plugin = self._grants.setdefault(plugin_id, {})
            previous = plugin.get(permission)
            plugin[permission] = True
            self._history.append({"plugin": plugin_id, "permission": permission, "granted": True})
            try:
                self._save()
            except OSError:
                if previous is None:
                    plugin.pop(permission, None)
                else:
                    plugin[permission] = previous
                if not plugin:
                    self._grants.pop(plugin_id, None)
                self._history.pop()
                raise
        return True

    def revoke(self, plugin_id, permission):
        if not isinstance(plugin_id, str) or not plugin_id.strip() or len(plugin_id) > 64:
            raise ValueError("Identificador de plugin inválido.")
        if not isinstance(permission, str) or permission not in KNOWN_PERMISSIONS:
            raise ValueError("Permissão desconhecida.")
        with self._lock:
            plugin = self._grants.setdefault(plugin_id, {})
            previous = plugin.get(permission)
            plugin[permission] = False
            self._history.append({"plugin": plugin_id, "permission": permission, "granted": False})
            try:
                self._save()
            except OSError:
                if previous is None:
                    plugin.pop(permission, None)
                else:
                    plugin[permission] = previous
                if not plugin:
                    self._grants.pop(plugin_id, None)
                self._history.pop()
                raise

    def require(self, plugin_id, permission, *, confirmed=False):
        if not self.allowed(plugin_id, permission):
            raise PermissionError(f"Permissão negada: {permission}")
        if permission in SENSITIVE and not confirmed:
            raise PermissionError(f"Confirmação explícita necessária: {permission}")
        return True

    def _save(self):
        self._ensure_safe_path()
        if not may_replace(self.path):
            raise OSError(f"Gravação bloqueada para preservar {self.path.name}.")
        if self.path.parent.exists() and self.path.parent.is_symlink():
            raise OSError("O diretório de permissões não pode ser um link simbólico")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink():
            raise OSError("O diretório de permissões não pode ser um link simbólico")
        fd, name = tempfile.mkstemp(prefix=".permissions-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"grants": self._grants, "history": self._history[-500:]}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
