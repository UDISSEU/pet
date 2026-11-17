"""Compatibility imports for the former ``nova_ai`` package."""

import importlib
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader
import sys

import aurova_ai as _aurova_ai

AurovaAI = _aurova_ai.AurovaAI
AurovaAIConfig = _aurova_ai.AurovaAIConfig
AurovaAIError = _aurova_ai.AurovaAIError
NovaAI = AurovaAI
NovaAIConfig = AurovaAIConfig
NovaAIError = AurovaAIError

__path__ = _aurova_ai.__path__
__all__ = [
    "AurovaAI", "AurovaAIConfig", "AurovaAIError",
    "NovaAI", "NovaAIConfig", "NovaAIError",
]


class _LegacyModuleLoader(Loader):
    def __init__(self, module):
        self.module = module

    def create_module(self, _spec):
        return self.module

    def exec_module(self, _module):
        return None


class _LegacyModuleFinder(MetaPathFinder):
    def find_spec(self, fullname, _path=None, _target=None):
        prefix = __name__ + "."
        if not fullname.startswith(prefix):
            return None
        canonical_name = "aurova_ai." + fullname[len(prefix):]
        module = importlib.import_module(canonical_name)
        return spec_from_loader(
            fullname,
            _LegacyModuleLoader(module),
            is_package=hasattr(module, "__path__"),
        )


sys.meta_path.insert(0, _LegacyModuleFinder())
