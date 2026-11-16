"""Focused tests for bounded performance history and proactive alert rules."""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from performance_monitor import (
    AlertEngine, PerformanceMonitor, PerformanceStore,
    collect_performance_sample, performance_context,
)


def sample(timestamp, *, cpu=20, memory=40, storage=50, temperature=None, connected=True):
    return {"timestamp": float(timestamp), "cpu_percent": cpu,
            "memory_percent": memory, "disk_percent": storage,
            "temperature_c": temperature, "upload_bytes_per_second": None,
            "download_bytes_per_second": None, "network_connected": connected}


class FakeNotifications:
    def __init__(self): self.items = []
    def create(self, *args, **kwargs):
        item = SimpleNamespace(args=args, kwargs=kwargs)
        self.items.append(item)
        return item


class PerformanceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "history.sqlite3"
        self.store = PerformanceStore(self.path, max_samples=10, max_alerts=10)
    def tearDown(self): self.temp.cleanup()

    def test_empty_history_and_bounded_persistent_samples(self):
        self.assertEqual(self.store.samples(), [])
        for index in range(15): self.store.add_sample(sample(index))
        rows = self.store.samples()
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["timestamp"], 5)
        self.assertEqual(rows[-1]["timestamp"], 14)
        reopened = PerformanceStore(self.path, max_samples=10)
        self.assertEqual(len(reopened.samples()), 10)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_clear_removes_samples_and_alert_history(self):
        self.store.add_sample(sample(1))
        alert = {"category": "cpu", "title": "CPU", "severity": "Atenção",
                 "description": "desc", "evidence": "evid", "recommendation": "rec", "timestamp": 2}
        self.store.add_alert(alert, notified=False)
        self.store.clear()
        self.assertEqual(self.store.samples(), [])
        self.assertEqual(self.store.alerts(), [])


