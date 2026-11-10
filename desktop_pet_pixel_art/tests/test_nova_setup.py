import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import nova_setup


class NovaSetupTests(unittest.TestCase):
    def test_dependency_probe_reports_each_import_from_the_virtual_environment(self):
        report = {name: True for name in nova_setup.REQUIRED_IMPORTS}
        report["OpenCV"] = False
        completed = mock.Mock(returncode=0, stdout=json.dumps(report))

        with mock.patch.object(nova_setup.subprocess, "run", return_value=completed) as run:
            result = nova_setup.probe_dependencies(Path("/app/.venv/bin/python"))

        self.assertEqual(result, report)
        self.assertEqual(run.call_args.args[0][0], "/app/.venv/bin/python")

    def test_dependency_probe_surfaces_failed_or_malformed_probe_as_not_ready(self):
        for completed in (
            mock.Mock(returncode=1, stdout=""),
            mock.Mock(returncode=0, stdout="not json"),
        ):
            with self.subTest(completed=completed.returncode), mock.patch.object(
                nova_setup.subprocess, "run", return_value=completed
            ):
                self.assertEqual(
                    nova_setup.probe_dependencies("python"),
                    {name: False for name in nova_setup.REQUIRED_IMPORTS},
                )

    def test_ollama_status_checks_installed_model_using_local_service(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({
            "models": [{"name": "llama3.2:1b"}],
        }).encode()

        with mock.patch.object(nova_setup.urllib.request, "urlopen", return_value=response) as open_url:
            status = nova_setup.ollama_status("llama3.2:1b")

        self.assertIn("está instalado", status)
        self.assertEqual(
            open_url.call_args.args[0],
            "http://127.0.0.1:11434/api/tags",
        )

    def test_ollama_status_rejects_invalid_model_names_without_network_access(self):
        with mock.patch.object(nova_setup.urllib.request, "urlopen") as open_url:
            status = nova_setup.ollama_status("../other-service/model")

        self.assertIn("inválido", status)
        open_url.assert_not_called()

    def test_refresh_status_checks_ollama_off_the_ui_thread(self):
        window = nova_setup.SetupWindow.__new__(nova_setup.SetupWindow)
        window.dependency_results = {name: True for name in nova_setup.REQUIRED_IMPORTS}
        window.dependency_labels = {
            name: mock.Mock() for name in nova_setup.REQUIRED_IMPORTS
        }
        window.operation = None
        window.install_button = mock.Mock()
        window.launch_button = mock.Mock()
        window.pull_button = mock.Mock()
        window.model = mock.Mock()
        window.model.get.return_value = "llama3.2:1b"
        window.ollama_status = mock.Mock()
        window.status_results = queue.Queue()
        window._status_generation = 0

        with (
            mock.patch.object(nova_setup, "system_prerequisites", return_value={"ready": True}),
            mock.patch.object(nova_setup.shutil, "which", return_value="/usr/bin/ollama"),
            mock.patch.object(nova_setup.threading, "Thread") as thread,
            mock.patch.object(nova_setup, "ollama_status") as check,
        ):
            window._refresh_status()

            check.assert_not_called()
            thread.return_value.start.assert_called_once()
            target = thread.call_args.kwargs["target"]
            target(*thread.call_args.kwargs["args"])
            check.assert_called_once_with("llama3.2:1b")
        self.assertEqual(
            window.status_results.get_nowait(),
            (1, check.return_value),
        )

    def test_install_requires_confirmation_and_targets_only_the_project_venv(self):
        window = nova_setup.SetupWindow.__new__(nova_setup.SetupWindow)
        window.root = mock.Mock()
        window.messagebox = mock.Mock()
        window.messagebox.askyesno.return_value = True
        window._start_process = mock.Mock()

        with (
            mock.patch.object(nova_setup, "system_prerequisites", return_value={"ready": True}),
            mock.patch.object(nova_setup, "VENV_DIR", Path("/project/.venv")),
        ):
            window.install_dependencies()

        window.messagebox.askyesno.assert_called_once()
        command = window._start_process.call_args.args[1]
        self.assertEqual(command, [str(nova_setup.INSTALLER), "--yes"])
        self.assertNotIn("sudo", command)

    def test_setup_completion_requires_an_explicit_true_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "installation_state.json"
            with mock.patch.object(nova_setup, "STATE_PATH", path):
                self.assertFalse(nova_setup._setup_completed())
                path.write_text('{"setup_completed": "true"}', encoding="utf-8")
                self.assertFalse(nova_setup._setup_completed())
                path.write_text('{"setup_completed": true}', encoding="utf-8")
                self.assertTrue(nova_setup._setup_completed())

    def test_launcher_reports_missing_tkinter_instead_of_skipping_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            with (
                mock.patch.object(nova_setup, "VENV_DIR", Path(temporary)),
                mock.patch.object(
                    nova_setup,
                    "system_prerequisites",
                    return_value={
                        "Python 3.10+": True,
                        "módulo venv": True,
                        "Tkinter": False,
                    },
                ),
                mock.patch.object(
                    nova_setup,
                    "probe_dependencies",
                    return_value={
                        name: True for name in nova_setup.REQUIRED_IMPORTS
                    },
                ),
                mock.patch.object(nova_setup, "_setup_completed", return_value=True),
                mock.patch.object(nova_setup.os, "execv") as execv,
                mock.patch("builtins.print"),
            ):
                result = nova_setup.main()

        self.assertEqual(result, 1)
        execv.assert_not_called()

    def test_closing_during_model_download_requests_cancellation(self):
        window = nova_setup.SetupWindow.__new__(nova_setup.SetupWindow)
        window.operation = None
        window.cancel_operation = threading.Event()
        window.messagebox = mock.Mock()
        window.messagebox.askyesno.return_value = True
        window.root = mock.Mock()
        window.process = None
        window.closing = False
        window._refresh_status = mock.Mock()
        window.progress = mock.Mock()
        window._append_log = mock.Mock()
        window._app_environment = mock.Mock(return_value={})
        process = mock.Mock()
        process.stdout = []
        process.wait.return_value = -15

        with (
            mock.patch.object(nova_setup.threading, "Thread") as thread,
            mock.patch.object(nova_setup.subprocess, "Popen", return_value=process),
        ):
            window._start_process("pull", ["ollama", "pull", "model"], "downloading")
            window.close()
            thread.call_args.kwargs["target"]()

        self.assertTrue(window.cancel_operation.is_set())
        process.terminate.assert_called_once()
        window.root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
