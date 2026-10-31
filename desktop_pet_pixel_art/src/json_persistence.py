"""Small safeguards shared by the user's JSON stores."""

import logging
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)
_unsafe_to_replace = set()


def _path_key(path):
    return str(Path(path).expanduser().resolve())


def preserve_corrupt_file(path, reason):
    """Copy a file before recovering from invalid JSON; never overwrite a backup."""
    path = Path(path)
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
