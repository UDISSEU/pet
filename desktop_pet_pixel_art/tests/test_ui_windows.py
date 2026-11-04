"""Tk window smoke tests; skipped when this runtime has no usable display."""
import tempfile
import tkinter as tk
import time
import unittest
from pathlib import Path
from tkinter import ttk

from desktop_pet_ui import DesktopPetUIMixin
from notifications import NotificationManager
from permissions import PermissionManager
from plugin_manager import PluginManager
from system_monitor import SystemMonitor


class WindowHarness(DesktopPetUIMixin):
    def __init__(self, root, directory):
        self.root = root
        self.settings = {"dashboard_interval": 2}
        self.notification_manager = NotificationManager(Path(directory) / "notifications.json")
        self.permission_manager = PermissionManager(Path(directory) / "permissions.json")
        self.plugin_manager = PluginManager(permission_manager=self.permission_manager)
        self.system_monitor = SystemMonitor()
        self.state = "idle"
        self._recent_errors = []

    def _authorize_core_action(self, permission, *, confirmed=False):
        return True

    def _set_nova_window_icon(self, window):
        return window

    def _dashboard_snapshot(self):
        return {
            "pet_state": "idle", "animation": "idle", "ai_provider": "ollama",
            "ai_status": "idle", "integrations": {}, "plugins": self.plugin_manager.counts,
            "tasks_running": 0, "recent_errors": [],
        }

    def persist_preferences(self):
        return True


class TkWindowSmokeTests(unittest.TestCase):
    def test_dashboard_notifications_and_permissions_open_and_close(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        with tempfile.TemporaryDirectory() as directory:
            pet = WindowHarness(root, directory)
            try:
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)

                pet.notification_manager.create("Teste", "Janela de notificações")
                dashboard = pet.show_dashboard()
                notifications = pet.show_notifications()
                permissions = pet.open_permissions()
                self.assertIs(pet.show_dashboard(), dashboard)
                self.assertIs(pet.show_notifications(), notifications)
                self.assertIs(pet.open_permissions(), permissions)
                dashboard.geometry("560x540")
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    root.update_idletasks()
                    root.update()
                    if any(isinstance(widget, ttk.Label)
                           and "CPU:" in widget.cget("text")
                           for widget in descendants(dashboard)):
                        break
                    time.sleep(0.01)
                self.assertGreater(dashboard.winfo_width(), 1)
                windows = [child for child in root.winfo_children()
                           if isinstance(child, tk.Toplevel)]
                titles = {window.title() for window in windows}
                self.assertEqual(titles, {
                    "Painel da Nova", "Notificações da Nova", "Permissões da Nova",
                })
                self.assertTrue(all(window.winfo_exists() for window in windows))
                permission_toggle = next(
                    widget for widget in descendants(permissions)
                    if isinstance(widget, ttk.Checkbutton)
                    and widget.cget("text") == "Ler arquivos selecionados"
                )
                permission_toggle.invoke()
                self.assertTrue(pet.permission_manager.allowed("nova.core", "file.read"))
                self.assertFalse(pet.permission_manager.allowed("Nova (recursos internos)", "file.read"))
                permission_toggle.invoke()
                self.assertFalse(pet.permission_manager.allowed("nova.core", "file.read"))

                listing = next(widget for widget in descendants(notifications)
                               if isinstance(widget, tk.Listbox))
                listing.selection_set(0)
                mark_read = next(widget for widget in descendants(notifications)
                                 if isinstance(widget, ttk.Button)
                                 and widget.cget("text") == "Marcar como lida")
                mark_read.invoke()
                self.assertEqual(pet.notification_manager.unread_count, 0)
                notifications = pet._notifications_window
                self.assertIsNotNone(notifications)
                self.assertEqual(sum(isinstance(child, tk.Toplevel)
                                     for child in root.winfo_children()), 3)
                dashboard.destroy()
                reopened_dashboard = pet.show_dashboard()
                self.assertIsNot(reopened_dashboard, dashboard)
                windows.append(reopened_dashboard)
                for window in windows:
                    try:
                        window.destroy()
                    except tk.TclError:
                        pass
                root.update_idletasks()
                self.assertTrue(all(not window.winfo_exists() for window in windows))
            finally:
                try:
                    root.destroy()
                except tk.TclError:
                    pass


if __name__ == "__main__":
    unittest.main()
