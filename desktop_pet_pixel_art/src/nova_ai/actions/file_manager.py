"""Busca e organização reversível de arquivos, restritas a Downloads."""

import ctypes
import errno
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat

from .base import Tool
from .results import ActionResult
from .action_validator import DirectoryAccessPolicy


_GROUPS = {
    "Imagens": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"},
    "Documentos": {".pdf", ".doc", ".docx", ".odt", ".txt", ".rtf", ".xls", ".xlsx", ".csv", ".md"},
    "Vídeos": {".mp4", ".mkv", ".mov", ".avi", ".webm"},
    "Áudio": {".mp3", ".wav", ".ogg", ".m4a", ".flac"},
    "Compactados": {".zip", ".rar", ".7z", ".tar", ".gz"},
}
_PLAN_KEY = secrets.token_bytes(32)
_DIRECTORY_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_RENAME_NOREPLACE = 1


def _rename_noreplace(source_fd, source_name, destination_fd, destination_name):
    """Linux renameat2, pinned to directory descriptors and never overwriting."""
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise OSError(errno.ENOTSUP, "renameat2 não está disponível")
    renameat2.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                          ctypes.c_char_p, ctypes.c_uint)
    renameat2.restype = ctypes.c_int
    result = renameat2(source_fd, os.fsencode(source_name), destination_fd,
                       os.fsencode(destination_name), _RENAME_NOREPLACE)
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), destination_name)


