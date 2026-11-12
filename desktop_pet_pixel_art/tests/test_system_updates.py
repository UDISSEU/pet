import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
_INVENTORY_TEST_SOURCES = {"APT/DEB", "Flatpak", "Snap"}

from system_updates import (
    apt_upgrade_command,
    build_installed_app_inventory,
    display_package_name,
    estimate_remaining_seconds,
    flatpak_upgrade_command,
    InventoryLoadState,
    InstalledAppInventoryStore,
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
        apt_lists.mkdir(parents=True)
        (apt_lists / "index").touch()
        return apt_lists

    def mocked_inventory_scan(self, directory, failed_sources=()):
        root = Path(directory)
        apt_lists = self.fresh_apt_lists(root)
        snap_root = root / "snap"
        snap_gui = snap_root / "demo-snap" / "current" / "meta" / "gui"
        snap_gui.mkdir(parents=True)
        (snap_gui / "demo.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Snap Demo\nExec=demo\n",
            encoding="utf-8",
        )
        applications = [
            {
                "name": "APT Demo",
                "command": "apt-demo",
                "desktop_file": "/usr/share/applications/apt-demo.desktop",
            },
            {
                "name": "Flatpak Demo",
                "command": "flatpak-demo",
                "desktop_file": (
                    "/home/user/.local/share/flatpak/exports/share/"
                    "applications/org.example.FlatpakDemo.desktop"
                ),
            },
        ]
        package_query = (
            "dpkg-query", "-W",
            "-f=${binary:Package}\\t${Version}\\t${Status}\\n",
        )

        def runner(command, **_kwargs):
            command = tuple(command)
            if command[:2] == ("dpkg-query", "-S"):
                return (
                    "apt-demo: /usr/share/applications/apt-demo.desktop\n",
                    "dpkg-query: no path found matching pattern "
                    + applications[1]["desktop_file"],
                )
            if command == package_query:
                if "APT/DEB" in failed_sources:
                    return "", "Permission denied"
                return "apt-demo\t1.0\tinstall ok installed\n", None
            if command == ("apt", "list", "--upgradable"):
                return "Listing...\n", None
            if command == (
                "flatpak", "list", "--app",
                "--columns=application,name,version,origin",
            ):
                if "Flatpak" in failed_sources:
                    return "", "flatpak indisponível"
                return "org.example.FlatpakDemo\tFlatpak Demo\t2.0\tflathub\n", None
            if command == (
                "flatpak", "remote-ls", "--updates",
                "--columns=ref,version,commit",
            ):
                return "", None
            if command == ("snap", "list"):
                if "Snap" in failed_sources:
                    return "", "snap indisponível"
                return (
                    "Name Version Rev Tracking Publisher Notes\n"
                    "demo-snap 3.0 12 stable publisher -\n",
                    None,
                )
            if command == ("snap", "refresh", "--list"):
                return "All snaps up to date.\n", None
            self.fail(f"Consulta inesperada: {command}")

        sources = query_installed_app_sources(
            applications,
            query_runner=runner,
            apt_lists_directory=apt_lists,
            apt_metadata_directories=(),
            snap_root=snap_root,
        )
        current = build_installed_app_inventory(
            applications,
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
        return current, sources

    def test_inventory_persists_across_new_store_instance_and_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "profiles" / "profile-a" / "inventory.json"
            first_scan, first_sources = self.mocked_inventory_scan(
                Path(tmpdir) / "first",
            )
            first_store = InstalledAppInventoryStore(path)
            first_store.save(first_scan, first_sources["source_results"])
            del first_store

            restarted_store = InstalledAppInventoryStore(path)
            cached = restarted_store.load()
            self.assertEqual(
                {app["name"] for app in cached["apps"]},
                {"APT Demo", "Flatpak Demo", "Snap Demo"},
            )
            self.assertTrue(all(
                app["update_status"] == "Verificação necessária"
                for app in cached["apps"]
            ))

            refreshed, refresh_sources = self.mocked_inventory_scan(
                Path(tmpdir) / "second",
            )
            failed_sources = (
                set(refresh_sources["source_results"])
                - refresh_sources["inventory_complete_sources"]
            )
            refreshed = merge_inventory_after_partial_failure(
                cached["apps"], refreshed, failed_sources,
            )
            self.assertTrue(all(
                app["update_status"] == "Atualizado" for app in refreshed
            ))
            restarted_store.save(
                refreshed,
                refresh_sources["source_results"],
                previous_sources=cached["sources"],
            )
            saved_payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(all(
                app["update_status"] == "Atualizado"
                for app in saved_payload["apps"]
            ))

            reopened = InstalledAppInventoryStore(path).load()

        self.assertEqual(
            {app["name"] for app in reopened["apps"]},
            {"APT Demo", "Flatpak Demo", "Snap Demo"},
        )
        self.assertTrue(all(
            app["update_status"] == "Verificação necessária"
            for app in reopened["apps"]
        ))
        self.assertEqual(
            {source for source, state in reopened["sources"].items()
             if state["checked_at"]},
            {"APT/DEB", "Flatpak", "Snap"},
        )

    def test_individual_source_failures_preserve_other_sources_and_cached_apps(self):
        for failed_source in ("APT/DEB", "Flatpak", "Snap"):
            with self.subTest(failed_source=failed_source):
                with tempfile.TemporaryDirectory() as tmpdir:
                    path = Path(tmpdir) / "inventory.json"
                    initial, initial_sources = self.mocked_inventory_scan(
                        Path(tmpdir) / "initial",
                    )
                    store = InstalledAppInventoryStore(path)
                    store.save(initial, initial_sources["source_results"])
                    cached = InstalledAppInventoryStore(path).load()

                    current, sources = self.mocked_inventory_scan(
                        Path(tmpdir) / "refresh", {failed_source},
                    )
                    failed = (
                        set(sources["source_results"])
                        - sources["inventory_complete_sources"]
                    )
                    merged = merge_inventory_after_partial_failure(
                        cached["apps"], current, failed,
                    )
                    by_name_before_save = {
                        app["name"]: app for app in merged
                    }
                    expected_statuses = {
                        "APT Demo": "Atualizado",
                        "Flatpak Demo": "Atualizado",
                        "Snap Demo": "Atualizado",
                    }
                    expected_statuses[{
                        "APT/DEB": "APT Demo",
                        "Flatpak": "Flatpak Demo",
                        "Snap": "Snap Demo",
                    }[failed_source]] = "Verificação necessária"
                    self.assertEqual(
                        {
                            name: app["update_status"]
                            for name, app in by_name_before_save.items()
                        },
                        expected_statuses,
                    )
                    store.save(
                        merged, sources["source_results"],
                        previous_sources=cached["sources"],
                    )
                    reopened = InstalledAppInventoryStore(path).load()

                by_name = {app["name"]: app for app in reopened["apps"]}
                self.assertEqual(
                    set(by_name), {"APT Demo", "Flatpak Demo", "Snap Demo"},
                )
                self.assertTrue(all(
                    app["update_status"] == "Verificação necessária"
                    for app in by_name.values()
                ))

    def test_all_failed_sources_keep_persisted_inventory_unverified(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "inventory.json"
            initial, initial_sources = self.mocked_inventory_scan(
                Path(tmpdir) / "initial",
            )
            store = InstalledAppInventoryStore(path)
            store.save(initial, initial_sources["source_results"])
            cached = InstalledAppInventoryStore(path).load()

            current, sources = self.mocked_inventory_scan(
                Path(tmpdir) / "failed", _INVENTORY_TEST_SOURCES,
            )
            failed = (
                set(sources["source_results"])
                - sources["inventory_complete_sources"]
            )
            merged = merge_inventory_after_partial_failure(
                cached["apps"], current, failed,
            )
            store.save(
                merged, sources["source_results"],
                previous_sources=cached["sources"],
            )
            reopened = InstalledAppInventoryStore(path).load()

        self.assertEqual(
            {app["name"] for app in reopened["apps"]},
            {"APT Demo", "Flatpak Demo", "Snap Demo"},
        )
        self.assertTrue(all(
            app["update_status"] == "Verificação necessária"
            for app in reopened["apps"]
        ))

    def test_inventory_store_skips_invalid_rows_and_recovers_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "inventory.json"
            path.write_text("{invalid", encoding="utf-8")

            store = InstalledAppInventoryStore(path)
            self.assertEqual(store.load()["apps"], [])
            self.assertTrue(list(Path(tmpdir).glob("inventory.json.corrupt-*")))

            path.write_text(json.dumps({
                "version": 1,
                "saved_at": "2026-11-12T10:00:00+00:00",
                "apps": [
                    {"name": "invalid"},
                    {
                        "name": "Valid App",
                        "version": "1.0",
                        "origin": "APT/DEB",
                        "package": "valid-app",
                        "source": "APT/DEB",
                        "candidate_version": "—",
                        "update_status": "Atualizado",
                    },
                ],
                "sources": {},
            }), encoding="utf-8")
            loaded = store.load()

        self.assertEqual([app["name"] for app in loaded["apps"]], ["Valid App"])
        self.assertEqual(
            loaded["apps"][0]["update_status"], "Verificação necessária",
        )

    def test_inventory_store_preserves_previous_file_when_atomic_replace_fails(self):
        application = {
            "name": "Safe App",
            "version": "1.0",
            "origin": "APT/DEB",
            "package": "safe-app",
            "source": "APT/DEB",
            "candidate_version": "—",
            "update_status": "Atualizado",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "inventory.json"
            store = InstalledAppInventoryStore(path)
            store.save([application], {})
            previous = path.read_bytes()

            with mock.patch(
                "json_persistence.os.replace",
                side_effect=OSError("interrupção simulada"),
            ), self.assertRaises(OSError):
                store.save(
                    [{**application, "version": "2.0"}],
                    {},
                )

            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(
                InstalledAppInventoryStore(path).load()["apps"][0]["version"],
                "1.0",
            )

    def test_inventory_store_merges_concurrent_writers_from_separate_instances(self):
        source_names = ("APT/DEB", "Flatpak", "Snap")

        def application(name, source, package, version):
            return {
                "name": name,
                "version": version,
                "origin": source,
                "package": package,
                "source": source,
                "candidate_version": "—",
                "update_status": "Atualizado",
            }

        def results(verified_source, checked_at):
            return {
                source: {
                    "inventory_complete": source == verified_source,
                    "updates_complete": source == verified_source,
                    "checked_at": checked_at if source == verified_source else "",
                    "metadata_updated_at": "",
                    "metadata_stale": False,
                }
                for source in source_names
            }

        initial_apps = [
            application("APT App", "APT/DEB", "apt-app", "1.0"),
            application("Flatpak App", "Flatpak", "flatpak-app", "1.0"),
            application("Snap App", "Snap", "snap-app", "1.0"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "inventory.json"
            InstalledAppInventoryStore(path).save(
                initial_apps,
                {
                    source: {
                        "inventory_complete": True,
                        "updates_complete": True,
                        "checked_at": "2026-11-12T10:00:00+00:00",
                        "metadata_updated_at": "",
                        "metadata_stale": False,
                    }
                    for source in source_names
                },
            )
            barrier = threading.Barrier(3)
            errors = []

            def save_from_separate_instance(apps, source_results):
                try:
                    barrier.wait(timeout=5)
                    InstalledAppInventoryStore(path).save(
                        apps, source_results,
                    )
                except Exception as exc:
                    errors.append(exc)

            writers = [
                threading.Thread(
                    target=save_from_separate_instance,
                    args=(
                        [application("APT App", "APT/DEB", "apt-app", "2.0")],
                        results("APT/DEB", "2026-11-12T10:01:00+00:00"),
                    ),
                ),
                threading.Thread(
                    target=save_from_separate_instance,
                    args=(
                        [application("Flatpak App", "Flatpak", "flatpak-app", "2.0")],
                        results("Flatpak", "2026-11-12T10:02:00+00:00"),
                    ),
                ),
            ]
            for writer in writers:
                writer.start()
            barrier.wait(timeout=5)
            for writer in writers:
                writer.join(timeout=5)
                self.assertFalse(writer.is_alive())
            self.assertEqual(errors, [])
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            {app["name"]: app["version"] for app in saved["apps"]},
            {"APT App": "2.0", "Flatpak App": "2.0", "Snap App": "1.0"},
        )

    def test_inventory_store_does_not_overwrite_data_after_permission_error(self):
        application = {
            "name": "Protected App",
            "version": "1.0",
            "origin": "APT/DEB",
            "package": "protected-app",
            "source": "APT/DEB",
            "candidate_version": "—",
            "update_status": "Atualizado",
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "inventory.json"
            store = InstalledAppInventoryStore(path)
            store.save([application], {})
            with mock.patch.object(
                Path, "read_text", side_effect=PermissionError("acesso negado"),
            ):
                self.assertEqual(store.load()["apps"], [])
            with self.assertRaisesRegex(OSError, "bloqueada"):
                store.save([application], {})

    def test_empty_apt_update_response_requires_verification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            apt_lists = self.fresh_apt_lists(tmpdir)

            def runner(command, **_kwargs):
                command = tuple(command)
                if command[0] == "dpkg-query":
                    return "editor\t1.0\tinstall ok installed\n", None
                if command[:2] == ("apt", "list"):
                    return "", None
                if command[:2] == ("flatpak", "list"):
                    return "", None
                if command[:2] == ("flatpak", "remote-ls"):
                    return "", None
                if command == ("snap", "list"):
                    return "Name Version Rev Tracking Publisher Notes\n", None
                if command[:2] == ("snap", "refresh"):
                    return "All snaps up to date.\n", None
                self.fail(f"Consulta inesperada: {command}")

            sources = query_installed_app_sources(
                [],
                query_runner=runner,
                apt_lists_directory=apt_lists,
                apt_metadata_directories=(),
            )

        self.assertNotIn("APT/DEB", sources["checked_sources"])
        self.assertFalse(sources["source_results"]["APT/DEB"]["updates_complete"])
        self.assertTrue(any("saída vazia inesperada" in error for error in sources["errors"]))

    def test_inventory_query_reports_timeout_and_permission_failures(self):
        with mock.patch(
            "system_updates.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["apt"], timeout=1),
        ):
            output, error = run_inventory_query(["apt", "list"], timeout=1)
        self.assertEqual(output, "")
        self.assertTrue(error)

        with mock.patch(
            "system_updates.subprocess.run",
            side_effect=PermissionError("acesso negado"),
        ):
            output, error = run_inventory_query(["apt", "list"], timeout=1)
        self.assertEqual(output, "")
        self.assertIn("acesso negado", error)

    def test_inventory_query_cancellation_terminates_running_process_group(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pid_path = Path(tmpdir) / "query.pid"
            cancel_event = threading.Event()
            timer = threading.Timer(0.2, cancel_event.set)
            timer.daemon = True
            timer.start()
            output, error = run_inventory_query(
                [
                    sys.executable,
                    "-c",
                    "import os,sys,time; "
                    "open(sys.argv[1], 'w').write(str(os.getpid())); "
                    "time.sleep(30)",
                    str(pid_path),
                ],
                timeout=10,
                cancel_event=cancel_event,
            )
            timer.join(timeout=2)

            self.assertEqual(output, "")
            self.assertEqual(error, "consulta cancelada")
            process_id = int(pid_path.read_text(encoding="utf-8"))
            with self.assertRaises(ProcessLookupError):
                os.kill(process_id, 0)

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
            [sys.executable, "-c", "import sys; sys.exit(2)"],
            timeout=5,
        )
        self.assertEqual(output, "")
        self.assertIn("código 2", error)

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
                ("apt", "list", "--upgradable"): ("Listing...\n", None),
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
            ("apt", "list", "--upgradable"): ("Listing...\n", None),
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
                ("apt", "list", "--upgradable"): ("Listing...\n", None),
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
            ("apt", "list", "--upgradable"): ("Listing...\n", None),
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
