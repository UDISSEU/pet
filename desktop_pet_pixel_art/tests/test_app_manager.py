"""Command safety and installed-app operation tests; never touch real packages."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from app_manager import (
    build_uninstall_command, build_update_all_commands, build_update_command,
    display_location, open_installed_application, preview_uninstall,
    resolve_executable,
)


class AppManagerTests(unittest.TestCase):
    def test_builds_manager_specific_update_and_remove_commands(self):
        apt = {"source": "APT/DEB", "package": "org-example:amd64"}
        flatpak = {"source": "Flatpak", "package": "org.example.Editor"}
        snap = {"source": "Snap", "package": "text-editor"}
        self.assertEqual(build_update_command(apt)[:2], ["pkexec", "apt-get"])
        self.assertIn("--only-upgrade", build_update_command(apt))
        self.assertEqual(build_update_command(flatpak)[0], "flatpak")
        self.assertEqual(build_update_command(snap), ["pkexec", "snap", "refresh", "text-editor"])
        self.assertIn("--no-related", build_uninstall_command(flatpak))
        self.assertEqual(build_uninstall_command(snap)[-1], "text-editor")
        grouped = build_update_all_commands([apt, flatpak, snap])
        self.assertEqual(len(grouped), 3)
        self.assertTrue(all("sudo" not in command for command in grouped))

    def test_rejects_untrusted_or_unmanaged_package_identifiers(self):
        for app in (
            {"source": "APT/DEB", "package": "editor; rm -rf /"},
            {"source": "Flatpak", "package": "org.example.App --delete-data"},
            {"source": "AppImage", "package": "/home/user/App.AppImage"},
        ):
            with self.subTest(app=app), self.assertRaises(ValueError):
                build_uninstall_command(app)
        with self.assertRaises(ValueError):
            build_update_all_commands([
                {"source": "APT/DEB", "package": "safe"},
                {"source": "Manual/outro", "package": "—"},
            ])

    def test_apt_removal_preview_reports_dependencies_without_privilege(self):
        result = SimpleNamespace(
            returncode=0, stdout="Remv app [1.0]\nRemv unused-lib [2.0]\n", stderr="",
        )
        run = mock.Mock(return_value=result)
        preview = preview_uninstall(
            {"source": "APT/DEB", "package": "app"}, run=run,
        )
        self.assertEqual(preview["packages"], ["app", "unused-lib"])
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["apt-get", "-s", "remove"])
        self.assertNotIn("pkexec", command)

    def test_open_uses_only_discovered_desktop_roots_or_validated_appimage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            applications = root / "applications"
            applications.mkdir()
            desktop = applications / "app.desktop"
            desktop.write_text("[Desktop Entry]\nName=Example\nExec=example\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {"XDG_DATA_HOME": str(root), "XDG_DATA_DIRS": ""}):
                popen = mock.Mock()
                open_installed_application(
                    {"source": "APT/DEB", "desktop_file": str(desktop)},
                    popen=popen, which=lambda name: "/usr/bin/gio" if name == "gio" else None,
                )
            self.assertEqual(popen.call_args.args[0], ["/usr/bin/gio", "launch", str(desktop)])
            outside = root / "outside.desktop"
            outside.touch()
            with self.assertRaises(ValueError):
                open_installed_application({"source": "Manual/outro", "desktop_file": str(outside)})

            appimage = root / "program.AppImage"
            appimage.write_text("payload", encoding="utf-8")
            appimage.chmod(0o700)
            app = {"source": "AppImage", "package": str(appimage)}
            self.assertEqual(resolve_executable(app), str(appimage))
            self.assertEqual(display_location(app), str(appimage))
            appimage.unlink()
            with self.assertRaises(ValueError):
                open_installed_application(app)


if __name__ == "__main__":
    unittest.main()
