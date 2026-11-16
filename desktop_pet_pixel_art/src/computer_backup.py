"""Versioned, integrity-checked backups of an explicit Nova configuration allowlist."""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from json_persistence import atomic_json_write, ensure_private_directory, validate_storage_path

logger = logging.getLogger(__name__)
FORMAT_ID = "nova-user-config-backup"
FORMAT_VERSION = 1
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_BYTES = 8 * 1024 * 1024
BACKUP_SUFFIX = ".nova-backup.json"
_LOGICAL_FILES = ("settings.json", "personality.json")
_LABEL_PATTERN = re.compile(r"[^\w .()\-]", re.UNICODE)


def default_backup_directory():
    return Path.home() / ".local" / "share" / "desktop_pet" / "backups"


def backup_location_settings_path():
    return Path.home() / ".config" / "desktop_pet" / "backup_location.json"


def load_backup_directory():
    try:
        path = backup_location_settings_path()
        validate_storage_path(path, label="localização de backup")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") == FORMAT_ID and isinstance(data.get("directory"), str):
            return validate_backup_directory(data["directory"], create=False)
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        pass
    return validate_backup_directory(default_backup_directory(), create=True)


def save_backup_directory(directory):
    path = validate_backup_directory(directory, create=True)
    atomic_json_write(backup_location_settings_path(),
                      {"format": FORMAT_ID, "directory": str(path)},
                      label="localização de backup")
    return path


def validate_backup_directory(directory, *, create=True):
    if not isinstance(directory, (str, os.PathLike)):
        raise ValueError("Diretório de backup inválido.")
    raw = os.path.expanduser(os.fspath(directory))
    candidate = Path(raw)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Escolha um caminho absoluto sem componentes '..'.")
    candidate = validate_storage_path(candidate, label="diretório de backup")
    if create:
        ensure_private_directory(candidate, label="diretório de backup")
    elif not candidate.is_dir():
        raise ValueError("O diretório configurado não existe.")
    info = candidate.stat()
    if info.st_uid != os.getuid():
        raise PermissionError("O diretório de backup precisa pertencer ao usuário atual.")
    return candidate


def _source_paths(profile_manager):
    if profile_manager is None:
        raise ValueError("O gerenciador de perfil da Nova não está disponível.")
    paths = {
        "settings.json": Path(profile_manager.settings_path()),
        "personality.json": Path(profile_manager.personality_state_path()),
    }
    allowed_names = {"settings.json": "settings.json",
                     "personality.json": "nova_personality.json"}
    if not hasattr(profile_manager, "base_dir"):
        raise ValueError("O gerenciador de perfil não informa uma raiz segura.")
    base = Path(profile_manager.base_dir)
    validate_storage_path(base, label="raiz de perfis")
    base = base.resolve()
    for logical, path in paths.items():
        validate_storage_path(path, label="configuração da Nova")
        if path.name != allowed_names[logical]:
            raise ValueError("O perfil forneceu um destino fora da lista segura de configurações.")
        try: path.resolve(strict=False).relative_to(base)
        except ValueError as exc:
            raise ValueError("O destino de configuração está fora da raiz de perfis.") from exc
    return paths


def _read_safe_source(path):
    validate_storage_path(path, label="configuração da Nova")
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise PermissionError(f"Arquivo de configuração inseguro ou sem acesso: {path.name}")
    if info.st_size > MAX_FILE_BYTES:
        raise ValueError(f"Arquivo de configuração excede o limite: {path.name}")
    raw = path.read_bytes()
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"Estrutura inesperada em {path.name}; esperado objeto JSON.")
    return _safe_json_bytes(parsed)


def _sensitive_key(key):
    normalized = str(key).casefold().replace("-", "_")
    return (any(part in normalized for part in
                ("password", "passwd", "secret", "token", "credential",
                 "authorization", "api_key", "apikey", "client_id"))
            or normalized.endswith("_key"))


