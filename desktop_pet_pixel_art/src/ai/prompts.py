"""Prompts comuns aos provedores da Nova."""

from assistant_actions import current_datetime_context
from ai.personality import Personality


def build_system_prompt(personality=None):
    return f"{(personality or Personality()).system_prompt()}\n\n{current_datetime_context()}"
