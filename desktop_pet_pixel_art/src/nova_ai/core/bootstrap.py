"""Ponto de entrada controlado para testes e integração futura."""

from .application import NovaAI
from .config import NovaAIConfig


def initialize_core(config=None):
    """Cria e inicializa o núcleo local sem carregar backends ou a mascote."""
    app = NovaAI(config=config if config is not None else NovaAIConfig())
    return app.initialize()
