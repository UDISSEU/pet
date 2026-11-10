"""Compatibility exports for the Nova mascot's dialogue system."""

from nova_ai.personality.speech import (
    APP_COMMENTS,
    GENERIC_COMMENTS,
    JOKES,
    PERSONALITY_IDENTITY,
    SIT_DOWN_LINES,
    SPEECH_LINES,
    SPEECH_POOLS,
    STAND_CLOSED_LINES,
    STAND_TIMEOUT_LINES,
    can_speak_spontaneously,
    pick_line,
    record_spontaneous_speech,
    reset_personality_state,
)

__all__ = [
    "APP_COMMENTS",
    "GENERIC_COMMENTS",
    "JOKES",
    "PERSONALITY_IDENTITY",
    "SIT_DOWN_LINES",
    "SPEECH_LINES",
    "SPEECH_POOLS",
    "STAND_CLOSED_LINES",
    "STAND_TIMEOUT_LINES",
    "can_speak_spontaneously",
    "pick_line",
    "record_spontaneous_speech",
    "reset_personality_state",
]
