"""Interface abstrata independente de fornecedor para geração de texto."""

from abc import ABC, abstractmethod

from ..core.errors import ModelError


class Model(ABC):
    @abstractmethod
    def generate(self, messages, *, max_new_tokens=256):
        """Gera texto a partir de mensagens; implementações devem impor limites."""

    def close(self):
        """Libera recursos explicitamente; implementação padrão não faz nada."""


__all__ = ["Model", "ModelError"]
