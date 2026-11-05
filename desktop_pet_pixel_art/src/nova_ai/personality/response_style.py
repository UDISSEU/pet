"""Estilo de resposta estável e configurável por preferências autorizadas."""

from dataclasses import dataclass
from enum import Enum


class Tone(str, Enum):
    NATURAL_FRIENDLY = "natural_friendly"
    CALM = "calm"
    NEUTRAL = "neutral"


class Verbosity(str, Enum):
    CONCISE = "concise"
    BALANCED = "balanced"
    DETAILED = "detailed"


@dataclass(frozen=True)
class ResponseStyle:
    tone: Tone = Tone.NATURAL_FRIENDLY
    verbosity: Verbosity = Verbosity.BALANCED
    language: str = "pt-BR"

    def __post_init__(self):
        try:
            object.__setattr__(self, "tone", Tone(self.tone))
            object.__setattr__(self, "verbosity", Verbosity(self.verbosity))
        except ValueError as exc:
            raise ValueError("Tom ou nível de detalhe inválido") from exc
        if self.language not in {"pt-BR", "pt-PT", "en"}:
            raise ValueError("Idioma de resposta não suportado")

    def guidance(self):
        tone = {
            Tone.NATURAL_FRIENDLY: "Use comunicação natural, amigável e clara.",
            Tone.CALM: "Use comunicação calma, gentil e clara.",
            Tone.NEUTRAL: "Use comunicação neutra, respeitosa e clara.",
        }[self.tone]
        verbosity = {
            Verbosity.CONCISE: "Prefira respostas curtas e diretas.",
            Verbosity.BALANCED: "Seja concisa, detalhando quando isso ajudar.",
            Verbosity.DETAILED: "Explique os passos e o contexto com mais detalhe.",
        }[self.verbosity]
        return f"{tone} {verbosity} Idioma: {self.language}."
