import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import MOVEMENTS_DIR, MOVEMENT_VIDEOS, SYSTEM_PROMPT, resolve_movement_path
from autonomy import (
    find_installed_apps,
    is_quiet_now,
    load_settings,
    resolve_app_command,
    save_settings,
    valid_reminder_time,
)
from desktop_pet import DesktopPet
import ollama_client
from ollama_client import ask_local_ai, load_history, save_history
from x11_helper import X11Helper


class TestHelperModules(unittest.TestCase):
    def test_autonomy_settings_round_trip_and_recover_invalid_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            settings = load_settings(path)
            settings["mode"] = "proativa"
            settings["memories"] = ["Prefere respostas curtas"]
            settings["apps"] = [
                {"name": "Editor", "command": "editor"},
                {"name": 42, "command": ""},
            ]
            self.assertTrue(save_settings(settings, path))
            self.assertEqual(load_settings(path)["memories"], ["Prefere respostas curtas"])
            self.assertEqual(load_settings(path)["apps"], [{"name": "Editor", "command": "editor"}])
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_settings(path)["mode"], "companhia")

    def test_focus_and_routine_settings_are_sanitized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text(
                json.dumps({"focus_minutes": 999, "break_minutes": 0, "evening_time": "25:99"}),
                encoding="utf-8",
            )
            settings = load_settings(path)
        self.assertEqual(settings["focus_minutes"], 180)
        self.assertEqual(settings["break_minutes"], 1)
        self.assertEqual(settings["evening_time"], "20:30")

    def test_quiet_hours_support_daytime_and_overnight_ranges(self):
        self.assertTrue(is_quiet_now("09:00", "17:00", datetime(2026, 1, 1, 12, 0)))
        self.assertFalse(is_quiet_now("09:00", "17:00", datetime(2026, 1, 1, 18, 0)))
        self.assertTrue(is_quiet_now("22:00", "08:00", datetime(2026, 1, 1, 23, 0)))
        self.assertTrue(is_quiet_now("22:00", "08:00", datetime(2026, 1, 1, 7, 0)))
        self.assertFalse(is_quiet_now("22:00", "08:00", datetime(2026, 1, 1, 12, 0)))

    def test_reminder_time_parser_rejects_invalid_dates(self):
        self.assertIsNotNone(valid_reminder_time("2026-12-31T23:59"))
        self.assertIsNone(valid_reminder_time("tomorrow"))

    def test_registered_app_matching_requires_an_opening_intent(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.settings = {"apps": [{"name": "Editor", "command": "editor"}]}
        self.assertEqual(pet._matching_app("abrir Editor"), pet.settings["apps"][0])
        self.assertIsNone(pet._matching_app("o Editor está aberto"))

    def test_app_command_parser_checks_executable_without_using_a_shell(self):
        command = f'"{sys.executable}" --version'
        self.assertEqual(resolve_app_command(command), [sys.executable, "--version"])
        with self.assertRaisesRegex(ValueError, "Não encontrei o executável"):
            resolve_app_command("aplicativo-que-nao-existe-123")
        with self.assertRaisesRegex(ValueError, "caractere inválido"):
            resolve_app_command("programa\x00 --flag")

    def test_installed_app_search_reads_desktop_entries_and_filters_hidden_apps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            apps_dir = Path(tmpdir) / "applications"
            apps_dir.mkdir()
            (apps_dir / "sample.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Sample Editor\n"
                "GenericName=Text Editor\n"
                f'Exec="{sys.executable}" --new-window %U\n',
                encoding="utf-8",
            )
            (apps_dir / "hidden.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Hidden App\n"
                "Exec=python3\nNoDisplay=true\n",
                encoding="utf-8",
            )

            results = find_installed_apps("text", [apps_dir])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Sample Editor")
        self.assertEqual(resolve_app_command(results[0]["command"]), [sys.executable, "--new-window"])


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

    def test_focus_cycle_uses_rest_pose_then_celebrates_and_returns_to_walking(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.focus_mode = "idle"
        pet.focus_goal = ""
        pet.focus_minutes = 25
        pet.break_minutes = 5
        pet._focus_job = None
        pet._closing = False
        pet.ai_request_active = False
        pet.dragging = False
        pet.state = "walk"
        pet.sit_win_id = 123
        pet.root = mock.Mock()
        pet.show_bubble = mock.Mock()

        self.assertTrue(pet.start_focus("Estudar Python", 5, 1))
        self.assertEqual((pet.focus_mode, pet.state, pet.sit_win_id), ("focus", "focused", None))
        pet.finish_focus()
        self.assertEqual((pet.focus_mode, pet.state), ("break", "sitting"))
        pet.finish_break()
        self.assertEqual((pet.focus_mode, pet.state, pet.focus_goal), ("idle", "celebrating", ""))
        self.assertEqual(pet._video_for_current_pose(), "wave")
        pet.finish_celebration()
        self.assertEqual((pet.focus_mode, pet.state, pet.focus_goal), ("idle", "walk", ""))

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


if __name__ == "__main__":
    unittest.main()
