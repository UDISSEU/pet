import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ai.ai_core import AICore
from ai.context_manager import ContextManager
from ai.model_router import ModelRouter
from autonomy import load_settings, save_settings
from providers.base_provider import ProviderError
from providers.gemini_provider import GeminiProvider
from providers.groq_provider import GroqProvider
from providers.ollama_provider import OllamaProvider


class FakeProvider:
    def __init__(self, result="resposta", error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def generate(self, messages, system_prompt, timeout=30):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class TestAIProviders(unittest.TestCase):
    def test_online_provider_is_not_used_without_both_authorizations(self):
        online, local = FakeProvider("nuvem"), FakeProvider("local")
        def factory(name, _settings):
            return online if name == "gemini" else local
        router = ModelRouter({"ai_provider": "gemini", "online_ai_enabled": True}, factory)
        self.assertEqual(router.generate([], "prompt"), "local")
        self.assertEqual((online.calls, local.calls), (0, 1))

    def test_online_provider_falls_back_to_local_without_revealing_error(self):
        online = FakeProvider(error=ProviderError("private detail"))
        local = FakeProvider("resposta local")
        def factory(name, _settings):
            return online if name == "gemini" else local
        router = ModelRouter({
            "ai_provider": "gemini", "online_ai_enabled": True,
            "allow_online_data": True, "confirm_free_tier": True,
        }, factory)
        self.assertEqual(router.generate([], "prompt"), "resposta local")
        self.assertEqual(local.calls, 1)

    def test_failure_of_both_providers_is_reported_safely(self):
        def factory(_name, _settings):
            return FakeProvider(error=ProviderError("secret key value"))
        router = ModelRouter({
            "ai_provider": "groq", "online_ai_enabled": True,
            "allow_online_data": True, "confirm_free_tier": True,
        }, factory)
        with self.assertRaises(ProviderError) as caught:
            router.generate([], "prompt")
        self.assertNotIn("secret key", str(caught.exception))

    def test_context_is_bounded_and_filters_invalid_messages(self):
        history = ([{"role": "user", "content": "x" * 5000}] * 15 + [
            {"role": "system", "content": "não incluir"},
        ])
        messages, memories = ContextManager().build(history, ["memória"], "Ana")
        self.assertEqual(len(messages), 12)
        self.assertEqual(len(messages[0]["content"]), 4000)
        self.assertEqual(memories, [])

    def test_context_only_selects_memories_related_to_latest_question(self):
        _messages, memories = ContextManager().build(
            [{"role": "user", "content": "Qual é minha preferência de respostas curtas?"}],
            ["Prefere respostas curtas", "Tem um gato chamado Nino"],
        )
        self.assertEqual(memories, ["Prefere respostas curtas"])

    def test_gemini_uses_official_generate_content_request_shape(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "Olá"}]}}],
        }).encode()
        provider = GeminiProvider(api_key="dummy", model="gemini-3.8-flash")
        with mock.patch("providers.gemini_provider.urllib.request.urlopen", return_value=response) as open_url:
            self.assertEqual(provider.generate([{"role": "assistant", "content": "Oi"}], "Nova"), "Olá")
        request = open_url.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/models/gemini-3.8-flash:generateContent"))
        payload = json.loads(request.data)
        self.assertEqual(payload["contents"][0]["role"], "model")
        self.assertIn("systemInstruction", payload)
        self.assertEqual(request.get_header("X-goog-api-key"), "dummy")

    def test_groq_uses_chat_completions_and_auth_header(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "choices": [{"message": {"content": "Oi"}}],
        }).encode()
        provider = GroqProvider(api_key="dummy")
        with mock.patch("providers.groq_provider.urllib.request.urlopen", return_value=response) as open_url:
            self.assertEqual(provider.generate([], "Nova"), "Oi")
        request = open_url.call_args.args[0]
        self.assertEqual(request.full_url, provider.endpoint)
        self.assertEqual(request.get_header("Authorization"), "Bearer dummy")

    def test_online_provider_requires_api_key(self):
        self.assertFalse(GeminiProvider(api_key="").is_available())
        self.assertFalse(GroqProvider(api_key="").is_available())

    def test_ollama_availability_checks_model_list(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({
            "models": [{"name": "llama3.2:1b"}],
        }).encode()
        provider = OllamaProvider(model="llama3.2:1b")
        with mock.patch("providers.ollama_provider.urllib.request.urlopen", return_value=response):
            self.assertTrue(provider.is_available())
        wrong_tag = OllamaProvider(model="llama3.2:1b")
        response.__enter__.return_value.read.return_value = json.dumps({
            "models": [{"name": "llama3.2:3b"}],
        }).encode()
        with mock.patch("providers.ollama_provider.urllib.request.urlopen", return_value=response):
            self.assertFalse(wrong_tag.is_available())
        untagged = OllamaProvider(model="llama3.2")
        response.__enter__.return_value.read.return_value = json.dumps({
            "models": [{"name": "llama3.2:latest"}],
        }).encode()
        with mock.patch("providers.ollama_provider.urllib.request.urlopen", return_value=response):
            self.assertTrue(untagged.is_available())
        with mock.patch(
            "providers.ollama_provider.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            self.assertFalse(provider.is_available())

    def test_gemini_http_429_becomes_a_sanitized_provider_error(self):
        error = urllib.error.HTTPError("https://example.invalid", 429, "limit", {}, None)
        provider = GeminiProvider(api_key="dummy")
        with mock.patch("providers.gemini_provider.urllib.request.urlopen", side_effect=error) as open_url:
            with self.assertRaises(ProviderError) as caught:
                provider.generate([{"role": "user", "content": "Oi"}], "Nova", timeout=7)
        self.assertIn("HTTP 429", str(caught.exception))
        self.assertNotIn("dummy", str(caught.exception))
        self.assertAlmostEqual(open_url.call_args.kwargs["timeout"], 7, delta=0.5)

    def test_settings_keep_local_private_defaults_and_validate_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            self.assertTrue(save_settings({"ai_timeout": 999, "ai_provider": "unknown"}, path))
            settings = load_settings(path)
        self.assertEqual(settings["ai_provider"], "ollama")
        self.assertFalse(settings["online_ai_enabled"])
        self.assertFalse(settings["allow_online_data"])
        self.assertFalse(settings["confirm_free_tier"])
        self.assertEqual(settings["ai_timeout"], 30)

    def test_ai_core_generates_contextual_prompt(self):
        router = mock.Mock(generate=mock.Mock(return_value="resposta"))
        core = AICore(router=router)
        result = core.process_message([{"role": "user", "content": "Oi"}])
        self.assertEqual(result, "resposta")

    def test_user_name_is_always_in_system_prompt_without_matching_memory(self):
        router = mock.Mock(generate=mock.Mock(return_value="resposta"))
        core = AICore(router=router)
        core.process_message(
            [{"role": "user", "content": "Como está o clima?"}], user_name="Ada"
        )
        prompt = router.generate.call_args.args[1]
        self.assertIn("Ada", prompt)
        self.assertIn("Como está o clima?", router.generate.call_args.args[0][0]["content"])


if __name__ == "__main__":
    unittest.main()
