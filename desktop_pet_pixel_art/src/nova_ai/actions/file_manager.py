"""Busca e organização reversível de arquivos, restritas à pasta Downloads."""

from pathlib import Path
import os
import shutil

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


def _downloads_root():
    path = Path.home() / "Downloads"
    if path.is_symlink():
        raise ValueError("Downloads não pode ser link simbólico")
    return path.resolve()


def _group(path):
    suffix = path.suffix.casefold()
    return next((name for name, endings in _GROUPS.items() if suffix in endings), "Outros")


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
        if set(arguments) - {"root", "query", "limit"}:
            raise ValueError("Argumentos de busca desconhecidos")
        root_arg = arguments.get("root", str(Path.home() / "Downloads"))
        query = arguments.get("query", "")
        limit = arguments.get("limit", 40)
        if not isinstance(root_arg, str) or not isinstance(query, str) or not query.strip():
            raise ValueError("Informe diretório e texto de busca")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit deve estar entre 1 e 100")
        requested = Path(root_arg).expanduser()
        if self.directory_policy.has_symlink_component(requested) or not requested.is_dir():
            raise ValueError("Diretório inexistente ou link simbólico")
        self.directory_policy.require(self.plugin_id, requested)
        root = requested.resolve()
        needle = query.casefold()
        matches, visited = [], 0
        for current, dirs, filenames in os.walk(root, followlinks=False):
            if context is not None:
                context.checkpoint()
            depth = len(Path(current).relative_to(root).parts)
            if depth >= 6:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith(".")
                       and not (Path(current) / d).is_symlink()]
            visited += len(dirs)
            for filename in filenames:
                if context is not None:
                    context.checkpoint()
                visited += 1
                path = Path(current) / filename
                if visited > 5_000:
                    break
                if needle in filename.casefold() and not path.is_symlink() and path.is_file():
                    matches.append(str(path))
                    if len(matches) >= limit:
                        break
            if visited > 5_000 or len(matches) >= limit:
                break
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
        if set(arguments) - {"directory", "limit"}:
            raise ValueError("Argumentos de listagem desconhecidos")
        directory = arguments.get("directory")
        limit = arguments.get("limit", 100)
        if not isinstance(directory, str) or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Diretório ou limite inválido")
        path = Path(directory).expanduser()
        if self.directory_policy.has_symlink_component(path) or not path.is_dir():
            raise ValueError("Diretório inexistente ou link simbólico")
        path = self.directory_policy.require(self.plugin_id, path)
        entries = []
        for index, item in enumerate(path.iterdir()):
            if context is not None:
                context.checkpoint()
            if index >= 10_000:
                break
            if item.is_symlink():
                continue
            entries.append({"name": item.name, "type": "directory" if item.is_dir() else "file"})
            if len(entries) >= limit:
                break
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
        allowed = ({}, {"path": "~/Downloads"},
                   {"path": str(Path.home() / "Downloads")})
        if arguments not in allowed:
            raise ValueError("A prévia é restrita à pasta padrão Downloads")
        root = _downloads_root()
        if not root.is_dir():
            raise FileNotFoundError("A pasta Downloads não foi encontrada")
        sources = []
        for source in root.iterdir():
            if context is not None:
                context.checkpoint()
            if (source.is_symlink() or not source.is_file() or source.name.startswith(".")
                    or source.name.endswith((".part", ".crdownload"))):
                continue
            sources.append(source)
            if len(sources) >= 500:
                break
        plan = []
        for source in sorted(sources, key=lambda item: item.name.casefold()):
            if context is not None:
                context.checkpoint()
            folder = _group(source)
            target = root / folder / source.name
            index = 1
            while target.exists():
                target = target.with_name(f"{source.stem} ({index}){source.suffix}")
                index += 1
            plan.append({"source": str(source), "destination": str(target)})
        return ActionResult(True, f"Prévia: {len(plan)} arquivo(s) seriam movidos.",
                            {"root": str(root), "plan": plan,
                             "limit_reached": len(plan) >= 500})


