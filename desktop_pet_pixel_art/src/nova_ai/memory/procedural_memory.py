"""Procedimentos aprovados descritos como dados, sem executá-los."""

from .types import MemoryKind


class ProceduralMemory:
    def __init__(self, manager):
        self.manager = manager

    def add_procedure(self, procedure, *, source="user", consent=False,
                      confidence=0.8, relevance=0.8):
        return self.manager.add(
            MemoryKind.PROCEDURAL, procedure, source=source, consent=consent,
            confidence=confidence, relevance=relevance,
        )