def _without_sensitive_values(value):
    if isinstance(value, dict):
        return {key: _without_sensitive_values(item) for key, item in value.items()
                if not _sensitive_key(key)}
    if isinstance(value, list):
        return [_without_sensitive_values(item) for item in value]
    return value


def _safe_json_bytes(value):
    return json.dumps(_without_sensitive_values(value), ensure_ascii=False,
                      indent=2, sort_keys=True).encode("utf-8")


def _preserve_sensitive_values(current, restored):
    if not isinstance(current, dict) or not isinstance(restored, dict):
        return restored
    merged = dict(restored)
    for key, value in current.items():
        if _sensitive_key(key):
            merged[key] = value
        elif key in merged and isinstance(value, dict) and isinstance(merged[key], dict):
            merged[key] = _preserve_sensitive_values(value, merged[key])
    return merged


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _seal(package):
    package.pop("integrity", None)
    package["integrity"] = {"algorithm": "sha256",
                            "digest": hashlib.sha256(_canonical(package)).hexdigest()}
    return package


def create_backup(profile_manager, directory=None, *, label="Backup manual"):
    destination = validate_backup_directory(directory or default_backup_directory())
    clean_label = _clean_label(label)
    entries = []
    for logical_name, source in _source_paths(profile_manager).items():
        raw = _read_safe_source(source)
        entries.append({
            "name": logical_name, "present": raw is not None,
            "size": len(raw) if raw is not None else 0,
            "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
            "data": base64.b64encode(raw).decode("ascii") if raw is not None else None,
        })
    package = _seal({
        "format": FORMAT_ID, "format_version": FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backup_id": uuid.uuid4().hex, "label": clean_label,
        "files": entries,
    })
    target = destination / f"{package['created_at'][:10]}-{package['backup_id'][:8]}{BACKUP_SUFFIX}"
    atomic_json_write(target, package, label="backup da Nova")
    logger.info("Backup da Nova criado: %s (%d bytes)", target.name,
                sum(entry["size"] for entry in entries))
    return target


def _clean_label(label):
    if not isinstance(label, str):
        raise ValueError("A identificação do backup deve ser texto.")
    cleaned = _LABEL_PATTERN.sub("", label).strip()[:80]
    if not cleaned:
        raise ValueError("Informe uma identificação válida para o backup.")
    return cleaned


def _safe_backup_file(path, directory):
    root = validate_backup_directory(directory, create=False)
    candidate = Path(path)
    if (not candidate.is_absolute() or candidate.parent != root
            or not candidate.name.endswith(BACKUP_SUFFIX)
            or candidate.name in (BACKUP_SUFFIX, ".", "..")):
        raise ValueError("O backup deve ser um arquivo direto do diretório configurado.")
    validate_storage_path(candidate, label="arquivo de backup")
    info = candidate.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise PermissionError("Arquivo de backup inseguro ou sem acesso.")
    if info.st_size > MAX_PACKAGE_BYTES:
        raise ValueError("O arquivo excede o limite permitido para backups.")
    return candidate


def read_backup(path, directory=None):
    root = validate_backup_directory(directory or Path(path).parent, create=False)
    candidate = _safe_backup_file(path, root)
    try:
        package = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("O arquivo de backup está corrompido ou ilegível.") from exc
    _validate_package(package)
    return package


