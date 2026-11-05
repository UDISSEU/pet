"""Composição local e opcional entre o núcleo Nova e o desktop legado."""

from pathlib import Path

from nova_ai.core import NovaAI, NovaAIConfig
from nova_ai.memory import MemoryManager, PreferenceMemory
from nova_ai.personality import PersonalityEngine
from nova_ai.actions import create_default_tool_registry
from nova_ai.actions.base import CancellationToken
from nova_ai.cognition import CognitiveEngine, DecisionKind, IntentName

class DesktopNovaIntegration:
    """Adapta memória e personalidade sem criar UI, filas ou workers próprios."""

    def __init__(self, *, config=None, memory_manager=None, personality=None,
                 permission_manager=None, actions=None, cognitive_engine=None):
        self.core = NovaAI(config=config or NovaAIConfig()).initialize()
        self.memory = memory_manager or MemoryManager()
        self.personality = personality or PersonalityEngine(
            preference_memory=PreferenceMemory(self.memory)
        )
        # A UI state from a previous run is not a persistent personality trait.
        self.personality.transition_behavior("IDLE")
        self.permission_manager = permission_manager
        self.actions = actions or create_default_tool_registry()
        self.cognition = cognitive_engine or CognitiveEngine(
            actions=self.actions,
            permissions=permission_manager,
            result_verifier=self._verify_organization,
        )
        self._visual_behavior = None
        self.last_undo_mapping = None

    def classify_task(self, text):
        """Return true only for the one task intentionally supported today."""
        try:
            intent = self.cognition.classifier.classify(text)
        except (TypeError, ValueError):
            return False
        return intent.name is IntentName.ORGANIZE_DOWNLOADS

    def prepare_task(self, text):
        return self.cognition.interpret(text)

    def execute_task(self, prepared, *, approved, cancellation=None):
        result = self.cognition.execute(
            prepared, approved=approved, cancellation=cancellation
        )
        if result.action_result is not None and result.action_result.success:
            mapping = result.action_result.data.get("undo_mapping")
            if isinstance(mapping, list):
                self.last_undo_mapping = mapping
        return result

    def undo_last_organization(self, *, approved):
        if approved is not True or not isinstance(self.last_undo_mapping, list):
            return None
        result = self.cognition.dispatcher.dispatch(
            "files.organize.undo", {"undo_mapping": self.last_undo_mapping}, approved=True
        )
        self.cognition.validator.validate_action_result(result)
        self.last_undo_mapping = None
        return result

    @staticmethod
    def _verify_organization(operation, result, _parameters):
        if operation != "files.organize_downloads" or not result.success:
            return False
        root = Path(result.data.get("undo_mapping", [{}])[0].get("source", "")).parent \
            if result.data.get("undo_mapping") else None
        mapping = result.data.get("undo_mapping")
        if root is None or not isinstance(mapping, list):
            return isinstance(mapping, list) and not mapping
        try:
            for row in mapping:
                source, destination = Path(row["source"]), Path(row["destination"])
                if (source.parent != root or destination.parent.parent != root
                        or source.exists() or source.is_symlink()
                        or destination.is_symlink() or not destination.is_file()):
                    return False
        except (KeyError, TypeError, OSError):
            return False
        return True

    def build_context(self, question, legacy_memories=(), *, limit=8):
        memories = list(legacy_memories or ())[:limit]
        try:
            records = self.memory.search(question, limit=limit)
        except Exception:
            return memories
        seen = {str(item).casefold() for item in memories}
        for record in records:
            context_item = (
                f"[memória; origem={record.provenance}; confiança={record.confidence:.2f}] "
                f"{record.content}"
            )
            if record.content.casefold() not in seen and len(memories) < limit:
                memories.append(context_item)
                seen.add(record.content.casefold())
        return memories

    def personality_instructions(self):
        if (self._visual_behavior
                and self.personality.get_behavior_state() != self._visual_behavior):
            self.personality.transition_behavior(self._visual_behavior)
        return self.personality.build_personality_instructions()

    def sync_visual_state(self, visual_state):
        mapping = {"thinking": "THINKING", "curious": "THINKING", "walk": "IDLE",
                   "idle": "IDLE", "sleep": "SLEEPING", "sleeping": "SLEEPING",
                   "error": "ERROR", "working": "WORKING", "happy": "HAPPY",
                   "thumbs_up": "HAPPY", "dance": "HAPPY", "sitting": "IDLE",
                   "reminder": "THINKING", "busy": "WORKING"}
        behavior = mapping.get(str(visual_state).lower())
        if behavior:
            # Setter is called from Tk's main thread; only retain a volatile
            # snapshot here. Persistence is applied later by the AI worker.
            self._visual_behavior = behavior
