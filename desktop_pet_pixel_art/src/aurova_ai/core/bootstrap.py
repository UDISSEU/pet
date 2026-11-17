"""Ponto de entrada controlado para testes e integração futura."""

from .application import AurovaAI
from .config import AurovaAIConfig


def initialize_core(config=None):
    """Cria e inicializa o núcleo local sem carregar backends ou a mascote."""
    app = AurovaAI(config=config if config is not None else AurovaAIConfig())
    return app.initialize()
