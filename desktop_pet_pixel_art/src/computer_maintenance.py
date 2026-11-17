"""Bounded SMART, log and cleanup services for the computer center."""

import json
import logging
import os
import re
import shutil
import stat
import subprocess
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class _QueryCancelled(Exception):
    pass


def _run_cancellable_command(args, *, timeout, cancel_event, popen=subprocess.Popen):
    process = popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + timeout
    while True:
        if cancel_event.is_set():
            process.terminate()
            try:
                process.communicate(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise _QueryCancelled
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            process.kill()
            process.communicate()
            raise subprocess.TimeoutExpired(args, timeout)
        try:
            stdout, stderr = process.communicate(timeout=min(0.1, remaining))
            return subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def inspect_disks(*, run=subprocess.run, which=shutil.which, timeout=8,
                  cancel_event=None, popen=subprocess.Popen):
    """Read disk inventory with lsblk and SMART data when smartctl is available."""
    if cancel_event is not None and cancel_event.is_set():
        return {"state": "indisponível", "reason": "Consulta cancelada.",
                "devices": [], "cancelled": True}
    lsblk = which("lsblk")
    if not lsblk:
        return {"state": "indisponível", "reason": "lsblk não está instalado.", "devices": []}
    try:
        args = [lsblk, "--json", "--bytes", "--nodeps", "-o",
                "NAME,PATH,TYPE,SIZE,MODEL,VENDOR,ROTA,TRAN"]
        if cancel_event is None:
            response = run(args, capture_output=True, text=True, timeout=timeout, check=False)
        else:
            response = _run_cancellable_command(
                args, timeout=timeout, cancel_event=cancel_event, popen=popen,
            )
        if response.returncode:
            return {"state": "indisponível", "reason": "Não foi possível listar os dispositivos.", "devices": []}
        raw = json.loads(response.stdout or "{}")
    except _QueryCancelled:
        return {"state": "indisponível", "reason": "Consulta cancelada.",
                "devices": [], "cancelled": True}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {"state": "indisponível", "reason": f"Inventário indisponível ({type(exc).__name__}).", "devices": []}
    smartctl = which("smartctl")
    devices = []
    for item in raw.get("blockdevices", ()):
        if cancel_event is not None and cancel_event.is_set():
            return {"state": "parcial" if devices else "indisponível",
                    "reason": "Consulta cancelada.", "devices": devices,
                    "cancelled": True}
        path = item.get("path")
        if item.get("type") not in ("disk", "rom") or not path or not _valid_block_path(path):
            continue
        device = {"path": path, "name": item.get("name"), "model": item.get("model") or None,
                  "vendor": item.get("vendor") or None, "capacity_bytes": item.get("size"),
                  "transport": item.get("tran"), "rotational": item.get("rota"),
                  "temperature_c": None, "wear": None, "indicators": [],
                  "smart_state": "indisponível", "detail": "SMART não consultado."}
        if not smartctl:
            device["detail"] = "smartctl não está instalado; estado SMART indisponível."
        else:
            try:
                args = [smartctl, "--json", "--all", path]
                if cancel_event is None:
                    result = run(args, capture_output=True, text=True, timeout=timeout, check=False)
                else:
                    result = _run_cancellable_command(
                        args, timeout=timeout, cancel_event=cancel_event, popen=popen,
                    )
                payload = json.loads(result.stdout or "{}")
                exit_status = int(result.returncode)
                passed = payload.get("smart_status", {}).get("passed")
                if payload.get("smart_support", {}).get("available") is False:
                    device["smart_state"] = "indisponível"
                    device["detail"] = "Este dispositivo não informa suporte SMART."
                elif passed is False or exit_status & 0x18:
                    device["smart_state"] = "crítico"
                    device["indicators"].append("Autoteste/estado SMART reportou falha")
                    device["detail"] = "smartctl informou falha SMART ou atributo pré-falha."
                elif exit_status & 0xE0:
                    device["smart_state"] = "atenção"
                    device["detail"] = "smartctl encontrou erros em atributos históricos ou nos logs SMART."
                elif exit_status & 0x07:
                    device["smart_state"] = "indisponível"
                    if "permission" in (result.stderr or "").casefold():
                        device["detail"] = "Permissão adicional necessária para ler SMART; nenhuma elevação foi solicitada."
                    else:
                        device["detail"] = "A consulta SMART falhou; não foi possível confirmar o estado do disco."
                elif passed is True:
                    device["smart_state"] = "saudável"
                    device["detail"] = "SMART disponível; verificação geral aprovada."
                temps = payload.get("temperature", {})
                device["temperature_c"] = temps.get("current")
                for attr in payload.get("ata_smart_attributes", {}).get("table", ()):
                    name = str(attr.get("name", ""))
                    raw_value = attr.get("raw", {}).get("value")
                    if name in ("Reallocated_Sector_Ct", "Current_Pending_Sector", "Offline_Uncorrectable") and raw_value:
                        device["indicators"].append(f"{name}: {raw_value}")
                        if device["smart_state"] == "saudável": device["smart_state"] = "atenção"
                    if any(key in name.casefold() for key in ("wear", "life_left", "percentage_used")) and raw_value is not None:
                        device["wear"] = {"attribute": name, "value": raw_value}
                if "nvme_smart_health_information_log" in payload:
                    nvme = payload["nvme_smart_health_information_log"]
                    if nvme.get("percentage_used") is not None:
                        device["wear"] = {"attribute": "percentage_used", "value": nvme["percentage_used"]}
                    if nvme.get("critical_warning"):
                        device["indicators"].append(f"Aviso crítico NVMe: {nvme['critical_warning']}")
                        device["smart_state"] = "crítico"
                if device["smart_state"] == "indisponível" and payload and not (exit_status & 0x07):
                    device["detail"] = "SMART não confirmou estado geral."
            except _QueryCancelled:
                device["detail"] = "Consulta SMART cancelada."
                devices.append(device)
                return {"state": "parcial", "reason": "Consulta cancelada.",
                        "devices": devices, "cancelled": True}
            except subprocess.TimeoutExpired:
                device["detail"] = "Consulta SMART excedeu o tempo limite."
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
                device["detail"] = f"Consulta SMART indisponível ({type(exc).__name__})."
        devices.append(device)
    return {"state": "disponível" if devices else "vazio",
            "reason": "" if devices else "Nenhum disco físico foi listado.", "devices": devices}


def _valid_block_path(value):
    try:
        path = Path(value)
        return path.is_absolute() and path.parent == Path("/dev") and path.name not in (".", "..")
    except (TypeError, OSError):
        return False


_SECRET_PATTERNS = (
    re.compile(r"(?i)(password|passwd|token|secret|api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@"),
)


def _redact(line):
    line = _SECRET_PATTERNS[0].sub(r"\1=[REDACTED]", line)
    line = _SECRET_PATTERNS[1].sub("Bearer [REDACTED]", line)
    return _SECRET_PATTERNS[2].sub(r"\1[REDACTED]@", line)


def collect_logs(*, app_log=None, run=subprocess.run, which=shutil.which,
                 max_records=500, max_bytes=2_000_000):
    """Read bounded Aurova logs and user journal warnings; redact credentials."""
    rows = []
    log_path = Path(app_log or Path.home() / ".local/state/desktop_pet/aurova.log")
    try:
        with log_path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - max_bytes))
            content = stream.read(max_bytes).decode("utf-8", errors="replace")
        for line in content.splitlines()[-max_records:]:
            match = re.match(r"^(\S+)\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+([^:]+):\s?(.*)$", line)
            if match:
                timestamp, level, source, message = match.groups()
                rows.append({"date": timestamp, "severity": level, "category": "Aurova",
                             "source": source, "message": _redact(message)[:2000]})
            elif line.strip():
                rows.append({"date": "", "severity": "INFO", "category": "Aurova",
                             "source": "Log da Aurova", "message": _redact(line)[:2000]})
    except FileNotFoundError:
        pass
    except (OSError, UnicodeError):
        pass
    journalctl = which("journalctl")
    if journalctl:
        try:
            result = run([journalctl, "--user", "-p", "warning", "-n", str(min(max_records, 300)), "--output=json", "--no-pager"],
                         capture_output=True, text=True, timeout=5, check=False)
            for line in (result.stdout or "").splitlines()[-max_records:]:
                try: event = json.loads(line)
                except json.JSONDecodeError: continue
                priority = int(event.get("PRIORITY", 4))
                raw_timestamp = event.get("__REALTIME_TIMESTAMP", "")
                try:
                    event_date = datetime.fromtimestamp(int(raw_timestamp) / 1_000_000).astimezone().isoformat(timespec="seconds")
                except (ValueError, OSError, OverflowError):
                    event_date = str(raw_timestamp)
                rows.append({"date": event_date,
                             "severity": "CRITICAL" if priority <= 2 else "ERROR" if priority == 3 else "WARNING",
                             "category": "Sistema", "source": str(event.get("_SYSTEMD_UNIT") or event.get("SYSLOG_IDENTIFIER") or "journal")[:120],
                             "message": _redact(str(event.get("MESSAGE", "")))[:2000]})
        except (OSError, subprocess.SubprocessError):
            pass
    rows.sort(key=lambda item: item["date"], reverse=True)
    return rows[:max_records]


