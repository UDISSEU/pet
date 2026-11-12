import ast
from contextlib import ExitStack
import inspect
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import desktop_pet
import animation_controller
import device_controller
import preferences_ai_ui
import preferences_apps_ui
import preferences_automation_ui
import preferences_behavior_ui
import preferences_common_ui
import preferences_computer_ui
import preferences_memory_ui
import preferences_ui
import speech_controller
import routine_controller
from desktop_pet import DesktopPet


class DesktopControllerRegressionTests(unittest.TestCase):
    def test_automation_file_preview_is_dispatched_to_worker(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.settings = {"automations": {"enabled": {}}}
        pet.automation_active = False
        pet.ai_request_active = False
        pet.app_launch_active = False
        pet.permission_manager = mock.Mock()
        pet._authorize_core_action = mock.Mock()
        pet._automation_action_buttons = {}
        pet.show_bubble = mock.Mock()
        pet.event_bus = mock.Mock()
        automation = next(
            item for item in desktop_pet.AUTOMATIONS
            if item["id"] == "organize_screenshots"
        )

        with (
            mock.patch("desktop_pet.threading.Thread") as thread,
            mock.patch("desktop_pet.preview_screenshots") as preview,
        ):
            pet._request_automation(automation)

        preview.assert_not_called()
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["target"], pet._automation_preview_worker)
        thread.return_value.start.assert_called_once_with()

    def test_cognitive_preview_limit_is_not_confirmed(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._closing = False
        pet._finish_cognitive_request = mock.Mock()
        prepared = SimpleNamespace(
            inspection=SimpleNamespace(data={"limit_reached": True}),
        )

        pet._handle_cognitive_prepared("organize downloads", prepared, None)

        pet._finish_cognitive_request.assert_called_once()
        self.assertIn("mais de 500", pet._finish_cognitive_request.call_args.args[1])

    def test_due_reminder_is_not_announced_when_persistence_fails(self):
        pet = DesktopPet.__new__(DesktopPet)
        reminder = {
            "at": "2000-01-01T00:00:00+00:00",
            "text": "Beber água",
        }
        pet._closing = False
        pet._state = "walk"
        pet.settings = {"reminders": [reminder], "user_name": "Ada"}
        pet._speech_history = []
        pet._can_speak_spontaneously = mock.Mock(return_value=True)
        pet._spontaneous_ready = mock.Mock(return_value=True)
        pet.root = mock.Mock()
        pet.show_bubble = mock.Mock()

        with (
            mock.patch.object(routine_controller, "save_settings", return_value=False),
            mock.patch.object(routine_controller, "pick_line") as pick_line,
        ):
            pet.check_reminders()

        self.assertNotIn("done", reminder)
        pick_line.assert_not_called()
        pet.show_bubble.assert_called_once()
        self.assertIn("continua pendente", pet.show_bubble.call_args.args[0])
        pet.root.after.assert_called_once_with(15000, pet.check_reminders)

    def test_due_reminder_is_announced_after_persistence_succeeds(self):
        pet = DesktopPet.__new__(DesktopPet)
        reminder = {
            "at": "2000-01-01T00:00:00+00:00",
            "text": "Beber água",
        }
        pet._closing = False
        pet._state = "walk"
        pet.settings = {"reminders": [reminder], "user_name": "Ada"}
        pet._speech_history = []
        pet._can_speak_spontaneously = mock.Mock(return_value=True)
        pet._spontaneous_ready = mock.Mock(return_value=True)
        pet.root = mock.Mock()
        pet.show_bubble = mock.Mock()

        with (
            mock.patch.object(routine_controller, "save_settings", return_value=True),
            mock.patch.object(routine_controller, "pick_line", return_value="Lembrete!") as pick_line,
            mock.patch.object(routine_controller, "record_spontaneous_speech") as record_speech,
        ):
            pet.check_reminders()

        self.assertTrue(reminder["done"])
        pick_line.assert_called_once()
        record_speech.assert_called_once()
        pet.show_bubble.assert_called_once_with("Lembrete! Beber água", duration=12000)

    def test_animation_frame_selection_keeps_elapsed_time_and_frame(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.state = "walk"
        pet.walk_dx = 1
        pet._walk_velocity_x = 0.0
        pet.busy = False
        pet._startup_walk_enabled = True
        pet._irritated_until = 0.0
        pet.stay_in_place_var = mock.Mock()
        pet.stay_in_place_var.get.return_value = False
        pet.video_frames = {"walk_right": ["first", "second", "third"]}
        pet.animation_time_ms = 250.0

        with mock.patch.object(animation_controller, "frame_index_at_elapsed", return_value=1) as select:
            result = pet._current_video_frame(now=1.0)

        self.assertEqual(result, ("walk_right", 1, "second"))
        select.assert_called_once()
        self.assertEqual(select.call_args.args[:2], (250.0, 3))

    def test_mouse_release_restores_walk_state_and_dispatches_click(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._ignore_next_click = False
        pet.was_drag = False
        pet.dragging = True
        pet.state = "held"
        pet.drag_target_tilt = 8.0
        pet._last_drag_pointer_x = 20
        pet._drag_focus_widget = None
        pet._post_drag_state = mock.Mock(return_value="walk")
        pet._handle_simple_click = mock.Mock()
        pet.root = mock.Mock()

        pet.stop_drag(None)

        self.assertFalse(pet.dragging)
        self.assertEqual(pet.drag_target_tilt, 0.0)
        self.assertIsNone(pet._last_drag_pointer_x)
        self.assertEqual(pet.state, "walk")
        pet._handle_simple_click.assert_called_once_with()

    def test_personality_line_keeps_public_speech_path(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._closing = False
        pet.settings = {"user_name": "Ada"}
        pet._speech_history = []
        pet.show_bubble = mock.Mock()

        with mock.patch.object(speech_controller, "pick_line", return_value="Olá, Ada!") as pick:
            shown = pet._show_personality_line("greeting", duration=2500)

        self.assertTrue(shown)
        pick.assert_called_once_with(
            "greeting",
            name="Ada",
            rng=desktop_pet.random,
            history=[],
        )
        pet.show_bubble.assert_called_once_with("Olá, Ada!", duration=2500)

    def test_usb_scanner_keeps_stable_device_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = root / "physical" / "1-2"
            interface = device / "1-2:1.0"
            interface.mkdir(parents=True)
            (interface / "bInterfaceClass").write_text("08", encoding="ascii")
            (device / "manufacturer").write_text("Nova", encoding="utf-8")
            (device / "product").write_text("Drive", encoding="utf-8")
            bus_devices = root / "devices"
            bus_devices.mkdir()
            (bus_devices / "1-2:1.0").symlink_to(interface, target_is_directory=True)

            def fake_path(path):
                if str(path) == "/sys/bus/usb/devices":
                    return root / "devices"
                if str(path) == "/sys/class/block":
                    return root / "block"
                return Path(path)

            with mock.patch.object(device_controller, "Path", side_effect=fake_path):
                devices = DesktopPet._scan_usb_storage_devices()

        self.assertEqual(devices, {"1-2": "Nova Drive"})

    def test_window_icon_assignment_remains_available(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._window_icon = mock.sentinel.icon
        window = mock.Mock()

        self.assertIs(pet._set_nova_window_icon(window), window)
        window.iconphoto.assert_called_once_with(False, mock.sentinel.icon)

    def test_preferences_keep_existing_tab_order_and_selection_ids(self):
        tree = ast.parse(
            (SRC / "preferences_ui.py").read_text(encoding="utf-8")
        )
        method = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "open_autonomy_settings"
        )
        registered_tabs = [
            (ast.literal_eval(call.args[1]), ast.unparse(call.args[0]))
            for call in ast.walk(method)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "register_tab"
        ]
        self.assertEqual(
            registered_tabs,
            [
                ("Comportamento", "behavior_tab"),
                ("Foco e rotina", "routine_tab"),
                ("Memórias", "memory_tab"),
                ("Histórico", "history_tab"),
                ("Lembretes", "reminder_tab"),
                ("Aplicativos", "apps_tab"),
                ("Meu Computador", "computer_tab"),
                ("Automações", "automation_tab"),
                ("Inteligência artificial", "ai_tab"),
            ],
        )
        source = ast.get_source_segment(
            (SRC / "preferences_ui.py").read_text(encoding="utf-8"),
            method,
        )
        for selected_tab in ("routine", "memory", "reminder", "apps", "computer", "automation", "ai"):
            self.assertIn(f'selected_tab == "{selected_tab}"', source)
        signature = inspect.signature(DesktopPet.open_autonomy_settings)
        self.assertEqual(tuple(signature.parameters), ("self", "selected_tab"))
        self.assertEqual(signature.parameters["selected_tab"].default, "behavior")

    def test_open_autonomy_settings_refreshes_computer_inventory_when_selected(self):
        class FakeVariable:
            def __init__(self, value=None):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

            def trace_add(self, *_args):
                return "trace"

        class FakeWidget:
            def __init__(self, *_args, **_kwargs):
                self.options = _kwargs
                self.children = []

            def pack(self, *args, **kwargs):
                return None

            def pack_forget(self):
                return None

            def bind(self, *_args, **_kwargs):
                return None

            def configure(self, *args, **kwargs):
                return None

            def __getattr__(self, name):
                if name in ("curselection", "selection"):
                    return lambda *args, **kwargs: ()
                if name == "winfo_exists":
                    return lambda: True
                if name.startswith("winfo_"):
                    return lambda *args, **kwargs: 100
                return lambda *args, **kwargs: None

        class FakeTk:
            TclError = RuntimeError
            StringVar = BooleanVar = DoubleVar = FakeVariable

            def __getattr__(self, _name):
                return FakeWidget

        class FakeTtk:
            def __getattr__(self, _name):
                return FakeWidget

        pet = DesktopPet.__new__(DesktopPet)
        pet.root = FakeWidget()
        pet.settings = {
            "mode": "companhia",
            "apps": [],
            "memories": [],
            "reminders": [],
            "automations": {"enabled": {}, "last_run": {}, "activity": []},
        }
        pet.history = []
        pet.auto_speech_var = FakeVariable(True)
        pet.observe_apps_var = FakeVariable(True)
        pet.auto_sit_var = FakeVariable(False)
        pet.peekaboo_var = FakeVariable(False)
        pet.focus_mode = "idle"
        pet.ai_request_active = False
        pet.dragging = False
        pet._set_nova_window_icon = lambda window: window
        pet._activate_panel = mock.Mock()
        pet._refresh_automation_activity = mock.Mock()
        refresh_called = mock.Mock()

        def fake_build_computer(self, context):
            context.refresh_computer_inventory = refresh_called

        with ExitStack() as stack:
            for module in (
                preferences_ui,
                preferences_ai_ui,
                preferences_apps_ui,
                preferences_automation_ui,
                preferences_behavior_ui,
                preferences_common_ui,
                preferences_computer_ui,
                preferences_memory_ui,
            ):
                stack.enter_context(mock.patch.object(module, "tk", FakeTk()))
                if hasattr(module, "ttk"):
                    stack.enter_context(mock.patch.object(module, "ttk", FakeTtk()))
            stack.enter_context(mock.patch.object(preferences_ui, "make_header"))
            stack.enter_context(
                mock.patch.object(
                    preferences_ui.PreferencesUIMixin,
                    "_build_computer_preferences_tab",
                    fake_build_computer,
                )
            )
            pet.open_autonomy_settings("computer")

        refresh_called.assert_called_once_with()

    def test_preference_tabs_build_without_a_display(self):
        class FakeVariable:
            def __init__(self, value=None):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

            def trace_add(self, *_args):
                return "trace"

        class FakeWidget:
            instances = []

            def __init__(self, *_args, **_kwargs):
                self.options = _kwargs
                self.instances.append(self)

            def __getattr__(self, name):
                if name == "curselection":
                    return lambda: ()
                if name in ("get_children", "selection"):
                    return lambda: ()
                if name == "winfo_exists":
                    return lambda: True
                if name.startswith("winfo_"):
                    return lambda: 100
                return lambda *_args, **_kwargs: FakeWidget()

        class FakeTk:
            TclError = RuntimeError
            StringVar = BooleanVar = DoubleVar = FakeVariable

            def __getattr__(self, _name):
                return FakeWidget

        class FakeTtk:
            def __getattr__(self, _name):
                return FakeWidget

        pet = DesktopPet.__new__(DesktopPet)
        pet.root = FakeWidget()
        pet.settings = {
            "mode": "companhia",
            "apps": [],
            "memories": [],
            "reminders": [],
            "automations": {"enabled": {}, "last_run": {}, "activity": []},
        }
        pet.history = []
        pet.auto_speech_var = FakeVariable(True)
        pet.observe_apps_var = FakeVariable(True)
        pet.auto_sit_var = FakeVariable(False)
        pet.peekaboo_var = FakeVariable(False)
        pet.focus_mode = "idle"
        pet.ai_request_active = False
        pet.dragging = False
        pet._set_nova_window_icon = lambda window: window
        pet._activate_panel = mock.Mock()
        pet._refresh_automation_activity = mock.Mock()
        FakeWidget.instances.clear()

        ui_modules = (
            preferences_ui,
            preferences_ai_ui,
            preferences_apps_ui,
            preferences_automation_ui,
            preferences_behavior_ui,
            preferences_common_ui,
            preferences_computer_ui,
            preferences_memory_ui,
        )
        with ExitStack() as stack:
            for module in ui_modules:
                stack.enter_context(mock.patch.object(module, "tk", FakeTk()))
                if hasattr(module, "ttk"):
                    stack.enter_context(mock.patch.object(module, "ttk", FakeTtk()))
            stack.enter_context(mock.patch.object(preferences_ui, "make_header"))
            pet.open_autonomy_settings("routine")

        self.assertGreaterEqual(
            pet._automation_status_labels.keys(), {"low_battery_alert"}
        )
        pet._refresh_automation_activity.assert_called_once_with()
        focus_button = next(
            widget for widget in FakeWidget.instances
            if widget.options.get("text") == "Iniciar foco"
        )
        focus_status = next(
            widget.options["textvariable"] for widget in FakeWidget.instances
            if widget.options.get("textvariable")
            and widget.options["textvariable"].get()
            == "Ao terminar, ela avisa para você fazer uma pausa."
        )
        pet.focus_mode = "focus"
        focus_button.options["command"]()
        self.assertEqual(
            focus_status.get(),
            "Não consigo iniciar outra sessão enquanto estou ocupada.",
        )


if __name__ == "__main__":
    unittest.main()
