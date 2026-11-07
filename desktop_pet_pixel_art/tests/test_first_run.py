import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from first_run import run_first_access_if_needed
from installation_state import InstallationStateError, InstallationStateStore
from environment_check import EnvironmentReport


_REPORT = EnvironmentReport(
    python_version="3.12.3",
    python_supported=True,
    dependencies={"Pillow": True, "OpenCV": True, "NumPy": True, "psutil": True},
    ollama_status="not_installed",
    selected_model="llama3.2:1b",
    database_status="not_created",
    personality_status="available",
    graphics_status="ready",
    graphics_available=16,
    graphics_total=16,
    free_disk_bytes=2 * 1024 ** 3,
    memory_total_bytes=4 * 1024 ** 3,
    cpu_count=2,
)


class InstallationStateTests(unittest.TestCase):
    def test_initial_state_is_incomplete_and_has_expected_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            state = InstallationStateStore(Path(directory) / "installation.json").load()
        self.assertFalse(state["setup_completed"])
        self.assertEqual(state["ollama_status"], "not_checked")
        self.assertEqual(state["dependencies_verified"], {})
        self.assertEqual(state["database_status"], "not_checked")

    def test_setup_completion_is_idempotent_and_uses_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config" / "installation.json"
            store = InstallationStateStore(path)
            first = store.complete_first_run()
            second = store.complete_first_run()
            self.assertTrue(first["setup_completed"])
            self.assertTrue(second["setup_completed"])
            self.assertIsNotNone(second["last_configured_at"])
            self.assertEqual(store.load(), second)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_update_preserves_other_state_and_rejects_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InstallationStateStore(Path(directory) / "installation.json")
            store.update(ollama_status="unavailable", selected_model="llama3.2:1b")
            self.assertEqual(store.load()["selected_model"], "llama3.2:1b")
            with self.assertRaises(ValueError):
                store.update(user_name="not installation state")

    def test_corrupt_state_is_preserved_and_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "installation.json"
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(InstallationStateError, "cópia foi preservada"):
                InstallationStateStore(path).load()
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")
            self.assertEqual(len(list(Path(directory).glob("installation.json.corrupt-*"))), 1)

    def test_symlink_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.json"
            target.write_text(json.dumps({"state_version": 1}), encoding="utf-8")
            link = Path(directory) / "installation.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(InstallationStateError, "link simbólico"):
                InstallationStateStore(link).load()


class FirstAccessTests(unittest.TestCase):
    def test_first_access_shows_welcome_and_persists_only_after_continue(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InstallationStateStore(Path(directory) / "installation.json")
            with mock.patch("first_run.check_environment", return_value=_REPORT), \
                 mock.patch("first_run._show_welcome_window", return_value=True) as welcome:
                self.assertTrue(run_first_access_if_needed("/app/nova.png", state_store=store))
            welcome.assert_called_once_with("/app/nova.png", _REPORT)
            state = store.load()
            self.assertTrue(state["setup_completed"])
            self.assertEqual(state["ollama_status"], "not_installed")
            self.assertEqual(state["graphics_status"], "ready")

    def test_cancel_does_not_complete_setup_and_welcome_reappears(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InstallationStateStore(Path(directory) / "installation.json")
            with mock.patch("first_run.check_environment", return_value=_REPORT), \
                 mock.patch("first_run._show_welcome_window", return_value=False) as welcome:
                self.assertFalse(run_first_access_if_needed(state_store=store))
                self.assertFalse(run_first_access_if_needed(state_store=store))
            self.assertEqual(welcome.call_count, 2)
            self.assertFalse(store.load()["setup_completed"])

    def test_completed_setup_skips_welcome(self):
        with tempfile.TemporaryDirectory() as directory:
            store = InstallationStateStore(Path(directory) / "installation.json")
            store.complete_first_run()
            with mock.patch("first_run.check_environment") as checker, \
                 mock.patch("first_run._show_welcome_window") as welcome:
                self.assertTrue(run_first_access_if_needed(state_store=store))
            checker.assert_not_called()
            welcome.assert_not_called()


if __name__ == "__main__":
    unittest.main()
