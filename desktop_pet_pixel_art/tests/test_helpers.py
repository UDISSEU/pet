import json
import ast
import queue
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import MOVEMENTS_DIR, MOVEMENT_VIDEOS, SYSTEM_PROMPT, resolve_movement_path
from autonomy import (
    find_installed_apps,
    is_quiet_now,
    load_settings,
    resolve_app_command,
    save_settings,
    valid_reminder_time,
)
import desktop_pet
from desktop_pet import DesktopPet
import ollama_client
from ollama_client import ask_local_ai, load_history, save_history
from x11_helper import X11Helper


def run_thread_immediately(*, target, args, daemon):
    thread = mock.Mock()
    thread.start.side_effect = lambda: target(*args)
    return thread


class TestHelperModules(unittest.TestCase):
    def test_main_block_resolves_path_without_creating_the_pet_ui(self):
        tree = ast.parse((SRC / "desktop_pet.py").read_text(encoding="utf-8"))
        main_block = next(
            node for node in tree.body
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Name)
            and node.test.left.id == "__name__"
        )
        namespace = dict(desktop_pet.__dict__)
        namespace["__name__"] = "__main__"
        pet_class = mock.Mock()
        namespace["DesktopPet"] = pet_class
        with tempfile.TemporaryDirectory() as tmpdir, \
             mock.patch.object(Path, "home", return_value=Path(tmpdir)), \
             mock.patch.object(desktop_pet.logging, "basicConfig"), \
             mock.patch.object(desktop_pet.logging, "FileHandler"):
            exec(compile(ast.Module(body=[main_block], type_ignores=[]), str(SRC / "desktop_pet.py"), "exec"), namespace)
        pet_class.return_value.run.assert_called_once()

    def test_maintenance_subprocesses_use_the_filtered_environment(self):
        tree = ast.parse((SRC / "desktop_pet.py").read_text(encoding="utf-8"))
        functions = {
            node.name: node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for function_name in ("run_maintenance", "preview_autoremove"):
            with self.subTest(function=function_name):
                calls = [
                    node for node in ast.walk(functions[function_name])
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "subprocess"
                    and node.func.attr == "run"
                ]
                self.assertEqual(len(calls), 1)
                env_arg = next(keyword.value for keyword in calls[0].keywords if keyword.arg == "env")
                self.assertIsInstance(env_arg, ast.Call)
                self.assertIsInstance(env_arg.func, ast.Attribute)
                self.assertEqual(env_arg.func.attr, "_child_process_env")

    def test_missing_pillow_or_opencv_shows_installer_hint_without_traceback(self):
        script = '''
import builtins, runpy, sys
sys.path.insert(0, sys.argv[1])
missing = sys.argv[2]
original_import = builtins.__import__
def import_without_dependency(name, *args, **kwargs):
    if name == missing:
        raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)
    return original_import(name, *args, **kwargs)
builtins.__import__ = import_without_dependency
try:
    runpy.run_path(sys.argv[3], run_name="__main__")
except SystemExit as exc:
    raise SystemExit(exc.code)
'''
        for missing, label in (("cv2", "OpenCV"), ("PIL", "Pillow"), ("numpy", "NumPy")):
            with self.subTest(dependency=label):
                result = desktop_pet.subprocess.run(
                    [sys.executable, "-c", script, str(SRC), missing, str(SRC / "desktop_pet.py")],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn(label, result.stderr)
                self.assertIn("./install.sh", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_autonomy_settings_round_trip_and_recover_invalid_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            settings = load_settings(path)
            settings["mode"] = "proativa"
            settings["memories"] = ["Prefere respostas curtas"]
            settings["apps"] = [
                {"name": "Editor", "command": "editor"},
                {
                    "name": "Google Chrome",
                    "command": "google-chrome-stable",
                    "desktop_file": "/usr/share/applications/google-chrome.desktop",
                },
                {"name": 42, "command": ""},
            ]
            self.assertTrue(save_settings(settings, path))
            self.assertEqual(load_settings(path)["memories"], ["Prefere respostas curtas"])
            self.assertEqual(load_settings(path)["apps"], [
                {"name": "Editor", "command": "editor"},
                {
                    "name": "Google Chrome",
                    "command": "google-chrome-stable",
                    "desktop_file": "/usr/share/applications/google-chrome.desktop",
                },
            ])
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_settings(path)["mode"], "companhia")

    def test_settings_trim_and_deduplicate_memories_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text(json.dumps({"memories": [
                " Prefere respostas curtas ", "prefere respostas curtas",
                "Tem um gato", "", None,
            ]}), encoding="utf-8")

            self.assertEqual(
                load_settings(path)["memories"],
                ["Prefere respostas curtas", "Tem um gato"],
            )

    def test_focus_and_routine_settings_are_sanitized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            path.write_text(
                json.dumps({"focus_minutes": 999, "break_minutes": 0, "evening_time": "25:99"}),
                encoding="utf-8",
            )
            settings = load_settings(path)
        self.assertEqual(settings["focus_minutes"], 180)
        self.assertEqual(settings["break_minutes"], 1)
        self.assertEqual(settings["evening_time"], "20:30")

    def test_quiet_hours_support_daytime_and_overnight_ranges(self):
        self.assertTrue(is_quiet_now("09:00", "17:00", datetime(2026, 1, 1, 12, 0)))
        self.assertFalse(is_quiet_now("09:00", "17:00", datetime(2026, 1, 1, 18, 0)))
        self.assertTrue(is_quiet_now("22:00", "08:00", datetime(2026, 1, 1, 23, 0)))
        self.assertTrue(is_quiet_now("22:00", "08:00", datetime(2026, 1, 1, 7, 0)))
        self.assertFalse(is_quiet_now("22:00", "08:00", datetime(2026, 1, 1, 12, 0)))

    def test_reminder_time_parser_rejects_invalid_dates(self):
        self.assertIsNotNone(valid_reminder_time("2026-12-31T23:59"))
        self.assertIsNone(valid_reminder_time("tomorrow"))

    def test_registered_app_matching_requires_an_opening_intent(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.settings = {"apps": [{"name": "Editor", "command": "editor"}]}
        self.assertEqual(pet._matching_app("abrir Editor"), pet.settings["apps"][0])
        self.assertIsNone(pet._matching_app("o Editor está aberto"))

    def test_app_open_target_accepts_polite_imperative_prefixes(self):
        firefox = {"name": "Firefox", "command": "firefox"}
        pet = DesktopPet.__new__(DesktopPet)
        pet.settings = {"apps": [firefox]}
        for request in (
            "Inicie o Firefox",
            "Quero abrir o Firefox",
            "Consegue abrir o firefox?",
            "Execute o Firefox",
            "Você pode abrir o Firefox",
            "voce pode abrir o Firefox",
            "Preciso abrir o Firefox",
            "Gostaria de abrir o Firefox",
        ):
            with self.subTest(request=request):
                self.assertEqual(pet._matching_app(request), firefox)
        for question in ("como abrir o Firefox?", "qual app abre o Firefox?"):
            with self.subTest(question=question):
                self.assertIsNone(pet._matching_app(question))

    def test_app_open_intent_recognizes_portuguese_verb_forms_case_insensitively(self):
        app = {
            "name": "Sober",
            "command": "sober",
            "desktop_file": "/apps/sober.desktop",
        }
        pet = DesktopPet.__new__(DesktopPet)
        pet.settings = {"apps": [app]}

        for request in (
            "Abra Sober",
            "ABRA Sober",
            "executar Sober",
            "Executa Sober",
            "pode abrir Sober",
            "poderia por favor, iniciar Sober",
        ):
            with self.subTest(request=request):
                self.assertTrue(DesktopPet._is_app_open_request(request))
                self.assertEqual(pet._matching_app(request), app)
        for question in (
            "como executar Sober?", "qual app abre Sober?", "por que iniciar Sober?",
            "o que executar Sober?", "quando abrir Sober?",
        ):
            with self.subTest(question=question):
                self.assertFalse(DesktopPet._is_app_open_request(question))
                self.assertIsNone(pet._matching_app(question))

    def test_registered_app_matching_accepts_google_alias_and_avoids_ambiguity(self):
        pet = DesktopPet.__new__(DesktopPet)
        google_chrome = {
            "name": "Google Chrome",
            "command": "google-chrome",
            "desktop_file": "/apps/google-chrome.desktop",
        }
        pet.settings = {"apps": [google_chrome]}

        self.assertEqual(pet._matching_app("pode abrir o Google?"), google_chrome)
        self.assertEqual(pet._matching_app("abra o Chrome"), google_chrome)

        google_drive = {
            "name": "Google Drive",
            "command": "google-drive",
            "desktop_file": "/apps/google-drive.desktop",
        }
        pet.settings["apps"].append(google_drive)
        self.assertIsNone(pet._matching_app("abrir Google"))
        self.assertEqual(pet._matching_app("abrir Google Chrome"), google_chrome)

    def test_conversation_routes_open_app_request_to_saved_command(self):
        pet = DesktopPet.__new__(DesktopPet)
        app = {"name": "Google", "command": "browser --new-window https://google.com"}
        pet.settings = {"apps": [app]}
        pet.ai_request_active = False
        pet._ask_question = mock.Mock(return_value="Abra o Google")
        pet._confirm_open_app = mock.Mock()

        pet.ask_menu()

        pet._confirm_open_app.assert_called_once_with("Abra o Google", app)

    def test_google_request_runs_saved_command_without_confirmation_when_disabled(self):
        pet = DesktopPet.__new__(DesktopPet)
        app = {"name": "Google Chrome", "command": "google-chrome --new-window"}
        pet.settings = {"apps": [app], "confirm_app_launch": False}
        pet.ai_request_active = False
        pet._app_launch_results = queue.Queue()
        pet._closing = False
        pet._ask_question = mock.Mock(return_value="Pode abrir o Google?")
        pet._record_local_interaction = mock.Mock(return_value="Aberto!")
        pet.show_bubble = mock.Mock()

        with mock.patch.object(desktop_pet, "messagebox") as messagebox, \
             mock.patch.object(desktop_pet, "find_installed_apps", return_value=[]), \
             mock.patch.object(desktop_pet, "resolve_app_command", return_value=["fake-browser", "--new-window"]) as resolve, \
             mock.patch.object(desktop_pet.subprocess, "Popen") as popen, \
             mock.patch.object(desktop_pet.threading, "Thread", side_effect=run_thread_immediately):
            pet.ask_menu()
            pet._drain_app_launch_results()

        messagebox.askyesno.assert_not_called()
        resolve.assert_called_once_with(app["command"])
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["fake-browser", "--new-window"])
        self.assertEqual(popen.call_args.kwargs["close_fds"], True)
        self.assertFalse(any(key.endswith("_API_KEY") for key in popen.call_args.kwargs["env"]))
        pet._record_local_interaction.assert_called_once_with(
            "Pode abrir o Google?", "Aberto!"
        )

    def test_legacy_saved_app_recovers_its_desktop_launcher_by_exact_name(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.settings = {"apps": [{"name": "Calculadora", "command": "old-calculator"}]}
        pet._installed_apps_cache = None
        system_app = {
            "name": "Calculadora",
            "command": "calculator",
            "desktop_file": "/apps/calculator.desktop",
        }

        with mock.patch.object(desktop_pet, "find_installed_apps", return_value=[system_app]):
            match = pet._matching_app("Abra a Calculadora")

        self.assertEqual(match["command"], "old-calculator")
        self.assertEqual(match["desktop_file"], "/apps/calculator.desktop")

    def test_conversation_opens_an_installed_app_not_yet_saved(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.settings = {
            "apps": [{"name": "Sober", "command": "sober"}],
            "confirm_app_launch": False,
        }
        pet._installed_apps_cache = None
        pet.ai_request_active = False
        pet._app_launch_results = queue.Queue()
        pet._closing = False
        pet._ask_question = mock.Mock(return_value="Abra a Calculadora")
        pet._record_local_interaction = mock.Mock(return_value="Aberto!")
        pet.show_bubble = mock.Mock()
        installed_calculator = {
            "name": "Calculadora",
            "command": "calculator",
            "desktop_file": "/apps/calculator.desktop",
        }

        with mock.patch.object(desktop_pet, "find_installed_apps", return_value=[installed_calculator]), \
             mock.patch.object(
                 desktop_pet.subprocess,
                 "run",
                 return_value=mock.Mock(returncode=0, stderr="", stdout=""),
             ) as run, \
             mock.patch.object(desktop_pet.threading, "Thread", side_effect=run_thread_immediately):
            pet.ask_menu()
            pet._drain_app_launch_results()

        run.assert_called_once_with(
            ["gio", "launch", "/apps/calculator.desktop"],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            env=mock.ANY,
        )
        self.assertFalse(any(key.endswith("_API_KEY") for key in run.call_args.kwargs["env"]))
        pet._record_local_interaction.assert_called_once_with(
            "Abra a Calculadora", "Aberto!"
        )

    def test_imperative_opens_saved_app_instead_of_ai(self):
        pet = DesktopPet.__new__(DesktopPet)
        app = {"name": "Sober", "command": "sober"}
        pet.settings = {"apps": [app], "confirm_app_launch": False}
        pet._installed_apps_cache = None
        pet.ai_request_active = False
        pet._ask_question = mock.Mock(return_value="Abra Sober")
        pet._app_launch_results = queue.Queue()
        pet._closing = False
        pet._record_local_interaction = mock.Mock(return_value="Aberto!")
        pet.show_bubble = mock.Mock()

        with mock.patch.object(desktop_pet, "find_installed_apps", return_value=[]), \
             mock.patch.object(desktop_pet, "resolve_app_command", return_value=["fake-sober"]), \
             mock.patch.object(desktop_pet.subprocess, "Popen") as popen, \
             mock.patch.object(desktop_pet.threading, "Thread", side_effect=run_thread_immediately) as worker_thread:
            pet.ask_menu()
            pet._drain_app_launch_results()

        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], ["fake-sober"])
        self.assertFalse(any(key.endswith("_API_KEY") for key in popen.call_args.kwargs["env"]))
        worker_thread.assert_called_once()
        self.assertEqual(
            worker_thread.call_args.kwargs["target"], pet._app_launch_worker
        )

    def test_google_alias_opens_google_page_through_chrome_desktop_entry(self):
        app = {
            "name": "Google Chrome",
            "command": "/usr/bin/google-chrome-stable",
            "desktop_file": "/usr/share/applications/google-chrome.desktop",
        }
        with mock.patch.object(
            desktop_pet.subprocess,
            "run",
            return_value=mock.Mock(returncode=0, stderr="", stdout=""),
        ) as run:
            DesktopPet._launch_app(app, "Abra o Google")

        self.assertEqual(run.call_args.args[0], [
            "gio",
            "launch",
            "/usr/share/applications/google-chrome.desktop",
            "https://www.google.com",
        ])

    def test_failed_desktop_launch_reports_failure_instead_of_success(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.settings = {"confirm_app_launch": False}
        pet._app_launch_results = queue.Queue()
        pet._closing = False
        pet._record_local_interaction = mock.Mock(side_effect=lambda _q, answer: answer)
        pet.show_bubble = mock.Mock()
        app = {
            "name": "Example App",
            "command": "example-app",
            "desktop_file": "/apps/example.desktop",
        }

        with mock.patch.object(
            desktop_pet.subprocess,
            "run",
            return_value=mock.Mock(returncode=1, stderr="launcher failed", stdout=""),
        ), mock.patch.object(desktop_pet.threading, "Thread", side_effect=run_thread_immediately):
            pet._confirm_open_app("Abra Example App", app)
            pet._drain_app_launch_results()

        answer = pet._record_local_interaction.call_args.args[1]
        self.assertIn("Não consegui abrir Example App", answer)
        self.assertIn("launcher failed", answer)
        self.assertEqual(pet.show_bubble.call_args.args[0], answer)

    def test_slow_desktop_launch_is_reported_as_still_in_progress(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._app_launch_results = queue.Queue()
        app = {"name": "Example App", "command": "example-app"}
        pet._launch_app = mock.Mock(
            side_effect=desktop_pet.subprocess.TimeoutExpired("gio launch", 60)
        )

        pet._app_launch_worker("Abra Example App", app)

        question, answer = pet._app_launch_results.get_nowait()
        self.assertEqual(question, "Abra Example App")
        self.assertEqual(answer, "A abertura de Example App ainda está em andamento.")

    def test_programming_questions_with_open_verbs_fall_through_to_ai(self):
        cases = (
            ("como executar um script Python?", [{"name": "Python IDLE", "command": "idle"}], []),
            ("como abrir um arquivo html no Firefox?", [], [{
                "name": "Firefox", "command": "firefox", "desktop_file": "/apps/firefox.desktop",
            }]),
            ("executa o código", [], []),
            ("executar sql", [], []),
            ("executar teste", [], []),
            ("iniciar projeto", [], []),
        )
        for question, saved_apps, installed_apps in cases:
            with self.subTest(question=question):
                pet = DesktopPet.__new__(DesktopPet)
                pet.settings = {"apps": saved_apps, "memories": []}
                pet._installed_apps_cache = None
                pet.ai_request_active = False
                pet.history = []
                pet._ask_question = mock.Mock(return_value=question)
                pet.show_bubble = mock.Mock()
                with mock.patch.object(desktop_pet, "find_installed_apps", return_value=installed_apps), \
                     mock.patch.object(desktop_pet.threading, "Thread") as thread:
                    pet.ask_menu()
                thread.assert_called_once()
                self.assertEqual(thread.call_args.kwargs["target"], pet._ask_worker)

    def test_imperative_firefox_command_matches_installed_app(self):
        pet = DesktopPet.__new__(DesktopPet)
        firefox = {
            "name": "Firefox", "command": "firefox", "desktop_file": "/apps/firefox.desktop",
        }
        pet.settings = {"apps": []}
        pet._installed_apps_cache = None
        pet.ai_request_active = False
        pet._ask_question = mock.Mock(return_value="abre o firefox")
        pet._confirm_open_app = mock.Mock()
        with mock.patch.object(desktop_pet, "find_installed_apps", return_value=[firefox]):
            pet.ask_menu()
        pet._confirm_open_app.assert_called_once_with("abre o firefox", firefox)

    def test_unmatched_short_imperative_open_app_request_does_not_fall_through_to_ai(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.settings = {"apps": []}
        pet.ai_request_active = False
        pet._ask_question = mock.Mock(return_value="Abra o Paint")
        pet._record_local_interaction = mock.Mock(side_effect=lambda _q, answer: answer)
        pet.show_bubble = mock.Mock()

        with mock.patch.object(desktop_pet.threading, "Thread") as thread:
            pet.ask_menu()

        thread.assert_not_called()
        answer = pet._record_local_interaction.call_args.args[1]
        self.assertIn("Cadastre-o na aba Aplicativos", answer)
        self.assertIn("Se era uma pergunta, comece com 'como...'", answer)
        pet.show_bubble.assert_called_once_with(answer)

    def test_confirmation_setting_defaults_to_confirmation_and_is_sanitized(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            self.assertTrue(load_settings(path)["confirm_app_launch"])
            path.write_text(json.dumps({"confirm_app_launch": "true"}), encoding="utf-8")
            self.assertTrue(load_settings(path)["confirm_app_launch"])

    def test_app_command_parser_checks_executable_without_using_a_shell(self):
        command = f'"{sys.executable}" --version'
        self.assertEqual(resolve_app_command(command), [sys.executable, "--version"])
        with self.assertRaisesRegex(ValueError, "Não encontrei o executável"):
            resolve_app_command("aplicativo-que-nao-existe-123")
        with self.assertRaisesRegex(ValueError, "caractere inválido"):
            resolve_app_command("programa\x00 --flag")

    def test_installed_app_search_reads_desktop_entries_and_filters_hidden_apps(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            apps_dir = Path(tmpdir) / "applications"
            apps_dir.mkdir()
            (apps_dir / "sample.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Sample Editor\n"
                "GenericName=Text Editor\n"
                f'Exec="{sys.executable}" --new-window %U\n',
                encoding="utf-8",
            )
            (apps_dir / "hidden.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Hidden App\n"
                "Exec=python3\nNoDisplay=true\n",
                encoding="utf-8",
            )

            results = find_installed_apps("text", [apps_dir])

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Sample Editor")
        self.assertEqual(resolve_app_command(results[0]["command"]), [sys.executable, "--new-window"])


    def test_system_prompt_uses_nova_name(self):
        self.assertIn("Você é Nova", SYSTEM_PROMPT)

    def test_resolve_movement_path_finds_idle_video(self):
        filename = MOVEMENT_VIDEOS["idle"]
        resolved = resolve_movement_path(filename)
        self.assertTrue(resolved.exists())
        self.assertEqual(resolved, MOVEMENTS_DIR / filename)

    def test_video_selection_matches_pet_state_and_direction(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._irritated_until = 0
        pet.busy = False
        pet.walk_dx = 1
        pet.stay_in_place_var = mock.Mock()
        pet.stay_in_place_var.get.return_value = False

        cases = (
            ("walking right", "walk", "walk_right", 1, False, 0),
            ("walking left", "walk", "walk_left", -1, False, 0),
            ("busy", "walk", "wave", 1, True, 0),
            ("irritated while busy", "walk", "angry", 1, True, 2),
            ("sitting", "sitting", "sleep", 1, False, 0),
            ("thinking", "thinking", "thinking", 1, False, 0),
            ("held", "held", "idle", 1, False, 0),
            ("unknown state", "unknown", "idle", 1, False, 0),
        )
        for label, state, expected, direction, busy, irritated_until in cases:
            with self.subTest(state=label):
                pet.state = state
                pet.walk_dx = direction
                pet.busy = busy
                pet._irritated_until = irritated_until
                self.assertEqual(pet._video_for_current_pose(now=1), expected)

    def test_staying_in_place_uses_idle_pose(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.state = "walk"
        pet.busy = False
        pet.walk_dx = 1
        pet._irritated_until = 0
        pet.stay_in_place_var = mock.Mock()
        pet.stay_in_place_var.get.return_value = True

        self.assertEqual(pet._video_for_current_pose(now=1), "idle")

    def test_question_dialog_is_placed_to_the_right_when_there_is_room(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.x = 100
        pet.y = 200
        pet.cur_height = 190
        pet.screen_w = 1200
        pet.screen_h = 800

        x, y, width, height = pet._question_dialog_geometry()

        self.assertEqual((x, width, height), (248, 420, 230))
        self.assertEqual(y, 180)
        self.assertGreaterEqual(x, pet.x + 140 + 8)

    def test_question_dialog_uses_left_side_at_right_screen_edge(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.x = 1000
        pet.y = 700
        pet.cur_height = 190
        pet.screen_w = 1200
        pet.screen_h = 800

        x, y, width, height = pet._question_dialog_geometry()

        self.assertEqual((x, width, height), (572, 420, 230))
        self.assertEqual(y, 570)
        self.assertLessEqual(x + width, pet.x - 8)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(y + height, pet.screen_h)

    def test_staying_in_place_prevents_movement(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._last_tick_at = 10.0
        pet.animation_time_ms = 0.0
        pet.step = 0
        pet._logic_accumulator = 0.0
        pet.dragging = False
        pet.drag_tilt = 0.0
        pet.drag_target_tilt = 0.0
        pet.state = "walk"
        pet.busy = False
        pet.stay_in_place_var = mock.Mock()
        pet.stay_in_place_var.get.return_value = True
        pet.walk_dx = 1
        pet.walk_dy = 0
        pet._next_walk_direction_change_at = 100.0
        pet.x = 50.0
        pet.y = 75.0
        pet.screen_w = 800
        pet.screen_h = 600
        pet.cur_height = 190
        pet._window_x = 50
        pet._window_y = 75
        pet._irritated_started_at = 0.0
        pet._irritated_until = 0.0
        pet.sit_win_id = None
        pet.behind_mode = False
        pet._next_tick_at = 10.016
        pet.root = mock.Mock()
        pet.render_and_show = mock.Mock()

        with mock.patch("desktop_pet.time.monotonic", return_value=10.04):
            pet.tick()

        self.assertEqual((pet.x, pet.y), (50.0, 75.0))
        pet.root.geometry.assert_not_called()

    def test_focus_cycle_uses_rest_pose_then_celebrates_and_returns_to_walking(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.focus_mode = "idle"
        pet.focus_goal = ""
        pet.focus_minutes = 25
        pet.break_minutes = 5
        pet._focus_job = None
        pet._closing = False
        pet.ai_request_active = False
        pet.dragging = False
        pet.state = "walk"
        pet.sit_win_id = 123
        pet.root = mock.Mock()
        pet.show_bubble = mock.Mock()

        self.assertTrue(pet.start_focus("Estudar Python", 5, 1))
        self.assertEqual((pet.focus_mode, pet.state, pet.sit_win_id), ("focus", "focused", None))
        pet.finish_focus()
        self.assertEqual((pet.focus_mode, pet.state), ("break", "sitting"))
        pet.finish_break()
        self.assertEqual((pet.focus_mode, pet.state, pet.focus_goal), ("idle", "celebrating", ""))
        self.assertEqual(pet._video_for_current_pose(), "celebrate")
        pet.finish_celebration()
        self.assertEqual((pet.focus_mode, pet.state, pet.focus_goal), ("idle", "walk", ""))

    def test_history_handles_invalid_and_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            path.write_text("{not valid json}", encoding="utf-8")
            self.assertEqual(load_history(path), [])

            history = [{"role": "user", "content": "Oi"}]
            self.assertTrue(save_history(history, path))
            self.assertEqual(load_history(path), history)

    def test_history_rejects_invalid_shapes_and_filters_invalid_messages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "history.json"
            for invalid_json_value in ('{"role": "user"}', "42", "null"):
                with self.subTest(value=invalid_json_value):
                    path.write_text(invalid_json_value, encoding="utf-8")
                    self.assertEqual(load_history(path), [])

            path.write_text(
                json.dumps([
                    {"role": "user", "content": "Oi"},
                    {"role": "system", "content": "instrução"},
                    {"role": "assistant", "content": 42},
                    "mensagem inválida",
                ]),
                encoding="utf-8",
            )
            self.assertEqual(
                load_history(path),
                [{"role": "user", "content": "Oi"}],
            )

    def test_history_handles_missing_unreadable_files_and_save_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "missing.json"
            self.assertEqual(load_history(missing_path), [])

            unreadable_path = Path(tmpdir) / "unreadable.json"
            unreadable_path.write_text("[]", encoding="utf-8")
            with mock.patch.object(Path, "read_text", side_effect=OSError("sem acesso")):
                self.assertEqual(load_history(unreadable_path), [])

            invalid_save_path = Path(tmpdir) / "missing" / "history.json"
            with self.assertLogs(ollama_client.logger, level="WARNING"):
                self.assertFalse(save_history([], invalid_save_path))

    def test_ask_local_ai_parses_successful_response(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": "  Olá!  "}}
        ).encode("utf-8")
        with mock.patch("ollama_client.urllib.request.urlopen", return_value=response) as urlopen:
            answer = ask_local_ai([{"role": "user", "content": "Oi"}])

        self.assertEqual(answer, "Olá!")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 60)

    def test_ask_local_ai_includes_user_selected_memories_in_system_context(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"message": {"content": "Certo."}}
        ).encode("utf-8")
        with mock.patch("ollama_client.urllib.request.urlopen", return_value=response) as urlopen:
            ask_local_ai([], memories=["Prefere respostas curtas"])
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertIn("Prefere respostas curtas", payload["messages"][0]["content"])

    def test_ask_local_ai_explains_connection_errors(self):
        with mock.patch(
            "ollama_client.urllib.request.urlopen",
            side_effect=ollama_client.urllib.error.URLError("offline"),
        ):
            answer = ask_local_ai([], model_name="modelo-teste")

        self.assertIn("Ollama", answer)
        self.assertIn("modelo-teste", answer)

    def test_x11_helper_is_safe_when_optional_dependency_is_unavailable(self):
        with mock.patch("x11_helper.XLIB_AVAILABLE", False):
            helper = X11Helper()

        self.assertFalse(helper.ok)
        self.assertEqual(helper.get_open_windows(), [])
        self.assertIsNone(helper.get_active_window_info())
        self.assertFalse(helper.window_exists(0))

    def test_x11_helper_returns_safe_values_when_display_is_unavailable(self):
        with mock.patch("x11_helper.XLIB_AVAILABLE", True), mock.patch(
            "x11_helper.xlib_display.Display", side_effect=OSError("sem display")
        ):
            helper = X11Helper()

        self.assertFalse(helper.ok)
        self.assertEqual(helper.get_open_windows(), [])
        self.assertIsNone(helper.get_active_window_info())
        self.assertFalse(helper.window_exists(0))


if __name__ == "__main__":
    unittest.main()
