"""Background loading for the character's larger animation sequences."""

import logging
import queue
import threading

from animation import load_video_frames, load_video_preview

logger = logging.getLogger(__name__)


class AnimationLoader:
    """Load one preview synchronously and the full videos on a daemon thread."""

    def __init__(self, videos, frame_loader=load_video_frames,
                 preview_loader=load_video_preview):
        self.videos = dict(videos)
        self.frame_loader = frame_loader
        self.preview_loader = preview_loader
        self.results = queue.Queue()
        self._stop = threading.Event()
        self._thread = None

    def preview(self, name):
        return self.preview_loader(self.videos[name])

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._load_all,
            name="nova-animation-loader",
            daemon=True,
        )
        self._thread.start()

    def _load_all(self):
        for name, filename in self.videos.items():
            if self._stop.is_set():
                return
            try:
                frames = self.frame_loader(filename)
                if not frames:
                    raise ValueError("A animação não contém quadros.")
            except Exception as exc:
                logger.warning(
                    "Falha ao carregar animação %s (%s)",
                    filename,
                    type(exc).__name__,
                )
                self.results.put((name, None, type(exc).__name__))
            else:
                self.results.put((name, frames, None))

    def drain(self):
        results = []
        while True:
            try:
                results.append(self.results.get_nowait())
            except queue.Empty:
                return results

    def close(self):
        self._stop.set()
