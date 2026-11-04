"""Explicitly registered trusted in-process skills for Nova."""
from dataclasses import dataclass, field
import json
import logging
import os
import shutil
import re
import subprocess
import threading
import tempfile
import signal
from pathlib import Path

from event_bus import Event, EventBus, EventType
from permissions import PermissionManager

logger = logging.getLogger(__name__)
API_VERSION = "1.0"
KNOWN_PERMISSIONS = {
    "file.read", "file.write", "file.move", "file.delete", "file.organize",
    "system.cpu.read", "system.memory.read", "system.disk.read",
    "system.process.read", "system.app.launch", "system.maintenance.read",
    "system.maintenance", "spotify.control", "ai.use", "network.access",
    "notification.create", "pet.animation.control", "task.create",
}


@dataclass
class PluginManifest:
    plugin_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    min_api_version: str = "1.0"
    permissions: tuple = ()
    config: dict = field(default_factory=dict)

    def validate(self):
        if not isinstance(self.plugin_id, str) or not re.fullmatch(r"[a-z][a-z0-9_.-]{1,63}", self.plugin_id):
            raise ValueError("ID de plugin inválido.")
        version_pattern = r"\d+\.\d+\.\d+"
        api_pattern = r"\d+\.\d+"
        if (not isinstance(self.name, str) or not self.name.strip()
                or not re.fullmatch(version_pattern, str(self.version))
                or not re.fullmatch(api_pattern, str(self.min_api_version))
                or self.min_api_version.split(".")[0] != API_VERSION.split(".")[0]
                or not isinstance(self.permissions, (list, tuple))
                or any(not isinstance(permission, str) or permission not in KNOWN_PERMISSIONS
                       for permission in self.permissions)
                or not isinstance(self.config, dict)):
            raise ValueError("Manifesto inválido ou incompatível.")
        return self


class Plugin:
    manifest = None
    def initialize(self, context): pass
    def activate(self): pass
    def deactivate(self): pass
    def shutdown(self): pass


class PluginPermissionView:
    """Read-only permission facade scoped to one plugin identifier."""
    def __init__(self, manager, plugin_id):
        self._manager = manager
        self.plugin_id = plugin_id

    def allowed(self, permission):
        return self._manager.allowed(self.plugin_id, permission)

    def require(self, permission, *, confirmed=False):
        return self._manager.require(self.plugin_id, permission, confirmed=confirmed)


