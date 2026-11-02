"""Prompts comuns aos provedores da Nova."""

from assistant_actions import current_datetime_context
from ai.personality import Personality


def build_system_prompt(personality=None, humor_style="equilibrada"):
    return f"{(personality or Personality(humor_style=humor_style)).system_prompt()}\n\n{current_datetime_context()}"
