"""Ferramentas somente leitura para relógio local e métricas do dispositivo."""

from datetime import datetime

from .base import Tool
from .results import ActionResult


class ClockTool(Tool):
    name = "system.clock"
    description = "Consulta o horário local do dispositivo."

    def execute(self, arguments):
        if arguments:
            raise ValueError("O relógio não aceita argumentos")
        now = datetime.now().astimezone()
        return ActionResult(True, now.strftime("%H:%M (%Z)"), {"datetime": now.isoformat()})


class SystemMonitorTool(Tool):
    name = "system.monitor"
    description = "Consulta métricas agregadas de CPU, memória e disco."

    def __init__(self, monitor=None):
        self._monitor = monitor

    def execute(self, arguments):
        if arguments:
            raise ValueError("O monitor não aceita argumentos")
        monitor = self._monitor
        if monitor is None:
            # Importação tardia mantém a inicialização leve e sem dependência de psutil.
            from system_monitor import SystemMonitor
            monitor = SystemMonitor(history_limit=1)
            self._monitor = monitor
        metrics = monitor.collect()
        if "error" in metrics:
            return ActionResult(False, "Métricas indisponíveis neste dispositivo.")
        allowed = {key: metrics[key] for key in (
            "cpu_percent", "memory_percent", "memory_used", "memory_total",
            "disk_percent", "disk_free", "uptime_seconds", "timestamp",
        ) if key in metrics}
        return ActionResult(True, "Métricas do sistema consultadas.", allowed)