def analyze_cleanup(*, cancel_event=None, max_entries=3000, max_seconds=5):
    """List old, user-owned cache/temp entries; scan never follows symlinks."""
    uid = os.getuid(); now = time.time(); cutoff = now - 7 * 86400
    roots = [(Path.home() / ".cache", "Cache", "Cache selecionado; pode ser recriado por aplicativos."),
             (Path("/tmp"), "Temporário antigo", "Item temporário com mais de 7 dias, pertencente ao usuário atual.")]
    found = []; seen = set(); started = time.monotonic(); visited = 0
    for root, category, reason in roots:
        if not root.exists() or root.is_symlink(): continue
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if cancel_event and cancel_event.is_set():
                        return {"items": found, "cancelled": True, "complete": False}
                    visited += 1
                    if visited > max_entries or time.monotonic() - started > max_seconds:
                        return {"items": found, "cancelled": False, "complete": False}
                    path = Path(entry.path)
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if info.st_uid != uid or stat.S_ISLNK(info.st_mode) or info.st_mtime > cutoff: continue
                        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)): continue
                        size = _tree_size(path, uid, cancel_event, max_entries - visited)
                        if size is None: continue
                        key = str(path.resolve(strict=True))
                        if key in seen: continue
                        seen.add(key)
                        found.append({"path": str(path), "name": path.name,
                                      "category": category, "bytes": size, "reason": reason})
                    except (OSError, PermissionError, ValueError): continue
        except OSError: continue
    return {"items": found, "cancelled": bool(cancel_event and cancel_event.is_set()), "complete": True}


