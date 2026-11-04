"""Small typed, thread-safe event bus used by Nova services."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import logging
import queue
import threading
import uuid
from collections import deque

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    PET_STATE_CHANGED = "pet.state_changed"
    ANIMATION_STARTED = "animation.started"
    ANIMATION_FINISHED = "animation.finished"
    ANIMATION_CANCELLED = "animation.cancelled"
    ANIMATION_LOAD_FAILED = "animation.load_failed"
    APP_LAUNCH_RESULT = "app_launch.result"
    AI_REQUEST_STARTED = "ai.request_started"
    AI_RESPONSE_RECEIVED = "ai.response_received"
    AI_REQUEST_FAILED = "ai.request_failed"
    TASK_STARTED = "task.started"
    TASK_FINISHED = "task.finished"
    TASK_FAILED = "task.failed"
    PLUGIN_DISCOVERED = "plugin.discovered"
    PLUGIN_ACTIVATED = "plugin.activated"
    PLUGIN_DEACTIVATED = "plugin.deactivated"
    PLUGIN_FAILED = "plugin.failed"
    NOTIFICATION_CREATED = "notification.created"
    SYSTEM_METRICS_UPDATED = "system.metrics_updated"
    APPLICATION_SHUTDOWN = "application.shutdown"


@dataclass(frozen=True)
class Event:
    type: EventType
    payload: dict = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not isinstance(self.type, EventType) or not isinstance(self.payload, dict):
            raise TypeError("Evento exige EventType e payload dict.")


class EventBus:
    """Synchronous delivery; `post` safely queues worker events for a UI poller."""
    def __init__(self):
        self._lock = threading.RLock()
        self._owner_thread = threading.get_ident()
        self._subscribers = {}
        self._closed = False
        self._queue = queue.Queue(maxsize=1000)
        self._seen_ids = set()
        self._seen_order = deque(maxlen=2048)
        self._dispatch_depth = 0

    def subscribe(self, event_type, callback):
        if not isinstance(event_type, EventType) or not callable(callback):
            raise ValueError("Assinatura de evento inválida.")
        token = str(uuid.uuid4())
        with self._lock:
            if self._closed:
                raise RuntimeError("EventBus encerrado.")
            callbacks = self._subscribers.setdefault(event_type, {})
            if callback in callbacks.values():
                return next(key for key, value in callbacks.items() if value == callback)
            callbacks[token] = callback
        return token

    def unsubscribe(self, token):
        with self._lock:
            for callbacks in self._subscribers.values():
                if callbacks.pop(token, None) is not None:
                    return True
        return False

    def publish(self, event):
        if not isinstance(event, Event):
            raise TypeError("publish espera um Event.")
        if threading.get_ident() != self._owner_thread:
            self.post(event)
            return 0
        with self._lock:
            if self._closed:
                return 0
            if event.event_id in self._seen_ids or self._dispatch_depth >= 32:
                logger.warning("Evento duplicado ou recursão excessiva ignorada: %s", event.type.value)
                return 0
            if len(self._seen_order) == self._seen_order.maxlen:
                self._seen_ids.discard(self._seen_order[0])
            self._seen_order.append(event.event_id)
            self._seen_ids.add(event.event_id)
            self._dispatch_depth += 1
            callbacks = tuple(self._subscribers.get(event.type, {}).values())
        try:
            for callback in callbacks:
                try:
                    callback(event)
                except Exception:
                    logger.exception("Assinante falhou no evento %s", event.type.value)
            return len(callbacks)
        finally:
            with self._lock:
                self._dispatch_depth -= 1

    def post(self, event):
        if not isinstance(event, Event):
            raise TypeError("post espera um Event.")
        with self._lock:
            if self._closed:
                return False
            try:
                self._queue.put_nowait(event)
            except queue.Full:
                logger.error("Fila do EventBus cheia; descartando %s", event.type.value)
                return False
        return True

    def drain(self, limit=100):
        if threading.get_ident() != self._owner_thread:
            raise RuntimeError("A fila do EventBus deve ser consumida pela thread que o criou.")
        count = 0
        while count < limit:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            self.publish(event)
            count += 1
        return count

    def close(self):
        with self._lock:
            self._closed = True
            self._subscribers.clear()
            while True:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
