"""Tipos explícitos para categorias, origem e certeza das memórias."""

from dataclasses import dataclass
from enum import Enum


class MemoryKind(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PREFERENCE = "preference"
    PROFILE = "profile"
    PROJECT = "project"
    CONVERSATION = "conversation"
    LEARNING = "learning"


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
    provenance: str = "user_provided"
    expires_at: str | None = None


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
        provenance=row["provenance"],
        expires_at=row["expires_at"],
    )
