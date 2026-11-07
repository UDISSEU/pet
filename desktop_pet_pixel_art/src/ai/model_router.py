"""Route inference through the stable provider contract using local Ollama only."""

import logging
import threading

from providers.base_provider import ProviderError
from providers.provider_factory import create_provider

logger = logging.getLogger(__name__)
SUPPORTED_PROVIDERS = frozenset({"ollama"})


class ModelRouter:
    def __init__(self, settings=None, provider_factory=create_provider):
        self.settings = dict(settings or {})
        self.provider_factory = provider_factory
        self._lock = threading.Lock()

    def generate(self, messages, system_prompt):
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
                return provider.generate(messages, system_prompt, timeout=self._timeout())
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

    def _timeout(self):
        try:
            return min(30, max(5, int(self.settings.get("ai_timeout", 30))))
        except (TypeError, ValueError):
            return 30
