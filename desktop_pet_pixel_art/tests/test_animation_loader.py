import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from animation import load_video_preview
from animation_loader import AnimationLoader
from config import MOVEMENT_VIDEOS, VIDEO_MAX_H, VIDEO_MAX_W


class TestAnimationLoader(unittest.TestCase):
    def test_preview_decodes_a_renderable_idle_frame(self):
        frame = load_video_preview(MOVEMENT_VIDEOS["idle"])
        self.assertEqual(frame.size, (VIDEO_MAX_W, VIDEO_MAX_H))
        self.assertEqual(frame.mode, "RGBA")
        self.assertIsNotNone(frame.getchannel("A").getbbox())

    def test_full_videos_load_off_thread_and_results_are_drained(self):
        finished = threading.Event()

        def frame_loader(filename):
            if filename == "bad.mp4":
                raise OSError("private filesystem detail")
            finished.set()
            return [filename, "frame"]

        loader = AnimationLoader(
            {"idle": "idle.mp4", "bad": "bad.mp4"},
            frame_loader=frame_loader,
            preview_loader=lambda _filename: "preview",
        )
        self.assertEqual(loader.preview("idle"), "preview")
        loader.start()
        self.assertTrue(finished.wait(2))
        loader._thread.join(2)
        results = loader.drain()
        self.assertEqual(results[0], ("idle", ["idle.mp4", "frame"], None))
        self.assertEqual(results[1][0:2], ("bad", None))
        self.assertEqual(results[1][2], "OSError")
        self.assertEqual(loader.drain(), [])
        loader.close()

    def test_close_before_start_marks_loading_cancelled(self):
        calls = []
        loader = AnimationLoader(
            {"idle": "idle.mp4"},
            frame_loader=lambda filename: calls.append(filename),
            preview_loader=lambda _filename: None,
        )
        loader.close()
        loader._load_all()
        self.assertEqual(calls, [])
        self.assertEqual(loader.drain(), [])


if __name__ == "__main__":
    unittest.main()
