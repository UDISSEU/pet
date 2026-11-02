import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import automations
from autonomy import load_settings


class AutomationTests(unittest.TestCase):
    def test_intents_are_local_and_specific(self):
        self.assertEqual(automations.recognize_automation("Como está meu notebook?")["id"], "laptop_status")
        self.assertEqual(automations.recognize_automation("organizar Downloads")['id'], "organize_downloads")
        self.assertEqual(automations.recognize_automation("esvaziar a lixeira")['id'], "empty_trash")
        self.assertEqual(automations.recognize_automation("procurar arquivos duplicados")['id'], "duplicates")
        for phrase in ("como está meu código", "organizar meu código", "me ajuda com downloads", "oi Nova"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(automations.recognize_automation(phrase))

    def test_download_organize_conflicts_skip_hidden_partial_and_folders_and_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Downloads"
            root.mkdir()
            (root / "Imagens").mkdir()
            (root / "Imagens" / "existente.png").write_text("existing")
            (root / "foto.png").write_text("photo")
            (root / "doc.pdf").write_text("doc")
            (root / "clip.mp4").write_text("video")
            (root / "som.mp3").write_text("audio")
            (root / "pacote.zip").write_text("zip")
            (root / "dado.bin").write_text("other")
            (root / ".oculto").write_text("hidden")
            (root / "incompleto.part").write_text("partial")
            (root / "baixando.crdownload").write_text("partial")
            (root / "subpasta").mkdir()
            (root / "subpasta" / "intacto.txt").write_text("untouched")
            undo_path = Path(tmp) / "config" / "undo.json"
            result = automations.organize_downloads(root, undo_path)
            self.assertEqual(result['status'], 'ok')
            self.assertEqual((root / "Imagens" / "foto.png").read_text(), "photo")
            self.assertEqual((root / "Documentos" / "doc.pdf").read_text(), "doc")
            self.assertEqual((root / "Vídeos" / "clip.mp4").read_text(), "video")
            self.assertTrue((root / ".oculto").exists())
            self.assertTrue((root / "incompleto.part").exists())
            self.assertEqual((root / "subpasta" / "intacto.txt").read_text(), "untouched")
            undone = automations.undo_downloads(undo_path, downloads=root)
            self.assertEqual(undone['status'], 'ok')
            self.assertEqual((root / "foto.png").read_text(), "photo")
            self.assertFalse((root / "Imagens" / "foto.png").exists())

    def test_status_with_and_without_battery(self):
        fake = types.SimpleNamespace(
            virtual_memory=lambda: types.SimpleNamespace(percent=40, used=2 * 1024**3, total=8 * 1024**3),
            disk_usage=lambda _p: types.SimpleNamespace(percent=50, used=50 * 1024**3, total=100 * 1024**3),
            sensors_battery=lambda: None,
            boot_time=lambda: 0,
            cpu_percent=lambda interval: 12,
            process_iter=lambda _attrs: [],
            Error=OSError,
        )
        with mock.patch.dict(sys.modules, {"psutil": fake}):
            self.assertTrue(any("Bateria: indisponível" in line for line in automations._status()['lines']))
            fake.sensors_battery = lambda: types.SimpleNamespace(percent=72, power_plugged=True)
            self.assertTrue(any("Bateria: 72%" in line for line in automations._status()['lines']))

    def test_legacy_settings_get_safe_automation_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"mode":"companhia"}', encoding="utf-8")
            result = load_settings(path)
            self.assertTrue(result['automations']['enabled']['laptop_status'])
            self.assertTrue(result['automations']['enabled']['organize_downloads'])
            self.assertTrue(result['automations']['enabled']['low_battery_alert'])
            self.assertEqual(result['automations']['last_run'], {})

    def test_large_files_duplicates_and_disk_summary_are_read_only_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            downloads = home / "Downloads"
            downloads.mkdir()
            (downloads / "a.bin").write_bytes(b"same payload")
            (downloads / "b.bin").write_bytes(b"same payload")
            (downloads / "large.bin").write_bytes(b"x" * 4096)
            (downloads / ".hidden").write_bytes(b"x" * 10000)
            (downloads / "partial.part").write_bytes(b"x" * 9000)
            (home / "Documents").mkdir()
            (home / "Documents" / "note.txt").write_text("hello")

            large = automations.find_large_files(downloads)
            self.assertEqual(large["items"][0]["name"], "large.bin")
            self.assertNotIn(".hidden", [item["name"] for item in large["items"]])
            duplicates = automations.find_duplicates(downloads)
            self.assertEqual(len(duplicates["groups"]), 1)
            self.assertEqual(len(duplicates["groups"][0]["paths"]), 2)
            plan = automations.preview_duplicate_removals(downloads)
            self.assertEqual(len(plan), 1)
            trash = home / ".local" / "share" / "Trash"
            with mock.patch.object(Path, "home", return_value=home):
                moved = automations.move_duplicates_to_trash(plan, downloads)
            self.assertEqual(moved["status"], "ok")
            self.assertEqual(len(list((trash / "files").iterdir())), 1)
            self.assertTrue((trash / "info" / "b.bin.trashinfo").exists())
            summary = automations.disk_summary(home)
            self.assertEqual(summary["items"][0]["folder"], "Downloads")

    def test_screenshot_organization_uses_confirmation_plan_and_can_be_undone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Downloads"
            root.mkdir()
            shot = root / "Screenshot from 2026-11-02.png"
            shot.write_bytes(b"image")
            (root / "wallpaper.png").write_bytes(b"keep")
            plan = automations.preview_screenshots(root)
            self.assertEqual(len(plan), 1)
            undo_path = Path(tmp) / "config" / "undo.json"
            result = automations.organize_screenshots(plan, root, undo_path)
            self.assertEqual(result["status"], "ok")
            self.assertTrue((root / "Capturas de tela" / shot.name).exists())
            automations.undo_downloads(undo_path, downloads=root)
            self.assertTrue(shot.exists())

    def test_empty_trash_preview_confirmation_plan_removes_only_trash_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            trash = home / ".local" / "share" / "Trash"
            files = trash / "files"
            info = trash / "info"
            files.mkdir(parents=True)
            info.mkdir()
            (files / "old.txt").write_text("old")
            (info / "old.txt.trashinfo").write_text("[Trash Info]")
            folder = files / "folder"
            folder.mkdir()
            (folder / "inside.txt").write_text("inside")
            outside = home / "outside.txt"
            outside.write_text("safe")
            (files / "link").symlink_to(outside)
            with mock.patch.object(Path, "home", return_value=home):
                plan = automations.preview_empty_trash()
                result = automations.empty_trash(plan)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(list(files.iterdir()), [])
            self.assertEqual(list(info.iterdir()), [])
            self.assertEqual(outside.read_text(), "safe")

    def test_ai_provider_entry_points_do_not_depend_on_automation_module(self):
        source = (SRC / "ai" / "request_handler.py").read_text(encoding="utf-8")
        self.assertNotIn("automations", source)
        self.assertNotIn("recognize_automation", source)


if __name__ == "__main__":
    unittest.main()
