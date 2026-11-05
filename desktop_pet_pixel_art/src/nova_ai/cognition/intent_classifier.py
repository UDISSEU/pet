"""Classificador offline por regras, com fallback opcional para um modelo injetado."""

from dataclasses import dataclass, field
from enum import Enum
import json
import re
import unicodedata

from nova_ai.core.errors import NovaAIError


class IntentName(str, Enum):
    ORGANIZE_DOWNLOADS = "organize_downloads"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Intent:
    name: IntentName
    confidence: float
    source: str
    entities: dict = field(default_factory=dict)


class IntentClassificationError(NovaAIError):
    code = "intent_classification_error"


def _normalize(text):
    normalized = unicodedata.normalize("NFKD", text.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.findall(r"[\w]+", normalized))


class IntentClassifier:
    _ORGANIZE_VERBS = {
        "organize", "organizar", "organiza", "organizar", "arrume", "arrumar",
        "arruma", "separe", "separar", "separa", "classifique", "classificar",
        "classifica", "organise", "sort",
    }

    def classify(self, text, *, model=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 4_000:
            raise ValueError("A solicitação deve ter entre 1 e 4000 caracteres")
        normalized = _normalize(text)
        tokens = set(normalized.split())
        has_downloads = bool(tokens & {"download", "downloads"})
        if has_downloads and tokens & self._ORGANIZE_VERBS:
            return Intent(
                IntentName.ORGANIZE_DOWNLOADS,
                confidence=0.98,
                source="rules",
                entities={"target": "downloads"},
            )
        if model is not None:
            return self._classify_with_model(text, model)
        return Intent(IntentName.UNKNOWN, confidence=0.0, source="rules")

    @staticmethod
    def _classify_with_model(text, model):
        if not callable(getattr(model, "generate", None)):
            raise IntentClassificationError("O modelo não implementa generate()")
        messages = [
            {
                "role": "system",
                "content": (
                    "Classifique a solicitação. Responda somente JSON com as chaves intent, "
                    "confidence e entities. Intenções permitidas: organize_downloads, unknown. "
                    "Use unknown quando houver incerteza. Não planeje nem execute ações."
                ),
            },
            {"role": "user", "content": text},
        ]
        try:
            output = model.generate(messages, max_new_tokens=128)
            data = json.loads(output)
        except Exception as exc:
            raise IntentClassificationError(
                "Não foi possível classificar a solicitação com o modelo", cause=exc
            ) from exc
        if not isinstance(data, dict):
            raise IntentClassificationError("Resposta de classificação inválida")
        try:
            name = IntentName(data.get("intent"))
            confidence = data.get("confidence")
            entities = data.get("entities", {})
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise ValueError("confidence precisa ser numérica")
            if not 0 <= confidence <= 1:
                raise ValueError("confidence fora do intervalo")
            if not isinstance(entities, dict) or set(entities) - {"target"}:
                raise ValueError("entities inválidas")
            if name is IntentName.ORGANIZE_DOWNLOADS and entities.get("target", "downloads") != "downloads":
                raise ValueError("alvo não suportado")
        except (ValueError, TypeError) as exc:
            raise IntentClassificationError("Resposta de classificação inválida", cause=exc) from exc
        if name is IntentName.ORGANIZE_DOWNLOADS:
            entities = {"target": "downloads"}
        else:
            entities = {}
        return Intent(name, float(confidence), "model", entities)
