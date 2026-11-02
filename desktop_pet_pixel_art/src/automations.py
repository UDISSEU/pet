"""Local allowlisted notebook automations. Recognition never executes actions."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import hashlib
import urllib.parse

from assistant_actions import _normalize
from json_persistence import mark_valid, may_replace, preserve_corrupt_file

DOWNLOADS = Path.home() / "Downloads"
UNDO_PATH = Path.home() / ".config" / "desktop_pet" / "downloads_undo.json"


def _status():
    import psutil
    vm = psutil.virtual_memory()
    usage = psutil.disk_usage(str(Path.home()))
    battery = psutil.sensors_battery()
    boot = datetime.fromtimestamp(psutil.boot_time()).astimezone()
    processes = []
    for proc in psutil.process_iter(("name", "memory_info")):
        try:
            info = proc.info
            processes.append((info.get("memory_info").rss, info.get("name") or "Processo"))
        except (psutil.Error, AttributeError, TypeError):
            continue
    processes.sort(reverse=True)
    cpu = psutil.cpu_percent(interval=0.15)
    battery_percent = None if battery is None else battery.percent
    lines = [f"CPU: {cpu:.0f}%", f"Memória: {vm.percent:.0f}% ({vm.used // (1024**3)} / {vm.total // (1024**3)} GB)", f"Disco: {usage.percent:.0f}% ({usage.used // (1024**3)} / {usage.total // (1024**3)} GB)", f"Ligado desde: {boot:%d/%m %H:%M}", "Bateria: indisponível" if battery is None else f"Bateria: {battery.percent:.0f}%" + (" · carregando" if battery.power_plugged else "")]
    top_processes = [{"name": name, "memory_mb": rss // (1024**2)} for rss, name in processes[:3]]
    lines.extend(f"Processo: {item['name']} · {item['memory_mb']} MB" for item in top_processes)
    return {"title": "Status do notebook", "lines": lines, "status": "ok", "metrics": {"cpu": cpu, "memory": vm.percent, "memory_label": f"{vm.used // (1024**3)} / {vm.total // (1024**3)} GB", "disk": usage.percent, "disk_label": f"{usage.used // (1024**3)} / {usage.total // (1024**3)} GB", "battery": battery_percent, "charging": None if battery is None else battery.power_plugged, "uptime": f"Ligado desde {boot:%H:%M} · {boot:%d/%m}", "processes": top_processes}}


def _extension_group(name):
    suffix = Path(name).suffix.casefold()
    groups = {"Imagens": {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tif", ".tiff"}, "Documentos": {".pdf", ".doc", ".docx", ".odt", ".txt", ".rtf", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".csv", ".md"}, "Vídeos": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".mpeg"}, "Áudio": {".mp3", ".wav", ".ogg", ".m4a", ".flac", ".aac"}, "Compactados": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"}}
    return next((group for group, extensions in groups.items() if suffix in extensions), "Outros")


def _files(downloads):
    requested_root = Path(downloads).expanduser()
    if requested_root.is_symlink():
        raise ValueError("A pasta de trabalho é um link simbólico e não será percorrida.")
    root = requested_root.resolve()
    if not root.is_dir():
        raise FileNotFoundError("A pasta Downloads não foi encontrada.")
    result = []
    for item in root.iterdir():
        if item.name.startswith(".") or item.name.endswith((".part", ".crdownload")) or not item.is_file() or item.is_symlink():
            continue
        resolved = item.resolve()
        if resolved.parent == root:
            result.append((item, _extension_group(item.name)))
    return sorted(result, key=lambda row: row[0].name.casefold())


def preview_downloads(downloads=DOWNLOADS):
    operations = []
    for source, group in _files(downloads):
        target = Path(downloads) / group / source.name
        index = 1
        while target.exists():
            target = target.with_name(f"{source.stem} ({index}){source.suffix}")
            index += 1
        operations.append((source, target))
    return operations


def organize_downloads(downloads=DOWNLOADS, undo_path=UNDO_PATH, plan=None):
    root = Path(downloads).resolve()
    mapping = []
    try:
        operations = preview_downloads(root) if plan is None else plan
        for source, target in operations:
            source, target = Path(source), Path(target)
            if source.parent.resolve() != root or source.is_symlink() or not source.is_file():
                continue
            if target.parent.resolve() != root and root not in target.parent.resolve().parents:
                raise ValueError("Destino fora da pasta Downloads.")
            if target.parent.parent.resolve() != root:
                raise ValueError("Destino inválido para Downloads.")
            target.parent.mkdir(exist_ok=True)
            candidate, index = target, 1
            while candidate.exists():
                candidate = target.with_name(f"{target.stem} ({index}){target.suffix}")
                index += 1
            shutil.move(str(source), str(candidate))
            mapping.append({"source": str(source), "destination": str(candidate)})
    except Exception:
        undo_downloads(undo_path=undo_path, mapping=mapping, downloads=root)
        raise
    path = Path(undo_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            json.loads(path.read_text(encoding="utf-8"))
            mark_valid(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            preserve_corrupt_file(path, type(exc).__name__)
    if not may_replace(path):
        undo_downloads(undo_path=undo_path, mapping=mapping, downloads=root)
        raise OSError("Não foi possível preservar o histórico de desfazer.")
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    return {"title": "Downloads organizados", "lines": [f"{len(mapping)} arquivo(s) movido(s).", "Você pode desfazer pela aba Automações."], "status": "ok", "mapping": mapping}


def undo_downloads(undo_path=UNDO_PATH, mapping=None, downloads=DOWNLOADS):
    path = Path(undo_path)
    loaded_from_disk = mapping is None
    root = Path(downloads).resolve()
    if mapping is None:
        try:
            mapping = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"title": "Nada para desfazer", "lines": ["Ainda não há uma organização para desfazer."], "status": "error"}
    restored = 0
    for item in reversed(mapping):
        src, dst = Path(item["source"]), Path(item["destination"])
        if src.parent.resolve() != root or dst.parent.parent.resolve() != root:
            continue
        if src.is_symlink() or dst.is_symlink():
            continue
        if not dst.exists() or src.exists():
            continue
        src.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(dst), str(src))
        restored += 1
    if loaded_from_disk and path.exists():
        path.unlink()
    return {"title": "Organização desfeita", "lines": [f"{restored} arquivo(s) restaurado(s)."], "status": "ok"}


def _walk_files(root):
    requested_root = Path(root).expanduser()
    if requested_root.is_symlink():
        return
    root = requested_root.resolve()
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(name for name in directories if not name.startswith(".") and not (current_path / name).is_symlink())
        for filename in filenames:
            if filename.startswith(".") or filename.endswith((".part", ".crdownload")):
                continue
            item = current_path / filename
            try:
                if item.is_symlink() or not item.is_file() or item.resolve().parent != current_path.resolve():
                    continue
                yield item
            except OSError:
                continue


def _inside_without_symlinks(root, path):
    root = Path(root).resolve()
    path = Path(path).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return False
    try:
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _format_size(size):
    size = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def _trash_locations():
    home = Path.home().resolve()
    paths = (home / ".local", home / ".local" / "share", home / ".local" / "share" / "Trash")
    for path in paths:
        if path.is_symlink():
            raise ValueError("A pasta da Lixeira contém um link simbólico e não será alterada.")
        try:
            path.resolve().relative_to(home)
        except ValueError as exc:
            raise ValueError("A pasta da Lixeira está fora da pasta pessoal.") from exc
    trash = paths[-1]
    return trash, trash / "files", trash / "info"


def find_large_files(downloads=DOWNLOADS, limit=10):
    files = []
    for path in _walk_files(downloads):
        try:
            files.append((path.stat().st_size, path))
        except OSError:
            continue
    files.sort(key=lambda item: item[0], reverse=True)
    rows = [{"path": str(path), "name": path.name, "size": size} for size, path in files[:limit]]
    lines = [f"{item['name']} · {_format_size(item['size'])}" for item in rows]
    return {"title": "Arquivos grandes em Downloads", "lines": lines or ["Não encontrei arquivos em Downloads."], "status": "ok", "items": rows}


def disk_summary(home=None):
    home = Path(home or Path.home()).resolve()
    folders = []
    for item in home.iterdir():
        if item.is_symlink() or not item.is_dir():
            continue
        size = 0
        for path in _walk_files(item):
            try:
                size += path.stat().st_size
            except OSError:
                continue
        folders.append((size, item.name))
    folders.sort(reverse=True)
    rows = [{"folder": name, "size": size} for size, name in folders[:10]]
    total = sum(size for size, _name in folders)
    lines = [f"{item['folder']} · {_format_size(item['size'])}" for item in rows]
    lines.append(f"Total nas pastas verificadas: {_format_size(total)}")
    return {"title": "Uso de espaço por pasta", "lines": lines, "status": "ok", "items": rows, "total_bytes": total}


def find_duplicates(downloads=DOWNLOADS, limit=10):
    by_size = {}
    for path in _walk_files(downloads):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size:
            by_size.setdefault(size, []).append(path)
    duplicates = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash = {}
        for path in paths:
            digest = hashlib.sha256()
            try:
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(block)
            except OSError:
                continue
            by_hash.setdefault(digest.hexdigest(), []).append(path)
        for matching in by_hash.values():
            if len(matching) > 1:
                matching.sort(key=lambda item: str(item).casefold())
                duplicates.append({"size": size, "paths": [str(item) for item in matching]})
    duplicates.sort(key=lambda item: item["size"] * (len(item["paths"]) - 1), reverse=True)
    chosen = duplicates if limit is None else duplicates[:limit]
    lines = []
    for group in chosen:
        lines.append(f"Grupo · {_format_size(group['size'])} cada")
        lines.extend(f"  {Path(path).relative_to(Path(downloads).resolve())}" for path in group["paths"])
    if not lines:
        lines.append("Não encontrei arquivos duplicados em Downloads.")
    elif limit is not None and len(duplicates) > limit:
        lines.insert(0, f"Mostrando {limit} dos {len(duplicates)} grupos encontrados.")
    reclaimable = sum(group["size"] * (len(group["paths"]) - 1) for group in duplicates)
    lines.append(f"Espaço repetido identificado: {_format_size(reclaimable)}")
    return {"title": "Arquivos duplicados", "lines": lines[:31], "status": "ok", "groups": chosen, "reclaimable_bytes": reclaimable}


def preview_duplicate_removals(downloads=DOWNLOADS):
    root = Path(downloads).expanduser()
    if root.is_symlink():
        raise ValueError("A pasta Downloads é um link simbólico e não será percorrida.")
    root = root.resolve()
    result = find_duplicates(root, limit=None)
    operations = []
    for group in result["groups"]:
        # Keep the first path in deterministic alphabetical order; send copies to Trash.
        for duplicate in group["paths"][1:]:
            operations.append((Path(duplicate), "Mover para a Lixeira · duplicado"))
    return operations


def move_duplicates_to_trash(plan=None, downloads=DOWNLOADS):
    root = Path(downloads).expanduser()
    if root.is_symlink():
        raise ValueError("A pasta Downloads é um link simbólico e não será percorrida.")
    root = root.resolve()
    trash, files, info_dir = _trash_locations()
    if files.is_symlink() or info_dir.is_symlink():
        raise ValueError("A pasta da Lixeira contém um link simbólico e não será alterada.")
    files.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    operations = preview_duplicate_removals(root) if plan is None else plan
    moved = 0
    for source, _label in operations:
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            continue
        if not _inside_without_symlinks(root, source):
            continue
        target = files / source.name
        index = 1
        while target.exists() or target.is_symlink() or (info_dir / f"{target.name}.trashinfo").exists():
            target = files / f"{source.stem} ({index}){source.suffix}"
            index += 1
        trash_info = info_dir / f"{target.name}.trashinfo"
        encoded_path = urllib.parse.quote(str(source.resolve()), safe="/")
        deleted = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S")
        trash_info.write_text(f"[Trash Info]\nPath={encoded_path}\nDeletionDate={deleted}\n", encoding="utf-8")
        try:
            shutil.move(str(source), str(target))
        except Exception:
            trash_info.unlink(missing_ok=True)
            raise
        moved += 1
    return {"title": "Cópias movidas para a Lixeira", "lines": [f"{moved} cópia(s) foram movidas para a Lixeira.", "Você pode restaurá-las pelo gerenciador de arquivos."], "status": "ok"}


def preview_screenshots(downloads=DOWNLOADS):
    root = Path(downloads).resolve()
    prefixes = ("screenshot", "captura de tela", "captura de ecran", "captura_de_tela", "screenshot from")
    images = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
    operations = []
    for source, _group in _files(root):
        normalized = _normalize(source.stem).replace("_", " ")
        if source.suffix.casefold() not in images or not normalized.startswith(prefixes):
            continue
        directory = root / "Capturas de tela"
        target = directory / source.name
        index = 1
        while target.exists():
            target = directory / f"{source.stem} ({index}){source.suffix}"
            index += 1
        operations.append((source, target))
    return operations


def organize_screenshots(plan=None, downloads=DOWNLOADS, undo_path=UNDO_PATH):
    operations = preview_screenshots(downloads) if plan is None else plan
    result = organize_downloads(downloads, undo_path, operations)
    result.update(title="Capturas de tela organizadas", lines=[f"{len(result.get('mapping', []))} captura(s) movida(s).", "Você pode desfazer pela aba Automações."])
    return result


def preview_empty_trash():
    _trash, files, _info = _trash_locations()
    if files.is_symlink():
        raise ValueError("A pasta da Lixeira é um link simbólico e não será alterada.")
    if not files.is_dir():
        return []
    operations = []
    for item in sorted(files.iterdir(), key=lambda path: path.name.casefold()):
        size = 0
        if item.is_dir() and not item.is_symlink():
            size = _tree_size(item)
        elif item.is_file() or item.is_symlink():
            try:
                size = item.lstat().st_size
            except OSError:
                continue
        else:
            continue
        operations.append((item, f"apagar definitivamente · {_format_size(size)}"))
    return operations


def _remove_trash_item(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        for child in path.iterdir():
            _remove_trash_item(child)
        path.rmdir()


def _tree_size(root):
    total = 0
    for current, directories, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        directories[:] = [name for name in directories if not (base / name).is_symlink()]
        for name in filenames:
            path = base / name
            try:
                total += path.lstat().st_size
            except OSError:
                continue
    return total


def empty_trash(plan=None):
    trash, files_path, info_dir = _trash_locations()
    if files_path.is_symlink():
        raise ValueError("A pasta da Lixeira é um link simbólico e não será alterada.")
    files = files_path.resolve()
    operations = preview_empty_trash() if plan is None else plan
    removed = 0
    for source, _label in operations:
        source = Path(source)
        if source.parent.resolve() != files:
            continue
        _remove_trash_item(source)
        if info_dir.is_dir() and not info_dir.is_symlink():
            info = info_dir / f"{source.name}.trashinfo"
            try:
                info.unlink()
            except FileNotFoundError:
                pass
        removed += 1
    return {"title": "Lixeira esvaziada", "lines": [f"{removed} item(ns) removido(s) definitivamente."], "status": "ok"}


def _battery_reading():
    import psutil
    battery = psutil.sensors_battery()
    return {"title": "Leitura da bateria", "lines": ["Sem bateria detectada." if battery is None else f"Bateria em {battery.percent:.0f}%"], "status": "ok", "percent": None if battery is None else battery.percent, "charging": None if battery is None else battery.power_plugged}


def _pause_reminder_info():
    return {"title": "Lembrete de pausa", "lines": ["O lembrete periódico é controlado pela rotina de pausas."], "status": "ok"}


AUTOMATIONS = (
    {"id": "laptop_status", "name": "Status do notebook", "description": "CPU, memória, disco, bateria e processos.", "phrases": ("como esta meu notebook", "status do notebook", "como esta o computador", "status do computador"), "read_only": True, "confirmation": False, "executor": _status},
    {"id": "organize_downloads", "name": "Organizar Downloads", "description": "Agrupa arquivos por tipo e permite desfazer.", "phrases": ("organizar downloads", "organiza downloads", "organize downloads", "organizar pasta downloads"), "read_only": False, "confirmation": True, "executor": organize_downloads},
    {"id": "undo_downloads", "name": "Desfazer organização", "description": "Restaura a última organização de Downloads.", "phrases": (), "read_only": False, "confirmation": False, "executor": undo_downloads},
    {"id": "large_files", "name": "Encontrar arquivos grandes", "description": "Lista os maiores arquivos de Downloads, sem alterar nada.", "phrases": ("encontrar arquivos grandes", "arquivos grandes em downloads", "mostrar arquivos grandes"), "read_only": True, "confirmation": False, "executor": find_large_files},
    {"id": "duplicates", "name": "Procurar arquivos duplicados", "description": "Compara o conteúdo em Downloads e estima o espaço repetido.", "phrases": ("procurar arquivos duplicados", "buscar arquivos duplicados", "arquivos duplicados em downloads"), "read_only": True, "confirmation": False, "executor": find_duplicates},
    {"id": "trash_duplicates", "name": "Mover duplicados para a Lixeira", "description": "Revise as cópias detectadas e confirme antes de movê-las à Lixeira.", "phrases": (), "read_only": False, "confirmation": True, "executor": move_duplicates_to_trash},
    {"id": "disk_summary", "name": "Resumo de espaço", "description": "Mostra o espaço usado pelas pastas principais da sua pasta pessoal.", "phrases": ("resumo de espaco", "uso de espaco por pasta", "quanto espaco estou usando"), "read_only": True, "confirmation": False, "executor": disk_summary},
    {"id": "empty_trash", "name": "Esvaziar a Lixeira", "description": "Revise os itens e confirme antes da remoção definitiva.", "phrases": ("esvaziar lixeira", "esvaziar a lixeira", "esvazia a lixeira", "limpar lixeira"), "read_only": False, "confirmation": True, "executor": empty_trash},
    {"id": "organize_screenshots", "name": "Organizar capturas de tela", "description": "Agrupa capturas encontradas em Downloads; pode desfazer.", "phrases": ("organizar capturas de tela", "organizar screenshots", "organiza capturas de tela"), "read_only": False, "confirmation": True, "executor": organize_screenshots},
    {"id": "pause_reminder", "name": "Lembrete de pausa", "description": "Sugere uma pausa quando você passa um tempo trabalhando.", "phrases": (), "read_only": True, "confirmation": False, "periodic": True, "executor": _pause_reminder_info},
    {"id": "low_battery_alert", "name": "Aviso de bateria baixa", "description": "Avisa quando a bateria chega a 20% ou menos.", "phrases": (), "read_only": True, "confirmation": False, "periodic": True, "executor": _battery_reading},
)


def recognize_automation(text):
    normalized = _normalize(text).strip(" .!?;:,\t\n")
    for automation in AUTOMATIONS:
        if normalized in {_normalize(phrase) for phrase in automation["phrases"]}:
            return automation
    return None
