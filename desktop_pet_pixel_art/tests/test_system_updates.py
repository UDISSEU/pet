import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from system_updates import (
    apt_upgrade_command,
    build_installed_app_inventory,
    display_package_name,
    estimate_remaining_seconds,
    flatpak_upgrade_command,
    InventoryLoadState,
    parse_apt_upgradable,
    parse_dpkg_query_owners,
    parse_dpkg_query_packages,
    find_installed_apt_applications,
    parse_flatpak_upgradable,
    parse_flatpak_installed,
    parse_package_activity,
    parse_snap_installed,
    parse_snap_upgradable,
    run_streaming_command,
    run_inventory_query,
    query_installed_app_sources,
    snap_upgrade_command,
    merge_inventory_after_partial_failure,
)


class AptUpdateParsingTests(unittest.TestCase):
    def fresh_apt_lists(self, directory):
        apt_lists = Path(directory) / "apt-lists"
        apt_lists.mkdir()
        (apt_lists / "index").touch()
        return apt_lists

    def test_inventory_query_failures_do_not_require_a_shell(self):
        output, error = run_inventory_query(
            [sys.executable, "-c", "print('available')"],
            timeout=5,
        )
        self.assertEqual(output.strip(), "available")
        self.assertIsNone(error)

        output, error = run_inventory_query(
            [sys.executable, "-c", "import sys; print('partial'); sys.exit(1)"],
            timeout=5,
            allow_partial=True,
        )
        self.assertEqual(output.strip(), "partial")
        self.assertIsNone(error)

        output, error = run_inventory_query(
            ["inventory-command-that-does-not-exist"],
            timeout=5,
        )
        self.assertEqual(output, "")
        self.assertTrue(error)

    def test_parses_multiple_packages_and_versions(self):
        output = """\
Listing...
apt-utils/noble-updates 2.8.4ubuntu0.1 amd64 [upgradable from: 2.8.3]
firefox/zena 160.0+linuxmint1 amd64 [upgradable from: 158.0.1+linuxmint1]
code/stable 1.147.0 amd64 [upgradable from: 1.146.0]
"""

        self.assertEqual(parse_apt_upgradable(output), [
            ("apt-utils", "2.8.3", "2.8.4ubuntu0.1"),
            ("firefox", "158.0.1+linuxmint1", "160.0+linuxmint1"),
            ("code", "1.146.0", "1.147.0"),
        ])

    def test_ignores_headers_warnings_and_non_update_lines(self):
        output = """\
WARNING: apt does not have a stable CLI interface.
Listing...
All packages are up to date.
"""

        self.assertEqual(parse_apt_upgradable(output), [])

    def test_accepts_package_architecture_qualifier(self):
        output = "libc6:amd64/noble-updates 2.39 amd64 [upgradable from: 2.38]"

        self.assertEqual(
            parse_apt_upgradable(output),
            [("libc6:amd64", "2.38", "2.39")],
        )

    def test_identifies_visual_studio_code_and_builds_targeted_upgrade(self):
        self.assertEqual(display_package_name("code"), "Visual Studio Code (code)")
        self.assertEqual(
            apt_upgrade_command("code"),
            [
                "pkexec", "apt-get", "-o", "Dpkg::Use-Pty=0",
                "install", "--only-upgrade", "-y", "code",
            ],
        )

    def test_rejects_invalid_package_name_for_targeted_upgrade(self):
        with self.assertRaises(ValueError):
            apt_upgrade_command("code; rm -rf /")

    def test_builds_alphabetical_inventory_from_apt_and_flatpak_apps(self):
        applications = [
            {"name": "Zeta Editor", "desktop_file": "/usr/share/applications/zeta.desktop"},
            {
                "name": "Spotify",
                "desktop_file": (
                    "/home/user/.local/share/flatpak/exports/share/applications/"
                    "com.spotify.Client.desktop"
                ),
            },
            {"name": "Visual Studio Code", "desktop_file": "/usr/share/applications/code.desktop"},
        ]
        package_versions = {"zeta-editor": "2.3.1", "code": "1.146.0"}
        package_owners = {
            "/usr/share/applications/zeta.desktop": "zeta-editor",
            "/usr/share/applications/code.desktop": "code",
        }
        flatpak = "com.spotify.Client\t1.2.95\tflathub\n"

        self.assertEqual(
            build_installed_app_inventory(
                applications, package_versions, package_owners, flatpak,
            ),
            [
                {
                    "name": "Spotify", "version": "1.2.95",
                    "origin": "Flatpak · flathub", "package": "com.spotify.Client",
                    "source": "Flatpak", "candidate_version": "—",
                    "update_status": "Verificação necessária",
                },
                {
                    "name": "Visual Studio Code", "version": "1.146.0",
                    "origin": "APT/DEB", "package": "code",
                    "source": "APT/DEB", "candidate_version": "—",
                    "update_status": "Verificação necessária",
                },
                {
                    "name": "Zeta Editor", "version": "2.3.1",
                    "origin": "APT/DEB", "package": "zeta-editor",
                    "source": "APT/DEB", "candidate_version": "—",
                    "update_status": "Verificação necessária",
                },
            ],
        )

    def test_inventory_removes_duplicate_menu_entries_for_same_application(self):
        applications = [
            {"name": "Backup Tool", "desktop_file": "/usr/share/applications/backup.desktop"},
            {"name": "Backup Tool", "desktop_file": "/usr/share/applications/mintbackup.desktop"},
        ]
        package_owners = {
            "/usr/share/applications/backup.desktop": "mintbackup",
            "/usr/share/applications/mintbackup.desktop": "mintbackup",
        }

        inventory = build_installed_app_inventory(
            applications, {"mintbackup": "2.4.7"}, package_owners,
        )

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["version"], "2.4.7")

    def test_inventory_marks_available_updates_and_unmanaged_apps(self):
        applications = [
            {
                "name": "Visual Studio Code",
                "desktop_file": "/usr/share/applications/code.desktop",
            },
            {
                "name": "Manual Tool",
                "command": "/bin/true",
                "desktop_file": "/home/user/.local/share/applications/manual.desktop",
            },
        ]
        inventory = build_installed_app_inventory(
            applications, {"code": "1.0"}, {
                "/usr/share/applications/code.desktop": "code",
            },
            apt_upgradable=[("code", "1.0", "1.1")],
            checked_sources={"APT/DEB"},
        )

        code = next(row for row in inventory if row["name"] == "Visual Studio Code")
        self.assertEqual(
            code["update_status"], "Atualização disponível",
        )
        self.assertEqual(code["candidate_version"], "1.1")
        manual = next(row for row in inventory if row["name"] == "Manual Tool")
        self.assertEqual(manual["update_status"], "Atualização não gerenciada")

    def test_inventory_marks_appimage_updates_as_unmanaged(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            appimage = Path(tmpdir) / "PortableEditor.AppImage"
            appimage.touch()
            inventory = build_installed_app_inventory(
                [{
                    "name": "Portable Editor",
                    "command": str(appimage),
                    "desktop_file": "/home/user/.local/share/applications/editor.desktop",
                }],
                {},
                {},
            )

        self.assertEqual(inventory[0]["source"], "AppImage")
        self.assertEqual(
            inventory[0]["update_status"], "Atualização não gerenciada",
        )

    def test_inventory_identifies_snap_application_updates(self):
        inventory = build_installed_app_inventory(
            [{
                "name": "Visual Studio Code",
                "desktop_file": "/var/lib/snapd/desktop/applications/code_code.desktop",
            }],
            {},
            {},
            snap_output="Name Version Rev Tracking Publisher Notes\ncode 1.90 180 stable vscode✓ classic\n",
            snap_update_output="Name Version Rev Publisher Notes\ncode 1.91 181 vscode✓ classic\n",
            checked_sources={"Snap"},
        )

        self.assertEqual(inventory[0]["source"], "Snap")
        self.assertEqual(inventory[0]["version"], "1.90")
        self.assertEqual(inventory[0]["candidate_version"], "1.91")
        self.assertEqual(inventory[0]["update_status"], "Atualização disponível")

    def test_parses_snap_installed_versions_and_updates(self):
        self.assertEqual(
            parse_snap_installed(
                "Name Version Rev Tracking Publisher Notes\n"
                "code 1.90 180 stable vscode✓ classic\n"
            ),
            {"code": "1.90"},
        )
        self.assertEqual(
            parse_snap_upgradable(
                "Name Version Rev Publisher Notes\n"
                "code 1.91 181 vscode✓ classic\n"
            ),
            {"code": "1.91"},
        )

    def test_builds_validated_flatpak_and_snap_commands(self):
        self.assertEqual(
            flatpak_upgrade_command(["org.example.Editor"]),
            [
                "flatpak", "update", "--noninteractive", "--assumeyes",
                "org.example.Editor",
            ],
        )
        self.assertEqual(
            snap_upgrade_command(["code"]),
            ["pkexec", "snap", "refresh", "code"],
        )
        with self.assertRaises(ValueError):
            flatpak_upgrade_command(["org.example.Editor; rm -rf /"])
        with self.assertRaises(ValueError):
            snap_upgrade_command(["code;reboot"])

    def test_parses_dpkg_package_versions_and_desktop_file_owners(self):
        versions = (
            "code\t1.146.0-1\tinstall ok installed\n"
            "not-installed\t1.0\t deinstall ok config-files\n"
        )
        owners = (
            "code: /usr/share/applications/code.desktop\n"
            "firefox:amd64: /usr/share/applications/firefox.desktop\n"
        )

        self.assertEqual(
            parse_dpkg_query_packages(versions),
            {"code": "1.146.0-1"},
        )
        self.assertEqual(
            parse_dpkg_query_owners(owners),
            {
                "/usr/share/applications/code.desktop": "code",
                "/usr/share/applications/firefox.desktop": "firefox:amd64",
            },
        )

    def test_parses_flatpak_application_inventory(self):
        self.assertEqual(
            parse_flatpak_installed(
                "com.spotify.Client\tSpotify\t1.2.95\tflathub\n"
                "runtime/org.freedesktop.Platform\tPlatform\t25.08\tflathub\n"
            ),
            {
                "com.spotify.Client": ("Spotify", "1.2.95", "flathub"),
            },
        )

    def test_includes_flatpak_apps_without_shortcuts_and_filters_runtimes(self):
        inventory = build_installed_app_inventory(
            [], {}, {}, "org.example.Editor\tEditor Pro\t2.4\tflathub\n"
            "runtime/org.example.Platform\tPlatform\t25.08\tflathub\n",
            flatpak_update_output="app/org.example.Editor/x86_64/stable\t2.5\tnew\n",
            checked_sources={"Flatpak"},
        )

        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["name"], "Editor Pro")
        self.assertEqual(inventory[0]["version"], "2.4")
        self.assertEqual(inventory[0]["candidate_version"], "2.5")
        self.assertEqual(inventory[0]["update_status"], "Atualização disponível")

    def test_marks_flatpak_updated_only_after_both_queries_succeed(self):
        applications = []
        installed = "org.example.Editor\tEditor Pro\t2.4\tflathub\n"
        self.assertEqual(
            build_installed_app_inventory(
                applications, {}, {}, installed, checked_sources={"Flatpak"},
            )[0]["update_status"],
            "Atualizado",
        )
        self.assertEqual(
            build_installed_app_inventory(
                applications, {}, {}, installed,
            )[0]["update_status"],
            "Verificação necessária",
        )

    def test_keeps_apt_launcher_when_package_owner_lookup_failed(self):
        inventory = build_installed_app_inventory(
            [{
                "name": "Editor",
                "command": "editor",
                "desktop_file": "/usr/share/applications/editor.desktop",
            }],
            {"editor": "1.0"},
            {"/usr/share/applications/editor.desktop": "editor"},
            checked_sources={"APT/DEB"},
            apt_owners_checked=False,
        )

        self.assertEqual(inventory[0]["update_status"], "Verificação necessária")

    def test_discovers_apt_app_without_shortcut_from_installed_appstream_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = Path(tmpdir) / "metainfo"
            metadata.mkdir()
            (metadata / "editor.metainfo.xml").write_text(
                "<component type='desktop-application'>"
                "<id>org.example.Editor</id><name>Editor Pro</name>"
                "<pkgname>editor</pkgname></component>",
                encoding="utf-8",
            )
            apt_lists = self.fresh_apt_lists(tmpdir)
            responses = {
                ("dpkg-query", "-W", "-f=${binary:Package}\\t${Version}\\t${Status}\\n"):
                    ("editor\t1.0\tinstall ok installed\n"
                     "internal-lib\t2.0\tinstall ok installed\n", None),
                ("apt", "list", "--upgradable"):
                    ("editor/stable 1.1 amd64 [upgradable from: 1.0]\n", None),
                ("flatpak", "list", "--app", "--columns=application,name,version,origin"):
                    ("", None),
                ("flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"):
                    ("", None),
                ("snap", "list"): ("Name Version Rev Tracking Publisher Notes\n", None),
                ("snap", "refresh", "--list"): ("All snaps up to date.\n", None),
            }

            sources = query_installed_app_sources(
                [],
                query_runner=lambda command, **_kwargs: responses[tuple(command)],
                apt_lists_directory=apt_lists,
                apt_metadata_directories=(metadata,),
                snap_root=Path(tmpdir) / "snap",
            )

        inventory = build_installed_app_inventory(
            [], sources["package_versions"], sources["package_owners"],
            apt_upgradable=sources["apt_upgradable"],
            checked_sources=sources["checked_sources"],
            apt_applications=sources["apt_applications"],
        )
        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["name"], "Editor Pro")
        self.assertEqual(inventory[0]["version"], "1.0")
        self.assertEqual(inventory[0]["candidate_version"], "1.1")
        self.assertEqual(inventory[0]["update_status"], "Atualização disponível")
        self.assertNotIn("internal-lib", {app["package"] for app in inventory})

    def test_appstream_matches_exact_package_architecture_and_skips_launcher_duplicates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            metadata = Path(tmpdir) / "metainfo"
            metadata.mkdir()
            (metadata / "apps.metainfo.xml").write_text(
                "<components>"
                "<component type='desktop-application' id='org.example.Editor'>"
                "<name>Editor</name><pkgname>editor:amd64</pkgname></component>"
                "<component type='desktop-application' id='org.example.Other'>"
                "<name>Other</name><pkgname>other:amd64</pkgname></component>"
                "</components>",
                encoding="utf-8",
            )
            package_versions = {
                "editor:amd64": "1.0-native",
                "editor:i386": "0.9-compat",
                "other:amd64": "2.0",
            }

            applications = find_installed_apt_applications(
                package_versions,
                launcher_packages={"other:amd64"},
                metadata_directories=(metadata,),
            )

        self.assertEqual(len(applications), 1)
        self.assertEqual(applications[0]["package"], "editor:amd64")
        self.assertEqual(applications[0]["name"], "Editor")

    def test_apt_update_does_not_match_another_installed_architecture(self):
        inventory = build_installed_app_inventory(
            [{
                "name": "Editor",
                "package": "editor:amd64",
                "source": "APT/DEB",
                "desktop_file": "appstream:org.example.Editor",
            }],
            {"editor:amd64": "1.0", "editor:i386": "1.0"},
            {},
            apt_upgradable=[("editor:i386", "1.0", "1.1")],
            checked_sources={"APT/DEB"},
        )

        self.assertEqual(inventory[0]["candidate_version"], "—")
        self.assertEqual(inventory[0]["update_status"], "Atualizado")

    def test_apt_update_does_not_match_amd64_update_to_installed_i386(self):
        inventory = build_installed_app_inventory(
            [{
                "name": "Editor",
                "package": "editor:i386",
                "source": "APT/DEB",
                "desktop_file": "appstream:org.example.Editor",
            }],
            {"editor:amd64": "1.0", "editor:i386": "1.0"},
            {},
            apt_upgradable=[("editor:amd64", "1.0", "1.1")],
            checked_sources={"APT/DEB"},
        )

        self.assertEqual(inventory[0]["candidate_version"], "—")
        self.assertEqual(inventory[0]["update_status"], "Atualizado")

    def test_apt_update_matches_exact_architecture(self):
        inventory = build_installed_app_inventory(
            [{
                "name": "Editor",
                "package": "editor:amd64",
                "source": "APT/DEB",
                "desktop_file": "appstream:org.example.Editor",
            }],
            {"editor:amd64": "1.0", "editor:i386": "1.0"},
            {},
            apt_upgradable=[("editor:amd64", "1.0", "1.2")],
            checked_sources={"APT/DEB"},
        )

        self.assertEqual(inventory[0]["candidate_version"], "1.2")
        self.assertEqual(inventory[0]["update_status"], "Atualização disponível")

    def test_unqualified_apt_update_matches_only_unambiguous_installed_package(self):
        inventory = build_installed_app_inventory(
            [{
                "name": "Editor",
                "package": "editor:amd64",
                "source": "APT/DEB",
                "desktop_file": "appstream:org.example.Editor",
            }],
            {"editor:amd64": "1.0"},
            {},
            apt_upgradable=[("editor", "1.0", "1.2")],
            checked_sources={"APT/DEB"},
        )

        self.assertEqual(inventory[0]["candidate_version"], "1.2")
        self.assertEqual(inventory[0]["update_status"], "Atualização disponível")

    def test_unqualified_apt_update_does_not_match_multiple_installed_architectures(self):
        inventory = build_installed_app_inventory(
            [{
                "name": "Editor",
                "package": "editor:amd64",
                "source": "APT/DEB",
                "desktop_file": "appstream:org.example.Editor",
            }],
            {"editor:amd64": "1.0", "editor:i386": "1.0"},
            {},
            apt_upgradable=[("editor", "1.0", "1.2")],
            checked_sources={"APT/DEB"},
        )

        self.assertEqual(inventory[0]["candidate_version"], "—")
        self.assertEqual(inventory[0]["update_status"], "Verificação necessária")

    def test_apt_package_without_architecture_uses_exact_update_match(self):
        inventory = build_installed_app_inventory(
            [{
                "name": "Editor",
                "package": "editor",
                "source": "APT/DEB",
                "desktop_file": "appstream:org.example.Editor",
            }],
            {"editor": "1.0"},
            {},
            apt_upgradable=[("editor", "1.0", "1.2")],
            checked_sources={"APT/DEB"},
        )

        self.assertEqual(inventory[0]["candidate_version"], "1.2")
        self.assertEqual(inventory[0]["update_status"], "Atualização disponível")

    def test_apt_package_without_available_update_is_not_reported_as_upgradable(self):
        inventory = build_installed_app_inventory(
            [{
                "name": "Editor",
                "package": "editor:amd64",
                "source": "APT/DEB",
                "desktop_file": "appstream:org.example.Editor",
            }],
            {"editor:amd64": "1.0"},
            {},
            apt_upgradable=[],
            checked_sources={"APT/DEB"},
        )

        self.assertEqual(inventory[0]["candidate_version"], "—")
        self.assertEqual(inventory[0]["update_status"], "Atualizado")

    def test_discovers_snap_app_without_exported_shortcut(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            gui = Path(tmpdir) / "snap" / "demo" / "current" / "meta" / "gui"
            gui.mkdir(parents=True)
            (gui / "editor.desktop").write_text(
                "[Desktop Entry]\nType=Application\nName=Snap Editor\n"
                "Exec=demo-editor\n",
                encoding="utf-8",
            )
            responses = {
                ("dpkg-query", "-W", "-f=${binary:Package}\\t${Version}\\t${Status}\\n"):
                    ("", None),
                ("apt", "list", "--upgradable"): ("", None),
                ("flatpak", "list", "--app", "--columns=application,name,version,origin"):
                    ("", None),
                ("flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"):
                    ("", None),
                ("snap", "list"): (
                    "Name Version Rev Tracking Publisher Notes\ndemo 3.2 42 stable pub -\n",
                    None,
                ),
                ("snap", "refresh", "--list"): (
                    "Name Version Rev Publisher Notes\ndemo 3.3 43 pub -\n",
                    None,
                ),
            }
            sources = query_installed_app_sources(
                [],
                query_runner=lambda command, **_kwargs: responses[tuple(command)],
                apt_lists_directory=self.fresh_apt_lists(tmpdir),
                apt_metadata_directories=(),
                snap_root=Path(tmpdir) / "snap",
            )

        inventory = build_installed_app_inventory(
            [], {}, {}, snap_output=sources["snap_output"],
            snap_update_output=sources["snap_update_output"],
            checked_sources=sources["checked_sources"],
            snap_applications=sources["snap_applications"],
        )
        self.assertEqual(len(inventory), 1)
        self.assertEqual(inventory[0]["name"], "Snap Editor")
        self.assertEqual(inventory[0]["version"], "3.2")
        self.assertEqual(inventory[0]["candidate_version"], "3.3")
        self.assertEqual(inventory[0]["update_status"], "Atualização disponível")

    def test_manual_shortcut_requires_existing_command_target(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "manual-editor"
            executable.touch()
            inventory = build_installed_app_inventory(
                [
                    {
                        "name": "Manual Editor",
                        "command": str(executable),
                        "desktop_file": "/home/user/.local/share/applications/editor.desktop",
                    },
                    {
                        "name": "Removed Editor",
                        "command": str(Path(tmpdir) / "removed-editor"),
                        "desktop_file": "/home/user/.local/share/applications/removed.desktop",
                    },
                ],
                {}, {}, apt_owners_checked=True,
            )

        self.assertEqual([app["name"] for app in inventory], ["Manual Editor"])
        self.assertEqual(inventory[0]["update_status"], "Atualização não gerenciada")

    def test_unowned_desktop_entries_do_not_make_dpkg_owner_query_incomplete(self):
        apt_launcher = "/usr/share/applications/editor.desktop"
        manual_launcher = "/home/user/.local/share/applications/manual.desktop"
        responses = {
            ("dpkg-query", "-S", "--", manual_launcher, apt_launcher):
                (
                    f"editor: {apt_launcher}\n",
                    f"dpkg-query: no path found matching pattern {manual_launcher}",
                ),
            ("dpkg-query", "-W", "-f=${binary:Package}\\t${Version}\\t${Status}\\n"):
                ("editor\t1.0\tinstall ok installed\n", None),
            ("apt", "list", "--upgradable"): ("", None),
            ("flatpak", "list", "--app", "--columns=application,name,version,origin"):
                ("", None),
            ("flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"):
                ("", None),
            ("snap", "list"): ("Name Version Rev Tracking Publisher Notes\n", None),
            ("snap", "refresh", "--list"): ("All snaps up to date.\n", None),
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            sources = query_installed_app_sources(
                [
                    {"name": "Editor", "desktop_file": apt_launcher},
                    {"name": "Manual", "desktop_file": manual_launcher},
                ],
                query_runner=lambda command, **_kwargs: responses[tuple(command)],
                apt_lists_directory=self.fresh_apt_lists(tmpdir),
                apt_metadata_directories=(),
            )

        self.assertTrue(sources["apt_owners_checked"])
        self.assertEqual(
            sources["package_owners"], {apt_launcher: "editor"},
        )
        self.assertFalse(any("dpkg (atalhos)" in error for error in sources["errors"]))

    def test_inventory_queries_force_stable_command_locale(self):
        seen_environments = []
        with tempfile.TemporaryDirectory() as tmpdir:
            def runner(_command, *, env, **_kwargs):
                seen_environments.append(env)
                return "", "manager absent"

            query_installed_app_sources(
                [], env={"PATH": "/usr/bin"}, query_runner=runner,
                apt_lists_directory=self.fresh_apt_lists(tmpdir),
                apt_metadata_directories=(),
            )

        self.assertTrue(seen_environments)
        self.assertTrue(all(environment["LC_ALL"] == "C" for environment in seen_environments))
        self.assertTrue(all(environment["PATH"] == "/usr/bin" for environment in seen_environments))

    def test_failed_apt_update_query_never_marks_installed_app_as_updated(self):
        apt_launcher = "/usr/share/applications/editor.desktop"
        with tempfile.TemporaryDirectory() as tmpdir:
            responses = {
                ("dpkg-query", "-S", "--", apt_launcher):
                    (f"editor: {apt_launcher}\n", None),
                ("dpkg-query", "-W", "-f=${binary:Package}\\t${Version}\\t${Status}\\n"):
                    ("editor\t1.0\tinstall ok installed\n", None),
                ("apt", "list", "--upgradable"): ("", "sem rede"),
                ("flatpak", "list", "--app", "--columns=application,name,version,origin"):
                    ("", "flatpak ausente"),
                ("flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"):
                    ("", "flatpak ausente"),
                ("snap", "list"): ("", "snap ausente"),
                ("snap", "refresh", "--list"): ("", "snap ausente"),
            }
            sources = query_installed_app_sources(
                [{"name": "Editor", "desktop_file": apt_launcher}],
                query_runner=lambda command, **_kwargs: responses[tuple(command)],
                apt_lists_directory=self.fresh_apt_lists(tmpdir),
                apt_metadata_directories=(),
            )

        inventory = build_installed_app_inventory(
            [{"name": "Editor", "desktop_file": apt_launcher}],
            sources["package_versions"], sources["package_owners"],
            apt_upgradable=sources["apt_upgradable"],
            checked_sources=sources["checked_sources"],
            apt_owners_checked=sources["apt_owners_checked"],
        )
        self.assertNotIn("APT/DEB", sources["checked_sources"])
        self.assertEqual(inventory[0]["update_status"], "Verificação necessária")

    def test_stale_apt_catalog_does_not_confirm_apps_as_updated(self):
        apt_launcher = "/usr/share/applications/editor.desktop"
        with tempfile.TemporaryDirectory() as tmpdir:
            apt_lists = self.fresh_apt_lists(tmpdir)
            os.utime(apt_lists / "index", (1, 1))
            responses = {
                ("dpkg-query", "-S", "--", apt_launcher):
                    (f"editor: {apt_launcher}\n", None),
                ("dpkg-query", "-W", "-f=${binary:Package}\\t${Version}\\t${Status}\\n"):
                    ("editor\t1.0\tinstall ok installed\n", None),
                ("apt", "list", "--upgradable"): ("", None),
                ("flatpak", "list", "--app", "--columns=application,name,version,origin"):
                    ("", None),
                ("flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"):
                    ("", None),
                ("snap", "list"): ("Name Version Rev Tracking Publisher Notes\n", None),
                ("snap", "refresh", "--list"): ("All snaps up to date.\n", None),
            }
            sources = query_installed_app_sources(
                [{"name": "Editor", "desktop_file": apt_launcher}],
                query_runner=lambda command, **_kwargs: responses[tuple(command)],
                apt_lists_directory=apt_lists,
                apt_metadata_directories=(),
            )

        inventory = build_installed_app_inventory(
            [{"name": "Editor", "desktop_file": apt_launcher}],
            sources["package_versions"], sources["package_owners"],
            checked_sources=sources["checked_sources"],
            apt_owners_checked=sources["apt_owners_checked"],
        )
        self.assertTrue(sources["source_results"]["APT/DEB"]["metadata_stale"])
        self.assertNotIn("APT/DEB", sources["checked_sources"])
        self.assertEqual(inventory[0]["update_status"], "Verificação necessária")

    def test_merge_preserves_failed_sources_but_marks_them_unverified(self):
        previous = [{
            "name": "Prior App",
            "package": "prior",
            "source": "Flatpak",
            "candidate_version": "2.0",
            "update_status": "Atualizado",
        }]
        current = [{
            "name": "New App",
            "package": "new",
            "source": "APT/DEB",
            "candidate_version": "—",
            "update_status": "Atualizado",
        }]

        inventory = merge_inventory_after_partial_failure(
            previous, current, {"Flatpak"},
        )

        retained = next(app for app in inventory if app["name"] == "Prior App")
        self.assertEqual(retained["update_status"], "Verificação necessária")
        self.assertEqual(retained["candidate_version"], "—")
        self.assertEqual([app["name"] for app in inventory], ["New App", "Prior App"])

    def test_query_failures_are_independent_and_reported(self):
        apt_launcher = "/usr/share/applications/editor.desktop"
        snap_launcher = "/var/lib/snapd/desktop/applications/code_code.desktop"
        responses = {
            ("dpkg-query", "-S", "--", apt_launcher, snap_launcher):
                (f"editor: {apt_launcher}\n", None),
            ("dpkg-query", "-W", "-f=${binary:Package}\\t${Version}\\t${Status}\\n"):
                ("editor\t1.0\tinstall ok installed\n", None),
            ("apt", "list", "--upgradable"): ("", None),
            ("flatpak", "list", "--app", "--columns=application,name,version,origin"):
                ("", "sem rede"),
            ("flatpak", "remote-ls", "--updates", "--columns=ref,version,commit"):
                ("", "sem rede"),
            ("snap", "list"): (
                "Name Version Rev Tracking Publisher Notes\ncode 1.0 1 stable pub -\n",
                None,
            ),
            ("snap", "refresh", "--list"): ("All snaps up to date.\n", None),
        }

        def runner(command, **_kwargs):
            return responses[tuple(command)]

        with tempfile.TemporaryDirectory() as tmpdir:
            sources = query_installed_app_sources(
                [
                    {"name": "Editor", "desktop_file": apt_launcher},
                    {"name": "Code", "desktop_file": snap_launcher},
                ],
                query_runner=runner,
                apt_lists_directory=self.fresh_apt_lists(tmpdir),
                apt_metadata_directories=(),
                snap_root=Path(tmpdir) / "snap",
            )
        inventory = build_installed_app_inventory(
            [
                {"name": "Editor", "desktop_file": apt_launcher},
                {"name": "Code", "desktop_file": snap_launcher},
            ],
            sources["package_versions"],
            sources["package_owners"],
            sources["flatpak_output"],
            apt_upgradable=sources["apt_upgradable"],
            flatpak_update_output=sources["flatpak_update_output"],
            snap_output=sources["snap_output"],
            snap_update_output=sources["snap_update_output"],
            checked_sources=sources["checked_sources"],
            apt_owners_checked=sources["apt_owners_checked"],
            apt_applications=sources["apt_applications"],
            snap_applications=sources["snap_applications"],
        )

        self.assertEqual(sources["checked_sources"], {"APT/DEB", "Snap"})
        self.assertTrue(any("Flatpak" in error for error in sources["errors"]))
        self.assertEqual(
            {app["name"]: app["update_status"] for app in inventory},
            {"Code": "Atualizado", "Editor": "Atualizado"},
        )

    def test_manager_failures_leave_apps_in_verification_state(self):
        def runner(_command, **_kwargs):
            return "", "sem conexão ou gerenciador ausente"

        with tempfile.TemporaryDirectory() as tmpdir:
            sources = query_installed_app_sources(
                [{
                    "name": "Editor",
                    "command": "/bin/true",
                    "desktop_file": "/usr/share/applications/editor.desktop",
                }],
                query_runner=runner,
                apt_lists_directory=self.fresh_apt_lists(tmpdir),
                apt_metadata_directories=(),
            )
        inventory = build_installed_app_inventory(
            [{
                "name": "Editor",
                "command": "/bin/true",
                "desktop_file": "/usr/share/applications/editor.desktop",
            }],
            sources["package_versions"],
            sources["package_owners"],
            sources["flatpak_output"],
            apt_upgradable=sources["apt_upgradable"],
            flatpak_update_output=sources["flatpak_update_output"],
            snap_output=sources["snap_output"],
            snap_update_output=sources["snap_update_output"],
            checked_sources=sources["checked_sources"],
            apt_owners_checked=sources["apt_owners_checked"],
        )

        self.assertEqual(sources["checked_sources"], set())
        self.assertEqual(len(sources["errors"]), 7)
        self.assertEqual(inventory[0]["update_status"], "Verificação necessária")

    def test_closed_inventory_stops_starting_additional_queries(self):
        state = InventoryLoadState()
        state.begin()
        state.close()
        runner = mock.Mock()

        sources = query_installed_app_sources(
            [], query_runner=runner, cancel_event=state.cancel_event,
        )

        runner.assert_not_called()
        self.assertIn("consulta cancelada", " ".join(sources["errors"]))

    def test_empty_successful_sources_produce_a_real_empty_inventory(self):
        self.assertEqual(build_installed_app_inventory([], {}, {}, checked_sources={
            "APT/DEB", "Flatpak", "Snap",
        }), [])

    def test_inventory_load_state_blocks_duplicates_and_closed_windows(self):
        state = InventoryLoadState()
        self.assertTrue(state.begin())
        self.assertFalse(state.begin())
        state.finish(completed=True)
        self.assertFalse(state.begin())
        self.assertTrue(state.begin(force=True))
        state.close()
        self.assertTrue(state.cancel_event.is_set())
        self.assertFalse(state.begin(force=True))
        state.finish()
        self.assertFalse(state.loading)

    def test_matches_flatpak_update_refs_to_installed_versions(self):
        updates = (
            "app/org.example.Editor/x86_64/stable\t2.4\tupdate-commit\n"
            "runtime/org.example.Platform/x86_64/50\t\tplatform-50\n"
            "runtime/org.example.Platform/x86_64/51\t\tplatform-51\n"
        )
        installed = (
            "org.example.Editor/x86_64/stable\t2.3\told-commit\n"
            "org.example.Platform/x86_64/50\t\told-platform-commit\n"
        )

        self.assertEqual(
            parse_flatpak_upgradable(updates, installed),
            [
                ("Flatpak · org.example.Editor (stable)", "2.3", "2.4"),
                ("Flatpak · org.example.Platform (50)", "—", "Nova revisão platform-50"),
                ("Flatpak · org.example.Platform (51)", "—", "Nova revisão platform-51"),
            ],
        )

    def test_marks_flatpak_update_when_display_version_is_unchanged(self):
        updates = "app/org.example.Editor/x86_64/stable\t2.4\tnew-commit\n"
        installed = "org.example.Editor/x86_64/stable\t2.4\told-commit\n"

        self.assertEqual(
            parse_flatpak_upgradable(updates, installed),
            [("Flatpak · org.example.Editor (stable)", "2.4", "2.4 (nova revisão)")],
        )

    def test_parses_live_apt_and_flatpak_package_activity(self):
        self.assertEqual(
            parse_package_activity(
                ["pkexec", "apt-get", "upgrade"],
                "Setting up firefox:amd64 (160.0+linuxmint1) ...",
            ),
            ("firefox", "Configurando", "160.0+linuxmint1"),
        )
        self.assertEqual(
            parse_package_activity(
                ["flatpak", "update"],
                "Updating: app/org.example.Editor/x86_64/stable",
            ),
            ("Flatpak · org.example.Editor (stable)", "Atualizando", ""),
        )
        self.assertIsNone(parse_package_activity(["apt", "list"], "Listing..."))

    def test_estimates_remaining_time_only_after_progress_is_observed(self):
        self.assertIsNone(estimate_remaining_seconds(10, 0, 5))
        self.assertIsNone(estimate_remaining_seconds(10, 5, 5))
        self.assertEqual(estimate_remaining_seconds(10, 2, 6), 20)

    def test_streaming_command_forwards_output_and_exit_code(self):
        received = []
        return_code, output = run_streaming_command(
            [sys.executable, "-c", "print('Unpacking demo (1.2)')"],
            env=os.environ.copy(),
            timeout=5,
            on_output=received.append,
        )

        self.assertEqual(return_code, 0)
        self.assertEqual(output, "Unpacking demo (1.2)\n")
        self.assertEqual(received, ["Unpacking demo (1.2)\n"])

    def test_streaming_command_enforces_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_streaming_command(
                [sys.executable, "-c", "import time; time.sleep(2)"],
                env=os.environ.copy(),
                timeout=0.1,
                on_output=lambda _line: None,
            )


if __name__ == "__main__":
    unittest.main()
