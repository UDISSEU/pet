"""Processa uma solicitação de IA fora da camada de interface."""

import logging

from ai.ai_core import AICore
from providers.base_provider import ProviderError

logger = logging.getLogger(__name__)

PROVIDER_FAILURE_MESSAGE = "A IA não conseguiu responder agora. Tente novamente daqui a pouco."


def conversation_context_for_request(history, settings):
    """Return saved conversation context only after an explicit opt-in."""
    if isinstance(settings, dict) and settings.get("conversation_context_enabled") is True:
        return list(history)
    latest_user_message = next(
        (
            message for message in reversed(history)
            if isinstance(message, dict) and message.get("role") == "user"
        ),
        None,
    )
    return [latest_user_message] if latest_user_message is not None else []


def conversation_history_is_enabled(settings):
    """Return whether persistent conversation storage was explicitly enabled."""
    return (
        isinstance(settings, dict)
        and settings.get("conversation_history_enabled") is True
    )


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
