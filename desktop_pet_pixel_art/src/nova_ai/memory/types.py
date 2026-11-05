"""Tipos explícitos para as quatro categorias persistentes de memória."""

from dataclasses import dataclass
from enum import Enum


class MemoryKind(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PREFERENCE = "preference"


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    kind: MemoryKind
    content: str
    source: str
    created_at: str
    updated_at: str
    confidence: float
    relevance: float
    consent_granted: bool = True


def record_from_row(row):
    return MemoryRecord(
        memory_id=row["id"],
        kind=MemoryKind(row["kind"]),
        content=row["content"],
        source=row["source"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        confidence=float(row["confidence"]),
        relevance=float(row["relevance"]),
        consent_granted=bool(row["consent_granted"]),
    )
