"""Operações tipadas para informações e conhecimentos confirmados."""

from .types import MemoryKind


class SemanticMemory:
    def __init__(self, manager):
        self.manager = manager

    def add_fact(self, fact, *, source="user", consent=False,
                 confidence=0.8, relevance=0.8):
        return self.manager.add(
            MemoryKind.SEMANTIC, fact, source=source, consent=consent,
            confidence=confidence, relevance=relevance,
        )
