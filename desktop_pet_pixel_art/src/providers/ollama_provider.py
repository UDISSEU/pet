"""Provedor local Ollama, usando a API HTTP oficial instalada localmente."""

import json
import threading
import urllib.error
import urllib.request

from config import OLLAMA_MODEL, OLLAMA_URL
from providers.base_provider import BaseProvider, ProviderError

_LOCAL_INFERENCE_LOCK = threading.Lock()


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, model=OLLAMA_MODEL, url=OLLAMA_URL, timeout=30,
                 num_ctx=1024, num_predict=96, num_threads=1, keep_alive="30s"):
        if (type(num_ctx) is not int or not 512 <= num_ctx <= 2048
                or type(num_predict) is not int or not 16 <= num_predict <= 256
                or type(num_threads) is not int or not 1 <= num_threads <= 2):
            raise ValueError("Limites conservadores do Ollama inválidos")
        self.model = model
        self.url = url
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.num_predict = num_predict
        self.num_threads = num_threads
        self.keep_alive = keep_alive

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
        if not _LOCAL_INFERENCE_LOCK.acquire(blocking=False):
            raise ProviderError("Já existe uma inferência local em andamento.")
        try:
            payload = {
                "model": self.model,
                "messages": [{"role": "system", "content": system_prompt}, *messages],
                "stream": False,
                "keep_alive": self.keep_alive,
                "options": {
                    "num_ctx": self.num_ctx,
                    "num_predict": self.num_predict,
                    "num_thread": self.num_threads,
                },
            }
            request = urllib.request.Request(
                self.url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            message = data.get("message") if isinstance(data, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str) or not content.strip():
                raise ProviderError("O Ollama retornou uma resposta vazia ou inválida.")
            answer = content.strip()
            return answer
        except urllib.error.HTTPError as exc:
            raise ProviderError(
                f"Ollama respondeu com HTTP {exc.code}. Confira se o serviço e o modelo estão disponíveis."
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, AttributeError) as exc:
            raise ProviderError("Não foi possível obter uma resposta válida do Ollama.") from exc
        finally:
            _LOCAL_INFERENCE_LOCK.release()
