"""Focused tests for safe Nova settings backups and restoration."""

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from computer_backup import (
    BACKUP_SUFFIX, FORMAT_ID, _canonical, create_backup, delete_backup,
    export_backup, list_backups, preview_restore, read_backup,
    rename_backup, restore_backup, save_backup_directory,
    validate_backup_directory,
)


class FakeProfiles:
    def __init__(self, root):
        self.base_dir = Path(root)
        self.config = self.base_dir / "profiles" / "settings.json"
        self.personality = self.base_dir / "profiles" / "nova_personality.json"
        self.config.parent.mkdir(parents=True)

    def settings_path(self): return self.config
    def personality_state_path(self): return self.personality


class ComputerBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.profiles = FakeProfiles(self.root / "profile-store")
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.profiles.config.write_text('{"theme":"dark","volume":40}', encoding="utf-8")
        self.profiles.personality.write_text('{"tone":"calm"}', encoding="utf-8")

    def tearDown(self): self.temp.cleanup()

    def create(self):
        return create_backup(self.profiles, self.backups, label="User snapshot")

    def test_create_read_integrity_and_rename(self):
        path = self.create()
        package = read_backup(path, self.backups)
        self.assertEqual(package["format"], FORMAT_ID)
        self.assertEqual([item["name"] for item in package["files"]], ["settings.json", "personality.json"])
        self.assertTrue(all(item["present"] for item in package["files"]))
        rename_backup(path, self.backups, "Before update")
        self.assertEqual(read_backup(path, self.backups)["label"], "Before update")
        self.assertEqual(list_backups(self.backups)[0]["integrity"], "Íntegro")

    def test_corrupt_and_incompatible_backups_are_reported(self):
        path = self.create()
        package = json.loads(path.read_text(encoding="utf-8"))
        package["label"] = "tampered"
        path.write_text(json.dumps(package), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "integridade"):
            read_backup(path, self.backups)
        self.assertTrue(list_backups(self.backups)[0]["integrity"].startswith("Inválido"))
        package["format_version"] = 77
        unsigned = dict(package); unsigned.pop("integrity", None)
        package["integrity"]["digest"] = hashlib.sha256(_canonical(unsigned)).hexdigest()
        path.write_text(json.dumps(package), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "incompatível"):
            read_backup(path, self.backups)

    def test_restore_preview_and_safety_backup(self):
        path = self.create()
        self.profiles.config.write_text('{"theme":"light"}', encoding="utf-8")
        self.profiles.personality.write_text('{"tone":"energetic"}', encoding="utf-8")
        preview = preview_restore(path, self.backups, self.profiles)
        self.assertEqual(sum(item["changed"] for item in preview["changes"]), 2)
        result = restore_backup(path, self.backups, self.profiles)
        self.assertEqual(json.loads(self.profiles.config.read_text()), {"theme": "dark", "volume": 40})
        self.assertEqual(json.loads(self.profiles.personality.read_text()), {"tone": "calm"})
        self.assertTrue(Path(result["safety_backup"]).is_file())
        self.assertEqual(len(list_backups(self.backups)), 2)

    def test_partial_restore_failure_rolls_back_already_replaced_files(self):
        import computer_backup
        path = self.create()
        old_settings = self.profiles.config.read_bytes()
        old_personality = self.profiles.personality.read_bytes()
        self.profiles.config.write_text('{"theme":"changed"}', encoding="utf-8")
        self.profiles.personality.write_text('{"tone":"changed"}', encoding="utf-8")
        original_replace = os.replace
        restore_replacements = {"count": 0}
        def fail_second_restore(source, target):
            if str(source).endswith(".restore"):
                restore_replacements["count"] += 1
                if restore_replacements["count"] == 2:
                    raise OSError("simulated disk failure")
            return original_replace(source, target)
        with mock.patch.object(computer_backup.os, "replace", side_effect=fail_second_restore):
            with self.assertRaisesRegex(OSError, "simulated disk failure"):
                restore_backup(path, self.backups, self.profiles)
        self.assertEqual(self.profiles.config.read_bytes(), b'{"theme":"changed"}')
        self.assertEqual(self.profiles.personality.read_bytes(), b'{"tone":"changed"}')
        self.assertNotEqual(old_settings, self.profiles.config.read_bytes())
        self.assertNotEqual(old_personality, self.profiles.personality.read_bytes())

    def test_export_refuses_overwrite_and_delete_requires_valid_child(self):
        path = self.create()
        exported = self.root / ("export" + BACKUP_SUFFIX)
        export_backup(path, self.backups, exported)
        self.assertEqual(read_backup(exported, self.root)["label"], "User snapshot")
        exported.write_text("keep", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            export_backup(path, self.backups, exported)
        self.assertEqual(exported.read_text(encoding="utf-8"), "keep")
        with self.assertRaises(ValueError):
            delete_backup(str(self.backups / ".." / Path(path).name), self.backups)

    def test_invalid_directory_and_symlink_are_rejected(self):
        with self.assertRaises(ValueError): validate_backup_directory("relative/path")
        link = self.root / "backup-link"
        link.symlink_to(self.backups, target_is_directory=True)
        with self.assertRaises(OSError): validate_backup_directory(link)

    def test_backup_directory_choice_is_persisted(self):
        import computer_backup
        config_path = self.root / "backup_location.json"
        chosen = self.root / "external-drive" / "Nova"
        with mock.patch.object(computer_backup, "backup_location_settings_path", return_value=config_path):
            self.assertEqual(save_backup_directory(chosen), chosen)
            self.assertEqual(computer_backup.load_backup_directory(), chosen)

    def test_backup_excludes_credentials_and_restore_preserves_current_local_credentials(self):
        self.profiles.config.write_text(
            '{"theme":"dark","api_token":"old-secret","spotify_client_id":"old-client"}',
            encoding="utf-8",
        )
        path = self.create()
        archived = read_backup(path, self.backups)
        archived_text = json.dumps(archived)
        self.assertNotIn("old-secret", archived_text)
        self.assertNotIn("old-client", archived_text)
        self.profiles.config.write_text(
            '{"theme":"light","api_token":"current-secret","spotify_client_id":"current-client"}',
            encoding="utf-8",
        )
        restore_backup(path, self.backups, self.profiles)
        current = json.loads(self.profiles.config.read_text(encoding="utf-8"))
        self.assertEqual(current["theme"], "dark")
        self.assertEqual(current["api_token"], "current-secret")
        self.assertEqual(current["spotify_client_id"], "current-client")

    def test_profile_paths_outside_managed_root_are_rejected(self):
        self.profiles.settings_path = lambda: Path("/etc/settings.json")
        with self.assertRaisesRegex(ValueError, "fora da raiz"):
            self.create()

    def test_interrupted_atomic_write_leaves_no_visible_partial_backup(self):
        import json_persistence
        with mock.patch.object(json_persistence.os, "replace", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError): self.create()
        self.assertEqual(list(self.backups.glob("*")), [])
        self.assertEqual(list(self.backups.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
