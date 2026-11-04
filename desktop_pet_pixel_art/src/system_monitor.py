"""Non-blocking system and Nova process metrics collector."""
import threading
import time
from collections import deque
from pathlib import Path


class SystemMonitor:
    def __init__(self, history_limit=120):
        self.started_at = time.monotonic()
        self.history = deque(maxlen=max(1, history_limit))
        self._lock = threading.Lock()

    def collect(self, extra=None):
        import psutil
        try:
            process = psutil.Process()
            battery = psutil.sensors_battery()
            vm = psutil.virtual_memory()
            disk = psutil.disk_usage(str(Path.home()))
            metrics = {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "memory_percent": vm.percent,
                "memory_used": vm.used,
                "memory_total": vm.total,
                "disk_percent": disk.percent,
                "disk_free": disk.free,
                "process_memory": process.memory_info().rss,
                "threads": threading.active_count(),
                "uptime_seconds": int(time.monotonic() - self.started_at),
                "battery_percent": None if battery is None else battery.percent,
                "timestamp": time.time(),
            }
        except Exception:
            metrics = {"error": "metrics_unavailable", "timestamp": time.time()}
        if isinstance(extra, dict):
            metrics.update(extra)
        with self._lock:
            self.history.append(metrics)
        return dict(metrics)
