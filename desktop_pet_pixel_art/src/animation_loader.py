"""Background loading for the character's larger animation sequences."""

import logging
import queue
import threading

from animation import load_video_frames, load_video_preview

logger = logging.getLogger(__name__)


class AnimationLoader:
    """Load one preview synchronously and the full videos on a daemon thread."""

    def __init__(self, videos, frame_loader=None,
                 preview_loader=load_video_preview, *, lazy=False):
        self.videos = dict(videos)
        self.frame_loader = (
            load_video_frames if frame_loader is None else frame_loader
        )
        self._supports_cooperative_cancel = (
            frame_loader is None or frame_loader is load_video_frames
        )
        self.preview_loader = preview_loader
        self.lazy = lazy
        self.results = queue.Queue()
        self._requests = queue.Queue()
        self._requested = set()
        self._requested_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def preview(self, name):
        return self.preview_loader(self.videos[name])

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._load_all,
            name="aurova-animation-loader",
            daemon=True,
        )
        self._thread.start()

    def request(self, name):
        """Queue one animation for background decoding when lazy mode is on."""
        if not self.lazy or name not in self.videos or self._stop.is_set():
            return False
        with self._requested_lock:
            if name in self._requested:
                return False
            self._requested.add(name)
        self._requests.put(name)
        return True

    def forget(self, name):
        """Allow an evicted animation to be decoded again later."""
        with self._requested_lock:
            self._requested.discard(name)

    def _load_all(self):
        if self.lazy:
            self._load_requested()
            return
        for name, filename in self.videos.items():
            if self._stop.is_set():
                return
            try:
                if self._supports_cooperative_cancel:
                    frames = self.frame_loader(filename, should_stop=self._stop.is_set)
                else:
                    frames = self.frame_loader(filename)
                if self._stop.is_set():
                    return
                if not frames:
                    raise ValueError("A animação não contém quadros.")
            except Exception as exc:
                logger.warning(
                    "Falha ao carregar animação %s (%s)",
                    filename,
                    type(exc).__name__,
                )
                if not self._stop.is_set():
                    self.results.put((name, None, type(exc).__name__))
            else:
                if not self._stop.is_set():
                    self.results.put((name, frames, None))

    def _load_requested(self):
        while not self._stop.is_set():
            try:
                name = self._requests.get(timeout=0.1)
            except queue.Empty:
                continue
            if self._stop.is_set():
                return
            filename = self.videos[name]
            try:
                if self._supports_cooperative_cancel:
                    frames = self.frame_loader(filename, should_stop=self._stop.is_set)
                else:
                    frames = self.frame_loader(filename)
                if self._stop.is_set():
                    return
                if not frames:
                    raise ValueError("A animação não contém quadros.")
            except Exception as exc:
                logger.warning(
                    "Falha ao carregar animação %s (%s)",
                    filename,
                    type(exc).__name__,
                )
                if not self._stop.is_set():
                    self.results.put((name, None, type(exc).__name__))
            else:
                if not self._stop.is_set():
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
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        if thread is not None and self._thread is thread and not thread.is_alive():
            self._thread = None
