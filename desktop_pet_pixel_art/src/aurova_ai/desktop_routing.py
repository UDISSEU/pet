"""Route desktop requests between migrated cognitive tasks and legacy actions."""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)


def _looks_like_ambiguous_organization(text):
    if not isinstance(text, str):
        return False
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    words = set(re.findall(r"[\w]+", normalized))
    verbs = {"organize", "organizar", "organiza", "arrume", "arrumar", "arruma",
             "separe", "separar", "separa", "classifique", "classificar", "classifica"}
    objects = {"arquivo", "arquivos", "pasta", "pastas", "downloads"}
    return bool(words & verbs and words & objects)


def route_user_request(text, *, cognitive_classifier=None, legacy_recognizer):
    """Return ``(route, payload)`` without executing either kind of task.

    Download organization is considered migrated even when the cognitive
    classifier fails or returns unknown. That request must fail through the
    cognitive path rather than fall back to the legacy file mover.
    """
    cognitive_supported = False
    if cognitive_classifier is not None:
        try:
            cognitive_supported = bool(cognitive_classifier(text))
        except Exception:
            logger.exception("Falha ao classificar solicitação para o núcleo cognitivo")

    if cognitive_supported:
        logger.info("Solicitação roteada pelo núcleo cognitivo")
        return "cognitive", None

    # Ambiguous organization requests go to cognition for clarification. They
    # never inherit Downloads as an implicit target.
    if cognitive_classifier is not None and _looks_like_ambiguous_organization(text):
        logger.info("Solicitação de organização ambígua roteada para esclarecimento cognitivo")
        return "cognitive", None

    legacy = legacy_recognizer(text)
    if legacy is not None and legacy.get("id") == "organize_downloads":
        if cognitive_classifier is None:
            logger.error("Organização de Downloads bloqueada: núcleo cognitivo indisponível")
            return "unavailable", None
        logger.warning("Organização de Downloads direcionada ao núcleo cognitivo após fallback seguro")
        return "cognitive", None
    if legacy is not None:
        logger.info("Solicitação roteada pela automação legado: %s", legacy.get("id", "unknown"))
        return "legacy", legacy
    logger.debug("Solicitação sem intenção de tarefa local reconhecida")
    return "conversation", None
