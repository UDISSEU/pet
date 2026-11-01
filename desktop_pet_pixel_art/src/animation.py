"""Carregamento e preparação dos quadros de animação da Nova."""

import math

import cv2
import numpy as np
from PIL import Image

from config import (
    VIDEO_FRAME_INTERVAL_MS,
    VIDEO_FRAME_RATE,
    VIDEO_DECODE_MAX_H,
    VIDEO_DECODE_MAX_W,
    VIDEO_MAX_H,
    VIDEO_MAX_W,
    resolve_movement_path,
)


def load_video_frames(filename):
    path = resolve_movement_path(filename)
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise OSError(f"Não foi possível abrir o vídeo de movimento: {path}")

    fps = capture.get(cv2.CAP_PROP_FPS)
    if not math.isfinite(fps) or fps <= 0:
        fps = VIDEO_FRAME_RATE
    frames = []
    source_frame = 0
    next_sample_at_ms = 0.0
    try:
        while True:
            success, frame = capture.read()
            if not success:
                break
            if source_frame * 1000 / fps >= next_sample_at_ms:
                height, width = frame.shape[:2]
                scale = min(
                    VIDEO_DECODE_MAX_W / width,
                    VIDEO_DECODE_MAX_H / height,
                    1.0,
                )
                if scale < 1:
                    frame = cv2.resize(
                        frame,
                        (max(1, round(width * scale)), max(1, round(height * scale))),
                        interpolation=cv2.INTER_AREA,
                    )
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                frames.append(prepare_video_frame(Image.fromarray(rgb), path.name))
                next_sample_at_ms += VIDEO_FRAME_INTERVAL_MS
            source_frame += 1
    finally:
        capture.release()

    if not frames:
        raise ValueError(f"O vídeo de movimento não contém quadros: {path}")
    return frames


def prepare_video_frame(frame, description):
    frame = remove_video_background(frame.convert("RGBA"))
    bounds = frame.getchannel("A").getbbox()
    if bounds is None:
        # Alguns vídeos, como o efeito de desmaterialização, terminam com
        # quadros vazios. Mantê-los transparentes faz parte da animação.
        return Image.new("RGBA", (VIDEO_MAX_W, VIDEO_MAX_H), (0, 0, 0, 0))
    frame = frame.crop(bounds)
    scale = min(VIDEO_MAX_W / frame.width, VIDEO_MAX_H / frame.height)
    if scale != 1:
        frame = frame.resize(
            (max(1, round(frame.width * scale)), max(1, round(frame.height * scale))),
            Image.Resampling.LANCZOS,
        )
    canvas = Image.new("RGBA", (VIDEO_MAX_W, VIDEO_MAX_H), (0, 0, 0, 0))
    canvas.alpha_composite(
        frame,
        ((VIDEO_MAX_W - frame.width) // 2, VIDEO_MAX_H - frame.height),
    )
    return canvas


def remove_video_background(frame):
    rgba = np.array(frame, dtype=np.uint8, copy=True)
    rgb = rgba[:, :, :3]
    low = rgb.min(axis=2)
    high = rgb.max(axis=2)
    candidates = ((low >= 220) & (high - low <= 24)).astype(np.uint8)
    _, labels = cv2.connectedComponents(candidates, connectivity=4)
    border_labels = np.concatenate((
        labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1],
    ))
    border_labels = np.unique(border_labels[border_labels != 0])
    if border_labels.size:
        background = np.isin(labels, border_labels)
        rgba[:, :, 3][background] = 0
        frame = Image.fromarray(rgba, "RGBA")
    return frame
