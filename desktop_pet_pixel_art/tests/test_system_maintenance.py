import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_pet import DesktopPet
from system_maintenance import (
    parse_removable_packages,
    parse_upgradable_packages,
    run_commands,
)


class TestSystemMaintenance(unittest.TestCase):
    def test_parses_upgradable_package_rows_and_ignores_summary_lines(self):
        output = (
            "Listing... Done\n"
            "firefox/stable 128.0 amd64 [upgradable from: 127.0]\n"
            "2 packages can be upgraded. Run 'apt list --upgradable' to see them.\n"
        )
        self.assertEqual(
            parse_upgradable_packages(output),
            [("firefox", "127.0", "128.0")],
        )

    def test_parses_simulated_removals(self):
        output = "Remv old-editor [1.2]\nPurg old-plugin [2.0]\nConf retained [1.0]\n"
        self.assertEqual(
            parse_removable_packages(output),
            [
                ("old-editor", "1.2", "Será removido"),
                ("old-plugin", "2.0", "Será removido"),
            ],
        )

    @patch("system_maintenance.subprocess.run")
    def test_command_runner_stops_after_first_failure(self, run):
        run.return_value = Mock(returncode=1, stdout="", stderr="APT falhou")
        output, error = run_commands([["apt-get", "update"], ["apt", "upgrade"]], env={})
        self.assertEqual((output, error), ("APT falhou", "APT falhou"))
        run.assert_called_once()

    @patch("system_maintenance.subprocess.run")
    def test_command_runner_reports_timeout(self, run):
        import subprocess

        run.side_effect = subprocess.TimeoutExpired(["apt-get", "update"], 1)
        self.assertEqual(
            run_commands([["apt-get", "update"]], env={}, timeout=1),
            ("", "A operação demorou demais e foi interrompida."),
        )

    def test_closing_preferences_releases_its_canvas_references(self):
        pet = DesktopPet.__new__(DesktopPet)
        canvas = object()
        key = str(canvas)
        pet._preferences_scroll_canvases = {key: canvas}
        window = object()
        pet._release_preferences_canvases(SimpleNamespace(widget=window), window, [canvas])
        self.assertEqual(pet._preferences_scroll_canvases, {})

    def test_destroy_events_from_child_widgets_do_not_release_other_canvases(self):
        pet = DesktopPet.__new__(DesktopPet)
        canvas = object()
        key = str(canvas)
        pet._preferences_scroll_canvases = {key: canvas}
        window = object()
        pet._release_preferences_canvases(SimpleNamespace(widget=object()), window, [canvas])
        self.assertEqual(pet._preferences_scroll_canvases, {key: canvas})


if __name__ == "__main__":
    unittest.main()
