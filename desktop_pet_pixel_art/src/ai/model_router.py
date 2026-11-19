"""Route inference through the stable provider contract using local Ollama only."""

import logging
import threading

from providers.base_provider import ProviderCancelled, ProviderError
from providers.provider_factory import create_provider

logger = logging.getLogger(__name__)
SUPPORTED_PROVIDERS = frozenset({"ollama"})


class ModelRouter:
    def __init__(self, settings=None, provider_factory=create_provider):
        self.settings = dict(settings or {})
        self.provider_factory = provider_factory
        self._lock = threading.Lock()

    def generate(self, messages, system_prompt, *, cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            raise ProviderCancelled("Solicitação cancelada.")
        if not self._lock.acquire(blocking=False):
            raise ProviderError("Já existe uma solicitação de IA em andamento.")
        try:
            selected = self.settings.get("ai_provider", "ollama")
            if selected not in SUPPORTED_PROVIDERS:
                raise ProviderError("Somente o Ollama local está disponível como provedor de IA.")
            try:
                provider = self.provider_factory(selected, self.settings)
            except Exception as exc:
                raise ProviderError("A configuração do provedor selecionado é inválida.") from exc
            try:
                kwargs = {"timeout": self._timeout()}
                if cancel_event is not None:
                    kwargs["cancel_event"] = cancel_event
                result = provider.generate(messages, system_prompt, **kwargs)
                if cancel_event is not None and cancel_event.is_set():
                    raise ProviderCancelled("Solicitação cancelada.")
                return result
            except Exception as exc:
                logger.warning(
                    "Inferência pelo Ollama falhou (%s)",
                    type(exc).__name__,
                )
                if isinstance(exc, ProviderError):
                    raise
                raise ProviderError("Não foi possível consultar a IA local.") from exc
        finally:
            self._lock.release()

    def generate_turn(self, messages, system_prompt, *, tools=(), cancel_event=None):
        """Structured provider turn; tool execution is deliberately not part of the router."""
        if cancel_event is not None and cancel_event.is_set():
            raise ProviderCancelled("Solicitação cancelada.")
        if not self._lock.acquire(blocking=False):
            raise ProviderError("Já existe uma solicitação de IA em andamento.")
        try:
            selected = self.settings.get("ai_provider", "ollama")
            if selected not in SUPPORTED_PROVIDERS:
                raise ProviderError("Somente o Ollama local está disponível como provedor de IA.")
            try:
                provider = self.provider_factory(selected, self.settings)
                kwargs = {"tools": tools, "timeout": self._timeout()}
                if cancel_event is not None:
                    kwargs["cancel_event"] = cancel_event
                result = provider.generate_turn(messages, system_prompt, **kwargs)
                if cancel_event is not None and cancel_event.is_set():
                    raise ProviderCancelled("Solicitação cancelada.")
                return result
            except ProviderCancelled:
                raise
            except ProviderError:
                raise
            except Exception as exc:
                logger.warning("Inferência estruturada falhou (%s)", type(exc).__name__)
                raise ProviderError("Não foi possível consultar a IA estruturada local.") from exc
        finally:
            self._lock.release()

    def _timeout(self):
        try:
            return min(30, max(5, int(self.settings.get("ai_timeout", 30))))
        except (TypeError, ValueError):
            return 30
