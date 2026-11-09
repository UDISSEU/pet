"""Profile isolation tests using temporary local directories."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nova_ai.desktop_integration import DesktopNovaIntegration
from nova_ai.memory import MemoryKind, MemoryManager, MemoryStorage
from nova_ai.profiles import ProfileStorageError, UserProfileManager
from autonomy import load_settings, save_settings
from ollama_client import load_history, save_history


class UserProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_existing_database_stays_in_legacy_profile_and_new_profiles_are_isolated(self):
        profiles = UserProfileManager(self.base_dir)
        legacy_path = profiles.memory_path()
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy = MemoryManager(MemoryStorage(legacy_path))
        legacy.add(
            MemoryKind.PROFILE,
            "A pessoa prefere conversas sobre jardinagem.",
            consent=True,
        )

        first = profiles.create("Ada")
        second = profiles.create("Bia", activate=False)
        self.assertEqual(profiles.memory_path("legacy"), legacy_path)
        self.assertNotEqual(profiles.memory_path(first.profile_id), legacy_path)
        self.assertNotEqual(
            profiles.memory_path(first.profile_id),
            profiles.memory_path(second.profile_id),
        )
        self.assertTrue(legacy_path.exists())

    def test_active_profile_and_registry_survive_restart(self):
        profiles = UserProfileManager(self.base_dir)
        profile = profiles.create("Ada")
        restored = UserProfileManager(self.base_dir)
        restored.memory_path(profile.profile_id)
        self.assertEqual(restored.active_profile, profile)
        self.assertEqual(restored.profiles[0].profile_id, "legacy")
        self.assertEqual(
            (self.base_dir / "user_profiles.json").stat().st_mode & 0o777,
            0o600,
        )
        self.assertEqual(
            (self.base_dir / "profiles" / profile.profile_id).stat().st_mode & 0o777,
            0o700,
        )

    def test_conversation_history_is_separate_and_legacy_history_is_preserved(self):
        legacy_history = self.base_dir / "legacy-history.json"
        with mock.patch("nova_ai.profiles.HISTORY_PATH", legacy_history):
            profiles = UserProfileManager(self.base_dir)
            new_profile = profiles.create("Ada")
            legacy_path = profiles.history_path("legacy")
            profile_path = profiles.history_path(new_profile.profile_id)

        old_messages = [{"role": "user", "content": "Conversa anterior"}]
        new_messages = [{"role": "user", "content": "Conversa da Ada"}]
        self.assertTrue(save_history(old_messages, legacy_path))
        self.assertTrue(save_history(new_messages, profile_path))
        self.assertEqual(load_history(legacy_path), old_messages)
        self.assertEqual(load_history(profile_path), new_messages)
        self.assertNotEqual(legacy_path, profile_path)

    def test_general_settings_are_isolated_and_new_profiles_start_with_defaults(self):
        profiles = UserProfileManager(self.base_dir)
        legacy_path = profiles.settings_path("legacy")
        legacy = load_settings(legacy_path)
        legacy["humor_style"] = "brincalhona"
        self.assertTrue(save_settings(legacy, legacy_path))

        profile = profiles.create("Ada")
        personal_path = profiles.settings_path(profile.profile_id)
        personal = load_settings(personal_path)
        self.assertEqual(personal["humor_style"], "equilibrada")
        personal["mode"] = "quietinha"
        self.assertTrue(save_settings(personal, personal_path))
        self.assertEqual(load_settings(legacy_path)["humor_style"], "brincalhona")
        self.assertEqual(load_settings(personal_path)["mode"], "quietinha")

    def test_memory_context_never_includes_legacy_memories_for_new_profile(self):
        profiles = UserProfileManager(self.base_dir)
        old_manager = MemoryManager(MemoryStorage(profiles.memory_path("legacy")))
        old_manager.add(
            MemoryKind.PROFILE,
            "Jardinagem é um interesse importante.",
            consent=True,
        )
        new_profile = profiles.create("Bia")
        profiles.select("legacy")
        integration = DesktopNovaIntegration(profile_manager=profiles)

        legacy_context = integration.build_context(
            "jardinagem", ["memória antiga do perfil"], limit=4
        )
        self.assertTrue(legacy_context)
        self.assertEqual(integration.select_profile(new_profile.profile_id), new_profile)
        isolated_context = integration.build_context(
            "jardinagem", ["memória antiga do perfil"], limit=4
        )
        self.assertEqual(isolated_context, [])

    def test_profile_memory_can_be_added_corrected_and_deleted(self):
        profiles = UserProfileManager(self.base_dir)
        profile = profiles.create("Ada")
        integration = DesktopNovaIntegration(profile_manager=profiles)
        saved = integration.memory.add(
            MemoryKind.PROJECT, "Projeto Nova: protótipo",
            consent=True, provenance="user_provided",
        )
        updated = integration.memory.update(
            saved.memory_id,
            content="Projeto Nova: versão inicial",
            consent=True,
        )
        self.assertEqual(updated.content, "Projeto Nova: versão inicial")
        self.assertEqual(
            [record.memory_id for record in integration.memory.search("", limit=100)],
            [saved.memory_id],
        )
        self.assertTrue(integration.memory.delete(saved.memory_id))
        self.assertEqual(integration.memory.search("", limit=100), [])
        self.assertEqual(profiles.active_profile, profile)

    def test_existing_profile_database_legacy_rows_are_adopted_without_crossing_profiles(self):
        profiles = UserProfileManager(self.base_dir)
        profile = profiles.create("Ada")
        profile_path = profiles.memory_path(profile.profile_id)
        old_manager = MemoryManager(MemoryStorage(profile_path))
        old_record = old_manager.add(
            MemoryKind.PROFILE, "A pessoa gosta de trilhas.", consent=True
        )

        integration = DesktopNovaIntegration(
            profile_manager=profiles, profile_id=profile.profile_id
        )

        records = integration.memory.search("trilhas")
        self.assertEqual([record.memory_id for record in records], [old_record.memory_id])
        stored = integration.memory.storage.get_memory(
            old_record.memory_id, user_id=profile.profile_id
        )
        self.assertEqual(stored["user_id"], profile.profile_id)
        legacy_view = MemoryManager(MemoryStorage(profile_path), user_id="legacy")
        self.assertEqual(legacy_view.search("trilhas"), [])

    def test_invalid_profile_ids_and_names_are_rejected(self):
        profiles = UserProfileManager(self.base_dir)
        with self.assertRaises(ValueError):
            profiles.create(" ")
        with self.assertRaises(ValueError):
            profiles.select("../other")

    def test_corrupt_profile_registry_is_preserved_and_reported(self):
        registry = self.base_dir / "user_profiles.json"
        registry.write_text("{invalid", encoding="utf-8")
        with self.assertRaises(ProfileStorageError):
            UserProfileManager(self.base_dir)
        backups = list(self.base_dir.glob("user_profiles.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{invalid")


if __name__ == "__main__":
    unittest.main()
