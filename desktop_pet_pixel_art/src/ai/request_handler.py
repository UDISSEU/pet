"""Processa uma solicitação de IA fora da camada de interface."""

import logging

from ai.ai_core import AICore
from providers.base_provider import ProviderError

logger = logging.getLogger(__name__)

PROVIDER_FAILURE_MESSAGE = "A IA não conseguiu responder agora. Tente novamente daqui a pouco."


def answer_request(history, memories=None, settings=None, user_name="", core_factory=AICore):
    """Return a displayable answer while keeping Tkinter out of the worker."""
    try:
        return core_factory(settings=settings or {}).process_message(
            history, memories=memories, user_name=user_name,
        )
    except ProviderError as exc:
        logger.info("Consulta de IA não concluída (%s)", type(exc).__name__)
        return PROVIDER_FAILURE_MESSAGE
    except Exception as exc:
        logger.warning(
            "Falha inesperada ao consultar o provedor de IA (%s)",
            type(exc).__name__,
        )
        return "Tive um problema ao consultar a IA. Tente novamente daqui a pouco."
