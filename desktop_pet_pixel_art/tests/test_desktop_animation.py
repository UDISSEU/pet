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
import desktop_pet
from desktop_pet import DesktopPet


class DesktopAnimationTests(unittest.TestCase):
    def test_system_prompt_uses_nova_name(self):
        self.assertIn("Você é Nova", SYSTEM_PROMPT)
    def test_resolve_movement_path_finds_idle_video(self):
        filename = MOVEMENT_VIDEOS["idle"]
        resolved = resolve_movement_path(filename)
        self.assertTrue(resolved.exists())
        self.assertEqual(resolved, MOVEMENTS_DIR / filename)
    def test_new_movement_videos_are_registered(self):
        expected = {
            "focused": "estudando.mp4",
            "reminder": "lembrete_visual.mp4",
            "thumbs_up": "joinha.mp4",
            "vanishing": "desmaterializando.mp4",
            "celebrate": "dancando.mp4",
        }
        for animation, filename in expected.items():
            with self.subTest(animation=animation):
                self.assertEqual(MOVEMENT_VIDEOS[animation], filename)
                self.assertTrue(resolve_movement_path(filename).is_file())
    def test_video_selection_matches_pet_state_and_direction(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._irritated_until = 0
        pet.busy = False
        pet.walk_dx = 1
        pet.focus_mode = "idle"
        pet.state = "walk"
        pet._reminder_animation_until = 0.0
        pet.stay_in_place_var = mock.Mock()
        pet.stay_in_place_var.get.return_value = False

        pet._reminder_animation_until = 2.0
        self.assertEqual(pet._video_for_current_pose(now=1), "reminder")
        pet._reminder_animation_until = 0.0

        cases = (
            ("walking right", "walk", "walk_right", 1, False, 0),
            ("walking left", "walk", "walk_left", -1, False, 0),
            ("busy", "walk", "wave", 1, True, 0),
            ("irritated while busy", "walk", "angry", 1, True, 2),
            ("sitting", "sitting", "sleep", 1, False, 0),
            ("thinking", "thinking", "thinking", 1, False, 0),
            ("focused", "focused", "focused", 1, False, 0),
            ("thumbs up", "thumbs_up", "thumbs_up", 1, False, 0),
            ("vanishing", "vanishing", "vanishing", 1, False, 0),
            ("celebrating", "celebrating", "celebrate", 1, False, 0),
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
    def test_stale_temporary_pose_timer_cannot_override_a_newer_action(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._closing = False
        pet.state = "curious"
        stale_generation = pet._state_generation

        pet.state = "walk"
        pet.state = "curious"
        callback = mock.Mock()

        self.assertFalse(
            pet._run_pose_callback("curious", stale_generation, callback)
        )
        callback.assert_not_called()
        self.assertEqual(pet.state, "curious")
    def test_one_shot_pose_holds_its_last_video_frame(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.state = "thumbs_up"
        pet._thumbs_up_started_at = 100.0
        pet._thinking_started_at = 100.0
        pet._reminder_started_at = 100.0
        pet._vanishing_started_at = 100.0
        pet._reminder_animation_until = 0.0
        pet.video_frames = {"thumbs_up": ["first", "middle", "last"]}

        self.assertEqual(
            pet._current_video_frame(now=200.0),
            ("thumbs_up", 2, "last"),
        )
    def test_missing_video_uses_its_configured_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "wave.mp4").touch()
            with mock.patch.object(
                desktop_pet,
                "MOVEMENT_VIDEOS",
                {"talking": "talking.mp4", "wave": "wave.mp4"},
            ), mock.patch.object(
                desktop_pet,
                "resolve_movement_path",
                side_effect=lambda filename: root / filename,
            ):
                self.assertEqual(
                    DesktopPet._video_with_fallback("talking"), "wave"
                )
    def test_clicking_a_resting_nova_uses_a_wake_line_and_wave(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._pending_click_job = "click-timer"
        pet._interaction_speech_allowed = mock.Mock(return_value=True)
        pet._show_personality_line = mock.Mock(return_value=True)
        pet._schedule_pose_return = mock.Mock()
        pet.state = "sitting"

        pet._finish_simple_click()

        self.assertEqual(pet.state, "greeting")
        pet._show_personality_line.assert_called_once_with(
            "wake", duration=2500
        )
        pet._schedule_pose_return.assert_called_once_with(
            round(desktop_pet.VIDEO_REACTION_SECONDS * 1000), "greeting"
        )
    def test_clicking_an_active_nova_uses_the_regular_click_reaction(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._pending_click_job = "click-timer"
        pet._interaction_speech_allowed = mock.Mock(return_value=True)
        pet._show_personality_line = mock.Mock(return_value=True)
        pet._schedule_pose_return = mock.Mock()
        pet.state = "walk"

        pet._finish_simple_click()

        pet._show_personality_line.assert_called_once_with(
            "click", duration=2500
        )
    def test_startup_idle_transitions_to_walking_after_the_delay(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._closing = False
        pet.state = "idle"
        pet.walk_dx = 1
        pet._startup_idle_elapsed = False
        pet._startup_walk_enabled = False
        pet._resolved_animations = set()

        pet._finish_startup_idle()

        self.assertEqual(pet.state, "idle")
        self.assertFalse(pet._startup_walk_enabled)
        pet._resolved_animations.add("walk_right")
        pet._maybe_enable_startup_walk()
        self.assertEqual(pet.state, "walk")
        self.assertTrue(pet._startup_walk_enabled)

    def test_startup_walk_waits_for_the_left_clip_when_facing_left(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._closing = False
        pet.state = "idle"
        pet.walk_dx = -1
        pet._startup_idle_elapsed = True
        pet._startup_walk_enabled = False
        pet._resolved_animations = {"walk_right"}

        pet._maybe_enable_startup_walk()

        self.assertEqual(pet.state, "idle")
        self.assertFalse(pet._startup_walk_enabled)
        pet._resolved_animations.add("walk_left")
        pet._maybe_enable_startup_walk()
        self.assertEqual(pet.state, "walk")
    def test_startup_idle_does_not_override_an_interaction(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._closing = False
        pet.state = "thinking"

        pet._finish_startup_idle()

        self.assertEqual(pet.state, "thinking")
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
        pet.settings = {"user_name": "", "routine_focus_celebration": False}
        pet._speech_history = []
        pet.busy = False
        pet._can_speak_spontaneously = mock.Mock(return_value=True)
        pet.sit_win_id = 123
        pet.root = mock.Mock()
        pet.show_bubble = mock.Mock()

        self.assertTrue(pet.start_focus("Estudar Python", 5, 1))
        self.assertEqual((pet.focus_mode, pet.state, pet.sit_win_id), ("focus", "focused", None))
        pet.finish_focus()
        self.assertEqual((pet.focus_mode, pet.state), ("break", "sitting"))
        pet.finish_break()
        self.assertEqual((pet.focus_mode, pet.state, pet.focus_goal), ("idle", "celebrating", ""))
        self.assertEqual(pet._video_for_current_pose(), "celebrate")
        pet.finish_celebration()
        self.assertEqual((pet.focus_mode, pet.state, pet.focus_goal), ("idle", "walk", ""))
