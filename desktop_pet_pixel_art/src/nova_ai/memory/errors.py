"""Erros públicos do subsistema de memória."""

from ..core.errors import NovaAIError


class MemoryErrorBase(NovaAIError):
    code = "memory_error"


class ConsentRequiredError(MemoryErrorBase):
    code = "consent_required"


class SensitiveInformationError(MemoryErrorBase):
    code = "sensitive_information_rejected"


class MemoryNotFoundError(MemoryErrorBase):
    code = "memory_not_found"


class DuplicateMemoryError(MemoryErrorBase):
    code = "duplicate_memory"


class MemoryStorageError(MemoryErrorBase):
    code = "memory_storage_error"
