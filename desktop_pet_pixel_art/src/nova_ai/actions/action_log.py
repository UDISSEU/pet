"""Log limitado em memória; não persiste conteúdos ou argumentos sensíveis."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import threading


@dataclass(frozen=True)
class ActionLogEntry:
    action: str
    outcome: str
    timestamp: str
    error_code: str | None = None


class ActionLog:
    def __init__(self, limit=200):
        if type(limit) is not int or not 1 <= limit <= 2_000:
            raise ValueError("limit deve estar entre 1 e 2000")
        self._entries = deque(maxlen=limit)
        self._lock = threading.Lock()

    def record(self, action, outcome, *, error_code=None):
        entry = ActionLogEntry(
            str(action)[:100], str(outcome)[:40],
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            None if error_code is None else str(error_code)[:80],
        )
        with self._lock:
            self._entries.append(entry)
        return entry

    def entries(self):
        with self._lock:
            return tuple(self._entries)
