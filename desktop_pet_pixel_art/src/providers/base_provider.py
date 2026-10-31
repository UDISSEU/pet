"""Contrato compartilhado e erros para provedores de IA."""

from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """Erro sanitizado de comunicação com um provedor."""


class BaseProvider(ABC):
    name = "base"

    @abstractmethod
    def is_available(self):
        """Retorna se o provedor pode receber uma solicitação agora."""

    @abstractmethod
    def generate(self, messages, system_prompt, timeout=30):
        """Gera uma resposta usando mensagens no formato role/content."""

    @abstractmethod
    def test_connection(self, timeout=10):
        """Valida credenciais, conectividade e disponibilidade do modelo sem enviar conversa."""
