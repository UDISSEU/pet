"""Conservative, temporary tone cues based only on explicit wording."""

import re
import unicodedata

from .emotional_state import BehaviorState


_CUES = (
    (
        BehaviorState.CARING,
        re.compile(
            r"\b(?:estou|to|me sinto|fiquei)\s+(?:muito\s+)?"
            r"(?:triste|ansios[oa]|frustrad[oa]|sobrecarregad[oa]|"
            r"preocupad[oa]|cansad[oa])\b"
        ),
    ),
    (
        BehaviorState.CARING,
        re.compile(r"\b(?:nao estou bem|dia dificil|preciso de apoio)\b"),
    ),
    (
        BehaviorState.HAPPY,
        re.compile(
            r"\b(?:deu certo|estou feliz|to feliz|que conquista|"
            r"estou orgulhos[oa])\b|\bconsegui!"
        ),
    ),
    (
        BehaviorState.FOCUSED,
        re.compile(r"\b(?:preciso focar|sem enrolacao|seja objetiv[oa])\b"),
    ),
    (
        BehaviorState.PLAYFUL,
        re.compile(r"\b(?:kkkk+|rsrs+|haha+|hehe+)\b"),
    ),
)


def _normalize(text):
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


class EmotionDetector:
    """Detects clear conversational cues without diagnoses or persistence."""

    def detect(self, message):
        if not isinstance(message, str) or not message.strip():
            return None
        normalized = _normalize(message[:4000])
        for state, cue in _CUES:
            if cue.search(normalized):
                return state
        return None
