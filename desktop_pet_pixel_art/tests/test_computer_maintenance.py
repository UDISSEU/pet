"""Focused coverage for autostart overrides and storage scanning."""

import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest import mock

from computer_services import analyze_directory, collect_storage_overview
from computer_center_ui import ComputerCenterUIMixin
from startup_manager import discover_startup_entries, set_startup_enabled


class StartupManagerTests(unittest.TestCase):
    def test_user_override_wins_and_disabled_entry_is_reported_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            user = root / "user"
            system = root / "system"
            user.mkdir()
            system.mkdir()
            (system / "sync.desktop").write_text(
                "[Desktop Entry]\nName=System Sync\nExec=sync\n", encoding="utf-8",
            )
            (user / "sync.desktop").write_text(
                "[Desktop Entry]\nName=User Sync\nExec=sync-user\nHidden=true\n",
                encoding="utf-8",
            )
            (system / "other.desktop").write_text(
                "[Desktop Entry]\nName=Other\nExec=other\n"
                "X-GNOME-Autostart-enabled=false\n", encoding="utf-8",
            )

            entries = discover_startup_entries(user, (system,))

        self.assertEqual(len(entries), 2)
        sync = next(item for item in entries if item["path"].endswith("sync.desktop"))
        self.assertEqual(sync["name"], "User Sync")
        self.assertEqual(sync["kind"], "Usuário")
        self.assertEqual(sync["state"], "Desabilitado")

    def test_toggle_is_reversible_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            user = home / ".config" / "autostart"
            user.mkdir(parents=True)
            system = home / "system"
            system.mkdir()
            target = user / "tool.desktop"
            original = (
                "# keep this comment\n[Desktop Entry]\nName=Tool\nExec=tool\n"
                "X-Custom=preserve\n"
            )
            target.write_text(original, encoding="utf-8")
            dirs = (system,)
            with mock.patch("startup_manager.Path.home", return_value=home):
                entry = discover_startup_entries(user, dirs)[0]
                result = set_startup_enabled(entry, False, user_dir=user,
                                             system_dirs=dirs)
                disabled = target.read_text(encoding="utf-8")
                self.assertIn("# keep this comment", disabled)
                self.assertIn("X-Custom=preserve", disabled)
                self.assertIn("Hidden=true", disabled)
                self.assertTrue(Path(result["backup"]).is_file())
                entry = discover_startup_entries(user, dirs)[0]
                set_startup_enabled(entry, True, user_dir=user, system_dirs=dirs)

            self.assertEqual(discover_startup_entries(user, dirs)[0]["state"], "Habilitado")
            self.assertIn("Hidden=false", target.read_text(encoding="utf-8"))

    def test_system_entry_is_overridden_without_modifying_system_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            user = home / ".config" / "autostart"
            system = home / "system"
            system.mkdir()
            source = system / "service.desktop"
            original = "[Desktop Entry]\nName=Service\nExec=service\n"
            source.write_text(original, encoding="utf-8")
            with mock.patch("startup_manager.Path.home", return_value=home):
                entry = discover_startup_entries(user, (system,))[0]
                set_startup_enabled(entry, False, user_dir=user, system_dirs=(system,))

            self.assertEqual(source.read_text(encoding="utf-8"), original)
            effective = discover_startup_entries(user, (system,))
            self.assertEqual(len(effective), 1)
            self.assertEqual(effective[0]["kind"], "Usuário")
            self.assertEqual(effective[0]["state"], "Desabilitado")

    def test_dangling_config_symlink_is_rejected_before_creating_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "home"
            home.mkdir()
            system = Path(temporary) / "system"
            system.mkdir()
            source = system / "service.desktop"
            source.write_text("[Desktop Entry]\nName=Service\nExec=service\n", encoding="utf-8")
            outside = Path(temporary) / "outside" / "not-created"
            config = home / ".config"
            try:
                config.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("Symlinks unavailable")
            with mock.patch("startup_manager.Path.home", return_value=home):
                entry = discover_startup_entries(system_dirs=(system,))[0]
                with self.assertRaises(OSError):
                    set_startup_enabled(entry, False, system_dirs=(system,))
            self.assertFalse(outside.exists())

    def test_unapproved_autostart_directory_is_rejected_before_mkdir(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            system = root / "system"
            system.mkdir()
            source = system / "service.desktop"
            source.write_text("[Desktop Entry]\nName=Service\nExec=service\n", encoding="utf-8")
            outside = root / "outside" / "autostart"
            with mock.patch("startup_manager.Path.home", return_value=home):
                entry = discover_startup_entries(system_dirs=(system,))[0]
                with self.assertRaises(ValueError):
                    set_startup_enabled(entry, False, user_dir=outside, system_dirs=(system,))
            self.assertFalse(outside.exists())


class StorageAnalysisTests(unittest.TestCase):
    def test_storage_overview_reports_usage_for_selected_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = collect_storage_overview(temporary)

        self.assertEqual(result["path"], temporary)
        self.assertGreaterEqual(result["percent"], 0)
        self.assertLessEqual(result["percent"], 100)

    def test_scans_files_and_directory_totals_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "chosen"
            child = root / "docs"
            child.mkdir(parents=True)
            (child / "large.bin").write_bytes(b"a" * 4096)
            (root / "small.txt").write_text("hello", encoding="utf-8")
            external = Path(temporary) / "outside.bin"
            external.write_bytes(b"x" * 8192)
            link = root / "outside-link"
            try:
                link.symlink_to(external)
            except OSError:
                self.skipTest("Symlinks unavailable")

            result = analyze_directory(root)

        self.assertTrue(result["complete"])
        self.assertEqual(result["files"], 2)
        self.assertEqual(result["bytes_scanned"], 4101)
        self.assertEqual(result["directories"]["docs"]["bytes"], 4096)
        self.assertEqual(result["largest_files"][0]["name"], "large.bin")

    def test_cancellation_returns_partial_result_without_scanning(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "file.bin").write_bytes(b"data")
            cancel = threading.Event()
            cancel.set()

            result = analyze_directory(root, cancel_event=cancel)

        self.assertTrue(result["cancelled"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["files"], 0)

    def test_entry_limit_marks_scan_as_partial(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(5):
                (root / f"{index}.dat").write_bytes(b"x")

            result = analyze_directory(root, max_entries=2)

        self.assertFalse(result["complete"])
        self.assertLessEqual(result["files"], 2)


class ComputerCenterUITests(unittest.TestCase):
    def test_startup_and_storage_pages_open_and_analyze_selected_folder(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        root.withdraw()
        style = ttk.Style(root)
        style.configure("Title.TLabel")
        style.configure("PageHint.TLabel")
        style.configure("Card.TFrame")
        style.configure("CardTitle.TLabel")
        style.configure("Maintenance.Treeview")

        class Harness(ComputerCenterUIMixin):
            def __init__(self):
                self.root = root
                self.opened_preferences_tab = None

            def open_autonomy_settings(self, selected_tab):
                self.opened_preferences_tab = selected_tab

            def _authorize_core_action(self, *_args, **_kwargs):
                return True

            def _set_nova_window_icon(self, window):
                return window

            def _activate_panel(self, _window):
                return None

            def _panel_back(self, window):
                window.destroy()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        def wait_for(predicate):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                root.update()
                if predicate():
                    return True
                time.sleep(0.01)
            root.update()
            return predicate()

        controller = Harness()
        window = controller.show_computer_center(root)
        try:
            buttons = lambda: [widget for widget in descendants(window)
                               if isinstance(widget, ttk.Button)]
            next(button for button in buttons()
                 if button.cget("text").startswith(
                     "✦  Biblioteca de Aplicativos · abrir inventário"
                 )).invoke()
            self.assertEqual(controller.opened_preferences_tab, "computer")
            self.assertTrue(wait_for(lambda: any(
                isinstance(widget, ttk.Label)
                and "processador" in str(widget.cget("text")).casefold()
                for widget in descendants(window)
            )))
            next(button for button in buttons() if button.cget("text") == "Inicialização").invoke()
            self.assertTrue(wait_for(lambda: any(
                isinstance(widget, ttk.Treeview)
                and "name" in widget["columns"]
                for widget in descendants(window)
            )))
            next(button for button in buttons() if button.cget("text") == "Armazenamento").invoke()
            storage_action_loaded = wait_for(lambda: any(
                isinstance(widget, ttk.Button)
                and widget.cget("text") == "Analisar pasta"
                for widget in descendants(window)
            ))
            status_messages = [
                str(window.getvar(widget.cget("textvariable")))
                for widget in descendants(window)
                if isinstance(widget, ttk.Label) and widget.cget("textvariable")
            ]
            self.assertTrue(storage_action_loaded, "; ".join(status_messages))
            with tempfile.TemporaryDirectory() as temporary:
                with mock.patch("computer_center_ui.filedialog.askdirectory",
                                return_value=temporary):
                    next(button for button in buttons()
                         if button.cget("text") == "Escolher pasta…").invoke()
                fake_result = {
                    "path": temporary, "total": 1000, "used": 200,
                    "free": 800, "files": 1, "directories_count": 0,
                    "bytes_scanned": 12, "inaccessible": 0,
                    "complete": True, "cancelled": False,
                    "directories": {".": {"path": temporary, "name": "tmp",
                                           "parent": "", "bytes": 12,
                                           "files": 1, "directories": 0}},
                    "largest_files": [{"path": str(Path(temporary) / "a.txt"),
                                       "name": "a.txt", "bytes": 12,
                                       "extension": ".txt"}],
                }
                with mock.patch("computer_center_ui.analyze_directory",
                                return_value=fake_result):
                    next(button for button in buttons()
                         if button.cget("text") == "Analisar pasta").invoke()
                    self.assertTrue(wait_for(lambda: any(
                        isinstance(widget, ttk.Treeview)
                        and "extension" in widget["columns"]
                        for widget in descendants(window)
                    )))
        finally:
            window.destroy()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
