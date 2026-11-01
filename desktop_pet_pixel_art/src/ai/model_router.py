"""Seleção explícita do provedor e contingência local."""

import logging
import threading

from providers.base_provider import ProviderError
from providers.provider_factory import create_provider

logger = logging.getLogger(__name__)
SUPPORTED_PROVIDERS = {"ollama", "gemini", "groq", "mistral"}


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
                raise ProviderError("O provedor selecionado não é reconhecido. Confira as preferências de IA.")
            online_allowed = (
                selected in ("gemini", "groq", "mistral")
                and self.settings.get("online_ai_enabled", False)
                and self.settings.get("allow_online_data", False)
                and self.settings.get("confirm_free_tier", False)
            )
            if selected in ("gemini", "groq", "mistral") and not online_allowed:
                selected = "ollama"
            try:
                provider = self.provider_factory(selected, self.settings)
            except Exception as exc:
                raise ProviderError("A configuração do provedor selecionado é inválida.") from exc
            if selected != "ollama" and not provider.is_available():
                raise ProviderError(
                    "A chave do provedor online selecionado não está configurada. "
                    "Configure-a ou escolha outro provedor nas preferências."
                )
            try:
                timeout = min(12, self._timeout()) if selected != "ollama" else self._timeout()
                return provider.generate(messages, system_prompt, timeout=timeout)
            except Exception as exc:
                logger.warning(
                    "Provedor %s falhou (%s); verificando contingência local",
                    selected, type(exc).__name__,
                )
                if selected == "ollama":
                    if isinstance(exc, ProviderError):
                        raise
                    raise ProviderError("Não foi possível consultar a IA local.") from exc
                try:
                    fallback = self.provider_factory("ollama", self.settings)
                    return fallback.generate(messages, system_prompt, timeout=min(10, self._timeout()))
                except Exception as fallback_error:
                    raise ProviderError(
                        "O provedor online falhou e a IA local também está indisponível. "
                        "Confira a conexão, a chave e o Ollama."
                    ) from fallback_error
        finally:
            self._lock.release()

    def _timeout(self):
        try:
            return min(30, max(5, int(self.settings.get("ai_timeout", 30))))
        except (TypeError, ValueError):
            return 30
