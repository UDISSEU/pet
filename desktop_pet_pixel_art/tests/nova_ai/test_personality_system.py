"""Testes da personalidade nova sem Tkinter, animações ou provedores de IA."""

from pathlib import Path
import sys
import tempfile
import unittest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nova_ai.memory import MemoryManager, MemoryStorage, PreferenceMemory
from nova_ai.memory.errors import ConsentRequiredError
from nova_ai.personality import (
    BehaviorRules,
    BehaviorState,
    EmotionalState,
    NovaIdentity,
    PersonalityEngine,
    PersonalityPersistenceError,
    ResponseStyle,
    SimulatedEmotion,
    Tone,
    Verbosity,
)


class PersonalitySystemTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "memory.sqlite3"
        self.state_path = self.root / "personality.json"

    def tearDown(self):
        self.temporary.cleanup()

    def make_engine(self):
        manager = MemoryManager(MemoryStorage(self.database_path))
        return PersonalityEngine(
            preference_memory=PreferenceMemory(manager), state_path=self.state_path
        )

    def test_identity_and_rules_are_stable_and_provider_independent(self):
        engine_one = self.make_engine()
        engine_two = self.make_engine()
        self.assertEqual(engine_one.identity, NovaIdentity())
        self.assertEqual(engine_one.build_personality_instructions(),
                         engine_two.build_personality_instructions())
        self.assertIn("Você é Nova", engine_one.build_personality_instructions())
        self.assertIn("Não realize ações sem autorização", engine_one.build_personality_instructions())
        self.assertIn("Não afirme consciência", engine_one.build_personality_instructions())
        self.assertIsInstance(engine_one.rules, BehaviorRules)

    def test_interaction_preferences_require_consent_and_persist_in_memory(self):
        engine = self.make_engine()
        with self.assertRaises(ConsentRequiredError):
            engine.set_response_preferences(tone=Tone.CALM)
        self.assertEqual(engine.response_style, ResponseStyle())

        configured = engine.set_response_preferences(
            tone=Tone.CALM,
            verbosity=Verbosity.CONCISE,
            consent_confirmed=True,
        )
        self.assertEqual(configured.tone, Tone.CALM)
        self.assertEqual(configured.verbosity, Verbosity.CONCISE)

        restarted = self.make_engine()
        self.assertEqual(restarted.response_style, configured)

    def test_preference_updates_replace_single_authorized_memory(self):
        engine = self.make_engine()
        engine.set_response_preferences(verbosity=Verbosity.CONCISE, consent_confirmed=True)
        engine.set_response_preferences(verbosity=Verbosity.DETAILED, consent_confirmed=True)
        records = engine.preference_memory.recall("Nova interaction preferences", limit=100)
        style_records = [
            record for record in records
            if record.content.startswith("Nova interaction preferences:")
        ]
        self.assertEqual(len(style_records), 1)
        self.assertIn("verbosity=detailed", style_records[0].content)

    def test_visual_behavior_states_have_simulated_emotions_and_persist(self):
        expected = {
            BehaviorState.IDLE: SimulatedEmotion.CALM,
            BehaviorState.THINKING: SimulatedEmotion.CURIOUS,
            BehaviorState.WORKING: SimulatedEmotion.FOCUSED,
            BehaviorState.HAPPY: SimulatedEmotion.JOYFUL,
            BehaviorState.SLEEPING: SimulatedEmotion.RESTING,
            BehaviorState.ERROR: SimulatedEmotion.CONCERNED,
        }
        engine = self.make_engine()
        for behavior, emotion in expected.items():
            current = engine.set_behavior_state(behavior)
            self.assertEqual(current.emotion, emotion)
            self.assertEqual(engine.get_behavior_state(), behavior.value)
            restored = self.make_engine()
            self.assertEqual(restored.behavior_state, behavior)
            self.assertEqual(restored.simulated_emotion, emotion)

    def test_state_round_trip_rejects_emotion_mismatch(self):
        state = EmotionalState.for_behavior(BehaviorState.THINKING)
        self.assertEqual(EmotionalState.restore(state.to_dict()), state)
        corrupt = state.to_dict()
        corrupt["emotion"] = SimulatedEmotion.JOYFUL.value
        with self.assertRaises(ValueError):
            EmotionalState.restore(corrupt)

    def test_corrupt_state_is_preserved_and_defaults_to_idle(self):
        original = b"{not valid json"
        self.state_path.write_bytes(original)
        engine = self.make_engine()
        self.assertEqual(engine.behavior_state, BehaviorState.IDLE)
        backups = list(self.root.glob("personality.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        engine.set_behavior_state(BehaviorState.WORKING)
        self.assertEqual(self.make_engine().behavior_state, BehaviorState.WORKING)

    def test_failed_state_write_rolls_back_in_memory_transition(self):
        engine = self.make_engine()
        engine.state_path = self.root / "missing" / "blocked" / "state.json"
        engine.state_path.parent.mkdir(parents=True)
        engine.state_path.parent.chmod(0o500)
        try:
            with self.assertRaises(PersonalityPersistenceError):
                engine.set_behavior_state(BehaviorState.ERROR)
            self.assertEqual(engine.behavior_state, BehaviorState.IDLE)
        finally:
            engine.state_path.parent.chmod(0o700)

    def test_interface_snapshot_exposes_behavior_without_ui_dependencies(self):
        engine = self.make_engine()
        engine.set_behavior_state("HAPPY")
        state = engine.snapshot()
        self.assertEqual(state["behavior_state"], "HAPPY")
        self.assertEqual(state["simulated_emotion"], "joyful")
        self.assertEqual(state["identity"].name, "Nova")
        self.assertEqual(state["response_style"].tone, Tone.NATURAL_FRIENDLY)


if __name__ == "__main__":
    unittest.main()
