"""Persistent, per-machine installation state without touching user data."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from json_persistence import (
    atomic_json_write,
    ensure_private_directory,
    preserve_corrupt_file,
    validate_storage_path,
)


STATE_VERSION = 1
CONFIGURATION_VERSION = 1


class InstallationStateError(RuntimeError):
    """Installation state could not be read or safely updated."""


def _default_state():
    return {
        "state_version": STATE_VERSION,
        "configuration_version": CONFIGURATION_VERSION,
        "setup_completed": False,
        "last_configured_at": None,
        "dependencies_verified": {},
        "ollama_status": "not_checked",
        "selected_model": "",
        "database_status": "not_checked",
        "personality_status": "not_checked",
        "graphics_status": "not_checked",
    }


class InstallationStateStore:
    """Store setup progress separately from profile preferences and memories."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else (
            Path.home() / ".config" / "desktop_pet" / "installation_state.json"
        )
        try:
            validate_storage_path(self.path, label="estado da instalação")
        except OSError as exc:
            raise InstallationStateError(
                "O estado da instalação não pode usar link simbólico ou caminho inseguro"
            ) from exc

    def load(self):
        if self.path.is_symlink():
            raise InstallationStateError("O estado da instalação não pode ser um link simbólico")
        try:
            content = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return _default_state()
        except OSError as exc:
            raise InstallationStateError("Não foi possível ler o estado da instalação") from exc

        try:
            data = json.loads(content)
            if not isinstance(data, dict) or data.get("state_version") != STATE_VERSION:
                raise ValueError("versão ou formato inválido")
            state = _default_state()
            state.update(data)
            self._validate(state)
            return state
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            backup = preserve_corrupt_file(self.path, type(exc).__name__)
            if backup is None:
                raise InstallationStateError(
                    "Estado inválido e não foi possível preservar o arquivo original"
                ) from exc
            raise InstallationStateError(
                f"Estado inválido; uma cópia foi preservada em {backup.name}"
            ) from exc

    def update(self, **changes):
        allowed = set(_default_state())
        if any(key not in allowed or key == "state_version" for key in changes):
            raise ValueError("Campo de estado da instalação não reconhecido")
        state = self.load()
        state.update(changes)
        self._validate(state)
        self._save(state)
        return state

    def complete_first_run(self, environment=None):
        changes = {
            "setup_completed": True,
            "configuration_version": CONFIGURATION_VERSION,
            "last_configured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        if environment is not None:
            changes.update(environment)
        return self.update(**changes)

    @staticmethod
    def _validate(state):
        if type(state.get("setup_completed")) is not bool:
            raise ValueError("setup_completed deve ser booleano")
        if (type(state.get("configuration_version")) is not int
                or state["configuration_version"] < 1):
            raise ValueError("configuration_version inválida")
        if not isinstance(state.get("dependencies_verified"), dict):
            raise ValueError("dependencies_verified deve ser um objeto")
        if any(not isinstance(key, str) or type(value) is not bool
               for key, value in state["dependencies_verified"].items()):
            raise ValueError("Verificação de dependências inválida")
        for key in (
            "ollama_status", "selected_model", "database_status",
            "personality_status", "graphics_status",
        ):
            if not isinstance(state.get(key), str):
                raise ValueError(f"{key} deve ser texto")
        configured_at = state.get("last_configured_at")
        if configured_at is not None and not isinstance(configured_at, str):
            raise ValueError("last_configured_at inválido")

    def _save(self, state):
        try:
            validate_storage_path(self.path, label="estado da instalação")
            ensure_private_directory(self.path.parent, label="diretório do estado da instalação")
            atomic_json_write(self.path, state, label="estado da instalação", mode=0o600)
        except (OSError, TypeError, ValueError) as exc:
            raise InstallationStateError(
                "Não foi possível salvar o estado da instalação"
            ) from exc
