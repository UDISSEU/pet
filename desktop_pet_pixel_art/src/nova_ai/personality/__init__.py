"""Personalidade declarativa, persistente e independente de modelos externos."""

from .behavior_rules import BehaviorRule, BehaviorRules
from .conversation import BehavioralState, Personality
from .emotion_detector import EmotionDetector
from .emotional_state import BehaviorState, EmotionalState, SimulatedEmotion
from .identity import NovaIdentity
from .personality_engine import PersonalityEngine, PersonalityPersistenceError
from .preference_learner import PreferenceLearner
from .response_style import ResponseStyle, Tone, Verbosity

__all__ = [
    "BehaviorRule", "BehaviorRules", "BehaviorState", "BehavioralState",
    "EmotionDetector",
    "EmotionalState", "NovaIdentity",
    "Personality", "PersonalityEngine", "PersonalityPersistenceError",
    "PreferenceLearner", "ResponseStyle", "SimulatedEmotion", "Tone", "Verbosity",
]
