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

import desktop_pet
import ollama_client
from ollama_client import ask_local_ai, load_history, save_history
from x11_helper import X11Helper


class PersistenceTests(unittest.TestCase):
    def test_history_handles_invalid_and_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            path.write_text("{not valid json}", encoding="utf-8")
            self.assertEqual(load_history(path), [])
            backup = next(Path(tmpdir).glob("history.json.corrupt-*"))
            self.assertEqual(backup.read_text(encoding="utf-8"), "{not valid json}")

            history = [{"role": "user", "content": "Oi"}]
            self.assertTrue(save_history(history, path))
            self.assertEqual(backup.read_text(encoding="utf-8"), "{not valid json}")
            self.assertEqual(load_history(path), history)
    def test_history_rejects_invalid_shapes_and_filters_invalid_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            for invalid_json_value in ('{"role": "user"}', "42", "null"):
                with self.subTest(value=invalid_json_value):
                    path.write_text(invalid_json_value, encoding="utf-8")
                    self.assertEqual(load_history(path), [])

            path.write_text(
                json.dumps([
                    {"role": "user", "content": "Oi"},
                    {"role": "system", "content": "instrução"},
                    {"role": "assistant", "content": 42},
                    "mensagem inválida",
                ]),
                encoding="utf-8",
            )
            self.assertEqual(
                load_history(path),
                [{"role": "user", "content": "Oi"}],
            )
    def test_history_handles_missing_unreadable_files_and_save_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "missing.json"
            self.assertEqual(load_history(missing_path), [])

            unreadable_path = Path(tmpdir) / "unreadable.json"
            unreadable_path.write_text("[]", encoding="utf-8")
            with mock.patch.object(Path, "read_text", side_effect=OSError("sem acesso")):
                self.assertEqual(load_history(unreadable_path), [])
            self.assertFalse(save_history([], unreadable_path))
            self.assertEqual(unreadable_path.read_text(encoding="utf-8"), "[]")

            invalid_save_path = Path(tmpdir) / "missing" / "history.json"
            with self.assertLogs(ollama_client.logger, level="WARNING"):
                self.assertFalse(save_history([], invalid_save_path))
    def test_ask_local_ai_parses_successful_response(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": "  Olá!  "}}
        ).encode("utf-8")
        with mock.patch("ollama_client.urllib.request.urlopen", return_value=response) as urlopen:
            answer = ask_local_ai([{"role": "user", "content": "Oi"}])

        self.assertEqual(answer, "Olá!")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 60)
    def test_ask_local_ai_includes_user_selected_memories_in_system_context(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": "Certo."}}
        ).encode("utf-8")
        with mock.patch("ollama_client.urllib.request.urlopen", return_value=response) as urlopen:
            ask_local_ai([], memories=["Prefere respostas curtas"])
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertIn("Prefere respostas curtas", payload["messages"][0]["content"])
    def test_ask_local_ai_explains_connection_errors(self):
        with mock.patch(
            "ollama_client.urllib.request.urlopen",
            side_effect=ollama_client.urllib.error.URLError("offline"),
        ):
            answer = ask_local_ai([], model_name="modelo-teste")

        self.assertIn("Ollama", answer)
        self.assertIn("modelo-teste", answer)
    def test_x11_helper_is_safe_when_optional_dependency_is_unavailable(self):
        with mock.patch("x11_helper.XLIB_AVAILABLE", False):
            helper = X11Helper()

        self.assertFalse(helper.ok)
        self.assertEqual(helper.get_open_windows(), [])
        self.assertIsNone(helper.get_active_window_info())
        self.assertFalse(helper.window_exists(0))
    def test_x11_helper_returns_safe_values_when_display_is_unavailable(self):
        with mock.patch("x11_helper.XLIB_AVAILABLE", True), mock.patch(
            "x11_helper.xlib_display.Display", side_effect=OSError("sem display")
        ):
            helper = X11Helper()

        self.assertFalse(helper.ok)
        self.assertEqual(helper.get_open_windows(), [])
        self.assertIsNone(helper.get_active_window_info())
        self.assertFalse(helper.window_exists(0))
