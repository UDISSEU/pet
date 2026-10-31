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
            wanted = self.model if ":" in self.model else f"{self.model}:latest"
            return any(
                item.get("name", "") == wanted
                for item in data.get("models", [])
            )
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
            message = data.get("message") if isinstance(data, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise ProviderError("O Ollama retornou uma resposta vazia ou inválida.")
            answer = content.strip()
            return answer
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")[:160]
            raise ProviderError(f"Ollama HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError) as exc:
            raise ProviderError("Não foi possível obter uma resposta válida do Ollama.") from exc
