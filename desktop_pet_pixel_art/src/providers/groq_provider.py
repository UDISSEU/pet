"""Integração com a API de chat compatível com OpenAI da Groq."""

import json
import os
import urllib.error
import urllib.request

from providers.base_provider import BaseProvider, ProviderError


class GroqProvider(BaseProvider):
    name = "groq"
    endpoint = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key=None, model="openai/gpt-oss-20b"):
        self.api_key = api_key if api_key is not None else os.environ.get("GROQ_API_KEY", "")
        self.model = model

    def is_available(self):
        return bool(self.api_key)

    def test_connection(self, timeout=10):
        if not self.is_available():
            raise ProviderError("GROQ_API_KEY não está configurada no ambiente.")
        request = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            available = {item.get("id", "") for item in data.get("data", [])}
            if self.model not in available:
                raise ProviderError(f"Groq autenticou, mas o modelo '{self.model}' não está disponível.")
            return f"Conectado à Groq; modelo {self.model} disponível."
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Groq HTTP {exc.code}; confira a chave e o acesso ao modelo.") from exc
        except ProviderError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError) as exc:
            raise ProviderError("Não foi possível testar a conexão com a Groq.") from exc

    def generate(self, messages, system_prompt, timeout=30):
        if not self.is_available():
            raise ProviderError("GROQ_API_KEY não está configurada no ambiente.")
        payload = {"model": self.model, "messages": [
            {"role": "system", "content": system_prompt}, *messages
        ], "max_tokens": 256, "temperature": 0.7}
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if not answer:
                raise ProviderError("Groq retornou uma resposta vazia.")
            return answer
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Groq HTTP {exc.code}; confira a chave e os limites de uso.") from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, IndexError, AttributeError) as exc:
            raise ProviderError("Não foi possível obter uma resposta da Groq.") from exc