def _validate_package(package):
    if not isinstance(package, dict) or package.get("format") != FORMAT_ID:
        raise ValueError("Formato de backup desconhecido.")
    if set(package) != {"format", "format_version", "created_at", "backup_id", "label", "files", "integrity"}:
        raise ValueError("O backup contém campos desconhecidos.")
    if package.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"Versão incompatível: {package.get('format_version')}.")
    if not isinstance(package.get("backup_id"), str) or not re.fullmatch(r"[a-f0-9]{32}", package["backup_id"]):
        raise ValueError("Identificador de backup inválido.")
    try: datetime.fromisoformat(package.get("created_at", "").replace("Z", "+00:00"))
    except (AttributeError, ValueError): raise ValueError("Data do backup inválida.")
    integrity = package.get("integrity")
    unsigned = dict(package); unsigned.pop("integrity", None)
    expected = hashlib.sha256(_canonical(unsigned)).hexdigest()
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "sha256" or not hmac.compare_digest(str(integrity.get("digest", "")), expected):
        raise ValueError("A verificação de integridade do backup falhou.")
    if not isinstance(package.get("label"), str) or not isinstance(package.get("created_at"), str):
        raise ValueError("Metadados do backup inválidos.")
    files = package.get("files")
    if not isinstance(files, list) or len(files) != len(_LOGICAL_FILES):
        raise ValueError("Estrutura de arquivos do backup inválida.")
    seen = set(); total = 0
    for item in files:
        if (not isinstance(item, dict)
                or set(item) != {"name", "present", "size", "sha256", "data"}
                or item.get("name") not in _LOGICAL_FILES or item["name"] in seen):
            raise ValueError("O backup contém uma entrada não permitida.")
        seen.add(item["name"])
        if type(item.get("present")) is not bool:
            raise ValueError("Indicador de presença inválido.")
        if not item["present"]:
            if item.get("data") is not None or item.get("sha256") is not None or item.get("size") != 0:
                raise ValueError("Entrada ausente contém dados inesperados.")
            continue
        if not isinstance(item.get("data"), str) or not isinstance(item.get("sha256"), str):
            raise ValueError("Conteúdo do backup inválido.")
        try: raw = base64.b64decode(item["data"], validate=True)
        except (ValueError, TypeError) as exc: raise ValueError("Conteúdo codificado inválido.") from exc
        if len(raw) > MAX_FILE_BYTES or item.get("size") != len(raw):
            raise ValueError("Tamanho do conteúdo incompatível.")
        total += len(raw)
        if not hmac.compare_digest(hashlib.sha256(raw).hexdigest(), item["sha256"]):
            raise ValueError(f"Integridade inválida em {item['name']}.")
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Estrutura inválida em {item['name']}.") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"Estrutura incompatível em {item['name']}.")
    if seen != set(_LOGICAL_FILES) or total > MAX_PACKAGE_BYTES:
        raise ValueError("O backup excede limites ou não contém os itens esperados.")
    return True


def list_backups(directory=None):
    root = validate_backup_directory(directory or default_backup_directory())
    backups = []
    for path in sorted(root.iterdir(), key=lambda p: p.name, reverse=True)[:200]:
        if not path.name.endswith(BACKUP_SUFFIX):
            continue
        try:
            package = read_backup(path, root)
            backups.append({"path": str(path), "label": package["label"],
                            "created_at": package["created_at"],
                            "size": path.stat().st_size, "integrity": "Íntegro",
                            "contents": [{"name": item["name"], "present": item["present"], "size": item["size"]} for item in package["files"]]})
        except (OSError, ValueError) as exc:
            try: size = path.lstat().st_size
            except OSError: size = 0
            backups.append({"path": str(path), "label": path.name,
                            "created_at": "", "size": size,
                            "integrity": f"Inválido · {str(exc)[:120]}", "contents": []})
    return backups


def rename_backup(path, directory, label):
    package = read_backup(path, directory)
    package["label"] = _clean_label(label)
    _seal(package)
    target = _safe_backup_file(path, directory)
    atomic_json_write(target, package, label="identificação do backup")
    logger.info("Identificação de backup da Nova atualizada: %s", target.name)
    return target


def delete_backup(path, directory):
    target = _safe_backup_file(path, directory)
    target.unlink()
    logger.info("Backup da Nova removido: %s", target.name)


def export_backup(path, directory, destination):
    package = read_backup(path, directory)
    target = Path(destination)
    if not target.is_absolute() or target.exists() or target.is_symlink():
        raise FileExistsError("Escolha um caminho absoluto novo para exportar o backup.")
    validate_storage_path(target, label="exportação de backup")
    parent = target.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("O diretório de exportação não existe ou é inválido.")
    source = _safe_backup_file(path, directory)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as output, source.open("rb") as input_stream:
            shutil.copyfileobj(input_stream, output)
            output.flush(); os.fsync(output.fileno())
        os.link(temp_name, target)
        os.unlink(temp_name)
    except BaseException:
        try: os.unlink(temp_name)
        except OSError: pass
        raise
    logger.info("Backup da Nova exportado: %s (%s)", target.name, package["backup_id"])
    return target


