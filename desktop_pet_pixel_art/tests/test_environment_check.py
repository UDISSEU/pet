import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import environment_check


class _Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit=-1):
        return json.dumps(self.value).encode("utf-8")


class EnvironmentCheckTests(unittest.TestCase):
    def test_ollama_reports_ready_only_when_configured_model_is_listed(self):
        with mock.patch("environment_check.shutil.which", return_value="/usr/bin/ollama"), \
             mock.patch(
                 "environment_check.urllib.request.urlopen",
                 return_value=_Response({"models": [{"name": "llama3.2:1b"}]}),
             ) as open_url:
            status = environment_check._check_ollama(
                "llama3.2:1b", "http://localhost:11434/api/chat"
            )
        self.assertEqual(status, "ready")
        open_url.assert_called_once()
        self.assertEqual(open_url.call_args.args[0], "http://localhost:11434/api/tags")

    def test_ollama_states_distinguish_missing_model_and_stopped_service(self):
        with mock.patch("environment_check.shutil.which", return_value="/usr/bin/ollama"), \
             mock.patch(
                 "environment_check.urllib.request.urlopen",
                 return_value=_Response({"models": []}),
             ):
            self.assertEqual(
                environment_check._check_ollama(
                    "llama3.2:1b", "http://localhost:11434/api/chat"
                ),
                "model_missing",
            )
        with mock.patch("environment_check.shutil.which", return_value="/usr/bin/ollama"), \
             mock.patch(
                 "environment_check.urllib.request.urlopen",
                 side_effect=urllib.error.URLError("not running"),
             ):
            self.assertEqual(
                environment_check._check_ollama(
                    "llama3.2:1b", "http://localhost:11434/api/chat"
                ),
                "installed_not_running",
            )

    def test_missing_ollama_is_optional_and_never_uses_remote_network(self):
        with mock.patch("environment_check.shutil.which", return_value=None), \
             mock.patch(
                 "environment_check.urllib.request.urlopen",
                 side_effect=AssertionError("remote endpoint must not be queried"),
             ) as open_url:
            status = environment_check._check_ollama(
                "llama3.2:1b", "https://example.com/api/chat"
            )
        self.assertEqual(status, "unavailable")
        open_url.assert_not_called()

    def test_environment_snapshot_includes_required_statuses_and_existing_assets(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("environment_check._module_available", return_value=True), \
             mock.patch("environment_check._check_ollama", return_value="not_installed"), \
             mock.patch("environment_check.os.cpu_count", return_value=2), \
             mock.patch("environment_check.sys.version_info", SimpleNamespace(
                 major=3, minor=12, micro=3,
             )):
            report = environment_check.check_environment(home=Path(directory))
        self.assertTrue(report.can_continue)
        self.assertEqual(report.ollama_status, "not_installed")
        self.assertEqual(report.graphics_available, report.graphics_total)
        self.assertEqual(report.personality_status, "available")
        self.assertEqual(report.database_status, "not_created")
        self.assertEqual(report.cpu_count, 2)
        state = report.to_installation_state()
        self.assertEqual(len(state["dependencies_verified"]), 4)

    def test_database_diagnostic_does_not_mutate_corrupt_profile_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".config" / "desktop_pet"
            config.mkdir(parents=True)
            registry = config / "user_profiles.json"
            registry.write_text("{broken", encoding="utf-8")
            before = set(config.iterdir())
            status = environment_check._check_existing_database(Path(directory))
            self.assertEqual(status, "profile_registry_invalid")
            self.assertEqual(registry.read_text(encoding="utf-8"), "{broken")
            self.assertEqual(set(config.iterdir()), before)

    def test_database_diagnostic_checks_selected_profile_without_creating_data(self):
        profile_id = "a" * 32
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / ".config" / "desktop_pet"
            config.mkdir(parents=True)
            (config / "user_profiles.json").write_text(json.dumps({
                "version": 1,
                "active_profile_id": profile_id,
                "profiles": [
                    {"profile_id": "legacy", "name": "Principal"},
                    {"profile_id": profile_id, "name": "Perfil ativo"},
                ],
            }), encoding="utf-8")
            status = environment_check._check_existing_database(Path(directory))
            self.assertEqual(status, "not_created")
            self.assertFalse((config / "profiles").exists())

    def test_unsupported_python_blocks_continue(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch("environment_check._module_available", return_value=True), \
             mock.patch("environment_check._check_ollama", return_value="not_installed"), \
             mock.patch("environment_check.sys.version_info", SimpleNamespace(
                 major=3, minor=9, micro=0,
             )):
            report = environment_check.check_environment(home=Path(directory))
        self.assertFalse(report.python_supported)
        self.assertFalse(report.can_continue)


if __name__ == "__main__":
    unittest.main()
