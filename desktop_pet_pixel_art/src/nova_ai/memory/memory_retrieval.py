"""Recuperação lexical local, limitada e sem embeddings."""

from dataclasses import dataclass
import re
import unicodedata

from .types import MemoryKind, record_from_row

_STOP_WORDS = {
    "a", "as", "o", "os", "um", "uma", "de", "do", "da", "dos", "das",
    "em", "no", "na", "nos", "nas", "e", "que", "como", "qual", "quais",
    "eu", "meu", "minha", "meus", "minhas", "prefiro", "prefere", "sobre",
    "para", "por", "com", "voce", "você", "nova", "minhas",
}


def _fold(text):
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _terms(text):
    return {
        term for term in re.findall(r"[\wÀ-ÿ]{2,}", _fold(text))
        if term not in _STOP_WORDS
    }


@dataclass(frozen=True)
class MemorySearchResult:
    memory: object
    score: float


class MemoryRetrieval:
    def __init__(self, storage):
        self._storage = storage

    def search(self, query="", *, kind=None, limit=20):
        if isinstance(kind, str):
            kind = MemoryKind(kind)
        if kind is not None and not isinstance(kind, MemoryKind):
            raise ValueError("Tipo de memória inválido")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit deve ser um inteiro entre 1 e 100")
        if not isinstance(query, str) or len(query) > 512:
            raise ValueError("A consulta deve ser texto de até 512 caracteres")
        query_terms = _terms(query)
        storage_kind = kind.value if kind else None
        if query and not query_terms:
            return []
        if query_terms:
            candidates = {}
            for term in sorted(query_terms)[:8]:
                for row in self._storage.search(
                    kind=storage_kind, terms=[term], limit=100
                ):
                    candidates[row["id"]] = row
            rows = list(candidates.values())
        else:
            rows = self._storage.search(kind=storage_kind, limit=100)
        results = []
        for row in rows:
            memory_terms = _terms(row["content"])
            matches = query_terms & memory_terms
            if query_terms and not matches:
                continue
            coverage = len(matches) / len(query_terms) if query_terms else 1.0
            score = coverage * float(row["confidence"]) * float(row["relevance"])
            results.append(MemorySearchResult(record_from_row(row), score))
        results.sort(
            key=lambda result: (
                -result.score, -result.memory.relevance, -result.memory.confidence,
                result.memory.updated_at,
            )
        )
        return results[:limit]
