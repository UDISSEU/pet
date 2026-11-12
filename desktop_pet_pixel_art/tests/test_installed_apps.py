import json
import os
import sys
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from tkinter import ttk
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import autonomy
from preferences_computer_ui import ComputerPreferencesTabMixin


class InstalledAppDiscoveryTests(unittest.TestCase):
    def test_keeps_shortcut_when_executable_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            applications = Path(tmpdir) / "applications"
            applications.mkdir()
            desktop_file = applications / "missing.desktop"
            desktop_file.write_text(
                "[Desktop Entry]\nType=Application\nName=Missing Editor\n"
                "Exec=programa-que-nao-esta-instalado-123\n",
                encoding="utf-8",
            )

            with mock.patch.object(autonomy, "resolve_app_command") as validate:
                results = autonomy.find_installed_apps(directories=[applications])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Missing Editor")
        validate.assert_not_called()
        with self.assertRaisesRegex(ValueError, "Não encontrei o executável"):
            autonomy.resolve_app_command(results[0]["command"])
        self.assertEqual(
            results[0]["command"],
            "programa-que-nao-esta-instalado-123",
        )
        self.assertEqual(results[0]["desktop_file"], str(desktop_file))


class InstalledAppsUITests(unittest.TestCase):
    def test_inventory_query_renders_results_without_duplicate_loads(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("NOVA_REQUIRE_TK") == "1":
                self.fail(f"Tk display unavailable in CI: {exc}")
            self.skipTest(f"Tk display unavailable: {exc}")

        cache_dir = tempfile.TemporaryDirectory()

        class Harness(ComputerPreferencesTabMixin):
            def __init__(self):
                self.settings = {"user_name": "Usuária"}
                self.settings_path = Path(cache_dir.name) / "settings.json"
                self.permission_manager = mock.Mock()
                self.system_maintenance_active = False

            def _authorize_core_action(self, _permission, *, confirmed=False):
                return True

            def _child_process_env(self):
                return os.environ.copy()

            def post_ui_callback(self, callback, *args, **kwargs):
                callback(*args, **kwargs)
                return True

        pending_workers = []
        launched_workers = {"count": 0}

        class ControlledThread:
            def __init__(self, *, target, daemon):
                self.target = target

            def start(self):
                launched_workers["count"] += 1
                if launched_workers["count"] == 1:
                    pending_workers.append(self.target)
                else:
                    self.target()

        def make_card(parent, title, hint=None):
            frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
            frame.pack(fill="x")
            ttk.Label(frame, text=title, style="CardTitle.TLabel").pack(anchor="w")
            if hint:
                ttk.Label(frame, text=hint, style="Hint.TLabel").pack(anchor="w")
            return frame

        window = tk.Toplevel(root)
        computer_content = ttk.Frame(window)
        computer_content.pack(fill="both", expand=True)
        memory_content = ttk.Frame(window)
        context = SimpleNamespace(
            card=make_card,
            computer_content=computer_content,
            memory_content=memory_content,
            window=window,
        )
        pet = Harness()
        application = {
            "name": "Demo Editor",
            "command": "demo-editor",
            "desktop_file": "/usr/share/applications/demo-editor.desktop",
        }
        sources = {
            "package_versions": {"demo-editor": "1.0"},
            "package_owners": {
                application["desktop_file"]: "demo-editor",
            },
            "apt_owners_checked": True,
            "apt_upgradable": [],
            "flatpak_output": "",
            "flatpak_update_output": "",
            "snap_output": "",
            "snap_update_output": "",
            "checked_sources": {"APT/DEB"},
            "inventory_complete_sources": {"APT/DEB"},
            "source_results": {
                "APT/DEB": {
                    "inventory_complete": True,
                    "updates_complete": True,
                    "checked_at": "2025-01-01T10:00:00+00:00",
                    "metadata_updated_at": "",
                    "metadata_stale": False,
                },
                "Flatpak": {
                    "inventory_complete": True,
                    "updates_complete": True,
                    "checked_at": "2025-01-01T10:00:00+00:00",
                    "metadata_updated_at": "",
                    "metadata_stale": False,
                },
                "Snap": {
                    "inventory_complete": True,
                    "updates_complete": True,
                    "checked_at": "2025-01-01T10:00:00+00:00",
                    "metadata_updated_at": "",
                    "metadata_stale": False,
                },
            },
            "apt_applications": [],
            "snap_applications": [],
            "errors": [],
        }
        try:
            with mock.patch(
                "preferences_computer_ui.find_installed_apps",
                return_value=[application],
            ) as discover, mock.patch(
                "preferences_computer_ui.query_installed_app_sources",
                return_value=sources,
            ) as query_sources, mock.patch(
                "preferences_computer_ui.threading.Thread",
                side_effect=lambda **kwargs: ControlledThread(**kwargs),
            ):
                pet._build_computer_preferences_tab(context)
                context.refresh_computer_inventory()
                context.refresh_computer_inventory()
                self.assertEqual(len(pending_workers), 1)
                pending_workers.pop()()

                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)

                widgets = list(descendants(window))
                inventory = next(
                    widget for widget in widgets
                    if isinstance(widget, ttk.Treeview)
                    and "candidate" in widget["columns"]
                )
                self.assertEqual(len(inventory.get_children()), 1)
                self.assertEqual(
                    inventory.item(inventory.get_children()[0], "values")[0],
                    "Demo Editor",
                )
                discover.assert_called_once()

                refresh_button = next(
                    widget for widget in widgets
                    if isinstance(widget, ttk.Button)
                    and widget.cget("text") == "Recarregar lista"
                )
                refresh_button.invoke()
                self.assertEqual(len(inventory.get_children()), 1)
                self.assertEqual(discover.call_count, 2)

                sources.update(
                    package_versions={},
                    package_owners={},
                    apt_owners_checked=False,
                    apt_upgradable=[],
                    flatpak_output="",
                    flatpak_update_output="",
                    snap_output="",
                    snap_update_output="",
                    checked_sources=set(),
                    inventory_complete_sources=set(),
                    errors=["dpkg-query indisponível"],
                )
                for source_result in sources["source_results"].values():
                    source_result.update(
                        inventory_complete=False,
                        updates_complete=False,
                        checked_at="",
                    )
                refresh_button.invoke()
                self.assertEqual(len(inventory.get_children()), 1)
                self.assertEqual(
                    inventory.item(inventory.get_children()[0], "values")[0],
                    "Demo Editor",
                )
                self.assertEqual(
                    inventory.item(inventory.get_children()[0], "values")[3],
                    "Verificação necessária",
                )
                self.assertTrue(refresh_button.instate(["!disabled"]))
                self.assertEqual(query_sources.call_count, 3)
                query_sources.side_effect = RuntimeError("consulta indisponível")
                refresh_button.invoke()
                self.assertEqual(len(inventory.get_children()), 1)
                self.assertEqual(
                    inventory.item(inventory.get_children()[0], "values")[0],
                    "Demo Editor",
                )
                self.assertEqual(
                    inventory.item(inventory.get_children()[0], "values")[3],
                    "Verificação necessária",
                )
                self.assertTrue(refresh_button.instate(["!disabled"]))
        finally:
            root.destroy()
            cache_dir.cleanup()

    def test_persisted_inventory_is_visible_before_refresh_and_survives_source_failures(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("NOVA_REQUIRE_TK") == "1":
                self.fail(f"Tk display unavailable in CI: {exc}")
            self.skipTest(f"Tk display unavailable: {exc}")

        cache_dir = tempfile.TemporaryDirectory()
        pending_workers = []

        class ControlledThread:
            def __init__(self, *, target, daemon):
                self.target = target

            def start(self):
                pending_workers.append(self.target)

        class Harness(ComputerPreferencesTabMixin):
            def __init__(self):
                self.settings = {"user_name": "Usuária"}
                self.settings_path = Path(cache_dir.name) / "settings.json"
                self.permission_manager = mock.Mock()
                self.system_maintenance_active = False

            def _authorize_core_action(self, _permission, *, confirmed=False):
                return True

            def _child_process_env(self):
                return os.environ.copy()

            def post_ui_callback(self, callback, *args, **kwargs):
                callback(*args, **kwargs)
                return True

        def make_context(window):
            computer_content = ttk.Frame(window)
            computer_content.pack(fill="both", expand=True)
            memory_content = ttk.Frame(window)

            def make_card(parent, title, hint=None):
                frame = ttk.Frame(parent, style="Card.TFrame", padding=14)
                frame.pack(fill="x")
                ttk.Label(
                    frame, text=title, style="CardTitle.TLabel",
                ).pack(anchor="w")
                if hint:
                    ttk.Label(
                        frame, text=hint, style="Hint.TLabel",
                    ).pack(anchor="w")
                return frame

            return SimpleNamespace(
                card=make_card,
                computer_content=computer_content,
                memory_content=memory_content,
                window=window,
            )

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        application = {
            "name": "Persisted Editor",
            "command": "persisted-editor",
            "desktop_file": "/usr/share/applications/persisted-editor.desktop",
        }
        successful_sources = {
            "package_versions": {"persisted-editor": "1.0"},
            "package_owners": {
                application["desktop_file"]: "persisted-editor",
            },
            "apt_owners_checked": True,
            "apt_upgradable": [],
            "flatpak_output": "",
            "flatpak_update_output": "",
            "snap_output": "",
            "snap_update_output": "",
            "checked_sources": {"APT/DEB", "Flatpak", "Snap"},
            "inventory_complete_sources": {"APT/DEB", "Flatpak", "Snap"},
            "source_results": {
                source: {
                    "inventory_complete": True,
                    "updates_complete": True,
                    "checked_at": "2026-11-12T10:00:00+00:00",
                    "metadata_updated_at": "",
                    "metadata_stale": False,
                }
                for source in ("APT/DEB", "Flatpak", "Snap")
            },
            "apt_applications": [],
            "snap_applications": [],
            "errors": [],
        }
        failed_sources = {
            **successful_sources,
            "package_versions": {},
            "package_owners": {},
            "apt_owners_checked": False,
            "checked_sources": set(),
            "inventory_complete_sources": set(),
            "source_results": {
                source: {
                    "inventory_complete": False,
                    "updates_complete": False,
                    "checked_at": "",
                    "metadata_updated_at": "",
                    "metadata_stale": False,
                }
                for source in ("APT/DEB", "Flatpak", "Snap")
            },
            "errors": [
                "APT indisponível",
                "Flatpak indisponível",
                "Snap indisponível",
            ],
        }

        first_window = tk.Toplevel(root)
        first_pet = Harness()
        first_context = make_context(first_window)
        second_window = None
        try:
            with mock.patch(
                "preferences_computer_ui.find_installed_apps",
                return_value=[application],
            ), mock.patch(
                "preferences_computer_ui.query_installed_app_sources",
                side_effect=[successful_sources, failed_sources],
            ), mock.patch(
                "preferences_computer_ui.threading.Thread",
                side_effect=lambda **kwargs: ControlledThread(**kwargs),
            ):
                first_pet._build_computer_preferences_tab(first_context)
                first_context.refresh_computer_inventory()
                self.assertTrue(any(
                    isinstance(widget, ttk.Label)
                    and widget.cget("text")
                    == "Consultando fontes; a lista será exibida quando a consulta terminar."
                    for widget in descendants(first_window)
                ))
                pending_workers.pop()()
                stored_path = Path(cache_dir.name) / "installed_apps_inventory.json"
                self.assertTrue(stored_path.is_file())
                stored = json.loads(stored_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["version"], 1)
                self.assertEqual(stored["apps"][0]["name"], "Persisted Editor")

                first_window.destroy()
                second_window = tk.Toplevel(root)
                second_pet = Harness()
                second_context = make_context(second_window)
                second_pet._build_computer_preferences_tab(second_context)
                widgets = list(descendants(second_window))
                inventory = next(
                    widget for widget in widgets
                    if isinstance(widget, ttk.Treeview)
                    and "candidate" in widget["columns"]
                )
                row = inventory.item(inventory.get_children()[0], "values")
                self.assertEqual(row[0], "Persisted Editor")
                self.assertEqual(row[3], "Verificação necessária")

                second_context.refresh_computer_inventory(force=True)
                self.assertEqual(len(inventory.get_children()), 1)
                self.assertEqual(
                    inventory.item(inventory.get_children()[0], "values")[0],
                    "Persisted Editor",
                )
                pending_workers.pop()()
                row = inventory.item(inventory.get_children()[0], "values")
                self.assertEqual(row[0], "Persisted Editor")
                self.assertEqual(row[3], "Verificação necessária")
                error_messages = [
                    second_window.getvar(widget.cget("textvariable"))
                    for widget in descendants(second_window)
                    if isinstance(widget, ttk.Label)
                    and widget.cget("textvariable")
                ]
                self.assertTrue(any(
                    "APT indisponível" in message
                    for message in error_messages
                ))
        finally:
            if second_window is not None:
                try:
                    second_window.destroy()
                except tk.TclError:
                    pass
            root.destroy()
            cache_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
