"""Tk window smoke tests; skipped when this runtime has no usable display."""
import os
import tempfile
import tkinter as tk
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from unittest import mock
from unittest.mock import Mock

from desktop_pet_ui import DesktopPetUIMixin
from notifications import NotificationManager
from preferences_computer_ui import ComputerPreferencesTabMixin
from preferences_automation_ui import AutomationPreferencesTabMixin
from preferences_ai_ui import AIPreferencesTabMixin
from aurova_ai.memory.memory_manager import MemoryManager
from aurova_ai.memory.memory_storage import MemoryStorage
from permissions import PermissionManager
from plugin_manager import PluginManager
from system_monitor import SystemMonitor
from preferences_common_ui import render_filtered_list, setup_list
from ui_theme import apply_theme


def capture_window_if_requested(window, filename):
    capture_dir = os.environ.get("AUROVA_GUI_CAPTURE_DIR") or os.environ.get("NOVA_GUI_CAPTURE_DIR")
    if not capture_dir:
        return
    from PIL import ImageGrab

    Path(capture_dir).mkdir(parents=True, exist_ok=True)
    window.update_idletasks()
    left, top = window.winfo_rootx(), window.winfo_rooty()
    ImageGrab.grab(
        bbox=(left, top, left + window.winfo_width(), top + window.winfo_height())
    ).save(Path(capture_dir) / filename)


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def scroll_widget_into_view(widget, *, vertical_fraction=0.75):
    canvas = widget
    while canvas is not None and not isinstance(canvas, tk.Canvas):
        canvas = canvas.master
    if canvas is None:
        return
    bounds = canvas.bbox("all")
    if not bounds:
        return
    content_height = bounds[3] - bounds[1]
    if content_height <= 0:
        return
    offset = widget.winfo_rooty() - canvas.winfo_rooty()
    target = max(0, offset - canvas.winfo_height() * vertical_fraction)
    canvas.yview_moveto(min(1, target / content_height))


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

    def _set_aurova_window_icon(self, window):
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
        self.settings["user_name"] = "Pessoa de teste"
        self.auto_speech_var = tk.BooleanVar(value=False)
        self.observe_apps_var = tk.BooleanVar(value=False)
        self.auto_sit_var = tk.BooleanVar(value=False)
        self.peekaboo_var = tk.BooleanVar(value=False)
        self._routine_greeted = True
        self.system_maintenance_active = False
        self.post_ui_callback = lambda callback: self.root.after(0, callback)
        self.show_bubble = Mock()

    def _build_ai_preferences_tab(self, _context):
        pass

    def _build_automation_preferences_tab(self, _context):
        pass

    def _build_computer_preferences_tab(self, _context):
        pass

    def switch_user_profile(self, _profile_id):
        raise AssertionError("No profile service is configured in this test")

    def stop_focus(self):
        return None


class InstalledAppsPreferencesHarness(PreferencesHarness):
    def _build_computer_preferences_tab(self, context):
        return ComputerPreferencesTabMixin._build_computer_preferences_tab(self, context)


class VisualPreferencesHarness(PreferencesHarness):
    """Render the real preference pages for screenshot validation."""

    def __init__(self, root, directory):
        super().__init__(root, directory)
        self._request_automation = Mock()
        self._refresh_automation_activity = Mock()
        self._child_process_env = lambda: dict(os.environ)

    def _build_ai_preferences_tab(self, context):
        return AIPreferencesTabMixin._build_ai_preferences_tab(self, context)

    def _build_automation_preferences_tab(self, context):
        return AutomationPreferencesTabMixin._build_automation_preferences_tab(
            self, context,
        )

    def _build_computer_preferences_tab(self, context):
        return ComputerPreferencesTabMixin._build_computer_preferences_tab(
            self, context,
        )


