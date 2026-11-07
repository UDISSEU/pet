import json
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

from personality import SPEECH_POOLS
from autonomy import (
    find_installed_apps,
    is_quiet_now,
    load_settings,
    resolve_app_command,
    save_settings,
    valid_reminder_time,
)
import desktop_pet
import desktop_pet_ui
import json_persistence
from desktop_pet import DesktopPet


def run_thread_immediately(*, target, args, daemon):
    thread = mock.Mock()
    thread.start.side_effect = lambda: target(*args)
    return thread


def prepare_app_result_pet(pet):
    pet.busy = False
    pet._speech_history = []
    pet.root = mock.Mock()
    pet._interaction_speech_allowed = mock.Mock(return_value=True)


class DesktopAppTests(unittest.TestCase):
    def test_panel_back_returns_to_the_main_menu_when_history_is_empty(self):
        from types import SimpleNamespace

        class Window:
            _nova_back_in_progress = False

            def winfo_exists(self):
                return True

            def destroy(self):
                self.destroyed = True

        pet = DesktopPet.__new__(DesktopPet)
        pet._last_menu_position = (410, 260)
        pet.show_menu = mock.Mock()
        window = Window()

        pet._panel_back(window)

        self.assertTrue(window.destroyed)
        event = pet.show_menu.call_args.args[0]
        self.assertIsInstance(event, SimpleNamespace)
        self.assertEqual((event.x_root, event.y_root), (410, 260))

    def test_panel_back_restores_the_same_previous_window(self):
        class Window:
            _nova_back_in_progress = False

            def __init__(self):
                self.destroyed = False
                self.restored = []

            def winfo_exists(self):
                return not self.destroyed

            def destroy(self):
                self.destroyed = True

            def deiconify(self):
                self.restored.append("shown")

            def lift(self):
                self.restored.append("lifted")

            def focus_set(self):
                self.restored.append("focused")

        pet = DesktopPet.__new__(DesktopPet)
        current, previous = Window(), Window()
        pet._active_panel_window = current
        pet._panel_history = [previous]

        pet._panel_back(current)

        self.assertTrue(current.destroyed)
        self.assertEqual(previous.restored, ["shown", "lifted", "focused"])
        self.assertIs(pet._active_panel_window, previous)

    def test_calendar_ui_mixin_delegates_to_the_calendar_window(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.root = mock.sentinel.root
        with mock.patch.object(desktop_pet_ui, "open_calendar_window") as open_calendar:
            result = pet.show_calendar()
        open_calendar.assert_called_once_with(
            mock.sentinel.root,
            on_back=mock.ANY,
            on_open=pet._activate_panel,
        )
        self.assertIs(result, open_calendar.return_value)

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
            backups = list(Path(tmpdir).glob("settings.json.corrupt-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "not json")
            self.assertTrue(save_settings(load_settings(path), path))
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "not json")
    def test_stale_settings_save_does_not_clear_saved_user_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            settings = load_settings(path)
            settings["user_name"] = "Ada"
            self.assertTrue(save_settings(settings, path))

            stale_settings = load_settings(path)
            stale_settings["user_name"] = ""
            stale_settings["mode"] = "proativa"
            self.assertTrue(save_settings(stale_settings, path))

            saved = load_settings(path)
        self.assertEqual(saved["user_name"], "Ada")
        self.assertEqual(saved["mode"], "proativa")
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
    def test_settings_corruption_is_not_replaced_when_backup_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "settings.json"
            original = "not recoverable JSON"
            path.write_text(original, encoding="utf-8")
            with mock.patch(
                "json_persistence.shutil.copyfileobj",
                side_effect=OSError("backup unavailable"),
            ):
                self.assertEqual(load_settings(path)["mode"], "companhia")
                self.assertFalse(save_settings(load_settings(path), path))
            self.assertEqual(path.read_text(encoding="utf-8"), original)
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
    def test_app_open_target_accepts_nova_address_and_trailing_politeness(self):
        chrome = {"name": "Google Chrome", "command": "google-chrome"}
        installed = [chrome]
        for question in (
            "Nova, você consegue abrir o Chrome pra mim?",
            "Nova, abre Google Chrome por favor",
        ):
            with self.subTest(question=question):
                self.assertEqual(
                    desktop_pet.match_registered_app(question, [], lambda: installed),
                    chrome,
                )
    def test_app_matching_uses_desktop_generic_name(self):
        calculator = {
            "name": "GNOME Calculator",
            "generic_name": "Calculadora",
            "command": "gnome-calculator",
        }
        self.assertEqual(
            desktop_pet.match_registered_app(
                "Abre a Calculadora", [], lambda: [calculator]
            ),
            calculator,
        )
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
        app = {"name": "Spotify", "command": "spotify"}
        pet.settings = {"apps": [app]}
        pet._installed_apps_cache = []
        pet.ai_request_active = False
        pet._ask_question = mock.Mock(return_value="abri spotify")
        pet._confirm_open_app = mock.Mock()

        pet.ask_menu()

        pet._confirm_open_app.assert_called_once_with("abri spotify", app)
    def test_google_request_runs_saved_command_without_confirmation_when_disabled(self):
        pet = DesktopPet.__new__(DesktopPet)
        app = {"name": "Google Chrome", "command": "google-chrome --new-window"}
        pet.settings = {"apps": [app], "confirm_app_launch": False}
        pet.ai_request_active = False
        pet._app_launch_results = queue.Queue()
        pet._closing = False
        prepare_app_result_pet(pet)
        pet._record_interaction = mock.Mock()
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
        pet._record_local_interaction.assert_called_once()
        self.assertEqual(
            pet._record_local_interaction.call_args.args[0], "Pode abrir o Google?"
        )
        self.assertIn(
            pet._record_local_interaction.call_args.args[1],
            SPEECH_POOLS["app_launch_ok"],
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
        prepare_app_result_pet(pet)
        pet._record_interaction = mock.Mock()
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
        pet._record_local_interaction.assert_called_once()
        self.assertEqual(
            pet._record_local_interaction.call_args.args[0], "Abra a Calculadora"
        )
        self.assertIn(
            pet._record_local_interaction.call_args.args[1],
            SPEECH_POOLS["app_launch_ok"],
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
        prepare_app_result_pet(pet)
        pet._record_interaction = mock.Mock()
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
        prepare_app_result_pet(pet)
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
        self.assertIn("launcher failed", answer)
        self.assertIn("Não consegui abrir Example App", answer)
        self.assertEqual(pet.show_bubble.call_args.args[0], answer)
    def test_slow_desktop_launch_is_reported_as_still_in_progress(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet._app_launch_results = queue.Queue()
        app = {"name": "Example App", "command": "example-app"}
        pet._launch_app = mock.Mock(
            side_effect=desktop_pet.subprocess.TimeoutExpired("gio launch", 60)
        )

        pet._app_launch_worker("Abra Example App", app)

        question, success, answer = pet._app_launch_results.get_nowait()
        self.assertEqual(question, "Abra Example App")
        self.assertFalse(success)
        self.assertEqual(
            answer,
            "O sistema demorou demais para abrir Example App. Tente novamente.",
        )
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
                pet.profile_manager = mock.Mock()
                pet.profile_manager.active_profile.profile_id = "test-profile"
                pet.profile_manager.active_profile.name = "Test user"
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
        pet._record_interaction = mock.Mock()
        pet._speech_history = []
        pet._closing = False
        pet.root = mock.Mock()
        pet._interaction_speech_allowed = mock.Mock(return_value=True)
        pet.show_bubble = mock.Mock()

        with mock.patch.object(desktop_pet.threading, "Thread") as thread:
            pet.ask_menu()

        thread.assert_not_called()
        answer = pet._record_local_interaction.call_args.args[1]
        self.assertIn("Não encontrei", answer)
        self.assertIn("Preferências > Aplicativos", answer)
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
