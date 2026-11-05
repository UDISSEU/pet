"""Preferências explícitas, nunca inferidas nem guardadas sem confirmação."""

from .types import MemoryKind


class PreferenceMemory:
    def __init__(self, manager):
        self.manager = manager

    def set_preference(self, preference, *, source="user", consent_confirmed=False,
                       confidence=1.0, relevance=1.0):
        return self.manager.add(
            MemoryKind.PREFERENCE, preference, source=source,
            consent=consent_confirmed, confidence=confidence, relevance=relevance,
        )

    def recall(self, question, *, limit=5):
        return self.manager.search(question, kind=MemoryKind.PREFERENCE, limit=limit)
