"""Create the active inference backend behind the shared provider contract."""

from providers.ollama_provider import OllamaProvider


def create_provider(name, settings=None):
    if name != "ollama":
        raise ValueError("Somente o Ollama local está disponível")
    settings = settings or {}
    timeout = int(settings.get("ai_timeout", 30))
    return OllamaProvider(
        model=settings.get("ollama_model"),
        timeout=timeout,
        num_ctx=settings.get("ollama_num_ctx", 1024),
        num_predict=settings.get("ollama_num_predict", 96),
        num_threads=settings.get("ollama_num_threads", 1),
    ) if settings.get("ollama_model") else OllamaProvider(timeout=timeout)
