#!/usr/bin/env python3
"""Print low-difference loop windows for the movement videos."""

import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from animation import load_video_frames
from config import MOVEMENT_VIDEOS, ONE_SHOT_VIDEOS, VIDEO_FRAME_RATE


MIN_WINDOW_FRAMES = round(1.5 * VIDEO_FRAME_RATE)
MAX_WINDOW_FRAMES = round(3.0 * VIDEO_FRAME_RATE)


def best_loop_window(filename):
    frames = load_video_frames(filename)
    samples = np.asarray(
        [np.asarray(frame)[::8, ::8, :3] for frame in frames],
        dtype=np.int16,
    )
    best = None
    for window_frames in range(
        MIN_WINDOW_FRAMES, min(MAX_WINDOW_FRAMES, len(frames) - 1) + 1
    ):
        starts = np.arange(len(frames) - window_frames)
        differences = np.abs(
            samples[starts] - samples[starts + window_frames]
        ).mean(axis=(1, 2, 3))
        candidate_index = int(np.argmin(differences))
        candidate = (
            float(differences[candidate_index]),
            int(starts[candidate_index]),
            window_frames,
        )
        if best is None or candidate < best:
            best = candidate
    if best is None:
        raise ValueError(f"{filename} is too short for a 1.5-second loop.")
    score, start_frame, window_frames = best
    return (
        start_frame / VIDEO_FRAME_RATE,
        (start_frame + window_frames) / VIDEO_FRAME_RATE,
        score,
    )


def main():
    print("video,start_s,end_s,duration_s,mean_abs_difference")
    for name, filename in MOVEMENT_VIDEOS.items():
        if name in ONE_SHOT_VIDEOS:
            continue
        start, end, score = best_loop_window(filename)
        print(
            f"{name},{start:.3f},{end:.3f},{end - start:.3f},{score:.3f}"
        )


if __name__ == "__main__":
    main()
