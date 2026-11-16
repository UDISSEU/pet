"""Focused tests for factual computer context and privacy-safe action history."""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import computer_consultant as consultant
from computer_consultant import ActionHistoryStore, collect_computer_context, consultant_context_memory


class ActionHistoryTests(unittest.TestCase):
    def test_persistent_bounded_actions_keep_metadata_without_prompt_content(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state" / "actions.sqlite3"
            store = ActionHistoryStore(path, limit=10)
            for i in range(14):
                store.record("consultor.computador", "Em andamento", origin="Meu Computador",
                             result=f"Resultado {i}")
            store.update(14, "Concluída", result="Respondida")
            rows = ActionHistoryStore(path, limit=10).list()
            self.assertEqual(len(rows), 10)
            self.assertEqual(rows[0]["status"], "Concluída")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertNotIn("question", rows[0])
            self.assertNotIn("token secreto", str(rows))

    def test_action_state_validation_rejects_unknown_values(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ActionHistoryStore(Path(temp) / "actions.sqlite3")
            with self.assertRaises(ValueError):
                store.record("consultor", "executada automaticamente")

    def test_existing_dispatcher_outcomes_are_persisted_in_user_facing_states(self):
        with tempfile.TemporaryDirectory() as temp:
            store = ActionHistoryStore(Path(temp) / "actions.sqlite3")
            store.record("files.organize_downloads", "succeeded", error_code=None)
            store.record("files.preview_downloads", "failed", error_code="authorization_required")
            self.assertEqual([row["status"] for row in store.list()], ["Aguardando autorização", "Concluída"])


class ContextTests(unittest.TestCase):
    def test_partial_source_failure_preserves_other_facts_and_marks_source_unavailable(self):
        health = {"cpu_percent": 30, "memory_percent": 50, "processes": [], "issues": []}
        with mock.patch.object(consultant, "collect_overview", return_value={"cpu_name": "CPU", "hostname": "private-host"}), \
             mock.patch.object(consultant, "_health_snapshot", return_value=health), \
             mock.patch.object(consultant, "_network", side_effect=PermissionError), \
             mock.patch.object(consultant, "performance_context", return_value={"samples": 1}), \
             mock.patch.object(consultant, "discover_startup_entries", return_value=[]):
            class Store:
                def alerts(self, limit=20): return []
            data = collect_computer_context("Minha conexão de rede está funcionando?", performance_store=Store())
        self.assertEqual(data["sources"]["hardware"]["data"]["cpu_name"], "CPU")
        self.assertNotIn("hostname", data["sources"]["hardware"]["data"])
        self.assertEqual(data["sources"]["network"]["state"], "unavailable")
        self.assertEqual(data["sources"]["network"]["reason"], "PermissionError")
        self.assertEqual(data["sources"]["performance"]["data"]["samples"], 1)

    def test_unavailable_context_is_explicit_and_prompt_memory_is_bounded(self):
        health = {"cpu_percent": None, "memory_percent": None, "processes": [], "issues": []}
        with mock.patch.object(consultant, "collect_overview", side_effect=OSError), \
             mock.patch.object(consultant, "_health_snapshot", return_value=health):
            data = collect_computer_context("Por que meu computador está lento?")
        self.assertEqual(data["sources"]["hardware"]["state"], "unavailable")
        self.assertEqual(data["sources"]["performance"]["state"], "unavailable")
        memory = consultant_context_memory({"sample": "x" * 20000})
        self.assertLessEqual(len(memory), consultant.MAX_CONTEXT_CHARS + len("[Dados observados do computador, coletados para esta pergunta; campos ausentes ou indisponíveis não devem ser inferidos] "))
        self.assertIn("campos ausentes ou indisponíveis", memory)

    def test_cancellation_is_reported_after_current_collector_returns(self):
        cancellation = threading.Event()
        def collect_then_cancel():
            cancellation.set()
            return {"cpu_percent": 10}
        with mock.patch.object(consultant, "collect_overview", side_effect=collect_then_cancel):
            result = collect_computer_context("estado", cancel_event=cancellation)
        self.assertTrue(result["cancelled"])
        self.assertNotIn("system", result["sources"])

    def test_installed_inventory_uses_existing_package_source_merger(self):
        source_data = {
            "package_versions": {}, "package_owners": {}, "flatpak_output": "",
            "apt_upgradable": [], "flatpak_update_output": "", "snap_output": "",
            "snap_update_output": "", "checked_sources": {"Flatpak"},
            "apt_owners_checked": True, "apt_applications": [], "snap_applications": [],
            "source_results": {"APT/DEB": {"inventory_complete": False, "updates_complete": False},
                               "Flatpak": {"inventory_complete": True, "updates_complete": True},
                               "Snap": {"inventory_complete": True, "updates_complete": True}},
        }
        row = {"name": "Exemplo", "version": "1.2", "source": "Flatpak",
               "candidate_version": "—", "update_status": "Atualizado"}
        with mock.patch("system_updates.query_installed_app_sources", return_value=source_data) as query, \
             mock.patch("system_updates.build_installed_app_inventory", return_value=[row]):
            result = consultant._applications(lambda: [{"name": "Exemplo", "desktop_file": "/tmp/example.desktop"}])
        query.assert_called_once()
        self.assertEqual(result["items"][0]["source"], "Flatpak")
        self.assertEqual(result["unavailable_sources"], ["APT/DEB"])

    def test_context_omits_process_usernames_and_home_paths(self):
        sample = {"cpu_percent": 50, "memory_percent": 70, "memory_used": 70,
                  "memory_total": 100, "memory_available": 30, "disk_percent": 10,
                  "disk_free": 90, "disk_total": 100, "temperature_c": None,
                  "issues": [], "timestamp": 1,
                  "processes": [{"name": "app", "pid": 42, "username": "private-user",
                                 "cpu_percent": 2, "memory_bytes": 4, "memory_percent": 4}]}
        with mock.patch.object(consultant, "collect_overview", return_value={"cpu_name": "CPU"}), \
             mock.patch.object(consultant.SystemHealthSampler, "sample", return_value=sample), \
             mock.patch.object(consultant, "collect_storage_overview", return_value={"path": "/home/private-user", "free": 10, "total": 20, "used": 10, "percent": 50}):
            result = collect_computer_context("Estou lento e quanto espaço livre tenho?")
        data = str(result)
        self.assertNotIn("private-user", data)


if __name__ == "__main__":
    unittest.main()
