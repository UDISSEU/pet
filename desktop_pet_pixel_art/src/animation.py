"""Carregamento e preparação dos quadros de animação da Nova."""

import math
from collections import deque

from PIL import Image

from config import (
    VIDEO_FRAME_INTERVAL_MS,
    VIDEO_FRAME_RATE,
    VIDEO_MAX_H,
    VIDEO_MAX_W,
    resolve_movement_path,
)


def load_video_frames(filename):
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Falta o OpenCV para reproduzir os movimentos em vídeo. "
            "Instale as dependências com: pip install -r requirements.txt"
        ) from exc

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
    frame.thumbnail((VIDEO_MAX_W, VIDEO_MAX_H), Image.Resampling.LANCZOS)
    frame = remove_video_background(frame.convert("RGBA"))
    bounds = frame.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError(f"Nenhum personagem encontrado no vídeo {description}.")
    frame = frame.crop(bounds)
    canvas = Image.new("RGBA", (VIDEO_MAX_W, VIDEO_MAX_H), (0, 0, 0, 0))
    canvas.alpha_composite(frame, ((VIDEO_MAX_W - frame.width) // 2, VIDEO_MAX_H - frame.height))
    return canvas


def remove_video_background(frame):
    width, height = frame.size
    pixels = list(frame.getdata())
    background = bytearray(
        int(min(red, green, blue) >= 220 and max(red, green, blue) - min(red, green, blue) <= 24)
        for red, green, blue, _ in pixels
    )
    transparent = bytearray(width * height)
    pending = deque()

    def enqueue(index):
        if background[index] and not transparent[index]:
            transparent[index] = 1
            pending.append(index)

    for x in range(width):
        enqueue(x)
        enqueue((height - 1) * width + x)
    for y in range(1, height - 1):
        enqueue(y * width)
        enqueue(y * width + width - 1)

    while pending:
        index = pending.popleft()
        x = index % width
        if x:
            enqueue(index - 1)
        if x + 1 < width:
            enqueue(index + 1)
        if index >= width:
            enqueue(index - width)
        if index + width < width * height:
            enqueue(index + width)

    alpha = Image.new("L", frame.size)
    alpha.putdata([0 if is_background else pixel[3] for is_background, pixel in zip(transparent, pixels)])
    frame.putalpha(alpha)
    return frame
