"""Composição e contratos centrais da Nova AI."""

from .application import NovaAI
from .config import NovaAIConfig
from .errors import NovaAIError
from .registry import ComponentRegistry

__all__ = ["ComponentRegistry", "NovaAI", "NovaAIConfig", "NovaAIError"]
