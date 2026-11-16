"""Lightweight, read-only system information for Meu Computador."""

import os
import platform
import heapq
import stat
import shutil
import socket
import time
from pathlib import Path


def _cpu_name():
    """Read the Linux CPU model when available, with a portable fallback."""
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.lower().startswith(("model name", "hardware")):
                return line.split(":", 1)[-1].strip()
    except (OSError, UnicodeError):
        pass
    return platform.processor() or platform.machine() or "Não identificado"


def collect_overview():
    """Collect a point-in-time system snapshot. Optional fields may be None."""
    import psutil

    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path.home()))
    try:
        load = os.getloadavg()[0]
        cpu = psutil.cpu_percent(interval=0.15)
    except (AttributeError, OSError):
        load, cpu = None, psutil.cpu_percent(interval=None)
    try:
        temperatures = psutil.sensors_temperatures(fahrenheit=False)
        readings = [sensor.current for group in temperatures.values() for sensor in group
                    if sensor.current is not None]
        temperature = max(readings) if readings else None
    except (AttributeError, OSError):
        temperature = None
    return {
        "cpu_name": _cpu_name(), "cpu_percent": cpu,
        "memory_total": memory.total, "memory_used": memory.used,
        "memory_percent": memory.percent, "disk_total": disk.total,
        "disk_used": disk.used, "disk_free": disk.free,
        "disk_percent": disk.percent, "system": platform.platform(),
        "hostname": socket.gethostname(), "load_average": load,
        "temperature_c": temperature,
    }


def collect_network():
    """Read active interface addresses and current counters without probing hosts."""
    import psutil

    stats = psutil.net_if_stats()
    addresses = psutil.net_if_addrs()
    counters = psutil.net_io_counters(pernic=True)
    rows = []
    for name, status in stats.items():
        if not status.isup:
            continue
        ips = [address.address for address in addresses.get(name, ())
               if address.family == socket.AF_INET and not address.address.startswith("127.")]
        counter = counters.get(name)
        rows.append({"name": name, "speed_mbps": status.speed or None,
                     "addresses": ips, "sent": counter.bytes_sent if counter else None,
                     "received": counter.bytes_recv if counter else None})
    return rows


def collect_storage(path=None, *, limit=8, cancel_event=None, time_limit=8.0,
                   entry_limit=12000):
    """Return filesystem capacity and largest immediate home directories.

    Directory sizes are a bounded, best-effort scan so very large home folders
    cannot monopolize the worker indefinitely. ``scan_complete`` makes that
    limitation visible instead of presenting partial totals as exact.
    """
    root = Path(path or Path.home()).expanduser()
    usage = shutil.disk_usage(root)
    children = []
    started = time.monotonic()
    visited = 0
    scan_complete = True
    try:
        for child in root.iterdir():
            if child.is_symlink() or not child.is_dir():
                continue
            total = 0
            try:
                for base, dirs, files in os.walk(child, followlinks=False):
                    if ((cancel_event and cancel_event.is_set())
                            or time.monotonic() - started >= time_limit
                            or visited >= entry_limit):
                        scan_complete = False
                        dirs[:] = []
                        break
                    dirs[:] = [name for name in dirs
                               if not (Path(base) / name).is_symlink()]
                    for name in files:
                        if ((cancel_event and cancel_event.is_set())
                                or time.monotonic() - started >= time_limit
                                or visited >= entry_limit):
                            scan_complete = False
                            break
                        visited += 1
                        try:
                            total += (Path(base) / name).stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue
            children.append({"name": child.name, "bytes": total})
    except OSError:
        pass
    children.sort(key=lambda item: item["bytes"], reverse=True)
    return {"path": str(root), "total": usage.total, "used": usage.used,
            "free": usage.free, "directories": children[:max(1, limit)],
            "scan_complete": scan_complete}


def collect_storage_overview(path=None):
    """Return capacity for the selected path and mounted filesystems."""
    import psutil

    selected = Path(path or Path.home()).expanduser().resolve(strict=True)
    usage = psutil.disk_usage(selected)
    volumes = []
    seen = set()
    for partition in psutil.disk_partitions(all=False):
        mount = partition.mountpoint
        if mount in seen:
            continue
        seen.add(mount)
        try:
            space = psutil.disk_usage(mount)
        except (PermissionError, OSError):
            continue
        volumes.append({"mountpoint": mount, "device": partition.device,
                        "filesystem": partition.fstype, "total": space.total,
                        "free": space.free, "used": space.used,
                        "percent": space.percent})
    return {"path": str(selected), "total": usage.total, "used": usage.used,
            "free": usage.free, "percent": usage.percent,
            "volumes": volumes}


