"""Provedor local Ollama, usando a API HTTP oficial instalada localmente."""

import json
import urllib.error
import urllib.request

from config import OLLAMA_MODEL, OLLAMA_URL
from providers.base_provider import BaseProvider, ProviderError


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, model=OLLAMA_MODEL, url=OLLAMA_URL, timeout=30):
        self.model = model
        self.url = url
        self.timeout = timeout

    def is_available(self):
        tags_url = self.url.rsplit("/api/", 1)[0] + "/api/tags"
        try:
            with urllib.request.urlopen(tags_url, timeout=min(self.timeout, 4)) as response:
                data = json.loads(response.read().decode("utf-8"))
            return any(item.get("name", "").split(":")[0] == self.model.split(":")[0]
                       for item in data.get("models", []))
        except (OSError, ValueError, AttributeError):
            return False

    def test_connection(self, timeout=10):
        if not self.is_available():
            raise ProviderError(f"Ollama não respondeu ou o modelo '{self.model}' não está instalado.")
        return f"Conectado ao Ollama; modelo {self.model} disponível."

    def generate(self, messages, system_prompt, timeout=None):
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": False,
        }
        request = urllib.request.Request(
            self.url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            answer = data.get("message", {}).get("content", "").strip()
            if not answer:
                raise ProviderError("O Ollama retornou uma resposta vazia.")
            return answer
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:160]
            raise ProviderError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise ProviderError("Não foi possível obter uma resposta do Ollama.") from exc