class IsolatedPluginProcess:
    """One-shot JSON-RPC process boundary for explicitly installed external skills.

    This limits credentials, message size, runtime and common resource exhaustion.
    It is defense-in-depth, not an OS sandbox: external code still runs as this user.
    """
    MAX_MESSAGE = 64 * 1024
    MAX_OUTPUT = 64 * 1024

    def __init__(self, command, *, cwd=None, timeout=5, cpu_seconds=3,
                 memory_bytes=256 * 1024 * 1024, network_access=False):
        if not isinstance(command, (list, tuple)) or not command or len(command) > 64:
            raise ValueError("Comando externo inválido.")
        if any(not isinstance(arg, str) or not arg or "\x00" in arg or len(arg) > 1024 for arg in command):
            raise ValueError("Argumento externo inválido.")
        self.command = list(command)
        self.cwd = str(Path(cwd).resolve()) if cwd else None
        self.timeout = max(0.1, min(float(timeout), 30.0))
        self.cpu_seconds = max(1, min(int(cpu_seconds), 10))
        self.memory_bytes = max(64 * 1024 * 1024, min(int(memory_bytes), 1024 * 1024 * 1024))
        self.network_access = bool(network_access)
        self.bwrap = shutil.which("bwrap")
        if not self.bwrap:
            raise RuntimeError("Plugins externos exigem bubblewrap para isolamento.")
        self._lock = threading.Lock()

    def request(self, action, payload=None):
        message = json.dumps({"protocol": 1, "action": str(action), "payload": payload or {}},
                             ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        if len(message) > self.MAX_MESSAGE:
            raise ValueError("Mensagem para plugin excede o limite.")
        sandbox = [self.bwrap, "--die-with-parent", "--unshare-user", "--unshare-pid",
                   "--ro-bind", "/usr", "/usr", "--proc", "/proc", "--dev", "/dev",
                   "--tmpfs", "/tmp", "--dir", "/home", "--ro-bind", self.cwd, "/plugin",
                   "--chdir", "/plugin", "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/usr/bin:/bin"]
        for library in ("/bin", "/lib", "/lib64", "/etc"):
            if Path(library).exists():
                sandbox.extend(["--ro-bind", library, library])
        if not self.network_access:
            sandbox.append("--unshare-net")
        prlimit = shutil.which("prlimit")
        if not prlimit:
            raise RuntimeError("Plugins externos exigem prlimit para limitar recursos.")
        sandbox.extend(["--", prlimit, f"--cpu={self.cpu_seconds}",
                        f"--as={self.memory_bytes}", "--nproc=32", "--nofile=32", "--core=0",
                        f"--fsize={self.MAX_OUTPUT}", "--", *self.command])
        with self._lock:
            with tempfile.TemporaryFile() as output_file:
                process = subprocess.Popen(
                    sandbox, stdin=subprocess.PIPE, stdout=output_file,
                    stderr=subprocess.DEVNULL, cwd=self.cwd,
                    env={"PATH": os.defpath, "LANG": os.environ.get("LANG", "C.UTF-8"), "PYTHONNOUSERSITE": "1"},
                    close_fds=True, start_new_session=True,
                )
                try:
                    process.communicate(message, timeout=self.timeout)
                except subprocess.TimeoutExpired as exc:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
                    raise TimeoutError("Plugin excedeu o tempo permitido.") from exc
                finally:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                output_file.seek(0)
                output = output_file.read(self.MAX_OUTPUT + 1)
            if len(output) > self.MAX_OUTPUT:
                raise ValueError("Resposta do plugin excede o limite.")
            if process.returncode:
                raise RuntimeError(f"Plugin encerrou com código {process.returncode}.")
            try:
                response = json.loads(output.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Resposta JSON inválida do plugin.") from exc
            if not isinstance(response, dict) or response.get("protocol") != 1 or not isinstance(response.get("ok"), bool):
                raise ValueError("Envelope de resposta inválido do plugin.")
            if not response["ok"]:
                raise RuntimeError(str(response.get("error", "Plugin reportou falha"))[:300])
            return response.get("result")

    def initialize(self, context):
        return self.request("initialize", {"api_version": API_VERSION})
    def activate(self):
        return self.request("activate")
    def deactivate(self):
        return self.request("deactivate")
    def shutdown(self):
        return self.request("shutdown")


class PluginManager:
    """Does not discover or import third-party code; only explicit instances register."""
    def __init__(self, context=None, event_bus=None, permission_manager=None):
        self.context = context or {}
        self.event_bus = event_bus or EventBus()
        self.permission_manager = permission_manager or self.context.get("permissions") or PermissionManager()
        self._plugins = {}
        self._active = set()
        self.errors = []

    def register(self, plugin):
        manifest = getattr(plugin, "manifest", None)
        if not isinstance(manifest, PluginManifest):
            raise ValueError("Plugin precisa declarar PluginManifest.")
        manifest.validate()
        if manifest.plugin_id in self._plugins:
            return False
        self._plugins[manifest.plugin_id] = plugin
        self.event_bus.publish(Event(EventType.PLUGIN_DISCOVERED, {
            "plugin_id": manifest.plugin_id, "name": manifest.name,
            "version": manifest.version,
        }))
        return True

    def register_external_manifest(self, manifest_path):
        """Install an explicit JSON manifest; never scans/imports a directory."""
        path = Path(manifest_path).expanduser().resolve()
        if path.stat().st_size > IsolatedPluginProcess.MAX_MESSAGE:
            raise ValueError("Manifesto excede o limite de tamanho.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("kind") != "external":
            raise ValueError("Manifesto deve declarar kind=external.")
        permissions = data.get("permissions", [])
        command = data.get("command")
        if not isinstance(permissions, list) or any(not isinstance(item, str) for item in permissions):
            raise ValueError("Permissões inválidas no manifesto.")
        manifest = PluginManifest(
            plugin_id=data.get("plugin_id"), name=data.get("name", ""),
            description=data.get("description", ""), version=data.get("version", "1.0.0"),
            min_api_version=data.get("min_api_version", "1.0"),
            permissions=tuple(permissions), config=data.get("config", {}),
        ).validate()
        plugin = IsolatedPluginProcess(
            command, cwd=path.parent, timeout=data.get("timeout", 5),
            cpu_seconds=data.get("cpu_seconds", 3), memory_bytes=data.get("memory_bytes", 256 * 1024 * 1024),
            network_access="network.access" in permissions,
        )
        plugin.manifest = manifest
        if not self.register(plugin):
            return False
        return True

    def activate(self, plugin_id):
        if plugin_id in self._active:
            return True
        plugin = self._plugins[plugin_id]
        try:
            for permission in plugin.manifest.permissions:
                if not self.permission_manager.allowed(plugin_id, permission):
                    raise PermissionError(f"Permissão não concedida: {permission}")
            plugin.initialize({
                "plugin_id": plugin_id,
                "permissions": PluginPermissionView(self.permission_manager, plugin_id),
                "config": dict(plugin.manifest.config),
            })
            plugin.activate()
            self._active.add(plugin_id)
            self.event_bus.publish(Event(EventType.PLUGIN_ACTIVATED, {"plugin_id": plugin_id}))
            return True
        except Exception as exc:
            self.errors.append({"plugin_id": plugin_id, "error": type(exc).__name__})
            logger.exception("Plugin %s falhou ao ativar", plugin_id)
            for method in (plugin.deactivate, plugin.shutdown):
                try:
                    method()
                except Exception:
                    pass
            self.event_bus.publish(Event(EventType.PLUGIN_FAILED, {"plugin_id": plugin_id, "error": type(exc).__name__}))
            return False

    def execute(self, plugin_id, permission, operation, *args, confirmed=False, **kwargs):
        """Run one operation only after checking its permission at call time."""
        if plugin_id not in self._active:
            raise RuntimeError("Plugin inativo.")
        if self.permission_manager is None:
            raise PermissionError("Permission Manager indisponível.")
        self.permission_manager.require(plugin_id, permission, confirmed=confirmed)
        if not callable(operation):
            raise TypeError("A operação do plugin precisa ser chamável.")
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            self.errors.append({"plugin_id": plugin_id, "error": type(exc).__name__})
            self.event_bus.publish(Event(EventType.PLUGIN_FAILED, {"plugin_id": plugin_id, "error": type(exc).__name__}))
            raise

    def execute_external(self, plugin_id, permission, action, payload=None, *, confirmed=False):
        if plugin_id not in self._active:
            raise RuntimeError("Plugin inativo.")
        self.permission_manager.require(plugin_id, permission, confirmed=confirmed)
        plugin = self._plugins[plugin_id]
        if not isinstance(plugin, IsolatedPluginProcess):
            raise TypeError("O plugin registrado não é externo.")
        try:
            return plugin.request(action, payload)
        except Exception as exc:
            self.errors.append({"plugin_id": plugin_id, "error": type(exc).__name__})
            self.event_bus.publish(Event(EventType.PLUGIN_FAILED, {"plugin_id": plugin_id, "error": type(exc).__name__}))
            raise

    def deactivate(self, plugin_id):
        if plugin_id not in self._active:
            return False
        try:
            self._plugins[plugin_id].deactivate()
            return True
        except Exception as exc:
            self.errors.append({"plugin_id": plugin_id, "error": type(exc).__name__})
            self.event_bus.publish(Event(EventType.PLUGIN_FAILED, {"plugin_id": plugin_id, "error": type(exc).__name__}))
            logger.exception("Plugin %s falhou ao desativar", plugin_id)
            return False
        finally:
            self._active.discard(plugin_id)
            self.event_bus.publish(Event(EventType.PLUGIN_DEACTIVATED, {"plugin_id": plugin_id}))

    def shutdown(self):
        for plugin_id in tuple(self._plugins):
            try:
                if plugin_id in self._active:
                    self.deactivate(plugin_id)
                self._plugins[plugin_id].shutdown()
            except Exception:
                logger.exception("Falha encerrando plugin %s", plugin_id)

    @property
    def counts(self):
        return {"installed": len(self._plugins), "active": len(self._active), "errors": len(self.errors)}
