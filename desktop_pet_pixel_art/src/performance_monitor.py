"""Low-rate bounded performance history and evidence-based proactive alerts."""

import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from json_persistence import atomic_json_write, ensure_private_directory, validate_storage_path
from notifications import NotificationCategory

logger = logging.getLogger(__name__)
DEFAULT_INTERVAL = 60
MAX_INTERVAL = 3600
MAX_SAMPLES = 43_200  # 30 days at the minimum 60-second interval.
MAX_ALERTS = 2_000
CATEGORIES = ("cpu", "memory", "storage", "temperature", "network", "disk_health")
DEFAULT_THRESHOLDS = {"cpu": 90.0, "memory": 90.0, "storage": 95.0, "temperature": 90.0}


def default_history_path():
    return Path.home() / ".local" / "state" / "desktop_pet" / "performance.sqlite3"


def default_settings_path():
    return Path.home() / ".config" / "desktop_pet" / "performance_monitor.json"


def _default_settings():
    return {"enabled": True, "interval_seconds": DEFAULT_INTERVAL,
            "confirm_seconds": 180, "cpu_confirm_seconds": 300,
            "repeat_minutes": 60, "thresholds": dict(DEFAULT_THRESHOLDS),
            "silenced_categories": []}


def load_settings(path=None):
    target = Path(path or default_settings_path())
    settings = _default_settings()
    try:
        validate_storage_path(target, label="configuração do monitor")
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict): return settings
        settings["enabled"] = data.get("enabled") is not False
        try: settings["interval_seconds"] = max(DEFAULT_INTERVAL, min(MAX_INTERVAL, int(data.get("interval_seconds", DEFAULT_INTERVAL))))
        except (TypeError, ValueError): pass
        for key in ("confirm_seconds", "cpu_confirm_seconds"):
            try: settings[key] = max(60, min(86_400, int(data.get(key, settings[key]))))
            except (TypeError, ValueError): pass
        try: settings["repeat_minutes"] = max(1, min(1440, int(data.get("repeat_minutes", settings["repeat_minutes"]))))
        except (TypeError, ValueError): pass
        thresholds = data.get("thresholds", {})
        if isinstance(thresholds, dict):
            for key, default in DEFAULT_THRESHOLDS.items():
                try: settings["thresholds"][key] = max(1.0, min(100.0, float(thresholds.get(key, default))))
                except (TypeError, ValueError): pass
        muted = data.get("silenced_categories", [])
        if isinstance(muted, list): settings["silenced_categories"] = [item for item in muted if item in CATEGORIES]
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return settings


