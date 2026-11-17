"""Operações tipadas para acontecimentos e experiências autorizados."""

from .types import MemoryKind


class EpisodicMemory:
    def __init__(self, manager):
        self.manager = manager

    def record_event(self, description, *, source="user", consent=False,
                     confidence=0.8, relevance=0.8):
        return self.manager.add(
            MemoryKind.EPISODIC, description, source=source, consent=consent,
            confidence=confidence, relevance=relevance,
        )