def _open_absolute_directory(path):
    """Open every path component with O_NOFOLLOW; caller owns returned fd."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Caminho de diretório malformado")
    current_fd = os.open("/", _DIRECTORY_FLAGS)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, _DIRECTORY_FLAGS, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except Exception:
        os.close(current_fd)
        raise


def _downloads_root():
    path = Path.home() / "Downloads"
    fd = _open_absolute_directory(path)
    os.close(fd)
    return path


def _group_name(name):
    suffix = Path(name).suffix.casefold()
    return next((group for group, endings in _GROUPS.items() if suffix in endings), "Outros")


def _stat_at(directory_fd, name):
    try:
        return os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _regular_file_at(directory_fd, name):
    info = _stat_at(directory_fd, name)
    return info if info is not None and stat.S_ISREG(info.st_mode) else None


def _identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def _signature(kind, *values):
    payload = json.dumps([kind, *values], ensure_ascii=False, separators=(",", ":"))
    return hmac.new(_PLAN_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _valid_signature(token, kind, *values):
    return (isinstance(token, str) and len(token) == 64
            and hmac.compare_digest(token, _signature(kind, *values)))


def _validate_relative_name(name):
    if (not isinstance(name, str) or not name or name in {".", ".."}
            or "/" in name or "\x00" in name or name.startswith(".")):
        raise ValueError("Nome de arquivo inválido")


def _validate_absolute_child(value, root, *, category=None):
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("Caminho malformado")
    if os.path.normpath(value) != value:
        raise ValueError("Caminho não canônico")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("Caminho absoluto obrigatório")
    _validate_relative_name(path.name)
    if category is None:
        if path.parent != root:
            raise ValueError("Origem fora da raiz Downloads")
    elif path.parent != root / category:
        raise ValueError("Destino fora da categoria autorizada")
    return path.name


def _open_category(root_fd, category, *, create=False):
    try:
        info = os.stat(category, dir_fd=root_fd, follow_symlinks=False)
    except FileNotFoundError:
        if not create:
            return None
        os.mkdir(category, mode=0o700, dir_fd=root_fd)
        info = os.stat(category, dir_fd=root_fd, follow_symlinks=False)
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Diretório de categoria é link simbólico ou não é diretório")
    return os.open(category, _DIRECTORY_FLAGS, dir_fd=root_fd)


def _choose_destination(root_fd, category, source_name, reserved):
    category_fd = _open_category(root_fd, category)
    try:
        stem, suffix = os.path.splitext(source_name)
        index = 0
        while True:
            name = source_name if index == 0 else f"{stem} ({index}){suffix}"
            if (category, name) not in reserved and (
                    category_fd is None or _stat_at(category_fd, name) is None):
                reserved.add((category, name))
                return name
            index += 1
    finally:
        if category_fd is not None:
            os.close(category_fd)


class FileSearchTool(Tool):
    name = "files.search"
    description = "Localiza arquivos por nome dentro de um diretório autorizado."

    def __init__(self, directory_policy=None, *, plugin_id="nova.core"):
        self.directory_policy = directory_policy or DirectoryAccessPolicy()
        self.plugin_id = plugin_id

    def execute(self, arguments):
        return self._search(arguments, None)

    def execute_with_context(self, arguments, context):
        return self._search(arguments, context)

    def _search(self, arguments, context):
        if not isinstance(arguments, dict) or set(arguments) - {"root", "query", "limit"}:
            raise ValueError("Argumentos de busca desconhecidos")
        root_arg, query = arguments.get("root", str(Path.home() / "Downloads")), arguments.get("query", "")
        limit = arguments.get("limit", 40)
        if not isinstance(root_arg, str) or not isinstance(query, str) or not query.strip():
            raise ValueError("Informe diretório e texto de busca")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit deve estar entre 1 e 100")
        requested = Path(root_arg).expanduser()
        root = self.directory_policy.require(self.plugin_id, requested)
        root_fd = _open_absolute_directory(root)
        matches, visited = [], 0
        try:
            root_path = Path(f"/proc/self/fd/{root_fd}")
            for current, dirs, filenames in os.walk(root_path, followlinks=False):
                if context is not None:
                    context.checkpoint()
                depth = len(Path(current).relative_to(root_path).parts)
                if depth >= 6:
                    dirs[:] = []
                dirs[:] = [d for d in dirs if not d.startswith(".")
                           and not (Path(current) / d).is_symlink()]
                visited += len(dirs)
                for filename in filenames:
                    if context is not None:
                        context.checkpoint()
                    visited += 1
                    if visited > 5_000:
                        break
                    info = os.stat(Path(current) / filename, follow_symlinks=False)
                    if (query.casefold() in filename.casefold() and stat.S_ISREG(info.st_mode)):
                        matches.append(str(root / Path(current).relative_to(root_path) / filename))
                        if len(matches) >= limit:
                            break
                if visited > 5_000 or len(matches) >= limit:
                    break
        finally:
            os.close(root_fd)
        return ActionResult(True, f"{len(matches)} arquivo(s) localizado(s).", {"files": matches})


class DirectoryListTool(Tool):
    name = "files.list_directory"
    description = "Lista conteúdo básico de um diretório autorizado, sem ler arquivos."

    def __init__(self, directory_policy=None, *, plugin_id="nova.core"):
        self.directory_policy = directory_policy or DirectoryAccessPolicy()
        self.plugin_id = plugin_id

    def execute(self, arguments):
        return self._list(arguments, None)

    def execute_with_context(self, arguments, context):
        return self._list(arguments, context)

    def _list(self, arguments, context):
        if not isinstance(arguments, dict) or set(arguments) - {"directory", "limit"}:
            raise ValueError("Argumentos de listagem desconhecidos")
        directory, limit = arguments.get("directory"), arguments.get("limit", 100)
        if not isinstance(directory, str) or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Diretório ou limite inválido")
        path = self.directory_policy.require(self.plugin_id, Path(directory).expanduser())
        directory_fd = _open_absolute_directory(path)
        entries = []
        try:
            for index, name in enumerate(os.listdir(directory_fd)):
                if context is not None:
                    context.checkpoint()
                if index >= 10_000:
                    break
                info = _stat_at(directory_fd, name)
                if info is None or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                    continue
                entries.append({"name": name, "type": "directory" if stat.S_ISDIR(info.st_mode) else "file"})
                if len(entries) >= limit:
                    break
        finally:
            os.close(directory_fd)
        return ActionResult(True, f"{len(entries)} item(ns) listado(s).", {
            "directory": str(path), "entries": entries,
        })


class FileOrganizerPreviewTool(Tool):
    name = "files.preview_downloads"
    description = "Mostra uma prévia sem mover arquivos."

    def execute(self, arguments):
        return self._preview(arguments, None)

    def execute_with_context(self, arguments, context):
        return self._preview(arguments, context)

    def _preview(self, arguments, context):
        allowed = ({}, {"path": "~/Downloads"}, {"path": str(Path.home() / "Downloads")})
        if arguments not in allowed:
            raise ValueError("A prévia é restrita à pasta padrão Downloads")
        root = _downloads_root()
        root_fd = _open_absolute_directory(root)
        plan, reserved, count, has_more = [], set(), 0, False
        try:
            for source_name in os.listdir(root_fd):
                if context is not None:
                    context.checkpoint()
                info = _regular_file_at(root_fd, source_name)
                if (info is None or source_name.startswith(".")
                        or source_name.endswith((".part", ".crdownload"))):
                    continue
                if count >= 500:
                    has_more = True
                    break
                category = _group_name(source_name)
                destination_name = _choose_destination(root_fd, category, source_name, reserved)
                identity = _identity(info)
                source = str(root / source_name)
                destination = str(root / category / destination_name)
                token = _signature("plan", str(root), source_name, category, destination_name, identity)
                plan.append({"source": source, "destination": destination, "token": token})
                count += 1
        finally:
            os.close(root_fd)
        summary = (
            "A prévia foi limitada a 500 arquivos; a organização completa foi bloqueada."
            if has_more else f"Prévia: {len(plan)} arquivo(s) seriam movidos."
        )
        return ActionResult(not has_more, summary,
                            {"root": str(root), "plan": plan, "limit_reached": has_more})


class FileOrganizerTool(Tool):
    name = "files.organize_downloads"
    description = "Move arquivos por tipo; cada movimentação pode ser desfeita."

    def execute(self, arguments):
        return self._organize(arguments, None)

    def execute_with_context(self, arguments, context):
        return self._organize(arguments, context)

    def _organize(self, arguments, context):
        if not isinstance(arguments, dict) or set(arguments) != {"plan"}:
            raise ValueError("Argumentos de organização inválidos")
        plan = arguments["plan"]
        root = _downloads_root()
        if not isinstance(plan, list) or len(plan) > 500:
            raise ValueError("Plano de organização inválido")
        root_fd = _open_absolute_directory(root)
        categories, validated, sources, destinations = {}, [], set(), set()
        try:
            for row in plan:
                if not isinstance(row, dict) or set(row) != {"source", "destination", "token"}:
                    raise ValueError("Item de plano inválido")
                source_name = _validate_absolute_child(row["source"], root)
                category = _group_name(source_name)
                destination_name = _validate_absolute_child(row["destination"], root, category=category)
                info = _regular_file_at(root_fd, source_name)
                if info is None or not _valid_signature(
                        row["token"], "plan", str(root), source_name, category,
                        destination_name, _identity(info)):
                    raise ValueError("Origem foi alterada desde a prévia")
                if source_name in sources or (category, destination_name) in destinations:
                    raise ValueError("Plano contém caminhos repetidos")
                cat_fd = categories.get(category)
                if category not in categories:
                    cat_fd = _open_category(root_fd, category)
                    categories[category] = cat_fd
                if cat_fd is not None and _stat_at(cat_fd, destination_name) is not None:
                    raise FileExistsError("O destino já existe")
                sources.add(source_name)
                destinations.add((category, destination_name))
                validated.append((source_name, category, destination_name, info))

            moved = []
            try:
                for source_name, category, destination_name, original_info in validated:
                    if context is not None:
                        context.checkpoint()
                    current_info = _regular_file_at(root_fd, source_name)
                    if current_info is None or _identity(current_info) != _identity(original_info):
                        raise ValueError("Arquivo de origem mudou durante a organização")
                    cat_fd = categories[category]
                    if cat_fd is None:
                        cat_fd = _open_category(root_fd, category, create=True)
                        categories[category] = cat_fd
                    if _stat_at(cat_fd, destination_name) is not None:
                        raise FileExistsError("Destino ocupado; nenhum arquivo será sobrescrito")
                    _rename_noreplace(root_fd, source_name, cat_fd, destination_name)
                    moved.append((source_name, category, destination_name))
                    placed = _regular_file_at(cat_fd, destination_name)
                    if placed is None or _identity(placed) != _identity(original_info):
                        raise ValueError("Arquivo de origem mudou durante a movimentação")
            except Exception:
                rollback_errors = []
                for source_name, category, destination_name in reversed(moved):
                    try:
                        _rename_noreplace(categories[category], destination_name, root_fd, source_name)
                    except OSError as rollback_error:
                        rollback_errors.append(rollback_error)
                if rollback_errors:
                    raise RuntimeError("Falha ao organizar e ao restaurar um ou mais arquivos") from rollback_errors[0]
                raise

            mapping = []
            for source_name, category, destination_name in moved:
                info = _regular_file_at(categories[category], destination_name)
                token = _signature("undo", str(root), source_name, category,
                                   destination_name, _identity(info))
                mapping.append({"source": str(root / source_name),
                                "destination": str(root / category / destination_name),
                                "token": token})
        finally:
            for descriptor in categories.values():
                if descriptor is not None:
                    os.close(descriptor)
            os.close(root_fd)
        return ActionResult(True, f"{len(mapping)} arquivo(s) organizado(s).",
                            {"undo_mapping": mapping})


class UndoFileOrganizationTool(Tool):
    name = "files.organize.undo"
    description = "Restaura arquivos movidos pela organização aprovada."

    def execute(self, arguments):
        return self._undo(arguments, None)

    def execute_with_context(self, arguments, context):
        return self._undo(arguments, context)

    def _undo(self, arguments, context):
        if not isinstance(arguments, dict) or set(arguments) != {"undo_mapping"}:
            raise ValueError("Argumentos de restauração inválidos")
        mapping = arguments["undo_mapping"]
        root = _downloads_root()
        if not isinstance(mapping, list) or len(mapping) > 500:
            raise ValueError("Dados de restauração inválidos")
        root_fd = _open_absolute_directory(root)
        categories, validated, sources, destinations = {}, [], set(), set()
        try:
            for row in reversed(mapping):
                if not isinstance(row, dict) or set(row) != {"source", "destination", "token"}:
                    raise ValueError("Item de restauração inválido")
                source_name = _validate_absolute_child(row["source"], root)
                category = _group_name(source_name)
                destination_name = _validate_absolute_child(row["destination"], root, category=category)
                stem, suffix = os.path.splitext(source_name)
                if destination_name != source_name:
                    prefix, marker = f"{stem} (", f"){suffix}"
                    if (not destination_name.startswith(prefix) or not destination_name.endswith(marker)
                            or not destination_name[len(prefix):-len(marker) or None].isdigit()):
                        raise ValueError("Destino não corresponde ao arquivo original")
                cat_fd = categories.get(category)
                if category not in categories:
                    cat_fd = _open_category(root_fd, category)
                    categories[category] = cat_fd
                if cat_fd is None:
                    raise ValueError("Categoria de restauração ausente")
                info = _regular_file_at(cat_fd, destination_name)
                if (info is None or _stat_at(root_fd, source_name) is not None
                        or not _valid_signature(row["token"], "undo", str(root), source_name,
                                                category, destination_name, _identity(info))):
                    raise ValueError("Restauração adulterada, alterada ou em conflito")
                if source_name in sources or (category, destination_name) in destinations:
                    raise ValueError("Restauração contém caminhos repetidos")
                sources.add(source_name)
                destinations.add((category, destination_name))
                validated.append((source_name, category, destination_name, info))

            restored = []
            try:
                for source_name, category, destination_name, original_info in validated:
                    if context is not None:
                        context.checkpoint()
                    current = _regular_file_at(categories[category], destination_name)
                    if (current is None or _identity(current) != _identity(original_info)
                            or _stat_at(root_fd, source_name) is not None):
                        raise ValueError("Arquivo mudou durante a restauração")
                    _rename_noreplace(categories[category], destination_name, root_fd, source_name)
                    restored.append((source_name, category, destination_name))
                    placed = _regular_file_at(root_fd, source_name)
                    if placed is None or _identity(placed) != _identity(original_info):
                        raise ValueError("Arquivo mudou durante a restauração")
            except Exception:
                rollback_errors = []
                for source_name, category, destination_name in reversed(restored):
                    try:
                        _rename_noreplace(root_fd, source_name, categories[category], destination_name)
                    except OSError as rollback_error:
                        rollback_errors.append(rollback_error)
                if rollback_errors:
                    raise RuntimeError("Falha ao restaurar e ao reverter um ou mais arquivos") from rollback_errors[0]
                raise
        finally:
            for descriptor in categories.values():
                if descriptor is not None:
                    os.close(descriptor)
            os.close(root_fd)
        return ActionResult(True, f"{len(restored)} arquivo(s) restaurado(s).",
                            {"restored": [str(root / item[0]) for item in restored]})
