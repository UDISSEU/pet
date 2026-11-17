"""Infraestrutura independente da Aurova AI, sem interface ou backend obrigatório."""

from .core.application import AurovaAI
from .core.config import AurovaAIConfig
from .core.errors import AurovaAIError

NovaAI = AurovaAI
NovaAIConfig = AurovaAIConfig
NovaAIError = AurovaAIError

__all__ = [
    "AurovaAI", "AurovaAIConfig", "AurovaAIError",
    "NovaAI", "NovaAIConfig", "NovaAIError",
]
