"""Integração REST com a API de chat da Mistral."""

import json
import os
import urllib.error
import urllib.request

from providers.base_provider import BaseProvider, ProviderError


class MistralProvider(BaseProvider):
    name = "mistral"
    endpoint = "https://api.mistral.ai/v1/chat/completions"
    models_endpoint = "https://api.mistral.ai/v1/models"

    def __init__(self, api_key=None, model="mistral-small-latest"):
        self.api_key = api_key if api_key is not None else os.environ.get("MISTRAL_API_KEY", "")
        self.model = model

    def is_available(self):
        return bool(self.api_key)

    def test_connection(self, timeout=10):
        if not self.is_available():
            raise ProviderError("MISTRAL_API_KEY não está configurada no ambiente ou no cofre do sistema.")
        request = urllib.request.Request(
            self.models_endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            available = {item.get("id", "") for item in data.get("data", [])}
            if self.model not in available:
                raise ProviderError(f"Mistral autenticou, mas o modelo '{self.model}' não está disponível.")
            return f"Conectado à Mistral; modelo {self.model} disponível."
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Mistral HTTP {exc.code}; confira a chave e o acesso à API.") from exc
        except ProviderError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError) as exc:
            raise ProviderError("Não foi possível testar a conexão com a Mistral.") from exc

    def generate(self, messages, system_prompt, timeout=30):
        if not self.is_available():
            raise ProviderError("MISTRAL_API_KEY não está configurada no ambiente ou no cofre do sistema.")
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "max_tokens": 256,
            "temperature": 0.7,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            answer = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            if not answer:
                raise ProviderError("A Mistral retornou uma resposta vazia.")
            return answer
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Mistral HTTP {exc.code}; confira a chave e os limites de uso.") from exc
        except ProviderError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, IndexError, AttributeError) as exc:
            raise ProviderError("Não foi possível obter uma resposta da Mistral.") from exc
