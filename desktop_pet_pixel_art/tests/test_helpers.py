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

from config import MOVEMENTS_DIR, MOVEMENT_VIDEOS, SYSTEM_PROMPT, resolve_movement_path
from desktop_pet import DesktopPet
import ollama_client
from ollama_client import ask_local_ai, load_history, save_history
from x11_helper import X11Helper


class TestHelperModules(unittest.TestCase):
    def test_system_prompt_uses_nova_name(self):
        self.assertIn("Você é Nova", SYSTEM_PROMPT)

    def test_resolve_movement_path_finds_idle_video(self):
        filename = MOVEMENT_VIDEOS["idle"]
        resolved = resolve_movement_path(filename)
        self.assertTrue(resolved.exists())
        self.assertEqual(resolved, MOVEMENTS_DIR / filename)

    def test_video_selection_matches_pet_state_and_direction(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._irritated_until = 0
        pet.busy = False
        pet.walk_dx = 1
        pet.stay_in_place_var = mock.Mock()
        pet.stay_in_place_var.get.return_value = False

        cases = (
            ("walking right", "walk", "walk_right", 1, False, 0),
            ("walking left", "walk", "walk_left", -1, False, 0),
            ("busy", "walk", "wave", 1, True, 0),
            ("irritated while busy", "walk", "angry", 1, True, 2),
            ("sitting", "sitting", "sleep", 1, False, 0),
            ("thinking", "thinking", "thinking", 1, False, 0),
            ("held", "held", "idle", 1, False, 0),
            ("unknown state", "unknown", "idle", 1, False, 0),
        )
        for label, state, expected, direction, busy, irritated_until in cases:
            with self.subTest(state=label):
                pet.state = state
                pet.walk_dx = direction
                pet.busy = busy
                pet._irritated_until = irritated_until
                self.assertEqual(pet._video_for_current_pose(now=1), expected)

    def test_staying_in_place_uses_idle_pose(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.state = "walk"
        pet.busy = False
        pet.walk_dx = 1
        pet._irritated_until = 0
        pet.stay_in_place_var = mock.Mock()
        pet.stay_in_place_var.get.return_value = True

        self.assertEqual(pet._video_for_current_pose(now=1), "idle")

    def test_question_dialog_is_placed_to_the_right_when_there_is_room(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.x = 100
        pet.y = 200
        pet.cur_height = 190
        pet.screen_w = 1200
        pet.screen_h = 800

        x, y, width, height = pet._question_dialog_geometry()

        self.assertEqual((x, width, height), (248, 420, 230))
        self.assertEqual(y, 180)
        self.assertGreaterEqual(x, pet.x + 140 + 8)

    def test_question_dialog_uses_left_side_at_right_screen_edge(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.x = 1000
        pet.y = 700
        pet.cur_height = 190
        pet.screen_w = 1200
        pet.screen_h = 800

        x, y, width, height = pet._question_dialog_geometry()

        self.assertEqual((x, width, height), (572, 420, 230))
        self.assertEqual(y, 570)
        self.assertLessEqual(x + width, pet.x - 8)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(y + height, pet.screen_h)

    def test_staying_in_place_prevents_movement(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._last_tick_at = 10.0
        pet.animation_time_ms = 0.0
        pet.step = 0
        pet._logic_accumulator = 0.0
        pet.dragging = False
        pet.drag_tilt = 0.0
        pet.drag_target_tilt = 0.0
        pet.state = "walk"
        pet.busy = False
        pet.stay_in_place_var = mock.Mock()
        pet.stay_in_place_var.get.return_value = True
        pet.walk_dx = 1
        pet.walk_dy = 0
        pet._next_walk_direction_change_at = 100.0
        pet.x = 50.0
        pet.y = 75.0
        pet.screen_w = 800
        pet.screen_h = 600
        pet.cur_height = 190
        pet._window_x = 50
        pet._window_y = 75
        pet._irritated_started_at = 0.0
        pet._irritated_until = 0.0
        pet.sit_win_id = None
        pet.behind_mode = False
        pet._next_tick_at = 10.016
        pet.root = mock.Mock()
        pet.render_and_show = mock.Mock()

        with mock.patch("desktop_pet.time.monotonic", return_value=10.04):
            pet.tick()

        self.assertEqual((pet.x, pet.y), (50.0, 75.0))
        pet.root.geometry.assert_not_called()

    def test_history_handles_invalid_and_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            path.write_text("{not valid json}", encoding="utf-8")
            self.assertEqual(load_history(path), [])

            history = [{"role": "user", "content": "Oi"}]
            self.assertTrue(save_history(history, path))
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


if __name__ == "__main__":
    unittest.main()
