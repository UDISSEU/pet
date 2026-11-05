"""Coordena identidade, regras, estilo, memórias autorizadas e estado visual."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from nova_ai.memory import MemoryManager, PreferenceMemory
from nova_ai.memory.errors import ConsentRequiredError, MemoryStorageError

from .behavior_rules import BehaviorRules
from .emotional_state import BehaviorState, EmotionalState
from .identity import NovaIdentity
from .response_style import ResponseStyle, Tone, Verbosity

_STATE_VERSION = 1
_PREFERENCE_PREFIX = "Nova interaction preferences:"
_DEFAULT_STATE_PATH = Path.home() / ".config" / "desktop_pet" / "nova_personality.json"


class PersonalityPersistenceError(RuntimeError):
    """Falha segura ao persistir ou recuperar o estado comportamental."""


class PersonalityEngine:
    def __init__(self, *, preference_memory=None, identity=None, rules=None,
                 response_style=None, state_path=None):
        self.identity = identity if identity is not None else NovaIdentity()
        self.rules = rules if rules is not None else BehaviorRules()
        if not isinstance(self.identity, NovaIdentity):
            raise TypeError("identity deve ser NovaIdentity")
        if not isinstance(self.rules, BehaviorRules):
            raise TypeError("rules deve ser BehaviorRules")
        self.preference_memory = preference_memory if preference_memory is not None else (
            PreferenceMemory(MemoryManager())
        )
        if not isinstance(self.preference_memory, PreferenceMemory):
            raise TypeError("preference_memory deve ser PreferenceMemory")
        self.state_path = Path(state_path) if state_path is not None else _DEFAULT_STATE_PATH
        self.response_style = response_style if response_style is not None else ResponseStyle()
        if not isinstance(self.response_style, ResponseStyle):
            raise TypeError("response_style deve ser ResponseStyle")
        self.emotional_state = self._load_state()
        self._load_persisted_response_style()

    @property
    def behavior_state(self):
        return self.emotional_state.behavior

    @property
    def simulated_emotion(self):
        return self.emotional_state.emotion

    def get_behavior_state(self):
        """Valor textual estável para a interface e integração visual futura."""
        return self.behavior_state.value

    def set_behavior_state(self, state):
        next_state = EmotionalState.for_behavior(state)
        previous = self.emotional_state
        self.emotional_state = next_state
        try:
            self._save_state()
        except Exception:
            self.emotional_state = previous
            raise
        return self.emotional_state

    def transition_behavior(self, state):
        """Update temporary mood in memory; it resets to IDLE after restart."""
        self.emotional_state = EmotionalState.for_behavior(state)
        return self.emotional_state

    def set_response_preferences(
        self, *, tone=None, verbosity=None, language=None, consent_confirmed=False
    ):
        if consent_confirmed is not True:
            raise ConsentRequiredError("A alteração de preferências exige confirmação explícita")
        next_style = ResponseStyle(
            tone=self.response_style.tone if tone is None else Tone(tone),
            verbosity=self.response_style.verbosity if verbosity is None else Verbosity(verbosity),
            language=self.response_style.language if language is None else language,
        )
        content = (
            f"{_PREFERENCE_PREFIX} tone={next_style.tone.value}; "
            f"verbosity={next_style.verbosity.value}; language={next_style.language}"
        )
        existing = self._find_style_preference()
        if existing is None:
            self.preference_memory.set_preference(
                content, source="nova_ai.personality", consent_confirmed=True
            )
        else:
            try:
                self.preference_memory.manager.update(
                    existing.memory_id, content=content,
                    source="nova_ai.personality", consent=True,
                )
            except MemoryStorageError:
                # Propagate persistence errors; in-memory preferences must not claim success.
                raise
        self.response_style = next_style
        return self.response_style

    def _find_style_preference(self):
        records = self.preference_memory.recall("Nova interaction preferences", limit=100)
        return next(
            (record for record in records if record.content.startswith(_PREFERENCE_PREFIX)),
            None,
        )

    def _load_persisted_response_style(self):
        record = self._find_style_preference()
        if record is None:
            return
        values = {}
        for part in record.content[len(_PREFERENCE_PREFIX):].strip().split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                values[key] = value
        try:
            self.response_style = ResponseStyle(
                tone=values.get("tone", self.response_style.tone.value),
                verbosity=values.get("verbosity", self.response_style.verbosity.value),
                language=values.get("language", self.response_style.language),
            )
        except ValueError:
            # Invalid or manually edited preferences do not break startup.
            return

    def build_personality_instructions(self):
        parts = [self.identity.system_description()]
        parts.extend(self.rules.instructions())
        parts.append(self.response_style.guidance())
        parts.append(
            f"Estado comportamental atual: {self.behavior_state.value}; "
            f"expressão simulada: {self.simulated_emotion.value}."
        )
        parts.append(self.emotional_state.prompt_guidance)
        parts.append(
            "O estado é apenas uma expressão conversacional temporária: não altera fatos, "
            "permissões, decisões de segurança nem o que a Nova realmente sabe."
        )
        return "\n".join(parts)

    def snapshot(self):
        return {
            "identity": self.identity,
            "behavior_state": self.behavior_state.value,
            "simulated_emotion": self.simulated_emotion.value,
            "response_style": self.response_style,
        }

    def _load_state(self):
        try:
            content = self.state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return EmotionalState.for_behavior(BehaviorState.IDLE)
        except OSError as exc:
            raise PersonalityPersistenceError("Não foi possível ler o estado da Nova") from exc
        try:
            data = json.loads(content)
            return EmotionalState.restore(data)
        except (json.JSONDecodeError, ValueError, TypeError):
            self._preserve_corrupt_state()
            return EmotionalState.for_behavior(BehaviorState.IDLE)

    def _preserve_corrupt_state(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        candidate = self.state_path.with_name(f"{self.state_path.name}.corrupt-{stamp}")
        suffix = 1
        while candidate.exists():
            candidate = self.state_path.with_name(
                f"{self.state_path.name}.corrupt-{stamp}-{suffix}"
            )
            suffix += 1
        try:
            os.replace(self.state_path, candidate)
        except OSError as exc:
            raise PersonalityPersistenceError(
                "Estado inválido e não foi possível preservar o arquivo original"
            ) from exc

    def _save_state(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.state_path.parent,
                prefix=f".{self.state_path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(self.emotional_state.to_dict(), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.state_path)
        except OSError as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise PersonalityPersistenceError("Não foi possível salvar o estado da Nova") from exc
