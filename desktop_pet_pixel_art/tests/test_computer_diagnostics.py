"""Focused tests for the network monitor and system health services."""

import socket
import unittest
from types import SimpleNamespace
from unittest import mock

from computer_diagnostics import (
    NetworkSampler, SystemHealthSampler, build_computer_consultant_context,
    diagnose_system_health, run_connectivity_diagnostics,
)


class NetworkSamplerTests(unittest.TestCase):
    def sample_inputs(self, sent, received):
        return {
            "stats": {"enp0s1": SimpleNamespace(isup=True, speed=1000)},
            "addresses": {"enp0s1": [SimpleNamespace(family=socket.AF_INET, address="192.168.1.5")]},
            "counters": {"enp0s1": SimpleNamespace(bytes_sent=sent, bytes_recv=received)},
            "gateways": {"enp0s1": "192.168.1.1"}, "dns_servers": ["192.168.1.1"],
        }

    def test_rates_are_derived_between_samples_and_history_is_bounded(self):
        sampler = NetworkSampler(history_limit=2)
        first = sampler.sample(now=10, **self.sample_inputs(100, 500))
        second = sampler.sample(now=12, **self.sample_inputs(300, 1100))
        third = sampler.sample(now=13, **self.sample_inputs(400, 1200))
        self.assertIsNone(first["upload_bytes_per_second"])
        self.assertEqual(second["upload_bytes_per_second"], 100)
        self.assertEqual(second["download_bytes_per_second"], 300)
        self.assertEqual(len(third["history"]), 2)
        self.assertEqual(second["gateway"], "192.168.1.1")

    def test_diagnostics_report_individual_checks_and_cancellation(self):
        snapshot = {"connected_interfaces": 1, "gateway": None}
        sock = mock.Mock()
        sock.SOCK_STREAM = socket.SOCK_STREAM
        sock.gaierror = socket.gaierror
        sock.getaddrinfo.side_effect = socket.gaierror("offline")
        connection = mock.Mock()
        sock.create_connection.return_value = connection
        checks = run_connectivity_diagnostics(snapshot, socket_module=sock, ping_path="") ["checks"]
        self.assertEqual([item["state"] for item in checks], ["Conectada", "Indisponível", "Falha nesta consulta", "Conexão TCP estabelecida"])
        connection.close.assert_called_once()
        cancelled = mock.Mock(is_set=mock.Mock(return_value=True))
        result = run_connectivity_diagnostics(snapshot, cancel_event=cancelled, socket_module=sock)
        self.assertTrue(result["cancelled"])
        self.assertEqual(len(result["checks"]), 1)


class HealthDiagnosisTests(unittest.TestCase):
    def test_health_findings_and_consultant_context_are_evidence_based(self):
        snapshot = {
            "memory_percent": 96, "memory_available": 100, "memory_total": 10000,
            "cpu_percent": 94, "disk_percent": 98, "disk_free": 20,
            "temperature_c": None,
            "processes": [{"pid": 12, "name": "worker", "cpu_percent": 85, "memory_bytes": 10}],
        }
        findings = diagnose_system_health(snapshot)
        self.assertGreaterEqual(len(findings), 3)
        context = build_computer_consultant_context(snapshot, {"connection_state": "local"})
        self.assertEqual(context["schema"], "computer-health-context.v1")
        self.assertEqual(context["top_processes"][0]["pid"], 12)
        self.assertEqual(context["network"]["connection_state"], "local")
        self.assertIsNone(context["system"]["temperature_c"])

    def test_process_sample_respects_process_limit_and_sensor_absence(self):
        memory = SimpleNamespace(total=1000, used=600, available=400, percent=60)
        disk = SimpleNamespace(total=1000, used=400, free=600, percent=40)
        fake_psutil = SimpleNamespace(
            virtual_memory=lambda: memory, disk_usage=lambda _p: disk,
            cpu_percent=lambda interval: 12.5, sensors_temperatures=lambda **_kw: {},
            process_iter=lambda **_kw: iter(()), Error=OSError,
        )
        with mock.patch.dict("sys.modules", {"psutil": fake_psutil}):
            snapshot = SystemHealthSampler().sample()
        self.assertIsNone(snapshot["temperature_c"])
        self.assertEqual(snapshot["processes"], [])
        self.assertEqual(snapshot["cpu_percent"], 12.5)


if __name__ == "__main__":
    unittest.main()
