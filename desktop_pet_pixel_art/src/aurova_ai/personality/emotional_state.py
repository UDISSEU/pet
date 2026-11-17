"""Estados simulados compatíveis com os estados visuais da mascote."""

from dataclasses import dataclass
from enum import Enum


class BehaviorState(str, Enum):
    CALM = "CALM"
    CURIOUS = "CURIOUS"
    CARING = "CARING"
    PLAYFUL = "PLAYFUL"
    FOCUSED = "FOCUSED"
    RESTING = "RESTING"
    IDLE = "IDLE"
    THINKING = "THINKING"
    WORKING = "WORKING"
    HAPPY = "HAPPY"
    SLEEPING = "SLEEPING"
    ERROR = "ERROR"


class SimulatedEmotion(str, Enum):
    CALM = "calm"
    CURIOUS = "curious"
    CARING = "caring"
    PLAYFUL = "playful"
    FOCUSED = "focused"
    JOYFUL = "joyful"
    RESTING = "resting"
    CONCERNED = "concerned"


_EMOTION_FOR_STATE = {
    BehaviorState.CALM: SimulatedEmotion.CALM,
    BehaviorState.CURIOUS: SimulatedEmotion.CURIOUS,
    BehaviorState.CARING: SimulatedEmotion.CARING,
    BehaviorState.PLAYFUL: SimulatedEmotion.PLAYFUL,
    BehaviorState.FOCUSED: SimulatedEmotion.FOCUSED,
    BehaviorState.RESTING: SimulatedEmotion.RESTING,
    BehaviorState.IDLE: SimulatedEmotion.CALM,
    BehaviorState.THINKING: SimulatedEmotion.CURIOUS,
    BehaviorState.WORKING: SimulatedEmotion.FOCUSED,
    BehaviorState.HAPPY: SimulatedEmotion.JOYFUL,
    BehaviorState.SLEEPING: SimulatedEmotion.RESTING,
    BehaviorState.ERROR: SimulatedEmotion.CONCERNED,
}

_PROMPT_GUIDANCE = {
    BehaviorState.CALM: "Mantenha um tom tranquilo e deixe a pessoa conduzir.",
    BehaviorState.CURIOUS: "Mostre curiosidade com perguntas úteis; não invente certeza.",
    BehaviorState.CARING: "Responda com acolhimento, sem presumir emoções nem oferecer diagnósticos.",
    BehaviorState.PLAYFUL: "Use brincadeiras leves apenas se combinarem com o pedido.",
    BehaviorState.FOCUSED: "Seja objetiva e informe apenas ações realmente concluídas.",
    BehaviorState.RESTING: "Use um tom tranquilo e menos comunicativo, sem sugerir que está literalmente dormindo.",
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