def _tree_size(root, uid, cancel_event, limit):
    """Bounded size walk, declining links, mount crossings and foreign-owned data."""
    try: root_info = root.lstat()
    except OSError: return None
    device = root_info.st_dev; total = 0; count = 0
    if stat.S_ISREG(root_info.st_mode): return root_info.st_size
    for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
        if cancel_event and cancel_event.is_set(): return None
        base_path = Path(base)
        safe_dirs = []
        for name in dirs:
            child_dir = base_path / name
            try:
                child_info = child_dir.lstat()
                if not stat.S_ISLNK(child_info.st_mode) and child_info.st_dev == device:
                    safe_dirs.append(name)
            except OSError:
                continue
        dirs[:] = safe_dirs
        for name in files:
            count += 1
            if count > max(1, limit): return None
            try:
                p = base_path / name; info = p.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_dev == device:
                    total += info.st_size
            except OSError: continue
    return total


def delete_cleanup_items(paths, *, cancel_event=None):
    """Permanently remove explicitly selected validated cache/temp entries."""
    uid = os.getuid(); allowed = ((Path.home() / ".cache").resolve(), Path("/tmp"))
    removed = []; errors = []
    for raw in paths:
        if cancel_event and cancel_event.is_set(): break
        try:
            path = Path(raw)
            if not path.is_absolute() or path.is_symlink(): raise ValueError("Caminho inválido ou link simbólico.")
            canonical = path.resolve(strict=True)
            if canonical in (Path("/"), Path.home(), Path("/tmp")) or not any(canonical.parent == root or root in canonical.parents for root in allowed):
                raise ValueError("Caminho fora das áreas de limpeza permitidas.")
            info = canonical.lstat()
            if info.st_uid != uid or info.st_dev != canonical.parent.stat().st_dev:
                raise PermissionError("Proprietário ou volume não permitido.")
            _validate_removal_tree(canonical, uid, info.st_dev)
            _remove_tree(canonical, uid, cancel_event)
            removed.append(str(canonical))
            logger.info("Limpeza assistida removeu %s", canonical)
        except (OSError, ValueError) as exc:
            errors.append({"path": str(raw), "error": str(exc)})
    return {"removed": removed, "errors": errors, "cancelled": bool(cancel_event and cancel_event.is_set())}


def _remove_tree(path, uid, cancel_event):
    if cancel_event and cancel_event.is_set(): return
    info = path.lstat()
    if info.st_uid != uid or stat.S_ISLNK(info.st_mode): raise PermissionError("Item deixou de ser seguro para remover.")
    if stat.S_ISDIR(info.st_mode):
        for entry in os.scandir(path):
            child = Path(entry.path)
            if child.is_symlink(): raise PermissionError("Diretório contém link simbólico; operação recusada.")
            _remove_tree(child, uid, cancel_event)
        if not (cancel_event and cancel_event.is_set()): path.rmdir()
    elif stat.S_ISREG(info.st_mode): path.unlink()
    else: raise ValueError("Tipo de arquivo não permitido.")


def _validate_removal_tree(path, uid, device, *, count=None):
    """Preflight the whole subtree so unsafe descendants cannot cause partial deletion."""
    count = count if count is not None else [0]
    count[0] += 1
    if count[0] > 5000:
        raise ValueError("Diretório excede o limite de validação para remoção.")
    info = path.lstat()
    if info.st_uid != uid or info.st_dev != device or stat.S_ISLNK(info.st_mode):
        raise PermissionError("A árvore contém links, outro proprietário ou outro volume.")
    if stat.S_ISDIR(info.st_mode):
        with os.scandir(path) as entries:
            for entry in entries:
                _validate_removal_tree(Path(entry.path), uid, device, count=count)
    elif not stat.S_ISREG(info.st_mode):
        raise ValueError("A árvore contém tipo de arquivo não permitido.")
