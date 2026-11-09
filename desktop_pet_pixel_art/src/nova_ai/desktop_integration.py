"""Composição local e opcional entre o núcleo Nova e o desktop legado."""

from pathlib import Path
import logging

from autonomy import save_settings
from nova_ai.core import NovaAI, NovaAIConfig
from nova_ai.memory import MemoryManager, MemoryStorage, PreferenceMemory
from nova_ai.memory.errors import MemoryStorageError
from nova_ai.personality import EmotionDetector, PersonalityEngine
from nova_ai.personality import PreferenceLearner
from nova_ai.profiles import UserProfileManager
from nova_ai.actions import create_default_tool_registry
from nova_ai.actions.base import CancellationToken
from nova_ai.cognition import CognitiveEngine, DecisionKind, IntentName

logger = logging.getLogger(__name__)


class DesktopNovaIntegration:
    """Adapta memória e personalidade sem criar UI, filas ou workers próprios."""

    def __init__(self, *, config=None, memory_manager=None, personality=None,
                 permission_manager=None, actions=None, cognitive_engine=None,
                 profile_manager=None, profile_id=None):
        self.core = NovaAI(config=config or NovaAIConfig()).initialize()
        self.profile_manager = profile_manager or UserProfileManager()
        if profile_id is not None:
            self.profile_manager.select(profile_id)
        self.profile = self.profile_manager.active_profile
        self._managed_memory = memory_manager is None
        self._managed_personality = personality is None
        self.memory = memory_manager or self._new_memory_manager()
        self._diagnose_memory()
        self.personality = personality or self._new_personality()
        self.preference_learner = PreferenceLearner()
        self.emotion_detector = EmotionDetector()
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

    def _new_memory_manager(self, profile=None):
        profile = profile or self.profile
        return MemoryManager(MemoryStorage(self.profile_manager.memory_path(
            profile.profile_id
        )))

    def _diagnose_memory(self):
        try:
            snapshot = self.memory.health_snapshot()
        except MemoryStorageError:
            logger.exception("Não foi possível diagnosticar o banco local da Nova.")
            return
        if snapshot.get("status") != "healthy":
            logger.warning(
                "Diagnóstico do banco local da Nova: estado=%s, integridade=%s, versão=%s",
                snapshot.get("status"), snapshot.get("integrity_check"),
                snapshot.get("user_version"),
            )
        else:
            logger.info(
                "Banco local da Nova verificado: schema=%s, tamanho=%s bytes",
                snapshot.get("user_version"), snapshot.get("database_size_bytes"),
            )

    def _new_personality(self, profile=None, memory=None):
        profile = profile or self.profile
        memory = memory or self.memory
        return PersonalityEngine(
            preference_memory=PreferenceMemory(memory),
            state_path=self.profile_manager.personality_state_path(
                profile.profile_id
            ),
        )

    def select_profile(self, profile_id):
        """Switch local memory and preferences without moving legacy records."""
        if not self._managed_memory or not self._managed_personality:
            raise RuntimeError(
                "A troca de perfil exige serviços de memória e personalidade gerenciados"
            )
        profile = self.profile_manager.get(profile_id)
        memory = self._new_memory_manager(profile)
        personality = self._new_personality(profile, memory)
        self.profile_manager.select(profile_id)
        self.profile = profile
        self.memory = memory
        self._diagnose_memory()
        self.personality = personality
        self.personality.transition_behavior("IDLE")
        self._visual_behavior = None
        return self.profile

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
        memories = (
            list(legacy_memories or ())[:limit]
            if self.profile.profile_id == "legacy" else []
        )
        try:
            records = self.memory.search(question, limit=limit)
        except MemoryStorageError:
            logger.exception(
                "Falha ao recuperar memórias do perfil; atenderei sem esse contexto."
            )
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

    def memory_health(self):
        """Retorna snapshot de saúde do SQLite para observabilidade da UI e automação."""
        return self.memory.health_snapshot()

    def memory_maintenance_report(self):
        """Emite um relatório de manutenção do banco para painel e diagnósticos."""
        return self.memory.maintenance_report()

    def run_memory_maintenance(self, *, create_backup=True, retain=10, max_age_days=90):
        """Executa limpeza de expirados e rotação de backups locais sob demanda."""
        return self.memory.run_maintenance(
            create_backup=create_backup, retain=retain, max_age_days=max_age_days
        )

    def restore_memory_backup(self, backup_path, *, keep_backup=True):
        """Restaura um backup local do SQLite e reabre o contexto de memória."""
        self.memory.restore_from(backup_path, keep_backup=keep_backup)
        self.memory = self._new_memory_manager(self.profile)
        self.personality = self._new_personality(self.profile, self.memory)
        return self.memory_health()

    def project_memories(self, *, limit=20):
        """Return explicitly saved project memories for a contextual greeting."""
        return self.memory.search("", kind="project", limit=limit)

    def learn_from_interaction(self, message, settings):
        """Store only explicit, daily preference signals when learning is enabled."""
        if not isinstance(settings, dict) or settings.get("adaptive_learning_enabled") is not True:
            return False
        state, changed = self.preference_learner.observe(
            message, settings.get("adaptive_learning_state")
        )
        if not changed:
            return False
        settings["adaptive_learning_state"] = state
        if not save_settings(
            settings, self.profile_manager.settings_path(self.profile.profile_id)
        ):
            logger.warning(
                "Não foi possível salvar evidências agregadas de preferências adaptativas."
            )
        return True

    def personality_instructions(self, settings=None, user_message=None):
        if (self._visual_behavior
                and self.personality.get_behavior_state() != self._visual_behavior):
            self.personality.transition_behavior(self._visual_behavior)
        instructions = self.personality.build_personality_instructions()
        if isinstance(settings, dict) and settings.get("adaptive_learning_enabled") is True:
            guidance = self.preference_learner.guidance(
                settings.get("adaptive_learning_state")
            )
            if guidance:
                instructions += "\nPreferências observadas gradualmente:\n" + "\n".join(
                    f"- {item}" for item in guidance
                )
        tone_state = self.emotion_detector.detect(user_message)
        if tone_state is not None:
            instructions += (
                "\nAjuste temporário para esta mensagem, sem diagnóstico ou memória: "
                f"{tone_state.value}. {self.personality.emotional_state.for_behavior(tone_state).prompt_guidance}"
            )
        return instructions

    def sync_visual_state(self, visual_state):
        mapping = {"thinking": "THINKING", "curious": "CURIOUS", "walk": "IDLE",
                   "idle": "IDLE", "calm": "CALM", "sleep": "SLEEPING",
                   "sleeping": "SLEEPING", "resting": "RESTING",
                   "error": "ERROR", "working": "WORKING", "happy": "HAPPY",
                   "celebrating": "HAPPY", "greeting": "HAPPY",
                   "thumbs_up": "HAPPY", "dance": "HAPPY", "sitting": "RESTING",
                   "yawning": "RESTING", "focused": "FOCUSED",
                   "caring": "CARING", "playful": "PLAYFUL",
                   "reminder": "THINKING", "busy": "WORKING"}
        behavior = mapping.get(str(visual_state).lower())
        if behavior:
            # Setter is called from Tk's main thread; only retain a volatile
            # snapshot here. Persistence is applied later by the AI worker.
            self._visual_behavior = behavior
