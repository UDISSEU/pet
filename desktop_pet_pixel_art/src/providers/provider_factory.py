"""Cria provedores sem acoplar o restante da aplicação a APIs específicas."""

from providers.gemini_provider import GeminiProvider
from providers.groq_provider import GroqProvider
from providers.mistral_provider import MistralProvider
from providers.ollama_provider import OllamaProvider


def create_provider(name, settings=None):
    settings = settings or {}
    timeout = int(settings.get("ai_timeout", 30))
    if name == "gemini":
        return GeminiProvider(model=settings.get("gemini_model", "gemini-3.8-flash"))
    if name == "groq":
        return GroqProvider(model=settings.get("groq_model", "openai/gpt-oss-20b"))
    if name == "mistral":
        return MistralProvider(model=settings.get("mistral_model", "mistral-small-latest"))
    return OllamaProvider(
        model=settings.get("ollama_model"),
        timeout=timeout,
    ) if settings.get("ollama_model") else OllamaProvider(timeout=timeout)