class FileOrganizerTool(Tool):
    name = "files.organize_downloads"
    description = "Move arquivos por tipo; cada movimentação pode ser desfeita."

    def execute(self, arguments):
        return self._organize(arguments, None)

    def execute_with_context(self, arguments, context):
        return self._organize(arguments, context)

    def _organize(self, arguments, context):
        root = _downloads_root()
        plan = arguments.get("plan")
        if not isinstance(plan, list) or len(plan) > 500:
            raise ValueError("Plano de organização inválido")
        validated = []
        for row in plan:
            if not isinstance(row, dict) or set(row) != {"source", "destination"}:
                raise ValueError("Item de plano inválido")
            source, destination = Path(row["source"]), Path(row["destination"])
            category = _group(source)
            expected = root / category / source.name
            suffix_index = 1
            while expected.exists() and expected != destination:
                expected = (root / category /
                            f"{source.stem} ({suffix_index}){source.suffix}")
                suffix_index += 1
            if (source.parent.resolve() != root or source.is_symlink() or not source.is_file()
                    or destination.parent.parent.resolve() != root
                    or destination.parent.name != category or destination != expected
                    or destination.exists() or destination.is_symlink()):
                raise ValueError("Plano contém caminho inseguro ou conflito")
            validated.append((source, destination))
        moved = []
        try:
            for source, destination in validated:
                if context is not None:
                    context.checkpoint()
                destination.parent.mkdir(exist_ok=True)
                if destination.exists() or source.is_symlink() or not source.is_file():
                    raise FileExistsError("Arquivo mudou desde a prévia")
                shutil.move(str(source), str(destination))
                moved.append({"source": str(source), "destination": str(destination)})
        except Exception:
            for item in reversed(moved):
                src, dst = Path(item["source"]), Path(item["destination"])
                if dst.is_file() and not src.exists():
                    shutil.move(str(dst), str(src))
            raise
        return ActionResult(True, f"{len(moved)} arquivo(s) organizado(s).",
                            {"undo_mapping": moved})


class UndoFileOrganizationTool(Tool):
    name = "files.organize.undo"
    description = "Restaura arquivos movidos pela organização aprovada."

    def execute(self, arguments):
        return self._undo(arguments, None)

    def execute_with_context(self, arguments, context):
        return self._undo(arguments, context)

    def _undo(self, arguments, context):
        root = _downloads_root()
        mapping = arguments.get("undo_mapping")
        if not isinstance(mapping, list) or len(mapping) > 500:
            raise ValueError("Dados de restauração inválidos")
        validated = []
        for row in reversed(mapping):
            if not isinstance(row, dict) or set(row) != {"source", "destination"}:
                raise ValueError("Item de restauração inválido")
            source, destination = Path(row["source"]), Path(row["destination"])
            if (source.parent.resolve() != root or destination.parent.parent.resolve() != root
                    or source.exists() or source.is_symlink() or destination.is_symlink()
                    or not destination.is_file()):
                raise ValueError("Restauração contém caminho inseguro ou conflito")
            validated.append((source, destination))
        if len({str(src) for src, _ in validated}) != len(validated):
            raise ValueError("Restauração contém origens repetidas")
        if len({str(dst) for _, dst in validated}) != len(validated):
            raise ValueError("Restauração contém destinos repetidos")
        restored = []
        try:
            for source, destination in validated:
                if context is not None:
                    context.checkpoint()
                if source.exists() or not destination.is_file() or destination.is_symlink():
                    raise ValueError("Arquivo mudou durante a restauração")
                shutil.move(str(destination), str(source))
                restored.append(str(source))
        except Exception:
            for source, destination in reversed(validated[:len(restored)]):
                if source.is_file() and not destination.exists():
                    shutil.move(str(source), str(destination))
            raise
        return ActionResult(True, f"{len(restored)} arquivo(s) restaurado(s).",
                            {"restored": restored})
