"""Local user-profile registry and per-profile data paths."""

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from json_persistence import preserve_corrupt_file
from config import HISTORY_PATH


_REGISTRY_VERSION = 1
_LEGACY_PROFILE_ID = "legacy"
_PROFILE_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")
_MAX_PROFILES = 50


class ProfileStorageError(RuntimeError):
    """A profile registry could not be safely read or written."""


@dataclass(frozen=True)
class UserProfile:
    profile_id: str
    name: str
    created_at: str

    def __post_init__(self):
        if self.profile_id != _LEGACY_PROFILE_ID and not _PROFILE_ID_PATTERN.fullmatch(
            self.profile_id
        ):
            raise ValueError("Identificador de perfil inválido")
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 60:
            raise ValueError("O nome do perfil deve ter entre 1 e 60 caracteres")


class UserProfileManager:
    """Keeps profile metadata separate while preserving the original memory DB."""

    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir is not None else (
            Path.home() / ".config" / "desktop_pet"
        )
        self.registry_path = self.base_dir / "user_profiles.json"
        self.legacy_memory_path = self.base_dir / "nova_memory.sqlite3"
        self._profiles, self._active_profile_id = self._load()

    @property
    def profiles(self):
        return tuple(self._profiles)

    @property
    def active_profile(self):
        return self.get(self._active_profile_id)

    def get(self, profile_id):
        for profile in self._profiles:
            if profile.profile_id == profile_id:
                return profile
        raise ValueError("Perfil não encontrado")

    def create(self, name, *, activate=True):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
            raise ValueError("O nome do perfil deve ter entre 1 e 60 caracteres")
        if len(self._profiles) >= _MAX_PROFILES:
            raise ValueError("O limite de perfis foi atingido")
        profile = UserProfile(
            profile_id=uuid.uuid4().hex,
            name=name.strip(),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        profiles = [*self._profiles, profile]
        active_id = profile.profile_id if activate else self._active_profile_id
        self._save(profiles, active_id)
        self._profiles, self._active_profile_id = profiles, active_id
        return profile

    def select(self, profile_id):
        self.get(profile_id)
        self._save(self._profiles, profile_id)
        self._active_profile_id = profile_id
        return self.active_profile

    def memory_path(self, profile_id=None):
        profile = self.get(profile_id or self._active_profile_id)
        if profile.profile_id == _LEGACY_PROFILE_ID:
            return self.legacy_memory_path
        return self._profile_directory(profile) / "nova_memory.sqlite3"

    def personality_state_path(self, profile_id=None):
        profile = self.get(profile_id or self._active_profile_id)
        if profile.profile_id == _LEGACY_PROFILE_ID:
            return self.base_dir / "nova_personality.json"
        return self._profile_directory(profile) / "nova_personality.json"

    def history_path(self, profile_id=None):
        profile = self.get(profile_id or self._active_profile_id)
        if profile.profile_id == _LEGACY_PROFILE_ID:
            return HISTORY_PATH
        return self._profile_directory(profile) / "history.json"

    def settings_path(self, profile_id=None):
        profile = self.get(profile_id or self._active_profile_id)
        if profile.profile_id == _LEGACY_PROFILE_ID:
            return self.base_dir / "settings.json"
        return self._profile_directory(profile) / "settings.json"

    def _profile_directory(self, profile):
        profiles_dir = self.base_dir / "profiles"
        profile_dir = profiles_dir / profile.profile_id
        try:
            profiles_dir.mkdir(mode=0o700, exist_ok=True)
            if profiles_dir.is_symlink():
                raise ProfileStorageError("O diretório de perfis não pode ser link simbólico")
            os.chmod(profiles_dir, 0o700)
            profile_dir.mkdir(mode=0o700, exist_ok=True)
            if profile_dir.is_symlink():
                raise ProfileStorageError("O diretório do perfil não pode ser link simbólico")
            os.chmod(profile_dir, 0o700)
        except OSError as exc:
            raise ProfileStorageError("Não foi possível preparar o diretório do perfil") from exc
        return profile_dir

    def _load(self):
        legacy = UserProfile(
            profile_id=_LEGACY_PROFILE_ID,
            name="Perfil principal",
            created_at="",
        )
        try:
            content = self.registry_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return [legacy], _LEGACY_PROFILE_ID
        except OSError as exc:
            raise ProfileStorageError("Não foi possível ler os perfis locais") from exc

        try:
            data = json.loads(content)
            if not isinstance(data, dict) or data.get("version") != _REGISTRY_VERSION:
                raise ValueError("Versão ou formato do registro inválido")
            rows = data.get("profiles")
            active_id = data.get("active_profile_id")
            if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_PROFILES:
                raise ValueError("Lista de perfis inválida")
            profiles = []
            seen = set()
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("Perfil inválido")
                profile = UserProfile(
                    profile_id=row.get("profile_id"),
                    name=row.get("name"),
                    created_at=row.get("created_at", ""),
                )
                if profile.profile_id in seen:
                    raise ValueError("Identificador de perfil duplicado")
                seen.add(profile.profile_id)
                profiles.append(profile)
            if _LEGACY_PROFILE_ID not in seen or active_id not in seen:
                raise ValueError("O perfil principal ou o perfil ativo está ausente")
            return profiles, active_id
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            backup = preserve_corrupt_file(self.registry_path, type(exc).__name__)
            if backup is None:
                raise ProfileStorageError(
                    "Registro de perfis inválido e não foi possível preservá-lo"
                ) from exc
            raise ProfileStorageError(
                f"Registro de perfis inválido; cópia preservada em {backup.name}"
            ) from exc

    def _save(self, profiles, active_id):
        self.base_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.registry_path.is_symlink():
            raise ProfileStorageError("O registro de perfis não pode ser um link simbólico")
        payload = {
            "version": _REGISTRY_VERSION,
            "active_profile_id": active_id,
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "name": profile.name,
                    "created_at": profile.created_at,
                }
                for profile in profiles
            ],
        }
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.base_dir,
                prefix=".user_profiles.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                os.chmod(temporary, 0o600)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.registry_path)
            os.chmod(self.registry_path, 0o600)
        except OSError as exc:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise ProfileStorageError("Não foi possível salvar os perfis locais") from exc
