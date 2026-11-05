"""Estados simulados compatíveis com os estados visuais da mascote."""

from dataclasses import dataclass
from enum import Enum


class BehaviorState(str, Enum):
    IDLE = "IDLE"
    THINKING = "THINKING"
    WORKING = "WORKING"
    HAPPY = "HAPPY"
    SLEEPING = "SLEEPING"
    ERROR = "ERROR"


class SimulatedEmotion(str, Enum):
    CALM = "calm"
    CURIOUS = "curious"
    FOCUSED = "focused"
    JOYFUL = "joyful"
    RESTING = "resting"
    CONCERNED = "concerned"


_EMOTION_FOR_STATE = {
    BehaviorState.IDLE: SimulatedEmotion.CALM,
    BehaviorState.THINKING: SimulatedEmotion.CURIOUS,
    BehaviorState.WORKING: SimulatedEmotion.FOCUSED,
    BehaviorState.HAPPY: SimulatedEmotion.JOYFUL,
    BehaviorState.SLEEPING: SimulatedEmotion.RESTING,
    BehaviorState.ERROR: SimulatedEmotion.CONCERNED,
}

_PROMPT_GUIDANCE = {
    BehaviorState.IDLE: "Mantenha um tom tranquilo e deixe a pessoa conduzir.",
    BehaviorState.THINKING: "Mostre curiosidade com perguntas úteis; não invente certeza.",
    BehaviorState.WORKING: "Seja objetiva e informe apenas ações realmente concluídas.",
    BehaviorState.HAPPY: "Use leveza moderada, sem exagerar intimidade ou elogios.",
    BehaviorState.SLEEPING: "Seja breve e tranquila; não sugira que está literalmente dormindo.",
    BehaviorState.ERROR: "Explique a limitação com calma e indique um próximo passo seguro.",
}


@dataclass(frozen=True)
class EmotionalState:
    behavior: BehaviorState = BehaviorState.IDLE
    emotion: SimulatedEmotion = SimulatedEmotion.CALM

    @property
    def prompt_guidance(self):
        return _PROMPT_GUIDANCE[self.behavior]

    @classmethod
    def for_behavior(cls, behavior):
        try:
            behavior = BehaviorState(behavior)
        except ValueError as exc:
            raise ValueError("Estado comportamental inválido") from exc
        return cls(behavior=behavior, emotion=_EMOTION_FOR_STATE[behavior])

    @classmethod
    def restore(cls, data):
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Estado persistido inválido")
        restored = cls.for_behavior(data.get("behavior"))
        if data.get("emotion") != restored.emotion.value:
            raise ValueError("Emoção não corresponde ao estado comportamental")
        return restored

    def to_dict(self):
        return {
            "version": 1,
            "behavior": self.behavior.value,
            "emotion": self.emotion.value,
        }
