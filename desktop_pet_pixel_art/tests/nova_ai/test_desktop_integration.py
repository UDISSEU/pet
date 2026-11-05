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

    def test_core_initializes_without_loading_model_or_training(self):
        self.assertTrue(self.integration.core.initialized)
        self.assertFalse(self.integration.core.config.load_model_on_start)
        self.assertFalse(self.integration.core.config.start_training_on_start)

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
