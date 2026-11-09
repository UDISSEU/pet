import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nova_ai.desktop_integration import DesktopNovaIntegration
from nova_ai.memory import MemoryManager, MemoryStorage, PreferenceMemory, SemanticMemory
from nova_ai.personality import PersonalityEngine
from nova_ai.actions import CancellationToken, create_default_tool_registry


class GrantedPermissions:
    def __init__(self, grants=()):
        self.grants = set(grants)

    def allowed(self, _plugin, permission):
        return permission in self.grants

    def require(self, _plugin, permission, *, confirmed=False):
        if permission not in self.grants:
            raise PermissionError(permission)
        if permission in {"file.organize", "file.move"} and not confirmed:
            raise PermissionError("confirmation required")
        return True


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
        self.permissions = GrantedPermissions({"file.read", "file.organize", "file.move"})
        self.integration = DesktopNovaIntegration(
            memory_manager=manager, personality=personality,
            permission_manager=self.permissions,
            actions=create_default_tool_registry(),
        )

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
        expected = {
            "focused": "FOCUSED",
            "curious": "CURIOUS",
            "caring": "CARING",
            "playful": "PLAYFUL",
            "resting": "RESTING",
            "celebrating": "HAPPY",
            "greeting": "HAPPY",
        }
        for visual, behavior in expected.items():
            self.integration.sync_visual_state(visual)
            self.integration.personality_instructions()
            self.assertEqual(self.integration.personality.get_behavior_state(), behavior)

    def test_adaptive_learning_is_opt_in_and_saves_only_aggregated_evidence(self):
        settings = {"adaptive_learning_enabled": False}
        with mock.patch("nova_ai.desktop_integration.save_settings") as save:
            self.assertFalse(self.integration.learn_from_interaction(
                "Prefiro respostas curtas.", settings
            ))
            save.assert_not_called()
            settings["adaptive_learning_enabled"] = True
            self.assertTrue(self.integration.learn_from_interaction(
                "Prefiro respostas curtas.", settings
            ))
        save.assert_called_once()
        serialized_settings = str(settings)
        self.assertNotIn("Prefiro respostas curtas.", serialized_settings)
        settings["adaptive_learning_state"]["evidence"]["verbosity"]["concise"] = 3
        self.assertIn("Prefira respostas breves e diretas", self.integration.personality_instructions(settings))
        self.assertIn("Você é Nova", self.integration.personality_instructions(settings))

    def test_explicit_emotional_tone_changes_only_the_current_response_guidance(self):
        original_state = self.integration.personality.get_behavior_state()
        instructions = self.integration.personality_instructions(
            {}, "Estou muito sobrecarregada hoje."
        )
        self.assertIn("sem diagnóstico ou memória", instructions)
        self.assertIn("Responda com acolhimento", instructions)
        self.assertEqual(self.integration.personality.get_behavior_state(), original_state)

    def test_core_initializes_without_loading_model_or_training(self):
        self.assertTrue(self.integration.core.initialized)
        self.assertFalse(self.integration.core.config.load_model_on_start)
        self.assertFalse(self.integration.core.config.start_training_on_start)

    def test_memory_health_and_maintenance_are_available_to_desktop_services(self):
        health = self.integration.memory_health()
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["integrity_check"], "ok")

        maintenance = self.integration.run_memory_maintenance(create_backup=True)
        self.assertTrue(Path(maintenance["backup_created"]).is_file())
        self.assertEqual(maintenance["expired_records_purged"], 0)
        self.assertEqual(self.integration.memory_health()["status"], "healthy")

    def test_normal_conversation_is_not_classified_as_a_tool_task(self):
        self.assertFalse(self.integration.classify_task("Me conte uma curiosidade sobre o mar."))

    def test_download_request_previews_confirms_executes_and_can_be_undone(self):
        import nova_ai.actions.file_manager as file_module

        root = Path(self.temporary.name) / "Downloads"
        root.mkdir()
        source = root / "notes.txt"
        source.write_text("conteúdo", encoding="utf-8")
        self.assertTrue(self.integration.classify_task("Organize meus Downloads"))
        with mock.patch.object(file_module, "_downloads_root", return_value=root):
            prepared = self.integration.prepare_task("Organize meus Downloads")
            self.assertTrue(prepared.files_checked)
            self.assertEqual(len(prepared.inspection.data["plan"]), 1)
            refused = self.integration.execute_task(prepared, approved=False)
            self.assertEqual(refused.status.value, "awaiting_confirmation")
            self.assertTrue(source.exists())
            executed = self.integration.execute_task(prepared, approved=True)
            self.assertTrue(executed.verified)
            self.assertTrue((root / "Documentos" / "notes.txt").exists())
            undone = self.integration.undo_last_organization(approved=True)
        self.assertTrue(undone.success)
        self.assertEqual(source.read_text(encoding="utf-8"), "conteúdo")

    def test_revoked_permission_is_rechecked_before_execution(self):
        import nova_ai.actions.file_manager as file_module

        root = Path(self.temporary.name) / "Downloads"
        root.mkdir()
        (root / "notes.txt").write_text("conteúdo", encoding="utf-8")
        with mock.patch.object(file_module, "_downloads_root", return_value=root):
            prepared = self.integration.prepare_task("Organize meus Downloads")
            self.permissions.grants.remove("file.organize")
            result = self.integration.execute_task(prepared, approved=True)
        self.assertEqual(result.status.value, "failed")
        self.assertTrue((root / "notes.txt").exists())

    def test_missing_permission_is_reported_without_preview_or_movement(self):
        self.permissions.grants.clear()
        prepared = self.integration.prepare_task("Organize meus Downloads")
        self.assertEqual(prepared.decision.kind.value, "request_permission")
        self.assertFalse(prepared.files_checked)

    def test_cooperative_cancellation_rolls_back_a_multi_file_task(self):
        import nova_ai.actions.file_manager as file_module

        root = Path(self.temporary.name) / "Downloads"
        root.mkdir()
        originals = [root / "one.txt", root / "two.txt"]
        for path in originals:
            path.write_text("keep", encoding="utf-8")

        class CancelAfterOneMove(CancellationToken):
            checks = 0

            @property
            def cancelled(self):
                self.checks += 1
                return self.checks >= 3

        with mock.patch.object(file_module, "_downloads_root", return_value=root):
            prepared = self.integration.prepare_task("Organize meus Downloads")
            result = self.integration.execute_task(
                prepared, approved=True, cancellation=CancelAfterOneMove()
            )
        self.assertEqual(result.status.value, "cancelled")
        self.assertTrue(all(path.exists() for path in originals))
        self.assertFalse((root / "Documentos" / "one.txt").exists())


if __name__ == "__main__":
    unittest.main()
