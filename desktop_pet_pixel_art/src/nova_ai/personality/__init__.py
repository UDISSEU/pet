"""Personalidade declarativa, persistente e independente de modelos externos."""

from .behavior_rules import BehaviorRule, BehaviorRules
from .emotional_state import BehaviorState, EmotionalState, SimulatedEmotion
from .identity import NovaIdentity
from .personality_engine import PersonalityEngine, PersonalityPersistenceError
from .response_style import ResponseStyle, Tone, Verbosity

__all__ = [
    "BehaviorRule", "BehaviorRules", "BehaviorState", "EmotionalState", "NovaIdentity",
    "PersonalityEngine", "PersonalityPersistenceError", "ResponseStyle",
    "SimulatedEmotion", "Tone", "Verbosity",
]
