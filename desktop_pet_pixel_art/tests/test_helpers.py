import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import MOVEMENTS_DIR, MOVEMENT_VIDEOS, resolve_movement_path
from desktop_pet import DesktopPet
from ollama_client import load_history, save_history
from x11_helper import X11Helper


class TestHelperModules(unittest.TestCase):
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

        pet.state = "walk"
        self.assertEqual(pet._video_for_current_pose(now=1), "walk_right")
        pet.walk_dx = -1
        self.assertEqual(pet._video_for_current_pose(now=1), "walk_left")

        pet.busy = True
        self.assertEqual(pet._video_for_current_pose(now=1), "wave")
        pet.state = "sitting"
        self.assertEqual(pet._video_for_current_pose(now=1), "sleep")
        pet.state = "thinking"
        self.assertEqual(pet._video_for_current_pose(now=1), "idle")
        pet.state = "walk"
        pet._irritated_until = 2
        self.assertEqual(pet._video_for_current_pose(now=1), "angry")

    def test_history_handles_invalid_and_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            path.write_text("{not valid json}", encoding="utf-8")
            self.assertEqual(load_history(path), [])

            history = [{"role": "user", "content": "Oi"}]
            save_history(history, path)
            self.assertEqual(load_history(path), history)

    def test_x11_helper_is_safe_when_optional_dependency_is_unavailable(self):
        helper = X11Helper()
        self.assertIsInstance(helper.get_open_windows(), list)
        self.assertIsInstance(helper.get_active_window_info(), (type(None), tuple))
        self.assertIsInstance(helper.window_exists(0), bool)


if __name__ == "__main__":
    unittest.main()