class PerformanceStore:
    """SQLite time series with fixed retention and per-operation connections."""

    def __init__(self, path=None, *, max_samples=MAX_SAMPLES, max_alerts=MAX_ALERTS):
        self.path = Path(path or default_history_path())
        validate_storage_path(self.path, label="histórico de desempenho")
        ensure_private_directory(self.path.parent, label="histórico de desempenho")
        self.max_samples = max(10, int(max_samples))
        self.max_alerts = max(10, int(max_alerts))
        self._lock = threading.RLock()
        self._writes = 0
        self._initialize()

    def _connect(self):
        validate_storage_path(self.path, label="histórico de desempenho")
        connection = sqlite3.connect(self.path, timeout=2)
        os.chmod(self.path, 0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=2000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    @contextmanager
    def _session(self):
        db = self._connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _initialize(self):
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.close(fd)
        info = self.path.lstat()
        if not self.path.is_file() or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise PermissionError("O histórico precisa ser um arquivo regular do usuário atual.")
        os.chmod(self.path, 0o600)
        with self._lock, self._session() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY, timestamp REAL NOT NULL,
                    cpu REAL, memory REAL, storage REAL, temperature REAL,
                    network_up REAL, network_down REAL, network_connected INTEGER
                );
                CREATE INDEX IF NOT EXISTS samples_timestamp ON samples(timestamp);
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL,
                    severity TEXT NOT NULL, description TEXT NOT NULL, evidence TEXT NOT NULL,
                    recommendation TEXT NOT NULL, created_at REAL NOT NULL,
                    notified INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS alerts_created ON alerts(created_at);
            """)
            os.chmod(self.path, 0o600)

    def add_sample(self, sample):
        timestamp = float(sample.get("timestamp", time.time()))
        fields = ("cpu_percent", "memory_percent", "disk_percent", "temperature_c",
                  "upload_bytes_per_second", "download_bytes_per_second")
        values = [sample.get(key) for key in fields]
        checkpoint = False
        with self._lock, self._session() as db:
            db.execute("INSERT INTO samples(timestamp,cpu,memory,storage,temperature,network_up,network_down,network_connected) VALUES(?,?,?,?,?,?,?,?)",
                       (timestamp, *values, None if sample.get("network_connected") is None else int(bool(sample["network_connected"]))))
            self._writes += 1
            count = db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            if self._writes % 100 == 0 or count > self.max_samples:
                cutoff = timestamp - 30 * 86400
                db.execute("DELETE FROM samples WHERE timestamp < ?", (cutoff,))
                db.execute("DELETE FROM samples WHERE id NOT IN (SELECT id FROM samples ORDER BY timestamp DESC LIMIT ?)", (self.max_samples,))
                db.execute("DELETE FROM alerts WHERE id NOT IN (SELECT id FROM alerts ORDER BY created_at DESC LIMIT ?)", (self.max_alerts,))
                checkpoint = True
        if checkpoint:
            with self._lock, self._session() as db:
                db.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def samples(self, *, since=None, until=None, limit=MAX_SAMPLES):
        query = "SELECT * FROM samples WHERE 1=1"; params = []
        if since is not None: query += " AND timestamp >= ?"; params.append(float(since))
        if until is not None: query += " AND timestamp < ?"; params.append(float(until))
        query += " ORDER BY timestamp DESC LIMIT ?"; params.append(max(1, min(self.max_samples, int(limit))))
        with self._lock, self._session() as db:
            rows = [dict(row) for row in db.execute(query, params).fetchall()]
        return list(reversed(rows))

    def add_alert(self, alert, *, notified):
        with self._lock, self._session() as db:
            db.execute("INSERT INTO alerts(category,title,severity,description,evidence,recommendation,created_at,notified) VALUES(?,?,?,?,?,?,?,?)",
                       (alert["category"], alert["title"], alert["severity"], alert["description"],
                        alert["evidence"], alert["recommendation"], float(alert["timestamp"]), int(bool(notified))))
            db.execute("DELETE FROM alerts WHERE id NOT IN (SELECT id FROM alerts ORDER BY created_at DESC LIMIT ?)", (self.max_alerts,))

    def alerts(self, *, category=None, severity=None, limit=500):
        query = "SELECT * FROM alerts WHERE 1=1"; params = []
        if category: query += " AND category=?"; params.append(category)
        if severity: query += " AND severity=?"; params.append(severity)
        query += " ORDER BY created_at DESC LIMIT ?"; params.append(max(1, min(self.max_alerts, int(limit))))
        with self._lock, self._session() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def last_alert_time(self, category):
        with self._lock, self._session() as db:
            row = db.execute("SELECT MAX(created_at) FROM alerts WHERE category=?", (category,)).fetchone()
        return row[0]

    def clear(self):
        with self._lock, self._session() as db:
            db.execute("DELETE FROM samples")
            db.execute("DELETE FROM alerts")
        with self._lock, self._session() as db:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def collect_performance_sample(*, now=None, psutil_module=None, previous_counters=None,
                               previous_time=None):
    """Collect a small local resource snapshot; never probes external hosts."""
    if psutil_module is None:
        import psutil as psutil_module
    now = time.time() if now is None else float(now)
    try: cpu = float(psutil_module.cpu_percent(interval=0.05))
    except (AttributeError, OSError, RuntimeError): cpu = None
    try: memory_percent = float(psutil_module.virtual_memory().percent)
    except (AttributeError, OSError, RuntimeError): memory_percent = None
    try: disk_percent = float(psutil_module.disk_usage(str(Path.home())).percent)
    except (AttributeError, OSError, RuntimeError): disk_percent = None
    try:
        temperatures = psutil_module.sensors_temperatures(fahrenheit=False)
        readings = [sensor.current for group in temperatures.values() for sensor in group if sensor.current is not None]
        temperature = max(readings) if readings else None
    except Exception:
        temperature = None
    try: counters = psutil_module.net_io_counters()
    except (AttributeError, OSError, RuntimeError): counters = None
    elapsed = now - previous_time if previous_time is not None else None
    up = down = None
    if counters is not None and previous_counters is not None and elapsed and elapsed > 0:
        up = max(0, counters.bytes_sent - previous_counters[0]) / elapsed
        down = max(0, counters.bytes_recv - previous_counters[1]) / elapsed
    connected = False
    try:
        addresses = psutil_module.net_if_addrs()
        for name, status in psutil_module.net_if_stats().items():
            if name == "lo" or not status.isup: continue
            if addresses.get(name):
                connected = True; break
    except (AttributeError, OSError, RuntimeError): connected = None
    sample = {"timestamp": now, "cpu_percent": cpu,
              "memory_percent": memory_percent, "disk_percent": disk_percent,
              "temperature_c": temperature, "upload_bytes_per_second": up,
              "download_bytes_per_second": down, "network_connected": connected,
              "_net_counters": ((counters.bytes_sent, counters.bytes_recv)
                                if counters is not None else None),
              "_net_counters_time": now if counters is not None else None}
    return sample


class AlertEngine:
    """Persistence windows and repeat suppression for resource alerts."""

    def __init__(self, store, settings, notification_manager=None):
        self.store = store
        self.settings = settings
        self.notification_manager = notification_manager
        self._pending = {}
        self._network_previous = None

    def update_settings(self, settings): self.settings = settings

    def reset_state(self):
        self._pending.clear()
        self._network_previous = None

    def evaluate(self, sample):
        timestamp = float(sample.get("timestamp", time.time()))
        conditions = []
        thresholds = self.settings["thresholds"]
        for category, key, title, metric, recommendation in (
            ("memory", "memory_percent", "Memória RAM próxima do limite", "RAM", "Confira os processos com maior uso de memória."),
            ("cpu", "cpu_percent", "Uso elevado de CPU", "CPU", "Confira se a tarefa que usa mais CPU é esperada."),
            ("storage", "disk_percent", "Armazenamento quase cheio", "volume da pasta pessoal", "Revise os maiores diretórios antes de remover arquivos."),
            ("temperature", "temperature_c", "Temperatura elevada", "temperatura", "Reduza tarefas pesadas e confira a ventilação."),
        ):
            value = sample.get(key); threshold = thresholds.get(category)
            if isinstance(value, (int, float)) and threshold is not None and value >= threshold:
                critical = (category == "storage" and value >= 98) or (category == "memory" and value >= 97) or (category == "temperature" and value >= 95)
                unit = "°C" if category == "temperature" else "%"
                conditions.append((category, title, "Crítico" if critical else "Atenção",
                                   f"{metric} em {value:.1f}{unit}; limite configurado {threshold:.1f}{unit}.", recommendation))
        connected = sample.get("network_connected")
        if connected is False and (self._network_previous is True or "network" in self._pending):
            conditions.append(("network", "Conectividade local interrompida", "Atenção",
                               "Uma interface de rede ativa anteriormente deixou de estar conectada.",
                               "Confira o cabo, Wi-Fi ou estado do adaptador. A internet não foi sondada."))
        if connected is not None: self._network_previous = bool(connected)
        active = {item[0] for item in conditions}
        for category in set(self._pending) - active: self._pending.pop(category, None)
        for category, title, severity, evidence, recommendation in conditions:
            started = self._pending.setdefault(category, timestamp)
            required = self.settings["cpu_confirm_seconds"] if category == "cpu" else self.settings["confirm_seconds"]
            if severity == "Crítico": required = min(required, 60)
            if timestamp - started < required: continue
            last = self.store.last_alert_time(category)
            cooldown = self.settings["repeat_minutes"] * 60
            if last is not None and timestamp - last < cooldown: continue
            alert = {"category": category, "title": title, "severity": severity,
                     "description": f"A condição permaneceu acima do limite por pelo menos {required} segundos.",
                     "evidence": evidence, "recommendation": recommendation,
                     "timestamp": timestamp}
            muted = category in self.settings["silenced_categories"]
            notified = False
            if not muted and self.notification_manager is not None:
                try:
                    item = self.notification_manager.create(
                        title, f"{evidence} {recommendation}",
                        NotificationCategory.SYSTEM_ALERT,
                        priority=90 if severity == "Crítico" else 70,
                    )
                    notified = item is not None
                except (OSError, ValueError, RuntimeError):
                    logger.exception("Falha ao encaminhar alerta de desempenho à central de notificações")
            self.store.add_alert(alert, notified=notified)
        return self.store.alerts(limit=100)


class PerformanceMonitor:
    """One daemon sampling thread at >=60s, stopped cooperatively on shutdown."""

    def __init__(self, notification_manager=None, *, store=None, settings_path=None,
                 collector=collect_performance_sample, smart_collector=None):
        self.settings_path = Path(settings_path or default_settings_path())
        self.settings = load_settings(self.settings_path)
        self.store = store or PerformanceStore()
        self.notifications = notification_manager
        self.collector = collector
        self.smart_collector = smart_collector
        self.engine = AlertEngine(self.store, self.settings, notification_manager)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = None
        self._previous_counters = None
        self._previous_time = None
        self._smart_checked_at = 0.0

    def start(self):
        if self._thread and self._thread.is_alive(): return
        self._thread = threading.Thread(target=self._run, name="aurova-performance-monitor", daemon=True)
        self._thread.start()

    def stop(self, timeout=2.0):
        self._stop.set(); self._wake.set()
        if self._thread and self._thread is not threading.current_thread(): self._thread.join(timeout=max(0.0, timeout))

    def configure(self, **changes):
        settings = json.loads(json.dumps(self.settings))
        settings.update({key: value for key, value in changes.items() if key in settings})
        try: settings["interval_seconds"] = max(DEFAULT_INTERVAL, min(MAX_INTERVAL, int(settings["interval_seconds"])))
        except (TypeError, ValueError): raise ValueError("Intervalo inválido; use ao menos 60 segundos.")
        try: settings["confirm_seconds"] = max(60, min(86_400, int(settings["confirm_seconds"])))
        except (TypeError, ValueError): raise ValueError("Tempo de confirmação inválido.")
        try: settings["cpu_confirm_seconds"] = max(60, min(86_400, int(settings["cpu_confirm_seconds"])))
        except (TypeError, ValueError): raise ValueError("Tempo de confirmação da CPU inválido.")
        try: settings["repeat_minutes"] = max(1, min(1440, int(settings["repeat_minutes"])))
        except (TypeError, ValueError): raise ValueError("Intervalo de repetição inválido.")
        for key, default in DEFAULT_THRESHOLDS.items():
            if not isinstance(settings.get("thresholds"), dict):
                raise ValueError("Limites de alerta inválidos.")
            try: value = float(settings["thresholds"].get(key, default))
            except (TypeError, ValueError): raise ValueError(f"Limite inválido: {key}.")
            if not 1 <= value <= 100: raise ValueError(f"Limite fora da faixa: {key}.")
            settings["thresholds"][key] = value
        if not isinstance(settings.get("silenced_categories", []), (list, tuple, set)):
            raise ValueError("Categorias silenciadas inválidas.")
        settings["silenced_categories"] = sorted(set(settings.get("silenced_categories", ())) & set(CATEGORIES))
        settings["enabled"] = bool(settings["enabled"])
        validate_storage_path(self.settings_path, label="configuração do monitor")
        atomic_json_write(self.settings_path, settings, label="configuração do monitor")
        self.settings = settings; self.engine.update_settings(settings); self._wake.set()
        return dict(settings)

    def sample_once(self, sample=None):
        sample = sample or self.collector(now=time.time(), previous_counters=self._previous_counters,
                                          previous_time=self._previous_time)
        counters = sample.pop("_net_counters", None)
        counters_time = sample.pop("_net_counters_time", None)
        if counters is not None:
            self._previous_counters = counters
            self._previous_time = float(counters_time or sample.get("timestamp", time.time()))
        self.store.add_sample(sample)
        return self.engine.evaluate(sample)

    def clear_history(self):
        self.store.clear()
        self.engine.reset_state()

    def _run(self):
        while not self._stop.is_set():
            if not self.settings["enabled"]:
                self._wake.wait(timeout=3600); self._wake.clear(); continue
            try:
                sample = self.collector(now=time.time(), previous_counters=self._previous_counters,
                                        previous_time=self._previous_time)
                if self._stop.is_set(): break
                self.sample_once(sample)
                if self.smart_collector and time.monotonic() - self._smart_checked_at >= 6 * 3600:
                    self._smart_checked_at = time.monotonic()
                    smart_result = self.smart_collector(cancel_event=self._stop)
                    if self._stop.is_set(): break
                    self._evaluate_smart(smart_result)
            except Exception:
                logger.exception("Amostra de desempenho não concluída; o monitor seguirá no próximo intervalo")
            self._wake.wait(timeout=self.settings["interval_seconds"]); self._wake.clear()

    def _evaluate_smart(self, result):
        issues = [disk for disk in result.get("devices", ())
                  if disk.get("smart_state") in ("atenção", "crítico")]
        if not issues or self._stop.is_set(): return
        category = "disk_health"; title = "Possível falha de disco"
        timestamp = time.time(); last = self.store.last_alert_time(category)
        if last is not None and timestamp - last < self.settings["repeat_minutes"] * 60: return
        critical = any(disk["smart_state"] == "crítico" for disk in issues)
        evidence = " · ".join(
            f"{disk.get('path')}: " + ("; ".join(disk.get("indicators", ())) or disk.get("detail", "SMART reportou atenção."))
            for disk in issues
        )
        alert = {"category": category, "title": title,
                 "severity": "Crítico" if critical else "Atenção",
                 "description": "A leitura SMART de um ou mais dispositivos reportou um estado de atenção.",
                 "evidence": evidence,
                 "recommendation": "Faça uma cópia dos dados importantes e procure assistência técnica; não execute reparos automaticamente.",
                 "timestamp": timestamp}
        muted = category in self.settings["silenced_categories"]
        notified = False
        if not muted and self.notifications:
            item = self.notifications.create(title, alert["evidence"] + " " + alert["recommendation"],
                                             NotificationCategory.SYSTEM_ALERT,
                                             priority=90 if critical else 70)
            notified = item is not None
        self.store.add_alert(alert, notified=notified)


def performance_context(store, *, hours=24):
    """Compact facts for future consultant integration, without adding a chatbot."""
    now = time.time(); period = max(1.0, min(720.0, float(hours))) * 3600
    samples = store.samples(since=now - period, limit=2000)
    alerts = store.alerts(limit=30)
    metrics = {}
    for name in ("cpu", "memory", "storage", "temperature", "network_up", "network_down"):
        values = [row[name] for row in samples if row[name] is not None]
        metrics[name] = {"current": values[-1] if values else None,
                         "maximum": max(values) if values else None,
                         "average": sum(values) / len(values) if values else None}
    return {"schema": "aurova-performance-context.v1", "period_hours": hours,
            "samples": len(samples), "metrics": metrics, "alerts": alerts[:10],
            "limitations": ["Métricas são amostras locais; conectividade externa não é sondada automaticamente."]}