def preview_restore(path, directory, profile_manager):
    package = read_backup(path, directory)
    destinations = _source_paths(profile_manager)
    changes = []
    for item in package["files"]:
        destination = destinations[item["name"]]
        validate_storage_path(destination, label="destino de restauração")
        current = _read_safe_source(destination)
        current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
        changes.append({"name": item["name"], "action": "substituir" if item["present"] else "remover",
                        "changed": current_hash != item["sha256"], "size": item["size"]})
    return {"label": package["label"], "created_at": package["created_at"], "changes": changes}


def restore_backup(path, directory, profile_manager):
    """Validate everything, create a safety backup, then atomically replace allowlisted JSON files."""
    package = read_backup(path, directory)
    preview = preview_restore(path, directory, profile_manager)
    destinations = _source_paths(profile_manager)
    originals = {}
    for destination in destinations.values():
        validate_storage_path(destination, label="destino de restauração")
        originals[destination] = _read_raw_current(destination) if destination.exists() else None
    current_backup = create_backup(profile_manager, directory, label="Segurança antes da restauração")
    staged = []
    mutated = set()
    try:
        for item in package["files"]:
            destination = destinations[item["name"]]
            validate_storage_path(destination, label="destino de restauração")
            ensure_private_directory(destination.parent, label="destino de restauração")
            if item["present"]:
                restored_data = json.loads(base64.b64decode(item["data"], validate=True).decode("utf-8"))
                if destination.exists():
                    current_data = json.loads(_read_raw_current(destination).decode("utf-8"))
                    restored_data = _preserve_sensitive_values(current_data, restored_data)
                raw = json.dumps(restored_data, ensure_ascii=False, indent=2,
                                 sort_keys=True).encode("utf-8")
                fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".restore", dir=destination.parent)
                staged.append((destination, Path(temp_name)))
                os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        for destination, temporary in staged:
            validate_storage_path(destination, label="destino de restauração")
            os.replace(temporary, destination)
            mutated.add(destination)
        for item in package["files"]:
            if item["present"]: continue
            destination = destinations[item["name"]]
            validate_storage_path(destination, label="destino de restauração")
            if destination.exists():
                if destination.is_symlink() or not destination.is_file():
                    raise ValueError("Destino de restauração inseguro.")
                destination.unlink()
                mutated.add(destination)
        logger.info("Backup da Nova restaurado: %s; segurança: %s", Path(path).name, current_backup.name)
    except BaseException:
        for _destination, temporary in staged:
            try: temporary.unlink(missing_ok=True)
            except OSError: pass
        for destination in mutated:
            try:
                original = originals[destination]
                if original is None:
                    destination.unlink(missing_ok=True)
                else:
                    _atomic_raw_write(destination, original)
            except OSError:
                logger.exception("Não foi possível reverter destino após falha de restauração: %s", destination.name)
        raise
    return {"restored": [change["name"] for change in preview["changes"] if change["changed"]],
            "safety_backup": str(current_backup)}


def _read_raw_current(path):
    """Read the original JSON only for preserving local secrets during restore."""
    validate_storage_path(path, label="configuração da Nova")
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > MAX_FILE_BYTES:
        raise PermissionError(f"Arquivo de configuração inseguro ou sem acesso: {path.name}")
    return path.read_bytes()


def _atomic_raw_write(destination, raw):
    validate_storage_path(destination, label="reversão de configuração")
    ensure_private_directory(destination.parent, label="reversão de configuração")
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".rollback", dir=destination.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp_name, destination)
    except BaseException:
        try: os.unlink(temp_name)
        except OSError: pass
        raise
