"""Persistent, deny-by-default plugin permissions."""
import json
import os
from pathlib import Path
import tempfile
import threading

DEFAULT_PERMISSION_PATH = Path.home() / ".config" / "desktop_pet" / "permissions.json"
SENSITIVE = {"file.write", "file.move", "file.delete", "file.organize", "system.app.launch", "system.maintenance", "spotify.control", "network.access"}


class PermissionManager:
    def __init__(self, path=DEFAULT_PERMISSION_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._grants = {}
        self._history = []
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._grants = data.get("grants", {}) if isinstance(data.get("grants"), dict) else {}
                self._history = data.get("history", []) if isinstance(data.get("history"), list) else []
        except (OSError, ValueError):
            pass

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
        if not plugin_id or not permission or (permission in SENSITIVE and not confirmed):
            return False
        with self._lock:
            plugin = self._grants.setdefault(str(plugin_id), {})
            previous = plugin.get(str(permission))
            plugin[str(permission)] = True
            self._history.append({"plugin": str(plugin_id), "permission": str(permission), "granted": True})
            try:
                self._save()
            except OSError:
                if previous is None:
                    plugin.pop(str(permission), None)
                else:
                    plugin[str(permission)] = previous
                self._history.pop()
                raise
        return True

    def revoke(self, plugin_id, permission):
        with self._lock:
            plugin = self._grants.setdefault(str(plugin_id), {})
            previous = plugin.get(str(permission))
            plugin[str(permission)] = False
            self._history.append({"plugin": str(plugin_id), "permission": str(permission), "granted": False})
            try:
                self._save()
            except OSError:
                if previous is None:
                    plugin.pop(str(permission), None)
                else:
                    plugin[str(permission)] = previous
                self._history.pop()
                raise

    def require(self, plugin_id, permission, *, confirmed=False):
        if not self.allowed(plugin_id, permission):
            raise PermissionError(f"Permissão negada: {permission}")
        if permission in SENSITIVE and not confirmed:
            raise PermissionError(f"Confirmação explícita necessária: {permission}")
        return True

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