class TkWindowSmokeTests(unittest.TestCase):
    def test_first_run_and_shared_dialog_use_aurova_theme(self):
        try:
            import first_run
            from ui_theme import show_dialog

            real_tk = first_run.tk.Tk
            callback_errors = []
            report = SimpleNamespace(
                dependencies={"Pillow": True, "OpenCV": True, "NumPy": True, "psutil": True},
                python_version="3.12.3",
                python_supported=True,
                ollama_status="not_installed",
                selected_model="llama3.2:1b",
                personality_status="available",
                graphics_available=4,
                graphics_total=4,
                database_status="not_created",
                free_disk_bytes=2 * 1024 ** 3,
                memory_total_bytes=4 * 1024 ** 3,
                cpu_count=4,
                can_continue=True,
            )

            def create_first_run_root():
                root = real_tk()

                def continue_first_run():
                    try:
                        capture_window_if_requested(root, "first-run.png")
                        button = next(
                            widget for widget in descendants(root)
                            if isinstance(widget, ttk.Button)
                            and widget.cget("text") == "Continuar sem baixar modelos"
                        )
                        self.assertEqual(ttk.Style(root).theme_use(), "clam")
                        button.invoke()
                    except Exception as exc:
                        callback_errors.append(exc)
                        root.destroy()

                root.after(150, continue_first_run)
                return root

            with mock.patch.object(first_run.tk, "Tk", side_effect=create_first_run_root):
                self.assertTrue(first_run._show_welcome_window(report=report))
            self.assertEqual(callback_errors, [])

            root = tk.Tk()
            apply_theme(root)
            root.geometry("480x360")
            root.update()
            callback_errors.clear()

            def cancel_shared_dialog():
                try:
                    dialog = next(
                        child for child in root.winfo_children()
                        if isinstance(child, tk.Toplevel)
                    )
                    capture_window_if_requested(dialog, "aurora-dialog.png")
                    button = next(
                        widget for widget in descendants(dialog)
                        if isinstance(widget, ttk.Button)
                        and widget.cget("text") == "Cancelar"
                    )
                    button.invoke()
                except Exception as exc:
                    callback_errors.append(exc)
                    for child in root.winfo_children():
                        if isinstance(child, tk.Toplevel):
                            child.destroy()

            root.after(150, cancel_shared_dialog)
            result = show_dialog(
                root, "Confirmar ação",
                "Esta confirmação usa os estilos globais e pode ser cancelada.",
                actions=(("Cancelar", False), ("Continuar", True)),
                destructive=True,
            )
            self.assertIs(result, False)
            self.assertEqual(callback_errors, [])
            root.destroy()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")

    def test_calendar_window_navigates_and_closes(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        from calendar_view import MONTH_NAMES, open_calendar_window

        apply_theme(root)
        try:
            window = open_calendar_window(root, on_back=lambda opened: opened.destroy())
            root.update()
            capture_window_if_requested(window, "calendar.png")
            title = next(
                widget for widget in descendants(window)
                if isinstance(widget, tk.Label)
                and any(
                    widget.cget("text").startswith(month + " ")
                    for month in MONTH_NAMES
                )
            )
            initial_month = title.cget("text")
            next_button = next(
                widget for widget in descendants(window)
                if isinstance(widget, ttk.Button) and widget.cget("text") == "›"
            )
            next_button.invoke()
            root.update()
            self.assertNotEqual(title.cget("text"), initial_month)
            previous_button = next(
                widget for widget in descendants(window)
                if isinstance(widget, ttk.Button) and widget.cget("text") == "‹"
            )
            previous_button.invoke()
            root.update()
            self.assertEqual(title.cget("text"), initial_month)
            next(
                widget for widget in descendants(window)
                if isinstance(widget, ttk.Button) and widget.cget("text") == "← Voltar"
            ).invoke()
            self.assertFalse(window.winfo_exists())
        finally:
            root.destroy()

    def test_conversation_dialog_opens_focused_and_cancels(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")

        apply_theme(root)
        root.update()
        pet = SimpleNamespace(
            root=root,
            _set_aurova_window_icon=lambda dialog: dialog,
            x=100,
            y=100,
            cur_height=190,
            screen_w=root.winfo_screenwidth(),
            screen_h=root.winfo_screenheight(),
        )
        pet._question_dialog_geometry = lambda: (
            DesktopPetUIMixin._question_dialog_geometry(pet)
        )
        pet._ask_question = lambda: DesktopPetUIMixin._ask_question(pet)
        callback_errors = []

        def cancel_conversation():
            try:
                dialog = next(
                    child for child in root.winfo_children()
                    if isinstance(child, tk.Toplevel)
                )
                capture_window_if_requested(dialog, "conversation.png")
                self.assertIs(dialog.grab_current(), dialog)
                question_entry = next(
                    widget for widget in descendants(dialog)
                    if isinstance(widget, tk.Text)
                )
                self.assertEqual(question_entry.focus_get(), question_entry)
                cancel_button = next(
                    widget for widget in descendants(dialog)
                    if isinstance(widget, ttk.Button)
                    and widget.cget("text") == "Cancelar"
                )
                cancel_button.invoke()
            except Exception as exc:
                callback_errors.append(exc)
                for child in root.winfo_children():
                    if isinstance(child, tk.Toplevel):
                        child.destroy()

        try:
            root.after(150, cancel_conversation)
            self.assertIsNone(pet._ask_question())
            self.assertEqual(callback_errors, [])
        finally:
            root.destroy()

    def test_conversation_dialog_geometry_fits_available_space(self):
        centered_pet = SimpleNamespace(
            x=330, y=200, cur_height=190, screen_w=800, screen_h=600,
        )
        self.assertEqual(
            DesktopPetUIMixin._question_dialog_geometry(centered_pet),
            (190, 155, 420, 280),
        )
        narrow_pet = SimpleNamespace(
            x=90, y=10, cur_height=190, screen_w=340, screen_h=320,
        )
        x, y, width, height = DesktopPetUIMixin._question_dialog_geometry(narrow_pet)
        self.assertEqual((x, width, height), (16, 308, 280))
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(y + height, narrow_pet.screen_h)

    def test_automation_toggle_reverts_and_reports_when_save_fails(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("AUROVA_REQUIRE_TK") == "1":
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
            if os.environ.get("AUROVA_REQUIRE_TK") == "1":
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
            if os.environ.get("AUROVA_REQUIRE_TK") == "1":
                self.fail(f"Tk display unavailable in CI: {exc}")
            self.skipTest(f"Tk display unavailable: {exc}")
        with tempfile.TemporaryDirectory() as directory:
            capture_dir = os.environ.get("AUROVA_GUI_CAPTURE_DIR") or os.environ.get("NOVA_GUI_CAPTURE_DIR")
            harness = VisualPreferencesHarness if capture_dir else PreferencesHarness
            pet = harness(root, directory)
            with mock.patch(
                "preferences_ai_ui.spotify_token_connected", return_value=False,
            ):
                window = pet.open_autonomy_settings()
            try:
                root.update_idletasks()
                root.update()
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
                for index, tab_name in enumerate(selector.cget("values"), start=1):
                    selector.set(tab_name)
                    selector.event_generate("<<ComboboxSelected>>")
                    root.update()
                    if capture_dir:
                        left, top = window.winfo_rootx(), window.winfo_rooty()
                        ImageGrab.grab(
                            bbox=(
                                left, top,
                                left + window.winfo_width(),
                                top + window.winfo_height(),
                            )
                        ).save(Path(capture_dir) / f"preferences-tab-{index:02}.png")
                selector.set("Comportamento")
                selector.event_generate("<<ComboboxSelected>>")
                root.update()
                selector.current(2)
                selector.event_generate("<<ComboboxSelected>>")
                root.update()
                self.assertEqual(selector.get(), "Memórias")
                memory_list = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, tk.Listbox)
                )
                self.assertTrue(memory_list._aurova_empty_state.winfo_ismapped())
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
                self.assertTrue(memory_list._aurova_list_frame.winfo_ismapped())
                self.assertFalse(memory_list._aurova_horizontal_scrollbar.winfo_ismapped())
                self.assertGreater(memory_list.winfo_width(), 1)
                self.assertGreater(memory_list.winfo_height(), 1)
                scroll_widget_into_view(memory_list)
                root.update()
                scroll_canvas = memory_list.master
                while not isinstance(scroll_canvas, tk.Canvas):
                    scroll_canvas = scroll_canvas.master
                self.assertLessEqual(
                    memory_list.winfo_rooty() + memory_list.winfo_height(),
                    scroll_canvas.winfo_rooty() + scroll_canvas.winfo_height(),
                    "A lista deve ficar visível após rolar sua página.",
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
                self.assertTrue(memory_list._aurova_empty_state.winfo_ismapped())
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

    def test_structured_memory_can_be_searched_edited_and_deleted(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        with tempfile.TemporaryDirectory() as directory:
            pet = PreferencesHarness(root, directory)
            manager = MemoryManager(MemoryStorage(Path(directory) / "memories.sqlite3"))
            pet.aurova_integration = SimpleNamespace(memory=manager)
            window = pet.open_autonomy_settings(selected_tab="memory")

            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            try:
                root.update()
                buttons = [
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Button)
                ]
                save_memory = next(button for button in buttons if button.cget("text") == "Guardar")
                input_box = next(
                    widget for widget in save_memory.master.winfo_children()
                    if isinstance(widget, ttk.Entry)
                )
                input_box.insert(0, "Prefere café sem açúcar")
                save_memory.invoke()
                root.update()

                memory_list = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, tk.Listbox)
                    and widget._aurova_empty_state.winfo_children()[1].winfo_children()[0].cget("text")
                    == "Nenhuma memória estruturada salva"
                )
                self.assertIn("Prefere café sem açúcar", memory_list.get(0))
                memory_list.selection_set(0)
                memory_list.event_generate("<<ListboxSelect>>")
                root.update()
                scroll_widget_into_view(memory_list, vertical_fraction=0.9)
                root.update()
                capture_window_if_requested(window, "memory.png")
                detail_label = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Label)
                    and widget.cget("textvariable")
                    and "Relevância" in root.getvar(widget.cget("textvariable"))
                )
                self.assertIn("Relevância", root.getvar(detail_label.cget("textvariable")))

                edit_button = next(
                    button for button in buttons
                    if button.cget("text") == "Corrigir selecionada"
                )
                with mock.patch(
                    "preferences_memory_ui.simpledialog.askstring",
                    return_value="Prefere café coado sem açúcar",
                ):
                    edit_button.invoke()
                root.update()
                self.assertEqual(
                    manager.search("café", limit=10)[0].content,
                    "Prefere café coado sem açúcar",
                )

                memory_list.selection_set(0)
                memory_list.event_generate("<<ListboxSelect>>")
                root.update()
                delete_button = next(
                    button for button in buttons
                    if button.cget("text") == "Apagar selecionada"
                )
                with mock.patch(
                    "preferences_memory_ui.messagebox.askyesno", return_value=True,
                ):
                    delete_button.invoke()
                self.assertEqual(manager.search("café", limit=10), [])
            finally:
                window.destroy()
                root.destroy()

    def test_conversation_history_groups_filters_and_opens_message_details(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        with tempfile.TemporaryDirectory() as directory:
            pet = PreferencesHarness(root, directory)
            now = datetime.now().astimezone()
            previous_month = now.replace(
                day=1, hour=12, minute=0, second=0, microsecond=0,
            ) - timedelta(days=1)
            pet.history = [
                {
                    "role": "user", "content": "A mensagem de ontem",
                    "timestamp": previous_month.isoformat(),
                },
                {
                    "role": "assistant", "content": "A resposta de hoje",
                    "timestamp": now.isoformat(),
                },
            ]
            window = pet.open_autonomy_settings(selected_tab="history")

            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            try:
                root.update()
                history_view = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, tk.Text) and int(widget.cget("height")) == 6
                )
                contents = history_view.get("1.0", "end")
                self.assertIn("── ", contents)
                self.assertIn("A mensagem de ontem", contents)
                self.assertIn("A resposta de hoje", contents)

                history_period = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Combobox)
                    and "Todos os períodos" in widget.cget("values")
                )
                self.assertGreaterEqual(len(history_period.cget("values")), 2)
                history_period.set(history_period.cget("values")[1])
                history_period.event_generate("<<ComboboxSelected>>")
                root.update()
                self.assertLessEqual(
                    history_view.get("1.0", "end").count("── "), 2
                )
                second_line = history_view.dlineinfo("2.0")
                history_view.event_generate(
                    "<Button-1>", x=20, y=second_line[1] + 1,
                )
                root.update()
                details = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, tk.Text) and int(widget.cget("height")) == 5
                )
                self.assertIn("Conversa", details.get("1.0", "end"))
                scroll_widget_into_view(history_view, vertical_fraction=0.9)
                root.update()
                capture_window_if_requested(window, "history.png")
            finally:
                window.destroy()
                root.destroy()

    def test_reminder_create_edit_complete_delete_and_save_flow(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        with tempfile.TemporaryDirectory() as directory:
            pet = PreferencesHarness(root, directory)
            pet.settings.update(routine_context=False, routine_greeting=False)
            now = datetime.now().astimezone()
            today = now + timedelta(minutes=10)
            overdue = now - timedelta(days=1)
            tomorrow = now + timedelta(days=2)
            completed = now - timedelta(days=2)
            original_reminders = [
                {"at": today.isoformat(timespec="minutes"), "text": "Compromisso de hoje", "done": False},
                {"at": overdue.isoformat(timespec="minutes"), "text": "Lembrete atrasado", "done": False},
                {"at": tomorrow.isoformat(timespec="minutes"), "text": "Próximo compromisso", "done": False},
                {"at": completed.isoformat(timespec="minutes"), "text": "Tarefa concluída", "done": True},
            ]
            pet.settings["reminders"] = original_reminders
            window = pet.open_autonomy_settings(selected_tab="reminder")

            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            try:
                root.update()
                reminder_filter = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Combobox)
                    and "Hoje" in widget.cget("values")
                )
                reminder_list = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, tk.Listbox)
                    and widget._aurova_empty_state.winfo_children()[1].winfo_children()[0].cget("text")
                    .startswith("Nenhum lembrete cadastrado")
                )
                for label, expected in (
                    ("Hoje", "Compromisso de hoje"),
                    ("Atrasados", "Lembrete atrasado"),
                    ("Próximos", "Próximo compromisso"),
                    ("Concluídos", "Tarefa concluída"),
                ):
                    reminder_filter.set(label)
                    reminder_filter.event_generate("<<ComboboxSelected>>")
                    root.update()
                    self.assertEqual(reminder_list.size(), 1)
                    self.assertIn(expected, reminder_list.get(0))
                reminder_filter.set("Todos")
                reminder_filter.event_generate("<<ComboboxSelected>>")
                root.update()

                submit = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Button)
                    and widget.cget("text") == "Adicionar"
                    and sum(
                        isinstance(child, ttk.Entry)
                        for child in widget.master.winfo_children()
                    ) == 3
                )
                form_entries = [
                    widget for widget in submit.master.winfo_children()
                    if isinstance(widget, ttk.Entry)
                ]
                due = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
                for entry, text in zip(
                    form_entries, (due, "09:30", "Revisar a agenda"),
                ):
                    entry.insert(0, text)
                submit.invoke()
                root.update()
                self.assertEqual(reminder_list.size(), 5)
                added_row = next(
                    row for row in range(reminder_list.size())
                    if "Revisar a agenda" in reminder_list.get(row)
                )
                reminder_list.selection_set(added_row)
                reminder_list.event_generate("<<ListboxSelect>>")
                root.update()
                scroll_widget_into_view(reminder_list, vertical_fraction=0.9)
                root.update()
                capture_window_if_requested(window, "reminders.png")
                form_entries[2].delete(0, "end")
                form_entries[2].insert(0, "Revisar a agenda atualizada")
                submit.invoke()
                root.update()
                added_row = next(
                    row for row in range(reminder_list.size())
                    if "Revisar a agenda atualizada" in reminder_list.get(row)
                )
                self.assertIn("Revisar a agenda atualizada", reminder_list.get(added_row))

                complete_button = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Button)
                    and widget.cget("text") == "Concluir / reativar"
                )
                reminder_list.selection_set(added_row)
                complete_button.invoke()
                added_row = next(
                    row for row in range(reminder_list.size())
                    if "Revisar a agenda atualizada" in reminder_list.get(row)
                )
                self.assertIn("Concluído", reminder_list.get(added_row))
                reminder_list.selection_set(added_row)
                with mock.patch(
                    "preferences_apps_ui.messagebox.askyesno", return_value=True,
                ):
                    next(
                        widget for widget in descendants(window)
                        if isinstance(widget, ttk.Button)
                        and widget.cget("text") == "Remover selecionado"
                    ).invoke()
                    self.assertEqual(reminder_list.size(), 4)
                next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Button)
                    and widget.cget("text") == "Salvar alterações"
                ).invoke()
                root.update()
                self.assertFalse(window.winfo_exists())
                from autonomy import load_settings
                self.assertEqual(
                    load_settings(Path(directory) / "settings.json")["reminders"],
                    original_reminders,
                )
            finally:
                if window.winfo_exists():
                    window.destroy()
                root.destroy()

    def test_installed_application_inventory_filters_and_explains_manual_removal(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")
        with tempfile.TemporaryDirectory() as directory:
            pet = InstalledAppsPreferencesHarness(root, directory)
            apps = [
                {
                    "name": "Editor", "version": "1.2", "candidate_version": "—",
                    "update_status": "Atualizado", "origin": "APT/DEB · atalho quebrado",
                    "package": "editor", "source": "APT/DEB",
                    "description": "Editor de texto", "categories": "Utility;TextEditor",
                    "icon": "", "desktop_file": "/usr/share/applications/editor.desktop",
                    "command": "editor", "location": "/usr/bin/editor",
                    "shortcut_state": "broken",
                },
                {
                    "name": "Editor", "version": "1.3", "candidate_version": "—",
                    "update_status": "Atualizado", "origin": "Flatpak · flathub",
                    "package": "org.example.Editor", "source": "Flatpak",
                    "description": "Editor portátil", "categories": "Utility;TextEditor",
                    "icon": "", "desktop_file": "", "command": "", "location": "",
                    "shortcut_state": "absent",
                },
                {
                    "name": "Portable Tool", "version": "Não informada",
                    "candidate_version": "—",
                    "update_status": "Atualização não gerenciada",
                    "origin": "Manual / origem não identificada",
                    "package": "—", "source": "Manual/outro",
                    "description": "Ferramenta instalada manualmente",
                    "categories": "Utility", "icon": "", "desktop_file": "",
                    "command": "", "location": "/opt/portable-tool",
                    "shortcut_state": "absent",
                },
            ]
            empty_sources = {
                source: {
                    "checked_at": "", "needs_verification": True,
                    "metadata_updated_at": "", "metadata_stale": False,
                }
                for source in ("APT/DEB", "Flatpak", "Snap")
            }
            inventory_begin_patch = mock.patch(
                "preferences_computer_ui.InventoryLoadState.begin",
                return_value=False,
            )
            inventory_begin_patch.start()
            with mock.patch(
                "preferences_computer_ui.InstalledAppInventoryStore.load",
                return_value={"apps": apps, "sources": empty_sources, "saved_at": ""},
            ):
                window = pet.open_autonomy_settings()

            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)

            try:
                root.update()
                selector = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Combobox)
                    and "Meu Computador" in widget.cget("values")
                )
                selector.set("Meu Computador")
                selector.event_generate("<<ComboboxSelected>>")
                root.update()
                inventory_table = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Treeview)
                    and {"name", "version", "origin"}.issubset(widget.cget("columns"))
                )
                self.assertEqual(len(inventory_table.get_children()), 3)
                search = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Entry)
                    and widget.master.winfo_children()
                    and any(
                        isinstance(child, ttk.Label) and child.cget("text") == "Buscar:"
                        for child in widget.master.winfo_children()
                    )
                )
                search.insert(0, "Editor")
                root.update()
                self.assertEqual(len(inventory_table.get_children()), 2)

                source_picker = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Combobox)
                    and "Todas as origens" in widget.cget("values")
                )
                source_picker.set("Flatpak")
                root.update()
                self.assertEqual(len(inventory_table.get_children()), 1)
                source_picker.set("Todas as origens")
                search.delete(0, "end")
                root.update()

                apt_item = next(
                    item_id for item_id in inventory_table.get_children()
                    if inventory_table.item(item_id, "values")[0] == "Editor"
                    and inventory_table.item(item_id, "values")[4] == "APT/DEB · atalho quebrado"
                )
                inventory_table.selection_set(apt_item)
                inventory_table.event_generate("<<TreeviewSelect>>")
                root.update()
                scroll_widget_into_view(inventory_table)
                root.update()
                details = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Label)
                    and widget.cget("textvariable")
                    and "Possíveis duplicados" in root.getvar(widget.cget("textvariable"))
                )
                self.assertIn("Quebrado", root.getvar(details.cget("textvariable")))
                capture_window_if_requested(window, "applications-manager.png")
                for canvas in descendants(window):
                    if isinstance(canvas, tk.Canvas):
                        canvas.yview_moveto(0.35)
                root.update()
                capture_window_if_requested(window, "applications-details.png")

                portable_item = next(
                    item_id for item_id in inventory_table.get_children()
                    if inventory_table.item(item_id, "values")[0] == "Portable Tool"
                )
                inventory_table.selection_set(portable_item)
                inventory_table.event_generate("<<TreeviewSelect>>")
                root.update()
                review_button = next(
                    widget for widget in descendants(window)
                    if isinstance(widget, ttk.Button)
                    and widget.cget("text") == "Revisar remoção"
                )
                with mock.patch(
                    "preferences_computer_ui.messagebox.showinfo",
                ) as show_info:
                    review_button.invoke()
                self.assertIn("não apagará o executável", show_info.call_args.args[1])
            finally:
                inventory_begin_patch.stop()
                window.destroy()
                root.destroy()

    def test_main_menu_more_expands_fits_screen_and_routes_actions(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("AUROVA_REQUIRE_TK") == "1":
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
                capture_dir = os.environ.get("AUROVA_GUI_CAPTURE_DIR") or os.environ.get("NOVA_GUI_CAPTURE_DIR")
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
            if os.environ.get("AUROVA_REQUIRE_TK") == "1":
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
            self.assertFalse(listing._aurova_list_frame.winfo_ismapped())
            self.assertTrue(listing._aurova_empty_state.winfo_ismapped())

            memories.append("Prefere chá")
            memories.append("Trabalha com design")
            render_filtered_list(listing, memories, str, lambda _item: True)
            root.update_idletasks()
            self.assertTrue(listing._aurova_list_frame.winfo_ismapped())
            self.assertFalse(listing._aurova_empty_state.winfo_ismapped())
            self.assertEqual(listing.get(0), "Prefere chá")
            render_filtered_list(
                listing, memories, str, lambda item: "design" in item.casefold()
            )
            self.assertEqual(listing.size(), 1)
            self.assertEqual(listing.get(0), "Trabalha com design")

            render_filtered_list(listing, memories, str, lambda _item: False)
            root.update_idletasks()
            self.assertFalse(listing._aurova_list_frame.winfo_ismapped())
            self.assertTrue(listing._aurova_empty_state.winfo_ismapped())
        finally:
            root.destroy()

    def test_dashboard_notifications_and_permissions_open_and_close(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("AUROVA_REQUIRE_TK") == "1":
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
                rendered_values = [
                    str(root.getvar(widget.cget("textvariable")))
                    for widget in descendants(dashboard)
                    if isinstance(widget, tk.Label) and widget.cget("textvariable")
                ]
                self.assertIn("Aurova está disponível", rendered_values)
                self.assertIn("IA  Ollama · disponível", rendered_values)
                self.assertFalse(any("AO VIVO" in value for value in rendered_values))
                capture_dir = os.environ.get("AUROVA_GUI_CAPTURE_DIR") or os.environ.get("NOVA_GUI_CAPTURE_DIR")
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
                    "Painel da Aurova", "Notificações da Aurova", "Permissões da Aurova",
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
                self.assertTrue(pet.permission_manager.allowed("aurova.core", "file.read"))
                self.assertFalse(pet.permission_manager.allowed("Aurova (recursos internos)", "file.read"))
                permission_toggle.invoke()
                self.assertFalse(pet.permission_manager.allowed("aurova.core", "file.read"))

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
