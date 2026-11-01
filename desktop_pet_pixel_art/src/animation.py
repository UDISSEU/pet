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
    MOVEMENT_VIDEOS,
    resolve_movement_path,
)

WATERMARK_RIGHT_FRACTION = 0.12
WATERMARK_BOTTOM_FRACTION = 0.08
WATERMARK_MAX_COMPONENT_FRACTION = 0.002


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
    allow_empty_frames = path.name == MOVEMENT_VIDEOS["vanishing"]
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
                frames.append(Image.fromarray(rgb))
                next_sample_at_ms += VIDEO_FRAME_INTERVAL_MS
            source_frame += 1
    finally:
        capture.release()

    if not frames:
        raise ValueError(f"O vídeo de movimento não contém quadros: {path}")
    return prepare_video_frames(
        frames, path.name, allow_empty=allow_empty_frames
    )


def load_video_preview(filename):
    """Decode only the first frame, so the desktop can render immediately."""
    path = resolve_movement_path(filename)
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise OSError(f"Não foi possível abrir o vídeo de movimento: {path}")
    try:
        success, frame = capture.read()
    finally:
        capture.release()
    if not success:
        raise ValueError(f"O vídeo de movimento não contém quadros: {path}")
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return prepare_video_frame(Image.fromarray(rgb), path.name)


def prepare_video_frame(frame, description, allow_empty=False):
    return prepare_video_frames([frame], description, allow_empty)[0]


def prepare_video_frames(frames, description, allow_empty=False):
    """Prepare a whole clip against one shared crop, scale, and foot anchor."""
    if not frames:
        raise ValueError(f"O vídeo de movimento não contém quadros: {description}.")

    processed_frames = []
    union = None
    for frame in frames:
        processed = remove_video_background(frame.convert("RGBA"))
        processed = remove_corner_watermark_components(processed)
        bounds = processed.getchannel("A").getbbox()
        if bounds is not None:
            if union is None:
                union = bounds
            else:
                union = (
                    min(union[0], bounds[0]),
                    min(union[1], bounds[1]),
                    max(union[2], bounds[2]),
                    max(union[3], bounds[3]),
                )
        processed_frames.append((processed, bounds))

    if union is None:
        if allow_empty:
            return [
                Image.new("RGBA", (VIDEO_MAX_W, VIDEO_MAX_H), (0, 0, 0, 0))
                for _ in processed_frames
            ]
        raise ValueError(f"Nenhum personagem encontrado no vídeo {description}.")

    crop_width = union[2] - union[0]
    crop_height = union[3] - union[1]
    scale = min(VIDEO_MAX_W / crop_width, VIDEO_MAX_H / crop_height)
    target_size = (
        max(1, round(crop_width * scale)),
        max(1, round(crop_height * scale)),
    )

    output = []
    for processed, bounds in processed_frames:
        canvas = Image.new("RGBA", (VIDEO_MAX_W, VIDEO_MAX_H), (0, 0, 0, 0))
        if bounds is not None:
            cropped = processed.crop(union)
            if cropped.size != target_size:
                cropped = cropped.resize(target_size, Image.Resampling.LANCZOS)
            canvas.alpha_composite(
                cropped,
                ((VIDEO_MAX_W - target_size[0]) // 2, VIDEO_MAX_H - target_size[1]),
            )
        output.append(canvas)
    return output


def remove_corner_watermark_components(frame):
    """Remove only tiny disconnected marks inside the lower-right watermark area.

    The tested margin is the lower-right 16% of frame width by 8% of frame
    height. Larger connected foreground (including a character reaching that
    corner) is retained.
    """
    rgba = np.array(frame, dtype=np.uint8, copy=True)
    alpha = rgba[:, :, 3]
    foreground = (alpha > 0).astype(np.uint8)
    if not foreground.any():
        return frame

    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        foreground, connectivity=8
    )
    height, width = alpha.shape
    corner_x = width * (1 - WATERMARK_RIGHT_FRACTION)
    corner_y = height * (1 - WATERMARK_BOTTOM_FRACTION)
    max_component_area = max(
        8, int(width * height * WATERMARK_MAX_COMPONENT_FRACTION)
    )
    for label in range(1, count):
        x, y, component_width, component_height, area = stats[label]
        center_x, center_y = centroids[label]
        if (
            area <= max_component_area
            and center_x >= corner_x
            and center_y >= corner_y
        ):
            alpha[labels == label] = 0
    return Image.fromarray(rgba, "RGBA")


def frame_index_at_elapsed(
    elapsed_ms,
    frame_count,
    loop_window=None,
    one_shot=False,
    fps=VIDEO_FRAME_RATE,
):
    if frame_count <= 0:
        raise ValueError("A animação precisa conter ao menos um quadro.")
    start_seconds, end_seconds = loop_window or (0.0, frame_count / fps)
    start_index = min(frame_count - 1, max(0, int(start_seconds * fps)))
    end_index = min(
        frame_count - 1,
        max(start_index, int(math.ceil(end_seconds * fps)) - 1),
    )
    elapsed_frames = max(0, int(max(0.0, elapsed_ms) * fps / 1000))
    if one_shot:
        return min(end_index, start_index + elapsed_frames)
    window_length = end_index - start_index + 1
    return start_index + elapsed_frames % window_length


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
