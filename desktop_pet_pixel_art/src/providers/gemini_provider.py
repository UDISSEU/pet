"""Integração REST com Gemini API, sem SDK ou dependências extras."""

import json
import os
import time
import urllib.error
import urllib.request

from providers.base_provider import BaseProvider, ProviderError


class GeminiProvider(BaseProvider):
    name = "gemini"
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    models_endpoint = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key=None, model="gemini-3.8-flash"):
        self.api_key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        self.model = model

    def is_available(self):
        return bool(self.api_key)

    def test_connection(self, timeout=10):
        if not self.is_available():
            raise ProviderError("GEMINI_API_KEY não está configurada no ambiente ou no cofre do sistema.")
        request = urllib.request.Request(
            self.models_endpoint,
            headers={"x-goog-api-key": self.api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            available = {item.get("name", "").removeprefix("models/") for item in data.get("models", [])}
            if self.model not in available:
                raise ProviderError(f"Gemini autenticou, mas o modelo '{self.model}' não está disponível.")
            return f"Conectado ao Gemini; modelo {self.model} disponível."
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"Gemini HTTP {exc.code}; confira a chave e o acesso ao projeto.") from exc
        except ProviderError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError) as exc:
            raise ProviderError("Não foi possível testar a conexão com o Gemini.") from exc

    def generate(self, messages, system_prompt, timeout=30):
        if not self.is_available():
            raise ProviderError("GEMINI_API_KEY não está configurada no ambiente.")
        contents = []
        for message in messages:
            role = "model" if message.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": message.get("content", "")}]})
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {"maxOutputTokens": 256, "temperature": 0.7},
        }
        request = urllib.request.Request(
            self.endpoint.format(model=self.model), data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        deadline = time.monotonic() + timeout
        for attempt in range(3):
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Prazo da solicitação esgotado")
                with urllib.request.urlopen(request, timeout=remaining) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in (500, 502, 503, 504) or attempt == 2:
                    raise ProviderError(
                        f"Gemini HTTP {exc.code}; confira a disponibilidade do serviço e os limites de uso."
                    ) from exc
                delay = min(2 ** attempt, 3, max(0, deadline - time.monotonic()))
                if delay <= 0:
                    raise ProviderError("O Gemini está temporariamente indisponível.") from exc
                time.sleep(delay)
            except urllib.error.URLError as exc:
                if attempt == 2 or time.monotonic() >= deadline:
                    raise ProviderError("Não foi possível obter uma resposta do Gemini.") from exc
                time.sleep(min(2 ** attempt, max(0, deadline - time.monotonic())))
            except (TimeoutError, OSError, ValueError) as exc:
                raise ProviderError("A geração no Gemini excedeu o tempo limite ou retornou dados inválidos.") from exc
        try:
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            answer = "".join(part.get("text", "") for part in parts).strip()
            if not answer:
                raise ProviderError("Gemini retornou uma resposta vazia ou bloqueada.")
            return answer
        except (IndexError, AttributeError) as exc:
            raise ProviderError("Gemini retornou uma resposta vazia ou inválida.") from exc
