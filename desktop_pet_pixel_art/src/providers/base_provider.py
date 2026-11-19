"""Contrato compartilhado e erros para provedores de IA."""

from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    """Erro sanitizado de comunicação com um provedor."""


class ProviderCancelled(ProviderError):
    """A solicitação foi cancelada cooperativamente pelo chamador."""


class BaseProvider(ABC):
    name = "base"

    @abstractmethod
    def is_available(self):
        """Retorna se o provedor pode receber uma solicitação agora."""

    @abstractmethod
    def generate(self, messages, system_prompt, timeout=30, cancel_event=None):
        """Gera uma resposta usando mensagens no formato role/content."""

    def generate_turn(self, messages, system_prompt, *, tools=(), timeout=30, cancel_event=None):
        """Structured optional contract; legacy providers remain text-compatible."""
        if cancel_event is not None and cancel_event.is_set():
            raise ProviderCancelled("Solicitação cancelada.")
        from providers.tool_contract import ProviderTurn
        result = ProviderTurn(text=self.generate(messages, system_prompt, timeout=timeout))
        if cancel_event is not None and cancel_event.is_set():
            raise ProviderCancelled("Solicitação cancelada.")
        return result

    @abstractmethod
    def test_connection(self, timeout=10):
        """Valida credenciais, conectividade e disponibilidade do modelo sem enviar conversa."""
