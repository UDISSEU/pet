"""Testes unitários do núcleo isolado, sem iniciar a mascote ou provedores."""

import os
import subprocess
import sys
import unittest
from pathlib import Path
from abc import ABC

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class NovaAIInfrastructureTests(unittest.TestCase):
    def test_controlled_initialization_is_local_and_lightweight(self):
        from nova_ai.core.bootstrap import initialize_core

        app = initialize_core()
        self.assertTrue(app.initialized)
        self.assertEqual(app.registry.names(), ())
        self.assertFalse(app.config.load_model_on_start)
        self.assertFalse(app.config.start_training_on_start)

    def test_initialization_does_not_import_legacy_providers_or_tk(self):
        script = """
import sys
import threading
import urllib.request
urllib.request.urlopen = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network used'))
before = threading.active_count()
import nova_ai
from nova_ai.core.bootstrap import initialize_core
initialize_core()
assert not any(name == 'providers' or name.startswith('providers.') for name in sys.modules)
assert 'tkinter' not in sys.modules
assert threading.active_count() == before
"""
        environment = dict(os.environ, PYTHONPATH=str(SRC))
        subprocess.run(
            [sys.executable, "-c", script],
            cwd=SRC.parent,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_configuration_defaults_and_bounds(self):
        from nova_ai.core.config import NovaAIConfig
        from nova_ai.core.errors import ConfigurationError

        self.assertEqual(NovaAIConfig().max_context_chars, 8_000)
        with self.assertRaises(ConfigurationError):
            NovaAIConfig(max_context_chars=100_000)
        with self.assertRaises(ConfigurationError):
            NovaAIConfig(max_memory_items=True)
        with self.assertRaises(ConfigurationError):
            NovaAIConfig(load_model_on_start=True)
        with self.assertRaises(ConfigurationError):
            NovaAIConfig(start_training_on_start=True)

    def test_registry_explicit_registration_and_limits(self):
        from nova_ai.core.errors import ComponentNotFoundError, ComponentRegistrationError
        from nova_ai.core.registry import ComponentRegistry

        registry = ComponentRegistry(max_components=1)
        component = object()
        self.assertIs(registry.register("sample", component), component)
        self.assertIs(registry.get("sample"), component)
        self.assertEqual(registry.names(), ("sample",))
        with self.assertRaises(ComponentRegistrationError):
            registry.register("sample", object())
        with self.assertRaises(ComponentRegistrationError):
            registry.register("extra", object())
        with self.assertRaises(ComponentNotFoundError):
            registry.get("missing")

    def test_errors_are_stable_and_unexpected_details_are_hidden(self):
        from nova_ai.core.errors import NovaAIError, normalize_error

        expected = NovaAIError("safe")
        self.assertIs(normalize_error(expected), expected)
        unexpected = normalize_error(RuntimeError("private data"))
        self.assertEqual(unexpected.code, "nova_ai_error")
        self.assertNotIn("private data", str(unexpected))
        self.assertIsInstance(unexpected.cause, RuntimeError)

    def test_model_and_tool_interfaces_are_abstract(self):
        from nova_ai.actions import Tool
        from nova_ai.model import Model

        self.assertTrue(issubclass(Model, ABC))
        with self.assertRaises(TypeError):
            Model()
        with self.assertRaises(TypeError):
            Tool()

    def test_initialization_is_one_shot_for_component_registration(self):
        from nova_ai.core.application import NovaAI
        from nova_ai.core.errors import InitializationError

        app = NovaAI().initialize()
        with self.assertRaises(InitializationError):
            app.register("late", object())

    def test_component_initialization_is_explicit_and_errors_are_normalized(self):
        from nova_ai.core.application import NovaAI
        from nova_ai.core.errors import InitializationError

        calls = []

        class Component:
            def initialize(self):
                calls.append("started")

        app = NovaAI()
        app.register("component", Component())
        with self.assertRaises(InitializationError):
            app.initialize_component("component")
        app.initialize()
        self.assertEqual(calls, [])
        app.initialize_component("component")
        app.initialize_component("component")
        self.assertEqual(calls, ["started"])

        class Broken:
            def initialize(self):
                raise RuntimeError("private detail")

        app2 = NovaAI()
        app2.register("broken", Broken())
        app2.initialize()
        with self.assertRaises(InitializationError) as caught:
            app2.initialize_component("broken")
        self.assertNotIn("private detail", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
