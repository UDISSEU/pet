"""Bounded notification queue, history and duplicate suppression."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid

from event_bus import Event, EventBus, EventType

DEFAULT_NOTIFICATION_PATH = Path.home() / ".config" / "desktop_pet" / "notifications.json"


class NotificationCategory(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    REMINDER = "reminder"
    TASK_COMPLETED = "task_completed"
    SYSTEM_ALERT = "system_alert"


@dataclass
class Notification:
    title: str
    message: str
    category: NotificationCategory = NotificationCategory.INFO
    priority: int = 0
    persistent: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notification_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    read: bool = False
    dismissed: bool = False


class NotificationManager:
    def __init__(self, path=DEFAULT_NOTIFICATION_PATH, event_bus=None, limit=200, silent=False,
                 categories=None, cooldown_seconds=30):
        self.path = Path(path)
        self.event_bus = event_bus or EventBus()
        self.limit = max(1, int(limit))
        self.silent = bool(silent)
        self.categories = {item.value: True for item in NotificationCategory}
        if isinstance(categories, dict):
            self.categories.update({str(key): bool(value) for key, value in categories.items()
                                    if key in self.categories})
        self.cooldown_seconds = max(0.0, min(3600.0, float(cooldown_seconds)))
        self._last_created = {}
        self._lock = threading.RLock()
        self.items = []
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                settings = data.get("settings", {})
                if isinstance(settings, dict):
                    self.silent = bool(settings.get("silent", self.silent))
                    saved_categories = settings.get("categories", {})
                    if isinstance(saved_categories, dict):
                        self.categories.update({key: bool(value) for key, value in saved_categories.items()
                                                if key in self.categories})
                    try:
                        self.cooldown_seconds = max(0.0, min(3600.0, float(settings.get("cooldown_seconds", self.cooldown_seconds))))
                    except (TypeError, ValueError):
                        pass
                rows = data.get("items", [])
            else:
                rows = data if isinstance(data, list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    row["category"] = NotificationCategory(row.get("category", "info"))
                    self.items.append(Notification(**row))
                except (TypeError, ValueError):
                    continue
        except (OSError, ValueError):
            pass
        self.items = self.items[-self.limit:]

    def create(self, title, message, category=NotificationCategory.INFO, priority=0, persistent=False):
        category = NotificationCategory(category)
        title, message = str(title).strip()[:160], str(message).strip()[:1000]
        if not title or not message:
            raise ValueError("Título e mensagem são obrigatórios.")
        priority = max(0, min(100, int(priority)))
        with self._lock:
            if not self.categories.get(category.value, True):
                return None
            now = time.monotonic()
            fingerprint = (category.value, title.casefold(), message.casefold())
            last = self._last_created.get(fingerprint, 0.0)
            if not persistent and self.cooldown_seconds and now - last < self.cooldown_seconds:
                return next((item for item in reversed(self.items)
                             if item.category == category and item.title == title
                             and item.message == message), None)
            for existing in reversed(self.items[-20:]):
                if existing.category == category and existing.title == title and existing.message == message:
                    try:
                        created = datetime.fromisoformat(existing.created_at).timestamp()
                        age = max(0.0, time.time() - created)
                    except (TypeError, ValueError, OSError):
                        age = self.cooldown_seconds + 1
                    if persistent or (self.cooldown_seconds and age < self.cooldown_seconds):
                        return existing if not existing.dismissed else None
            item = Notification(title, message, category, int(priority), bool(persistent))
            self.items.append(item)
            self.items = self.items[-self.limit:]
            self._last_created[fingerprint] = now
            self._save()
        self.event_bus.publish(Event(EventType.NOTIFICATION_CREATED, {"notification_id": item.notification_id, "category": category.value, "priority": item.priority}))
        return item

    def configure_category(self, category, enabled):
        category = NotificationCategory(category)
        self.categories[category.value] = bool(enabled)
        self._save()
        return self.categories[category.value]

    def configure_cooldown(self, seconds):
        self.cooldown_seconds = max(0.0, min(3600.0, float(seconds)))
        self._save()
        return self.cooldown_seconds

    def set_silent(self, silent):
        self.silent = bool(silent)
        self._save()

    def filtered(self, category=None, *, unread_only=False, include_dismissed=False):
        selected = NotificationCategory(category) if category is not None else None
        return [item for item in reversed(self.items)
                if (selected is None or item.category == selected)
                and (not unread_only or (not item.read and not item.dismissed))
                and (include_dismissed or not item.dismissed)]

    def should_display(self, item):
        return (isinstance(item, Notification)
                and self.categories.get(item.category.value, True)
                and (not self.silent or item.persistent or item.priority >= 90))

    @property
    def pending(self):
        return sorted((item for item in self.items if not item.read and not item.dismissed),
                      key=lambda item: (item.priority, item.created_at), reverse=True)

    def mark_read(self, notification_id):
        item = self._find(notification_id)
        item.read = True
        self._save()
        return item

    def dismiss(self, notification_id):
        item = self._find(notification_id)
        item.dismissed = True
        self._save()
        return item

    def clear_dismissible(self):
        before = len(self.items)
        self.items = [item for item in self.items if item.persistent or not item.dismissed]
        self._save()
        return before - len(self.items)

    def _find(self, notification_id):
        for item in self.items:
            if item.notification_id == notification_id:
                return item
        raise KeyError(notification_id)

    @property
    def unread_count(self):
        return sum(not item.read and not item.dismissed for item in self.items)

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".notifications-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                rows = []
                for item in self.items:
                    row = asdict(item)
                    row["category"] = item.category.value
                    rows.append(row)
                json.dump({"items": rows, "settings": {
                    "silent": self.silent,
                    "categories": self.categories,
                    "cooldown_seconds": self.cooldown_seconds,
                }}, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
