"""Read and safely override Linux XDG autostart desktop entries."""

import configparser
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime
from pathlib import Path


def _enabled(parser):
    entry = parser["Desktop Entry"]
    try:
        if entry.getboolean("Hidden", fallback=False):
            return False
        if not entry.getboolean("X-GNOME-Autostart-enabled", fallback=True):
            return False
    except ValueError:
        return False
    return True


def _parse_entry(path, source):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
        entry = parser["Desktop Entry"]
        name = entry.get("Name", path.stem).strip() or path.stem
        description = entry.get("Comment", "").strip()
        command = entry.get("Exec", "").strip()
        error = "" if command else "A entrada não contém um comando Exec."
        state = "Habilitado" if _enabled(parser) else "Desabilitado"
    except (OSError, UnicodeError, configparser.Error, KeyError, ValueError) as exc:
        name, description, command = path.stem, "", ""
        error = f"Arquivo inválido ou inacessível ({type(exc).__name__})."
        state = "Desabilitado"
    return {
        "name": name, "description": description, "command": command,
        "path": str(path), "source": source, "state": state,
        "kind": "Usuário" if source == "user" else "Sistema",
        "error": error,
    }


def discover_startup_entries(user_dir=None, system_dirs=None):
    """Return effective user/system entries, preferring user overrides by name."""
    user_dir = Path(user_dir or Path.home() / ".config" / "autostart")
    system_dirs = tuple(Path(item) for item in (
        system_dirs if system_dirs is not None else ("/etc/xdg/autostart",)
    ))
    entries = {}
    for directory in system_dirs:
        try:
            candidates = sorted(directory.glob("*.desktop"))
        except OSError:
            continue
        for path in candidates:
            if path.is_symlink() or not path.is_file():
                continue
            entries.setdefault(path.name, _parse_entry(path, "system"))
    try:
        candidates = sorted(user_dir.glob("*.desktop"))
    except OSError:
        candidates = []
    for path in candidates:
        if path.is_symlink() or not path.is_file():
            continue
        entries[path.name] = _parse_entry(path, "user")
    return sorted(entries.values(), key=lambda item: item["name"].casefold())


def _set_desktop_boolean(text, key, value):
    """Set one Desktop Entry boolean while preserving unrelated file contents."""
    lines = text.splitlines(keepends=True)
    section_start = next(
        (index for index, line in enumerate(lines)
         if line.strip() == "[Desktop Entry]"), None,
    )
    if section_start is None:
        raise ValueError("O arquivo não contém a seção [Desktop Entry].")
    section_end = next(
        (index for index in range(section_start + 1, len(lines))
         if lines[index].lstrip().startswith("[")), len(lines),
    )
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*(?:\r?\n)?$")
    matches = [index for index in range(section_start + 1, section_end)
               if pattern.match(lines[index])]
    replacement = f"{key}={'true' if value else 'false'}\n"
    if matches:
        lines[matches[0]] = replacement
        for index in reversed(matches[1:]):
            del lines[index]
    else:
        lines.insert(section_end, replacement)
    return "".join(lines)


def set_startup_enabled(entry, enabled, *, user_dir=None, system_dirs=None):
    """Create/update a current-user autostart entry and keep a dated backup."""
    if type(enabled) is not bool:
        raise ValueError("O estado de inicialização deve ser booleano.")
    user_dir = Path(user_dir or Path.home() / ".config" / "autostart")
    system_dirs = tuple(Path(item) for item in (
        system_dirs if system_dirs is not None else ("/etc/xdg/autostart",)
    ))
    name = Path(str(entry.get("path", ""))).name
    if not name.endswith(".desktop") or name in (".desktop", ""):
        raise ValueError("Nome de entrada de inicialização inválido.")

    home = Path.home().resolve()
    config_dir = home / ".config"
    if config_dir.exists() and config_dir.is_symlink():
        raise OSError("O diretório ~/.config é um link simbólico; alteração recusada.")
    if user_dir.exists() and user_dir.is_symlink():
        raise OSError("O diretório autostart é um link simbólico; alteração recusada.")
    user_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    user_dir = user_dir.resolve()
    expected_dir = (home / ".config" / "autostart").resolve()
    if user_dir != expected_dir:
        raise ValueError("O destino precisa ser o autostart do usuário atual.")

    current_entries = discover_startup_entries(
        user_dir=user_dir, system_dirs=system_dirs,
    )
    current = next((item for item in current_entries
                    if Path(item["path"]).name == name), None)
    if current is None:
        raise FileNotFoundError("A entrada de inicialização não está mais disponível.")
    source_path = Path(current["path"])
    target = user_dir / name
    if source_path == target and target.is_symlink():
        raise OSError("Links simbólicos de inicialização não podem ser alterados.")

    original = target if target.exists() else source_path
    if original.is_symlink() or not original.is_file():
        raise OSError("O arquivo de configuração não é um arquivo regular.")
    text = original.read_text(encoding="utf-8")
    text = _set_desktop_boolean(text, "Hidden", not enabled)
    text = _set_desktop_boolean(text, "X-GNOME-Autostart-enabled", enabled)

    backup_path = None
    if target.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = target.with_name(f"{target.name}.backup-{stamp}")
        shutil.copy2(target, backup_path, follow_symlinks=False)
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else 0o600
    fd, temporary_name = tempfile.mkstemp(prefix=".autostart-", dir=user_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temporary:
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        if backup_path and not target.exists():
            shutil.copy2(backup_path, target)
        raise
    return {"path": str(target), "backup": str(backup_path) if backup_path else ""}
