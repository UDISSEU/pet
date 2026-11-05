"""API de alto nível; grava apenas após consentimento explícito."""

import re
import uuid

from .errors import (
    ConsentRequiredError,
    DuplicateMemoryError,
    SensitiveInformationError,
)
from .memory_retrieval import MemoryRetrieval
from .memory_storage import MemoryStorage
from .types import MemoryKind, record_from_row

_MAX_CONTENT_CHARS = 8_000
_MAX_SOURCE_CHARS = 128
_SENSITIVE_PATTERNS = (
    re.compile(
        r"(?i)\b(?:password|passwd|senha|credential|credencial|api[_ -]?key|"
        r"access[_ -]?token|refresh[_ -]?token|secret|segredo|chave)"
        r"\s*(?:(?:is|é)\s+|[:=]\s*|\s+)\S+"
    ),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AIza[\w-]{30,})\b"),
)


def _validate_confidence(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"{field} deve estar entre 0 e 1")
    return float(value)


def _clean_text(value, field, maximum):
    if not isinstance(value, str):
        raise ValueError(f"{field} deve ser texto")
    result = value.strip()
    if not result or len(result) > maximum:
        raise ValueError(f"{field} deve ter entre 1 e {maximum} caracteres")
    if any(ord(char) < 32 and char not in "\n\t" for char in result):
        raise ValueError(f"{field} contém caracteres de controle")
    return result


def _kind(value):
    try:
        return MemoryKind(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Tipo de memória inválido") from exc


class MemoryManager:
    def __init__(self, storage=None):
        self.storage = storage if storage is not None else MemoryStorage()
        self.retrieval = MemoryRetrieval(self.storage)

    @staticmethod
    def _require_consent(consent):
        if consent is not True:
            raise ConsentRequiredError("A gravação exige consentimento explícito")

    @staticmethod
    def _reject_sensitive_content(content):
        if any(pattern.search(content) for pattern in _SENSITIVE_PATTERNS):
            raise SensitiveInformationError(
                "O conteúdo parece conter credencial e não será armazenado"
            )

    def add(
        self, kind, content, *, source="user", consent=False,
        confidence=0.8, relevance=0.8,
    ):
        self._require_consent(consent)
        kind = _kind(kind)
        content = _clean_text(content, "content", _MAX_CONTENT_CHARS)
        source = _clean_text(source, "source", _MAX_SOURCE_CHARS)
        self._reject_sensitive_content(content)
        self._reject_sensitive_content(source)
        confidence = _validate_confidence(confidence, "confidence")
        relevance = _validate_confidence(relevance, "relevance")
        duplicate = self.find_duplicate(kind, content)
        if duplicate is not None:
            return duplicate
        try:
            row = self.storage.insert({
                "id": uuid.uuid4().hex,
                "kind": kind.value,
                "content": content,
                "source": source,
                "confidence": confidence,
                "relevance": relevance,
                "consent_granted": True,
            })
        except DuplicateMemoryError:
            # Another process may have inserted the same record after our lookup.
            duplicate = self.find_duplicate(kind, content)
            if duplicate is None:
                raise
            return duplicate
        return record_from_row(row)

    def get(self, memory_id):
        return record_from_row(self.storage.get(memory_id))

    def find_duplicate(self, kind, content):
        kind = _kind(kind)
        content = _clean_text(content, "content", _MAX_CONTENT_CHARS)
        row = self.storage.find_duplicate(kind.value, content)
        return record_from_row(row) if row else None

    def search(self, query="", *, kind=None, limit=20):
        results = self.retrieval.search(query, kind=kind, limit=limit)
        return [item.memory for item in results]

    def search_scored(self, query="", *, kind=None, limit=20):
        return self.retrieval.search(query, kind=kind, limit=limit)

    def update(
        self, memory_id, *, content=None, source=None, consent=False,
        confidence=None, relevance=None,
    ):
        self._require_consent(consent)
        existing = self.storage.get(memory_id)
        new_content = existing["content"] if content is None else _clean_text(
            content, "content", _MAX_CONTENT_CHARS
        )
        new_source = existing["source"] if source is None else _clean_text(
            source, "source", _MAX_SOURCE_CHARS
        )
        self._reject_sensitive_content(new_content)
        self._reject_sensitive_content(new_source)
        new_confidence = existing["confidence"] if confidence is None else _validate_confidence(
            confidence, "confidence"
        )
        new_relevance = existing["relevance"] if relevance is None else _validate_confidence(
            relevance, "relevance"
        )
        duplicate = self.storage.find_duplicate(
            existing["kind"], new_content, exclude_id=memory_id
        )
        if duplicate is not None:
            from .errors import DuplicateMemoryError
            raise DuplicateMemoryError("A atualização duplicaria outra memória")
        row = self.storage.update(
            memory_id, content=new_content, source=new_source,
            confidence=new_confidence, relevance=new_relevance, consent=True,
        )
        return record_from_row(row)

    def delete(self, memory_id):
        # Invoking delete is itself the user's explicit request to remove data.
        return self.storage.delete(memory_id)

    def backup(self, destination):
        return self.storage.backup_to(destination)

    def export_json(self, destination, *, kind=None):
        if kind is not None:
            kind = _kind(kind)
            kind = kind.value
        return self.storage.export_json(destination, kind=kind)
