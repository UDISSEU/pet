"""Tk window smoke tests; skipped when this runtime has no usable display."""
import os
import tempfile
import tkinter as tk
import time
import unittest
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest import mock
from unittest.mock import Mock

from desktop_pet_ui import DesktopPetUIMixin
from notifications import NotificationManager
from permissions import PermissionManager
from plugin_manager import PluginManager
from system_monitor import SystemMonitor
from preferences_common_ui import render_filtered_list, setup_list
from ui_theme import apply_theme


class WindowHarness(DesktopPetUIMixin):
    def __init__(self, root, directory):
        self.root = root
        apply_theme(root)
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


class PreferencesHarness(WindowHarness):
    """Isolate preference window construction and tab routing from services."""

    def __init__(self, root, directory):
        super().__init__(root, directory)
        self.settings.update({"memories": [], "reminders": [], "apps": []})
        self.settings_path = Path(directory) / "settings.json"
        self.history_path = Path(directory) / "history.json"
        self.history = []
        self.focus_mode = "idle"
        self.focus_goal = ""
        self.auto_speech_var = tk.BooleanVar(value=False)
        self.observe_apps_var = tk.BooleanVar(value=False)
        self.auto_sit_var = tk.BooleanVar(value=False)
        self.peekaboo_var = tk.BooleanVar(value=False)
        self._routine_greeted = True

    def _build_ai_preferences_tab(self, _context):
        pass

    def _build_automation_preferences_tab(self, _context):
        pass

    def _build_computer_preferences_tab(self, _context):
        pass

    def _build_reminders_and_apps_preferences_tabs(self, _context):
        pass

    def switch_user_profile(self, _profile_id):
        raise AssertionError("No profile service is configured in this test")

    def stop_focus(self):
        return None


