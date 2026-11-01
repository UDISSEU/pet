import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from animation import (
    frame_index_at_elapsed,
    load_video_frames,
    load_video_preview,
    prepare_video_frames,
)
from animation_loader import AnimationLoader
from config import (
    MOVEMENT_VIDEOS,
    ONE_SHOT_VIDEOS,
    VIDEO_LOOP_WINDOWS,
    VIDEO_MAX_H,
    VIDEO_MAX_W,
)
from PIL import Image, ImageDraw


class TestAnimationLoader(unittest.TestCase):
    @staticmethod
    def frame_with_shapes(shapes):
        frame = Image.new("RGBA", (128, 128), (255, 255, 255, 255))
        draw = ImageDraw.Draw(frame)
        for box, color in shapes:
            draw.rectangle(box, fill=color)
        return frame

    def test_preview_decodes_a_renderable_idle_frame(self):
        frame = load_video_preview(MOVEMENT_VIDEOS["idle"])
        self.assertEqual(frame.size, (VIDEO_MAX_W, VIDEO_MAX_H))
        self.assertEqual(frame.mode, "RGBA")
        self.assertIsNotNone(frame.getchannel("A").getbbox())

    def test_new_animations_decode_all_frames(self):
        for name in ("focused", "reminder", "thumbs_up", "vanishing", "celebrate"):
            with self.subTest(animation=name):
                frames = load_video_frames(MOVEMENT_VIDEOS[name])
                self.assertTrue(frames)
                self.assertEqual(frames[0].size, (VIDEO_MAX_W, VIDEO_MAX_H))
                self.assertIsNotNone(frames[0].getchannel("A").getbbox())
                if name == "vanishing":
                    self.assertTrue(
                        any(frame.getchannel("A").getbbox() is None for frame in frames)
                    )

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

    def test_video_frames_share_one_crop_scale_and_feet_anchor(self):
        character = ((40, 20, 70, 100), (25, 30, 35, 255))
        prop = ((15, 5, 30, 18), (220, 30, 30, 255))
        frames = prepare_video_frames(
            [
                self.frame_with_shapes([character]),
                self.frame_with_shapes([character, prop]),
            ],
            "synthetic.mp4",
        )
        self.assertEqual(frames[0].size, (VIDEO_MAX_W, VIDEO_MAX_H))
        self.assertEqual(frames[1].size, (VIDEO_MAX_W, VIDEO_MAX_H))
        body_bounds = []
        for frame in frames:
            pixels = frame.load()
            body_pixels = [
                (x, y)
                for y in range(frame.height)
                for x in range(frame.width)
                if pixels[x, y][3] and pixels[x, y][0] < 100
                and pixels[x, y][1] < 100 and pixels[x, y][2] < 100
            ]
            body_bounds.append((
                min(x for x, _ in body_pixels),
                min(y for _, y in body_pixels),
                max(x for x, _ in body_pixels) + 1,
                max(y for _, y in body_pixels) + 1,
            ))
        self.assertEqual(body_bounds[0], body_bounds[1])

    def test_small_lower_right_watermark_does_not_change_crop(self):
        character = ((25, 20, 65, 110), (30, 30, 40, 255))
        plain = self.frame_with_shapes([character])
        marked = self.frame_with_shapes([
            character,
            ((123, 123, 123, 123), (220, 20, 160, 255)),
        ])
        self.assertEqual(
            prepare_video_frames([plain], "plain.mp4")[0].tobytes(),
            prepare_video_frames([marked], "marked.mp4")[0].tobytes(),
        )

    def test_character_touching_watermark_margin_is_not_removed(self):
        character = ((65, 70, 120, 120), (30, 30, 40, 255))
        plain = self.frame_with_shapes([character])
        marked = self.frame_with_shapes([
            character,
            ((126, 126, 126, 126), (220, 20, 160, 255)),
        ])
        self.assertEqual(
            prepare_video_frames([plain], "plain.mp4")[0].tobytes(),
            prepare_video_frames([marked], "near-corner.mp4")[0].tobytes(),
        )

    def test_loop_window_and_one_shot_frame_selection(self):
        self.assertEqual(
            frame_index_at_elapsed(0, 10, (0.2, 0.6), fps=10), 2
        )
        self.assertEqual(
            frame_index_at_elapsed(300, 10, (0.2, 0.6), fps=10), 5
        )
        self.assertEqual(
            frame_index_at_elapsed(400, 10, (0.2, 0.6), fps=10), 2
        )
        self.assertEqual(
            frame_index_at_elapsed(5000, 10, one_shot=True, fps=10), 9
        )
        self.assertEqual(
            set(VIDEO_LOOP_WINDOWS), set(MOVEMENT_VIDEOS) - ONE_SHOT_VIDEOS
        )
        for start, end in VIDEO_LOOP_WINDOWS.values():
            self.assertGreaterEqual(start, 0)
            self.assertGreater(end, start)
            self.assertLessEqual(end, 8.1)


if __name__ == "__main__":
    unittest.main()