def analyze_directory(path, *, cancel_event=None, progress_callback=None,
                      max_entries=100000, max_directories=2500, top_files=100):
    """Analyze one selected directory without following symlinks or mounts.

    The scan is read-only and bounded. File details are retained only for the
    largest ``top_files`` files; directory nodes are capped independently.
    """
    root = Path(path).expanduser().resolve(strict=True)
    root_stat = root.stat()
    if not root.is_dir():
        raise ValueError("Selecione uma pasta para analisar.")
    device = root_stat.st_dev
    nodes = {".": {"path": str(root), "name": root.name or str(root),
                    "parent": "", "bytes": 0, "files": 0,
                    "directories": 0}}
    largest = []
    sequence = 0
    files_seen = 0
    directories_seen = 0
    bytes_seen = 0
    inaccessible = 0
    entries_seen = 0
    complete = True
    cancelled = False
    root_device_usage = shutil.disk_usage(root)

    def report():
        if progress_callback:
            progress_callback({"files": files_seen,
                               "directories": directories_seen,
                               "bytes": bytes_seen,
                               "inaccessible": inaccessible})

    def on_error(_error):
        nonlocal inaccessible, complete
        inaccessible += 1
        complete = False

    for base, dirnames, filenames in os.walk(root, topdown=True,
                                              followlinks=False,
                                              onerror=on_error):
        if cancel_event and cancel_event.is_set():
            cancelled = True
            complete = False
            break
        base_path = Path(base)
        try:
            base_relative = base_path.relative_to(root).as_posix() or "."
        except ValueError:
            dirnames[:] = []
            continue

        safe_directories = []
        for name in dirnames:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                complete = False
                break
            if entries_seen >= max_entries:
                complete = False
                break
            child = base_path / name
            try:
                info = child.stat(follow_symlinks=False)
                if child.is_symlink() or info.st_dev != device:
                    continue
            except OSError:
                inaccessible += 1
                complete = False
                continue
            directories_seen += 1
            entries_seen += 1
            safe_directories.append(name)
            relative = child.relative_to(root).as_posix()
            parent = base_relative
            if relative not in nodes:
                if len(nodes) < max_directories:
                    nodes[relative] = {"path": str(child), "name": name,
                                       "parent": parent, "bytes": 0,
                                       "files": 0, "directories": 0}
                else:
                    complete = False
            ancestor = parent
            while ancestor in nodes:
                nodes[ancestor]["directories"] += 1
                ancestor = nodes[ancestor]["parent"]
        dirnames[:] = safe_directories

        for name in filenames:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                complete = False
                break
            entries_seen += 1
            if entries_seen > max_entries:
                complete = False
                break
            file_path = base_path / name
            try:
                info = file_path.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    continue
            except OSError:
                inaccessible += 1
                complete = False
                continue
            size = info.st_size
            files_seen += 1
            bytes_seen += size
            ancestor = base_relative
            while ancestor not in nodes and ancestor not in ("", "."):
                ancestor = Path(ancestor).parent.as_posix()
            while ancestor in nodes:
                nodes[ancestor]["bytes"] += size
                nodes[ancestor]["files"] += 1
                ancestor = nodes[ancestor]["parent"]
            sequence += 1
            item = {"path": str(file_path), "name": name, "bytes": size,
                    "extension": file_path.suffix.casefold() or "(sem extensão)"}
            entry = (size, sequence, item)
            if len(largest) < max(1, top_files):
                heapq.heappush(largest, entry)
            elif size > largest[0][0]:
                heapq.heapreplace(largest, entry)
            if entries_seen % 200 == 0:
                report()
        if entries_seen > max_entries:
            break
        if cancelled:
            break

    report()
    return {
        "path": str(root), "total": root_device_usage.total,
        "used": root_device_usage.used, "free": root_device_usage.free,
        "files": files_seen, "directories_count": directories_seen,
        "bytes_scanned": bytes_seen, "inaccessible": inaccessible,
        "complete": complete, "cancelled": cancelled,
        "directories": nodes,
        "largest_files": [entry[2] for entry in sorted(largest, reverse=True)],
    }
def format_bytes(value):
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
