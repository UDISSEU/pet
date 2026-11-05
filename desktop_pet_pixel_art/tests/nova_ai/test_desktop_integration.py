import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nova_ai.desktop_integration import DesktopNovaIntegration
from nova_ai.memory import MemoryManager, MemoryStorage, PreferenceMemory, SemanticMemory
from nova_ai.personality import PersonalityEngine


class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        manager = MemoryManager(MemoryStorage(Path(self.temporary.name) / "memory.sqlite3"))
        SemanticMemory(manager).add_fact(
            "A Nova não deve colocar PDFs nessa pasta.", consent=True
        )
        personality = PersonalityEngine(
            preference_memory=PreferenceMemory(manager),
            state_path=Path(self.temporary.name) / "personality.json",
        )
        self.integration = DesktopNovaIntegration(memory_manager=manager, personality=personality)

    def tearDown(self):
        self.temporary.cleanup()

    def test_context_uses_relevant_local_memory_and_caps_legacy_items(self):
        context = self.integration.build_context("Onde colocar os PDFs?", ["legado"], limit=3)
        self.assertLessEqual(len(context), 3)
        self.assertEqual(context[0], "legado")
        self.assertIn("PDFs", context[1])

    def test_visual_state_maps_to_persisted_personality(self):
        self.integration.sync_visual_state("thinking")
        self.integration.personality_instructions()
        self.assertEqual(self.integration.personality.get_behavior_state(), "THINKING")
        self.integration.sync_visual_state("idle")
        self.integration.personality_instructions()
        self.assertEqual(self.integration.personality.get_behavior_state(), "IDLE")

    def test_core_initializes_without_loading_model_or_training(self):
        self.assertTrue(self.integration.core.initialized)
        self.assertFalse(self.integration.core.config.load_model_on_start)
        self.assertFalse(self.integration.core.config.start_training_on_start)


if __name__ == "__main__":
    unittest.main()