class CollectionTests(unittest.TestCase):
    def test_collects_local_metrics_and_marks_missing_temperature_and_first_network_rate(self):
        psutil = SimpleNamespace(
            cpu_percent=lambda interval: 25.0,
            virtual_memory=lambda: SimpleNamespace(percent=62.0),
            disk_usage=lambda _path: SimpleNamespace(percent=70.0),
            sensors_temperatures=lambda **_kw: {},
            net_io_counters=lambda: SimpleNamespace(bytes_sent=100, bytes_recv=300),
            net_if_addrs=lambda: {"enp0s1": [object()]},
            net_if_stats=lambda: {"enp0s1": SimpleNamespace(isup=True)},
        )
        result = collect_performance_sample(now=10, psutil_module=psutil)
        self.assertEqual(result["cpu_percent"], 25.0)
        self.assertIsNone(result["temperature_c"])
        self.assertIsNone(result["upload_bytes_per_second"])
        self.assertTrue(result["network_connected"])

    def test_no_temperature_sensor_does_not_create_temperature_alert(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = PerformanceStore(Path(temporary) / "db.sqlite3")
            engine = AlertEngine(store, PerformanceMonitor(store=store).settings)
            engine.evaluate(sample(0, temperature=None))
            engine.evaluate(sample(300, temperature=None))
            self.assertEqual(store.alerts(category="temperature"), [])


class AlertEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = PerformanceStore(Path(self.temp.name) / "history.sqlite3")
        self.notifications = FakeNotifications()
        self.settings = {"thresholds": {"cpu": 90, "memory": 85, "storage": 95, "temperature": 85},
                         "confirm_seconds": 120, "cpu_confirm_seconds": 300,
                         "repeat_minutes": 30, "silenced_categories": []}
        self.engine = AlertEngine(self.store, self.settings, self.notifications)
    def tearDown(self): self.temp.cleanup()

    def test_persistent_cpu_alert_notifies_once_and_suppresses_repeats(self):
        for timestamp in (0, 120, 240, 300):
            self.engine.evaluate(sample(timestamp, cpu=95))
        self.assertEqual(len(self.notifications.items), 1)
        self.assertEqual(len(self.store.alerts(category="cpu")), 1)
        self.assertEqual(self.notifications.items[0].kwargs["priority"], 70)
        self.engine.evaluate(sample(1200, cpu=95))
        self.assertEqual(len(self.notifications.items), 1)
        self.engine.evaluate(sample(3000, cpu=95))
        self.assertEqual(len(self.notifications.items), 2)

    def test_silencing_records_evidence_but_sends_no_notification(self):
        self.settings["silenced_categories"] = ["memory"]
        self.engine.evaluate(sample(0, memory=90))
        self.engine.evaluate(sample(120, memory=90))
        self.assertEqual(len(self.notifications.items), 0)
        alert = self.store.alerts(category="memory")[0]
        self.assertEqual(alert["notified"], 0)
        self.assertIn("90.0%", alert["evidence"])

    def test_connectivity_alert_requires_observed_loss_after_connection(self):
        self.engine.evaluate(sample(0, connected=True))
        self.engine.evaluate(sample(60, connected=False))
        self.engine.evaluate(sample(180, connected=False))
        self.assertEqual(len(self.store.alerts(category="network")), 1)
        self.assertEqual(len(self.notifications.items), 1)

    def test_missing_data_and_non_persistent_cpu_do_not_alert(self):
        self.engine.evaluate(sample(0, cpu=None, memory=None, storage=None, temperature=None))
        self.engine.evaluate(sample(180, cpu=95))
        self.assertEqual(self.store.alerts(), [])


class MonitorLifecycleTests(unittest.TestCase):
    def test_configuration_clamps_interval_and_can_disable_collection(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = PerformanceStore(Path(temporary) / "history.sqlite3")
            collector = mock.Mock()
            monitor = PerformanceMonitor(store=store, settings_path=Path(temporary) / "settings.json", collector=collector)
            settings = monitor.configure(enabled=False, interval_seconds=1)
            self.assertFalse(settings["enabled"])
            self.assertEqual(settings["interval_seconds"], 60)
            monitor.start(); time.sleep(0.05)
            monitor.stop()
            collector.assert_not_called()

    def test_worker_stops_cleanly_and_consultant_context_is_compact(self):
        with tempfile.TemporaryDirectory() as temporary:
            called = threading.Event()
            def collector(**_kwargs):
                called.set()
                return sample(time.time())
            store = PerformanceStore(Path(temporary) / "history.sqlite3")
            monitor = PerformanceMonitor(store=store, settings_path=Path(temporary) / "settings.json", collector=collector)
            monitor.start()
            self.assertTrue(called.wait(2))
            monitor.stop(timeout=2)
            self.assertFalse(monitor._thread.is_alive())
            context = performance_context(store, hours=1)
            self.assertEqual(context["schema"], "nova-performance-context.v1")
            self.assertEqual(context["samples"], 1)

    def test_configurable_threshold_and_repeat_ranges_are_saved(self):
        with tempfile.TemporaryDirectory() as temporary:
            monitor = PerformanceMonitor(store=PerformanceStore(Path(temporary) / "db.sqlite3"),
                                         settings_path=Path(temporary) / "settings.json")
            settings = monitor.configure(thresholds={"memory": 88, "cpu": 91, "storage": 96, "temperature": 82}, repeat_minutes=1)
            self.assertEqual(settings["thresholds"]["memory"], 88)
            self.assertEqual(settings["repeat_minutes"], 1)

    def test_smart_failure_is_routed_through_existing_notification_manager(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = PerformanceStore(Path(temporary) / "db.sqlite3")
            notifications = FakeNotifications()
            monitor = PerformanceMonitor(notifications, store=store, settings_path=Path(temporary) / "settings.json")
            monitor._evaluate_smart({"devices": [{"path": "/dev/sda", "smart_state": "crítico",
                                                   "indicators": ["pending sectors: 3"]}]})
            rows = store.alerts(category="disk_health")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["severity"], "Crítico")
            self.assertEqual(len(notifications.items), 1)


if __name__ == "__main__": unittest.main()
