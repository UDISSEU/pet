"""Small safeguards shared by the user's JSON stores."""

import json
import logging
import os
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
_unsafe_to_replace = set()


def _path_key(path):
    return str(Path(os.path.abspath(os.path.expanduser(str(path)))))


def validate_storage_path(path, *, label="arquivo"):
    """Reject symlinks anywhere in the target path, including broken ancestors."""
    candidate = Path(os.path.abspath(os.path.expanduser(str(path))))
    if ".." in candidate.parts:
        raise OSError(f"O caminho de {label} contém componentes inválidos")
    current = candidate
    while True:
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            if current == current.parent:
                break
            current = current.parent
            continue
        if stat.S_ISLNK(st.st_mode):
            raise OSError(f"O {label} não pode ser um link simbólico")
        if current == current.parent:
            break
        current = current.parent
    return candidate


def ensure_private_directory(path, *, label="diretório"):
    directory = validate_storage_path(path, label=label)
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise OSError(f"Não foi possível preparar o diretório de {label}") from exc
    if not directory.is_dir() or directory.is_symlink():
        raise OSError(f"O diretório de {label} não pode ser um link simbólico")
    try:
        os.chmod(directory, 0o700)
    except OSError as exc:
        raise OSError(f"Não foi possível aplicar permissões de segurança ao diretório de {label}") from exc
    return directory


def atomic_json_write(path, payload, *, label="arquivo", mode=0o600):
    """Write JSON atomically while keeping the original file intact on failure."""
    target = validate_storage_path(path, label=label)
    parent = ensure_private_directory(target.parent, label=label)
    temporary = None
    try:
        try:
            rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"Não foi possível serializar {label}") from exc
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(parent)
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, mode)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(rendered)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            os.chmod(target, mode)
            temporary = None
            return target
        except OSError as exc:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            raise OSError(f"Não foi possível gravar {label} de forma segura") from exc
    except (OSError, TypeError, ValueError) as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def preserve_corrupt_file(path, reason):
    """Copy a file before recovering from invalid JSON; never overwrite a backup."""
    path = validate_storage_path(path, label="arquivo")
    key = _path_key(path)
    try:
        if not path.exists():
            _unsafe_to_replace.discard(key)
            return None
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = path.with_name(f"{path.name}.corrupt-{stamp}")
        temporary = None
        try:
            with path.open("rb") as source, tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=f".{path.name}.backup-",
                suffix=".tmp", delete=False,
            ) as target:
                temporary = target.name
                shutil.copyfileobj(source, target)
                target.flush()
                os.fsync(target.fileno())
            suffix = 0
            while True:
                candidate = backup if suffix == 0 else path.with_name(
                    f"{path.name}.corrupt-{stamp}-{suffix}"
                )
                try:
                    os.link(temporary, candidate)
                    backup = candidate
                    break
                except FileExistsError:
                    suffix += 1
            os.unlink(temporary)
            temporary = None
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
    except OSError as exc:
        _unsafe_to_replace.add(key)
        logger.error(
            "Não foi possível preservar %s (%s); gravações foram bloqueadas",
            path.name,
            type(exc).__name__,
        )
        return None
    _unsafe_to_replace.discard(key)
    logger.warning(
        "Arquivo %s inválido (%s); cópia preservada em %s",
        path.name,
        reason,
        backup.name,
    )
    return backup


def may_replace(path):
    """Return false when recovery could not preserve an invalid original."""
    return _path_key(path) not in _unsafe_to_replace


def mark_valid(path):
    """Clear a previous recovery guard after a valid or absent file is observed."""
    _unsafe_to_replace.discard(_path_key(path))


def block_replacement(path, reason):
    """Prevent writes when a read failure leaves the file's contents unknown."""
    _unsafe_to_replace.add(_path_key(path))
    logger.error(
        "Não foi possível ler %s (%s); gravações foram bloqueadas",
        Path(path).name,
        reason,
    )