class TkWindowSmokeTests(unittest.TestCase):
    def test_automation_toggle_reverts_and_reports_when_save_fails(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("NOVA_REQUIRE_TK") == "1":
                self.fail(f"Tk display unavailable in CI: {exc}")
            self.skipTest(f"Tk display unavailable: {exc}")
        with tempfile.TemporaryDirectory() as directory:
            pet = WindowHarness(root, directory)
            pet.settings.update({
                "automations": {
                    "enabled": {"laptop_status": True},
                    "last_run": {},
                    "activity": [],
                },
                "routine_break_tip": True,
            })
            pet.settings_path = Path(directory) / "settings.json"
            pet._request_automation = Mock()
            pet._refresh_automation_activity = Mock()
            window = tk.Toplevel(root)
            content = ttk.Frame(window)
            content.pack(fill="both", expand=True)
            context = SimpleNamespace(automation_content=content, window=window)
            try:
                with mock.patch(
                    "preferences_automation_ui.save_settings", return_value=False,
                ), mock.patch(
                    "preferences_automation_ui.messagebox.showerror",
                ) as show_error:
                    pet._build_automation_preferences_tab(context)
                    status_card = content.winfo_children()[2]
                    checkbutton = next(
                        widget for widget in status_card.winfo_children()[0].winfo_children()
                        if isinstance(widget, ttk.Checkbutton)
                        and widget.cget("text") == "Ativada"
                    )
                    checkbutton.invoke()
                    self.assertTrue(checkbutton.instate(["selected"]))
                    self.assertTrue(pet.settings["automations"]["enabled"]["laptop_status"])
                    show_error.assert_called_once()
            finally:
                window.destroy()
                root.destroy()

    def test_filtered_lists_clear_stale_selection_when_re_rendered(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("NOVA_REQUIRE_TK") == "1":
                self.fail(f"Tk display unavailable in CI: {exc}")
            self.skipTest(f"Tk display unavailable: {exc}")
        frame = ttk.Frame(root)
        frame.pack()
        items = ["m1", "m2", "m3"]
        listing, _, _ = setup_list(frame, items, lambda item: item, "Empty", height=3)
        listing.selection_set(1)
        visible = render_filtered_list(listing, items, str, lambda item: item != "m2")
        self.assertEqual(visible, ["m1", "m3"])
        self.assertEqual(listing.curselection(), ())
        root.destroy()

    def test_preferences_open_and_navigate_all_nine_tabs(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("NOVA_REQUIRE_TK") == "1":
                self.fail(f"Tk display unavailable in CI: {exc}")
            self.skipTest(f"Tk display unavailable: {exc}")
        with tempfile.TemporaryDirectory() as directory:
            pet = PreferencesHarness(root, directory)
            window = pet.open_autonomy_settings()
            try:
                root.update_idletasks()
                root.update()
                capture_dir = os.environ.get("NOVA_GUI_CAPTURE_DIR")
                if capture_dir:
                    from PIL import ImageGrab

                    Path(capture_dir).mkdir(parents=True, exist_ok=True)
                    left, top = window.winfo_rootx(), window.winfo_rooty()
                    ImageGrab.grab(
                        bbox=(left, top, left + window.winfo_width(), top + window.winfo_height())
                    ).save(Path(capture_dir) / "preferences.png")
                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)

                selector = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Combobox)
                    and len(widget.cget("values")) == 9
                )
                navigation = selector.master
                self.assertEqual(len(selector.cget("values")), 9)
                self.assertEqual(selector.get(), "Comportamento")
                selector.current(2)
                selector.event_generate("<<ComboboxSelected>>")
                root.update()
                self.assertEqual(selector.get(), "Memórias")
                memory_list = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, tk.Listbox)
                )
                self.assertTrue(memory_list._nova_empty_state.winfo_ismapped())
                if capture_dir:
                    root.update()
                    left, top = window.winfo_rootx(), window.winfo_rooty()
                    ImageGrab.grab(
                        bbox=(left, top, left + window.winfo_width(), top + window.winfo_height())
                    ).save(Path(capture_dir) / "preferences-memory-empty.png")
                add_button = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Button) and widget.cget("text") == "Adicionar"
                )
                input_box = next(
                    widget for widget in add_button.master.winfo_children()
                    if isinstance(widget, ttk.Entry)
                )
                input_box.insert(0, "Prefere chá")
                add_button.invoke()
                root.update()
                self.assertEqual(memory_list.get(0), "Prefere chá")
                self.assertTrue(memory_list._nova_list_frame.winfo_ismapped())
                self.assertFalse(memory_list._nova_horizontal_scrollbar.winfo_ismapped())
                self.assertGreater(memory_list.winfo_width(), 1)
                self.assertGreater(memory_list.winfo_height(), 1)
                scroll_canvas = memory_list.master
                while not isinstance(scroll_canvas, tk.Canvas):
                    scroll_canvas = scroll_canvas.master
                self.assertLessEqual(
                    memory_list.winfo_rooty() + memory_list.winfo_height(),
                    scroll_canvas.winfo_rooty() + scroll_canvas.winfo_height(),
                    "A lista precisa estar visível sem rolar a página.",
                )
                if capture_dir:
                    root.update_idletasks()
                    left, top = window.winfo_rootx(), window.winfo_rooty()
                    ImageGrab.grab(
                        bbox=(left, top, left + window.winfo_width(), top + window.winfo_height())
                    ).save(Path(capture_dir) / "preferences-memory.png")
                remove_button = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Button)
                    and widget.cget("text") == "Remover selecionada"
                )
                self.assertTrue(remove_button.instate(["disabled"]))
                memory_list.selection_set(0)
                memory_list.event_generate("<<ListboxSelect>>")
                root.update()
                self.assertFalse(remove_button.instate(["disabled"]))
                remove_button.invoke()
                root.update()
                self.assertEqual(memory_list.size(), 0)
                self.assertTrue(memory_list._nova_empty_state.winfo_ismapped())
                next_button = next(
                    widget for widget in navigation.winfo_children()
                    if isinstance(widget, ttk.Button) and widget.cget("text") == "▶"
                )
                next_button.invoke()
                self.assertEqual(selector.get(), "Histórico")
                previous_button = next(
                    widget for widget in navigation.winfo_children()
                    if isinstance(widget, ttk.Button) and widget.cget("text") == "◀"
                )
                previous_button.invoke()
                self.assertEqual(selector.get(), "Memórias")
                window.destroy()
                root.update_idletasks()
                self.assertFalse(window.winfo_exists())
            finally:
                if window.winfo_exists():
                    window.destroy()
                root.destroy()

    def test_main_menu_more_expands_fits_screen_and_routes_actions(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("NOVA_REQUIRE_TK") == "1":
                self.fail(f"Tk display unavailable in CI: {exc}")
            self.skipTest(f"Tk display unavailable: {exc}")
        with tempfile.TemporaryDirectory() as directory:
            pet = WindowHarness(root, directory)
            pet._context_popup = None
            for variable_name in (
                "behind_var", "stay_in_place_var", "auto_speech_var",
                "observe_apps_var", "peekaboo_var", "auto_sit_var",
            ):
                setattr(pet, variable_name, tk.BooleanVar(value=False))
            for callback_name in (
                "ask_menu", "show_calendar", "show_dashboard", "show_notifications",
                "open_autonomy_settings", "say_something", "open_permissions",
                "show_diagnostics", "forget_history", "forget_memories", "close_app",
                "toggle_behind_mode", "persist_preferences", "toggle_peekaboo",
                "toggle_auto_sit",
            ):
                setattr(pet, callback_name, Mock())
            try:
                pet.show_menu(SimpleNamespace(
                    x_root=20, y_root=root.winfo_screenheight() - 2,
                ))
                popup = pet._context_popup
                root.update()

                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)

                more_button = next(
                    widget for widget in descendants(popup)
                    if isinstance(widget, tk.Button)
                    and widget.cget("text").startswith("Mostrar mais")
                )
                collapsed_height = popup.winfo_height()
                capture_dir = os.environ.get("NOVA_GUI_CAPTURE_DIR")
                if capture_dir:
                    from PIL import ImageGrab

                    Path(capture_dir).mkdir(parents=True, exist_ok=True)
                    left, top = popup.winfo_rootx(), popup.winfo_rooty()
                    ImageGrab.grab(
                        bbox=(left, top, left + popup.winfo_width(), top + collapsed_height)
                    ).save(Path(capture_dir) / "main-menu.png")
                more_button.invoke()
                root.update()
                self.assertGreater(popup.winfo_height(), collapsed_height)
                self.assertEqual(more_button.cget("text"), "Mostrar menos  ▴")
                self.assertLessEqual(
                    popup.winfo_rooty() + popup.winfo_height(),
                    popup.winfo_screenheight(),
                )
                if capture_dir:
                    ImageGrab.grab().save(
                        Path(capture_dir) / "main-menu-expanded-desktop.png"
                    )
                speak_button = next(
                    widget for widget in descendants(popup)
                    if isinstance(widget, tk.Button) and widget.cget("text") == "Falar algo"
                )
                speak_button.invoke()
                pet.say_something.assert_called_once_with()
                self.assertFalse(popup.winfo_viewable())
                close_button = next(
                    widget for widget in descendants(popup)
                    if isinstance(widget, tk.Button) and widget.cget("text") == "×"
                )
                close_button.invoke()
                self.assertIsNone(pet._context_popup)
            finally:
                if pet._context_popup is not None:
                    pet._context_popup.destroy()
                root.destroy()

    def test_filtered_memory_list_transitions_between_empty_and_populated(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("NOVA_REQUIRE_TK") == "1":
                self.fail(f"Tk display unavailable in CI: {exc}")
            self.skipTest(f"Tk display unavailable: {exc}")
        try:
            root.geometry("480x360")
            content = ttk.Frame(root)
            content.pack(fill="both", expand=True)
            memories = []
            listing, _refresh, _remove = setup_list(
                content, memories, str, "Suas memórias ficam neste computador."
            )
            render_filtered_list(listing, memories, str, lambda _item: True)
            root.update_idletasks()
            self.assertFalse(listing._nova_list_frame.winfo_ismapped())
            self.assertTrue(listing._nova_empty_state.winfo_ismapped())

            memories.append("Prefere chá")
            memories.append("Trabalha com design")
            render_filtered_list(listing, memories, str, lambda _item: True)
            root.update_idletasks()
            self.assertTrue(listing._nova_list_frame.winfo_ismapped())
            self.assertFalse(listing._nova_empty_state.winfo_ismapped())
            self.assertEqual(listing.get(0), "Prefere chá")
            render_filtered_list(
                listing, memories, str, lambda item: "design" in item.casefold()
            )
            self.assertEqual(listing.size(), 1)
            self.assertEqual(listing.get(0), "Trabalha com design")

            render_filtered_list(listing, memories, str, lambda _item: False)
            root.update_idletasks()
            self.assertFalse(listing._nova_list_frame.winfo_ismapped())
            self.assertTrue(listing._nova_empty_state.winfo_ismapped())
        finally:
            root.destroy()

    def test_dashboard_notifications_and_permissions_open_and_close(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("NOVA_REQUIRE_TK") == "1":
                self.fail(f"Tk display unavailable in CI: {exc}")
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
                root.update_idletasks()
                root.update()
                deadline = time.monotonic() + 5
                metrics_loaded = False
                while time.monotonic() < deadline:
                    root.update_idletasks()
                    root.update()
                    metrics_loaded = any(
                        isinstance(widget, tk.Label)
                        and widget.cget("text").startswith("CPU:")
                        and widget.cget("text") != "CPU: —"
                        for widget in descendants(dashboard)
                    )
                    if metrics_loaded:
                        break
                    time.sleep(0.01)
                self.assertTrue(metrics_loaded, "Dashboard não exibiu métricas coletadas")
                capture_dir = os.environ.get("NOVA_GUI_CAPTURE_DIR")
                if capture_dir:
                    from PIL import ImageGrab

                    Path(capture_dir).mkdir(parents=True, exist_ok=True)
                    for name, window in (
                        ("dashboard", dashboard),
                        ("notifications", notifications),
                        ("permissions", permissions),
                    ):
                        window.deiconify()
                        window.lift()
                        window.update_idletasks()
                        root.update()
                        left, top = window.winfo_rootx(), window.winfo_rooty()
                        width, height = window.winfo_width(), window.winfo_height()
                        if width < 2 or height < 2 or not window.winfo_ismapped():
                            self.fail(f"Janela {name} não ficou visível para captura")
                        image = ImageGrab.grab(
                            bbox=(left, top, left + width, top + height)
                        )
                        image.save(Path(capture_dir) / f"{name}.png")
                self.assertGreater(dashboard.winfo_width(), 1)
                windows = [child for child in root.winfo_children()
                           if isinstance(child, tk.Toplevel)]
                titles = {window.title() for window in windows}
                self.assertEqual(titles, {
                    "Painel da Nova", "Notificações da Nova", "Permissões da Nova",
                })
                silent_control = next(
                    widget for widget in descendants(notifications)
                    if isinstance(widget, ttk.Checkbutton)
                    and widget.cget("text") == "Modo silencioso"
                )
                self.assertGreater(silent_control.winfo_height(), 0)
                for label in ("Marcar como lida", "Descartar", "Limpar descartadas"):
                    button = next(
                        widget for widget in descendants(notifications)
                        if isinstance(widget, ttk.Button) and widget.cget("text") == label
                    )
                    self.assertTrue(button.winfo_ismapped(), f"{label} não está visível")
                    self.assertLessEqual(
                        button.winfo_rooty() + button.winfo_height(),
                        notifications.winfo_rooty() + notifications.winfo_height(),
                        f"{label} ficou fora da janela",
                    )
                    self.assertGreaterEqual(
                        button.winfo_rootx(), notifications.winfo_rootx(),
                        f"{label} começou fora da janela",
                    )
                    self.assertLessEqual(
                        button.winfo_rootx() + button.winfo_width(),
                        notifications.winfo_rootx() + notifications.winfo_width(),
                        f"{label} ficou fora da janela",
                    )
                self.assertTrue(silent_control.winfo_ismapped())
                self.assertLessEqual(
                    silent_control.winfo_rootx() + silent_control.winfo_width(),
                    notifications.winfo_rootx() + notifications.winfo_width(),
                )
                self.assertLessEqual(
                    silent_control.winfo_rooty() + silent_control.winfo_height(),
                    notifications.winfo_rooty() + notifications.winfo_height(),
                )
                category_toggle = next(
                    widget for widget in descendants(notifications)
                    if isinstance(widget, ttk.Checkbutton)
                    and widget.cget("text") == "Ativar categoria"
                )
                self.assertTrue(category_toggle.winfo_ismapped())
                for control in (category_toggle, silent_control):
                    self.assertGreaterEqual(
                        control.winfo_rootx(), notifications.winfo_rootx()
                    )
                    self.assertGreaterEqual(
                        control.winfo_rooty(), notifications.winfo_rooty()
                    )
                    self.assertLessEqual(
                        control.winfo_rootx() + control.winfo_width(),
                        notifications.winfo_rootx() + notifications.winfo_width(),
                    )
                    self.assertLessEqual(
                        control.winfo_rooty() + control.winfo_height(),
                        notifications.winfo_rooty() + notifications.winfo_height(),
                    )
                silent_control.invoke()
                self.assertTrue(pet.notification_manager.silent)
                silent_control.invoke()
                self.assertFalse(pet.notification_manager.silent)
                self.assertTrue(all(window.winfo_exists() for window in windows))
                self.assertTrue(all(window.winfo_ismapped() for window in windows))
                for window in windows:
                    self.assertGreater(window.winfo_width(), 1)
                    self.assertGreater(window.winfo_height(), 1)
                    self.assertGreaterEqual(window.winfo_rootx(), 0)
                    self.assertGreaterEqual(window.winfo_rooty(), 0)
                    self.assertLessEqual(
                        window.winfo_rootx() + window.winfo_width(),
                        root.winfo_screenwidth(),
                    )
                    self.assertLessEqual(
                        window.winfo_rooty() + window.winfo_height(),
                        root.winfo_screenheight(),
                    )
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
                self.assertIsNone(pet._dashboard_window)
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
