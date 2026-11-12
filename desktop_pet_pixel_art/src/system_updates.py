"""Package-manager update parsing, progress estimation, and command streaming."""

import json
import logging
import os
import fcntl
import queue
import re
import signal
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from autonomy import application_command_target_exists
from json_persistence import (
    atomic_json_write,
    block_replacement,
    ensure_private_directory,
    mark_valid,
    may_replace,
    preserve_corrupt_file,
    validate_storage_path,
)


logger = logging.getLogger(__name__)
_INVENTORY_CACHE_VERSION = 1
_INVENTORY_SOURCES = ("APT/DEB", "Flatpak", "Snap")
_INVENTORY_APP_FIELDS = (
    "name", "version", "origin", "package", "source",
    "candidate_version", "update_status",
)
_INVENTORY_UPDATE_STATES = {
    "Atualizado",
    "Atualização disponível",
    "Verificação necessária",
    "Atualização não gerenciada",
}


_APT_UPGRADE_LINE = re.compile(
    r"^\s*(?P<package>[^/\s]+)/\S+\s+(?P<candidate>\S+).*?"
    r"\[upgradable from:\s*(?P<installed>[^\]]+)\]",
    re.IGNORECASE,
)
_APT_PACKAGE_ACTIVITY = re.compile(
    r"^(?P<action>Unpacking|Setting up)\s+"
    r"(?P<package>[a-zA-Z0-9.+:_-]+)(?:\s+\((?P<version>[^)]*)\))?",
)
_FLATPAK_PACKAGE_ACTIVITY = re.compile(
    r"^(?P<action>Updating|Installing):?\s+"
    r"(?P<kind>app|runtime)/(?P<ref>[^/\s]+)/[^/\s]+/(?P<branch>[^\s]+)",
    re.IGNORECASE,
)
_APT_PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?$")
_APT_METADATA_MAX_AGE = timedelta(days=7)


def display_package_name(name):
    """Translate well-known package IDs to names people recognize."""
    friendly_names = {
        "code": "Visual Studio Code (code)",
        "code-insiders": "Visual Studio Code - Insiders (code-insiders)",
    }
    return friendly_names.get(name, name)


def parse_dpkg_query_packages(output):
    """Return installed package versions from dpkg-query's tab-separated output."""
    packages = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) != 3 or fields[2].strip() != "install ok installed":
            continue
        package, version, _status = fields
        packages[package] = version
    return packages


def parse_dpkg_query_owners(output):
    """Map desktop-entry paths to their owning Debian package."""
    owners = {}
    for line in output.splitlines():
        package, separator, path = line.partition(": ")
        if separator and package and path:
            owners[path] = package.split(", ", 1)[0]
    return owners


def latest_apt_metadata_time(directory="/var/lib/apt/lists"):
    """Return the newest local APT index timestamp, if any."""
    try:
        entries = Path(directory).iterdir()
        timestamps = [
            entry.stat().st_mtime
            for entry in entries
            if entry.is_file() and entry.name not in ("lock", "partial")
        ]
    except OSError:
        return None
    if not timestamps:
        return None
    return datetime.fromtimestamp(max(timestamps)).astimezone()


def find_installed_apt_applications(
    package_versions, *, launcher_packages=(), metadata_directories=None,
):
    """Find installed GUI packages from AppStream metadata without launchers."""
    if metadata_directories is None:
        metadata_directories = ("/usr/share/metainfo", "/usr/share/appdata")
    installed_packages = {}
    for package in sorted(package_versions):
        installed_packages[package] = package
        installed_packages.setdefault(package.split(":", 1)[0], package)
    packages_with_launchers = {
        package.split(":", 1)[0] for package in launcher_packages
    }
    applications = []
    seen = set()
    for directory in metadata_directories:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        metadata_files = sorted({
            *directory.rglob("*.metainfo.xml"),
            *directory.rglob("*.appdata.xml"),
        })
        for metadata_file in metadata_files:
            try:
                root = ET.parse(metadata_file).getroot()
            except (OSError, ET.ParseError):
                continue
            for component in root.iter():
                if (
                    component.tag.rsplit("}", 1)[-1] != "component"
                    or component.get("type") != "desktop-application"
                ):
                    continue
                component_id = component.get("id", "")
                name = next(
                    (
                        element.text.strip()
                        for element in component
                        if element.tag.rsplit("}", 1)[-1] == "name"
                        and element.text and element.text.strip()
                    ),
                    component_id,
                )
                package_names = [
                    element.text.strip()
                    for element in component.iter()
                    if element.tag.rsplit("}", 1)[-1] == "pkgname"
                    and element.text and element.text.strip()
                ]
                for package_name in package_names:
                    installed_package = installed_packages.get(package_name)
                    if (
                        not installed_package
                        or installed_package.split(":", 1)[0] in packages_with_launchers
                    ):
                        continue
                    key = (component_id or name.casefold(), installed_package)
                    if key in seen:
                        continue
                    seen.add(key)
                    applications.append({
                        "name": name or installed_package,
                        "command": "",
                        "desktop_file": f"appstream:{component_id}",
                        "package": installed_package,
                        "source": "APT/DEB",
                    })
    return applications


def find_installed_snap_applications(snap_output, *, snap_root="/snap"):
    """Find graphical apps in installed snaps' own GUI metadata directories."""
    from autonomy import find_installed_apps

    applications = []
    snap_root = Path(snap_root)
    for snap_name in sorted(parse_snap_installed(snap_output)):
        gui_directory = snap_root / snap_name / "current" / "meta" / "gui"
        for application in find_installed_apps(directories=[gui_directory]):
            application["package"] = snap_name
            application["source"] = "Snap"
            applications.append(application)
    return applications


def _stop_inventory_process(process):
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError:
        process.terminate()
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            process.kill()
        process.communicate()


def run_inventory_query(
    command, *, timeout, env=None, allow_partial=False, cancel_event=None,
):
    """Run one inventory source without making other sources depend on it."""
    try:
        if cancel_event is None:
            result = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout,
                check=False, env=env,
            )
        else:
            if cancel_event.is_set():
                return "", "consulta cancelada"
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout
            while True:
                if cancel_event.is_set():
                    _stop_inventory_process(process)
                    return "", "consulta cancelada"
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _stop_inventory_process(process)
                    raise subprocess.TimeoutExpired(command, timeout)
                try:
                    stdout, stderr = process.communicate(
                        timeout=min(0.1, remaining),
                    )
                    break
                except subprocess.TimeoutExpired:
                    continue
            result = subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc)
    if result.returncode and allow_partial and result.returncode == 1:
        return result.stdout, result.stderr.strip() or None
    if result.returncode:
        return "", result.stderr.strip() or f"o comando terminou com código {result.returncode}"
    return result.stdout, None


def parse_flatpak_installed(output):
    """Return Flatpak application IDs with display names, versions, and remotes."""
    installed = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if not fields or fields[0].strip().lower() in ("application", "ref"):
            continue
        application = fields[0].strip()
        if application.startswith("runtime/"):
            continue
        if application.startswith("app/"):
            application = application.removeprefix("app/")
        if not application or "." not in application:
            continue
        if len(fields) >= 4:
            name, version, remote = (field.strip() for field in fields[1:4])
        else:
            name = application
            version = fields[1].strip() if len(fields) > 1 else ""
            remote = fields[2].strip() if len(fields) > 2 else ""
        installed[application] = (name or application, version, remote)
    return installed


def parse_snap_installed(output):
    """Return installed snap names with their current versions."""
    installed = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].lower() != "name":
            installed[fields[0]] = fields[1]
    return installed


def parse_snap_upgradable(output):
    """Return snap names with candidate versions from ``snap refresh --list``."""
    updates = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0].lower() != "name":
            updates[fields[0]] = fields[1]
    return updates


def parse_flatpak_upgradable_apps(output):
    """Return candidate versions for Flatpak applications, excluding runtimes."""
    updates = {}
    for line in output.splitlines():
        fields = line.split("\t") if "\t" in line else line.split()
        if not fields:
            continue
        ref = fields[0]
        if ref.startswith("app/"):
            ref = ref[len("app/"):]
        elif ref.startswith("runtime/"):
            continue
        parts = ref.split("/")
        if len(parts) < 3:
            continue
        app_id = parts[0]
        version = fields[1].strip() if len(fields) > 1 else ""
        commit = fields[2].strip() if len(fields) > 2 else ""
        updates[app_id] = (
            version if version else
            f"Nova revisão {commit[:12]}" if commit else "Nova revisão"
        )
    return updates


def build_installed_app_inventory(
    applications, package_versions, package_owners, flatpak_output="",
    *, apt_upgradable=(), flatpak_update_output="", snap_output="",
    snap_update_output="", checked_sources=(), apt_owners_checked=True,
    apt_applications=(), snap_applications=(),
):
    """Combine desktop launchers with package versions and known update status."""
    flatpak_apps = parse_flatpak_installed(flatpak_output)
    flatpak_updates = parse_flatpak_upgradable_apps(flatpak_update_output)
    snap_apps = parse_snap_installed(snap_output)
    snap_updates = parse_snap_upgradable(snap_update_output)
    apt_updates = {
        package: candidate for package, _installed, candidate in apt_upgradable
    }

    def apt_candidate(package):
        exact_candidate = apt_updates.get(package)
        if exact_candidate:
            return exact_candidate, False

        base_package = package.split(":", 1)[0]
        installed_variants = {
            installed_package
            for installed_package in package_versions
            if installed_package.split(":", 1)[0] == base_package
        }
        if len(installed_variants) != 1:
            return None, base_package in apt_updates
        return apt_updates.get(base_package), False

    checked_sources = set(checked_sources)
    inventory = []
    seen = set()
    linked_flatpak_apps = set()
    for application in (*applications, *apt_applications, *snap_applications):
        name = application.get("name", "").strip()
        desktop_file = application.get("desktop_file", "")
        if not name:
            continue
        flatpak_id = Path(desktop_file).name.removesuffix(".desktop")
        source_hint = application.get("source", "")
        package = (
            application.get("package")
            or package_owners.get(desktop_file, "")
        )
        command = application.get("command", "").casefold()
        candidate = None
        apt_update_ambiguous = False
        if source_hint == "APT/DEB":
            source = "APT/DEB"
            version = (
                package_versions.get(package)
                or package_versions.get(package.split(":", 1)[0])
            )
            if version is None:
                continue
            origin = "APT/DEB"
            candidate, apt_update_ambiguous = apt_candidate(package)
        elif (
            source_hint == "Flatpak"
            or "/flatpak/exports/share/applications/" in desktop_file
        ):
            flatpak_id = package or flatpak_id
            if flatpak_id not in flatpak_apps:
                continue
            flatpak_name, version, remote = flatpak_apps.get(
                flatpak_id, (name, "", ""),
            )
            origin = f"Flatpak · {remote}" if remote else "Flatpak"
            package = flatpak_id
            source = "Flatpak"
            candidate = flatpak_updates.get(flatpak_id)
            linked_flatpak_apps.add(flatpak_id)
            if flatpak_name and flatpak_name != flatpak_id:
                name = flatpak_name
        elif source_hint == "Snap":
            snap_name = package
            if snap_name not in snap_apps:
                continue
            version = snap_apps[snap_name]
            origin = "Snap"
            source = "Snap"
            candidate = snap_updates.get(snap_name)
        elif (
            desktop_file.startswith("/var/lib/snapd/desktop/applications/")
            or desktop_file.startswith("/snap/")
            or command.startswith("/snap/")
            or command.startswith("snap run ")
        ):
            snap_name = package or flatpak_id.split("_", 1)[0]
            if command.startswith("/snap/bin/"):
                snap_name = command.split("/", 3)[3].split("/", 1)[0]
            elif command.startswith("/snap/"):
                snap_name = command.split("/", 2)[2].split("/", 1)[0]
            elif command.startswith("snap run "):
                snap_name = command.split()[2]
            elif desktop_file.startswith("/snap/"):
                snap_name = desktop_file.split("/", 2)[2].split("/", 1)[0]
            if snap_name not in snap_apps:
                continue
            package = snap_name
            version = snap_apps.get(package, "")
            origin = "Snap"
            source = "Snap"
            candidate = snap_updates.get(package) if package else None
        elif ".appimage" in command or ".appimage" in desktop_file.casefold():
            if not application_command_target_exists(
                application.get("command", ""),
            ):
                continue
            version = ""
            origin = "AppImage / arquivo local"
            source = "AppImage"
        elif package:
            if (
                package not in package_versions
                and package.split(":", 1)[0] not in package_versions
            ):
                continue
            version = (
                package_versions.get(package)
                or package_versions.get(package.split(":", 1)[0])
                or ""
            )
            origin = "APT/DEB"
            source = "APT/DEB"
            candidate, apt_update_ambiguous = apt_candidate(package)
        else:
            if (
                not desktop_file
                or not application_command_target_exists(
                    application.get("command", ""),
                )
            ):
                continue
            version = ""
            origin = "Manual / origem não identificada"
            source = "Manual/outro"

        if candidate:
            update_status = "Atualização disponível"
        elif apt_update_ambiguous:
            update_status = "Verificação necessária"
        elif (
            source in checked_sources
            and (source != "APT/DEB" or apt_owners_checked)
        ):
            update_status = "Atualizado"
        elif source == "AppImage":
            update_status = "Atualização não gerenciada"
        elif source == "Manual/outro" and apt_owners_checked:
            update_status = "Atualização não gerenciada"
        else:
            update_status = "Verificação necessária"

        key = (name.casefold(), package or desktop_file)
        if key in seen:
            continue
        seen.add(key)
        inventory.append({
            "name": name,
            "version": version or "Não informada",
            "origin": origin,
            "package": package or "—",
            "source": source,
            "candidate_version": candidate or "—",
            "update_status": update_status,
        })

    for application_id, (name, version, remote) in flatpak_apps.items():
        if application_id in linked_flatpak_apps:
            continue
        candidate = flatpak_updates.get(application_id)
        if candidate:
            update_status = "Atualização disponível"
        elif "Flatpak" in checked_sources:
            update_status = "Atualizado"
        else:
            update_status = "Verificação necessária"
        inventory.append({
            "name": name or application_id,
            "version": version or "Não informada",
            "origin": f"Flatpak · {remote}" if remote else "Flatpak",
            "package": application_id,
            "source": "Flatpak",
            "candidate_version": candidate or "—",
            "update_status": update_status,
        })

    return sorted(inventory, key=lambda item: (item["name"].casefold(), item["package"].casefold()))


def query_installed_app_sources(
    applications, *, env=None, query_runner=None, cancel_event=None,
    apt_lists_directory="/var/lib/apt/lists",
    apt_metadata_directories=None, snap_root="/snap", now=None,
):
    """Query package managers independently and return parsed inventory data."""
    query = query_runner or run_inventory_query
    checked_at = (now or datetime.now().astimezone()).astimezone()
    query_env = dict(os.environ if env is None else env)
    query_env["LC_ALL"] = "C"

    def run(command, **kwargs):
        if cancel_event is not None and cancel_event.is_set():
            return "", "consulta cancelada"
        command_env = kwargs.pop("env", None)
        command_env = dict(query_env if command_env is None else command_env)
        command_env["LC_ALL"] = "C"
        kwargs["env"] = command_env
        kwargs["cancel_event"] = cancel_event
        return query(command, **kwargs)

    desktop_files = sorted({
        application["desktop_file"]
        for application in applications
        if application.get("desktop_file")
    })
    errors = []
    package_owners = {}
    apt_owners_checked = not desktop_files
    if desktop_files:
        output, error = run(
            ["dpkg-query", "-S", "--", *desktop_files],
            timeout=60, env=env, allow_partial=True,
        )
        package_owners = parse_dpkg_query_owners(output)
        expected_unowned_paths = bool(error) and all(
            "no path found matching pattern" in line.casefold()
            for line in error.splitlines()
        )
        apt_owners_checked = not error or expected_unowned_paths
        if error and not expected_unowned_paths:
            errors.append(f"dpkg (atalhos): {error}")

    output, error = run(
        [
            "dpkg-query", "-W", "-f=" +
            "${binary:Package}\\t${Version}\\t${Status}\\n",
        ],
        timeout=60, env=env, allow_partial=True,
    )
    package_versions = parse_dpkg_query_packages(output)
    package_query_ok = not error and bool(output.strip())
    if not error and not output.strip():
        error = "a consulta retornou saída vazia inesperada"
    if error:
        errors.append(f"dpkg (pacotes instalados): {error}")

    apt_output, apt_error = run(
        ["apt", "list", "--upgradable"], timeout=120, env=env,
    )
    if not apt_error and not apt_output.strip():
        apt_error = "a consulta retornou saída vazia inesperada"
    apt_upgradable = parse_apt_upgradable(apt_output) if not apt_error else []
    apt_metadata_time = latest_apt_metadata_time(apt_lists_directory)
    if apt_metadata_time is None:
        apt_metadata_stale = True
        errors.append("APT: não foi possível confirmar a data do catálogo local.")
    else:
        age = checked_at - apt_metadata_time
        apt_metadata_stale = age < timedelta(minutes=-5) or age > _APT_METADATA_MAX_AGE
        if apt_metadata_stale:
            errors.append(
                "APT: o catálogo local pode estar desatualizado "
                f"(última atualização {apt_metadata_time.strftime('%d/%m/%Y %H:%M')})."
            )
    if apt_error:
        errors.append(f"APT: {apt_error}")

    apt_installation_complete = package_query_ok and apt_owners_checked
    apt_updates_complete = not apt_error and not apt_metadata_stale

    launcher_packages = set(package_owners.values())
    apt_applications = []
    if package_query_ok:
        try:
            apt_applications = find_installed_apt_applications(
                package_versions,
                launcher_packages=launcher_packages,
                metadata_directories=apt_metadata_directories,
            )
        except OSError as exc:
            apt_installation_complete = False
            errors.append(f"APT (metadados de aplicativos): {exc}")

    checked_sources = set()
    if apt_installation_complete and apt_updates_complete:
        checked_sources.add("APT/DEB")

    flatpak_output, flatpak_error = run(
        [
            "flatpak", "list", "--app",
            "--columns=application,name,version,origin",
        ],
        timeout=60, env=env,
    )
    flatpak_update_output, flatpak_update_error = run(
        [
            "flatpak", "remote-ls", "--updates",
            "--columns=ref,version,commit",
        ],
        timeout=120, env=env,
    )
    if flatpak_error:
        errors.append(f"Flatpak (aplicativos): {flatpak_error}")
    if flatpak_update_error:
        errors.append(f"Flatpak (atualizações): {flatpak_update_error}")
    flatpak_installation_complete = not flatpak_error
    flatpak_updates_complete = not flatpak_update_error
    if flatpak_installation_complete and flatpak_updates_complete:
        checked_sources.add("Flatpak")

    snap_output, snap_error = run(
        ["snap", "list"], timeout=60, env=env,
    )
    if not snap_error and not snap_output.strip():
        snap_error = "a consulta retornou saída vazia inesperada"
    snap_update_output, snap_update_error = run(
        ["snap", "refresh", "--list"], timeout=120, env=env,
    )
    if not snap_update_error and not snap_update_output.strip():
        snap_update_error = "a consulta retornou saída vazia inesperada"
    if snap_error:
        errors.append(f"Snap (aplicativos): {snap_error}")
    if snap_update_error:
        errors.append(f"Snap (atualizações): {snap_update_error}")
    snap_installation_complete = not snap_error
    snap_updates_complete = not snap_update_error
    if snap_installation_complete and snap_updates_complete:
        checked_sources.add("Snap")

    snap_applications = []
    if snap_installation_complete:
        try:
            snap_applications = find_installed_snap_applications(
                snap_output, snap_root=snap_root,
            )
        except OSError as exc:
            snap_installation_complete = False
            errors.append(f"Snap (atalhos gráficos): {exc}")
    source_results = {
        "APT/DEB": {
            "inventory_complete": apt_installation_complete,
            "updates_complete": not apt_error,
            "checked_at": checked_at.isoformat() if not apt_error else "",
            "metadata_updated_at": (
                apt_metadata_time.isoformat() if apt_metadata_time else ""
            ),
            "metadata_stale": apt_metadata_stale,
        },
        "Flatpak": {
            "inventory_complete": flatpak_installation_complete,
            "updates_complete": flatpak_updates_complete,
            "checked_at": checked_at.isoformat() if flatpak_updates_complete else "",
            "metadata_updated_at": "",
            "metadata_stale": False,
        },
        "Snap": {
            "inventory_complete": snap_installation_complete,
            "updates_complete": snap_updates_complete,
            "checked_at": checked_at.isoformat() if snap_updates_complete else "",
            "metadata_updated_at": "",
            "metadata_stale": False,
        },
    }

    return {
        "package_versions": package_versions,
        "package_owners": package_owners,
        "apt_owners_checked": apt_owners_checked,
        "apt_upgradable": apt_upgradable,
        "apt_applications": apt_applications,
        "flatpak_output": flatpak_output if not flatpak_error else "",
        "flatpak_update_output": (
            flatpak_update_output if not flatpak_update_error else ""
        ),
        "snap_output": snap_output if not snap_error else "",
        "snap_update_output": snap_update_output if not snap_update_error else "",
        "snap_applications": snap_applications,
        "checked_sources": checked_sources,
        "source_results": source_results,
        "inventory_complete_sources": {
            source for source, result in source_results.items()
            if result["inventory_complete"]
        },
        "errors": errors,
    }


def merge_inventory_after_partial_failure(previous, current, failed_sources):
    """Keep prior rows for sources whose installed-app query did not complete."""
    inventory = list(current)
    identities = {
        (app["source"], app["package"], app["name"].casefold())
        for app in inventory
    }
    for application in previous:
        if application["source"] not in failed_sources:
            continue
        identity = (
            application["source"],
            application["package"],
            application["name"].casefold(),
        )
        if identity in identities:
            continue
        retained = dict(application)
        retained["update_status"] = "Verificação necessária"
        retained["candidate_version"] = "—"
        inventory.append(retained)
        identities.add(identity)
    return sorted(
        inventory,
        key=lambda app: (app["name"].casefold(), app["package"].casefold()),
    )


class InstalledAppInventoryStore:
    """Persist the last known inventory with versioned, atomic JSON writes."""

    def __init__(self, path):
        self.path = Path(path)

    @staticmethod
    def _normalize_app(application):
        if not isinstance(application, dict):
            return None
        normalized = {
            field: application.get(field)
            for field in _INVENTORY_APP_FIELDS
        }
        if any(not isinstance(value, str) for value in normalized.values()):
            return None
        if (
            not normalized["name"].strip()
            or normalized["source"] not in (
                *_INVENTORY_SOURCES, "AppImage", "Manual/outro",
            )
            or normalized["update_status"] not in _INVENTORY_UPDATE_STATES
        ):
            return None
        return normalized

    @staticmethod
    def _valid_timestamp(value):
        if not isinstance(value, str) or not value:
            return False
        try:
            datetime.fromisoformat(value)
        except ValueError:
            return False
        return True

    @classmethod
    def _normalize_sources(cls, sources):
        if not isinstance(sources, dict):
            return {}
        normalized = {}
        for source in _INVENTORY_SOURCES:
            state = sources.get(source)
            if not isinstance(state, dict):
                continue
            checked_at = state.get("checked_at", "")
            metadata_updated_at = state.get("metadata_updated_at", "")
            metadata_stale = state.get("metadata_stale", False)
            needs_verification = state.get("needs_verification", False)
            if (
                not isinstance(checked_at, str)
                or not isinstance(metadata_updated_at, str)
                or (
                    checked_at and not cls._valid_timestamp(checked_at)
                )
                or (
                    metadata_updated_at
                    and not cls._valid_timestamp(metadata_updated_at)
                )
                or not isinstance(metadata_stale, bool)
                or not isinstance(needs_verification, bool)
            ):
                continue
            normalized[source] = {
                "checked_at": checked_at,
                "metadata_updated_at": metadata_updated_at,
                "metadata_stale": metadata_stale,
                "needs_verification": needs_verification,
            }
        return normalized

    @classmethod
    def _sources_after_refresh(cls, previous_sources, source_results):
        sources = cls._normalize_sources(previous_sources)
        if not isinstance(source_results, dict):
            source_results = {}
        for source in _INVENTORY_SOURCES:
            result = source_results.get(source)
            if not isinstance(result, dict):
                continue
            checked_at = result.get("checked_at", "")
            metadata_updated_at = result.get("metadata_updated_at", "")
            fully_checked = (
                result.get("inventory_complete") is True
                and result.get("updates_complete") is True
                and not result.get("metadata_stale", False)
                and cls._valid_timestamp(checked_at)
                and (
                    not metadata_updated_at
                    or cls._valid_timestamp(metadata_updated_at)
                )
            )
            if fully_checked:
                previous = sources.get(source, {})
                previous_checked_at = previous.get("checked_at", "")
                if (
                    not previous_checked_at
                    or datetime.fromisoformat(checked_at).timestamp()
                    >= datetime.fromisoformat(previous_checked_at).timestamp()
                ):
                    sources[source] = {
                        "checked_at": checked_at,
                        "metadata_updated_at": metadata_updated_at,
                        "metadata_stale": False,
                        "needs_verification": False,
                    }
            else:
                state = dict(sources.get(source, {}))
                state["needs_verification"] = True
                sources[source] = {
                    "checked_at": state.get("checked_at", ""),
                    "metadata_updated_at": state.get("metadata_updated_at", ""),
                    "metadata_stale": state.get("metadata_stale", False),
                    "needs_verification": True,
                }
        return sources

    def _read_snapshot(self, *, mark_unverified):
        try:
            path = validate_storage_path(self.path, label="inventário de aplicativos")
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            mark_valid(self.path)
            return {"apps": [], "sources": {}, "saved_at": ""}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            preserve_corrupt_file(self.path, type(exc).__name__)
            logger.error(
                "O inventário persistido está corrompido; iniciando sem cache válido",
            )
            return {"apps": [], "sources": {}, "saved_at": ""}
        except OSError as exc:
            block_replacement(self.path, type(exc).__name__)
            logger.error(
                "Não foi possível ler o inventário persistido (%s)",
                type(exc).__name__,
            )
            return {"apps": [], "sources": {}, "saved_at": ""}

        if (
            not isinstance(payload, dict)
            or type(payload.get("version")) is not int
            or payload.get("version") != _INVENTORY_CACHE_VERSION
            or not isinstance(payload.get("apps"), list)
        ):
            preserve_corrupt_file(self.path, "formato ou versão inválidos")
            logger.error(
                "O formato do inventário persistido é inválido ou incompatível",
            )
            return {"apps": [], "sources": {}, "saved_at": ""}

        applications = []
        for item in payload["apps"]:
            application = self._normalize_app(item)
            if application is None:
                logger.warning("Um item inválido do inventário persistido foi ignorado")
                continue
            if mark_unverified and application["source"] in _INVENTORY_SOURCES:
                application["update_status"] = "Verificação necessária"
                application["candidate_version"] = "—"
            applications.append(application)

        saved_at = payload.get("saved_at", "")
        if saved_at and not self._valid_timestamp(saved_at):
            saved_at = ""
        sources = self._normalize_sources(payload.get("sources", {}))
        if mark_unverified:
            for state in sources.values():
                state["needs_verification"] = True
        mark_valid(self.path)
        return {"apps": applications, "sources": sources, "saved_at": saved_at}

    def load(self):
        """Return cached applications as unverified until a fresh scan completes."""
        return self._read_snapshot(mark_unverified=True)

    def save(self, applications, source_results, *, previous_sources=None):
        """Serialize writers and merge failed or superseded source snapshots."""
        normalized_apps = []
        for item in applications:
            application = self._normalize_app(item)
            if application is None:
                raise ValueError("O inventário contém um aplicativo inválido")
            normalized_apps.append(application)
        path = validate_storage_path(self.path, label="inventário de aplicativos")
        ensure_private_directory(path.parent, label="inventário de aplicativos")
        lock_path = validate_storage_path(
            path.with_name(f".{path.name}.lock"),
            label="bloqueio do inventário de aplicativos",
        )
        lock_flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            lock_flags |= os.O_NOFOLLOW
        lock_fd = os.open(lock_path, lock_flags, 0o600)
        try:
            os.fchmod(lock_fd, 0o600)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            if not may_replace(path):
                raise OSError(
                    "A gravação foi bloqueada para preservar o inventário original",
                )

            latest = self._read_snapshot(mark_unverified=False)
            latest_sources = self._normalize_sources(latest["sources"])
            for source, state in self._normalize_sources(previous_sources).items():
                latest_sources.setdefault(source, state)

            complete_sources = {
                source for source in _INVENTORY_SOURCES
                if (
                    isinstance(source_results, dict)
                    and isinstance(source_results.get(source), dict)
                    and source_results[source].get("inventory_complete") is True
                )
            }
            failed_sources = set(_INVENTORY_SOURCES) - complete_sources
            stale_sources = set()
            if isinstance(source_results, dict):
                for source in _INVENTORY_SOURCES:
                    result = source_results.get(source)
                    old_checked_at = latest_sources.get(source, {}).get(
                        "checked_at", "",
                    )
                    new_checked_at = (
                        result.get("checked_at", "")
                        if isinstance(result, dict) else ""
                    )
                    if (
                        old_checked_at
                        and self._valid_timestamp(old_checked_at)
                        and self._valid_timestamp(new_checked_at)
                        and datetime.fromisoformat(new_checked_at)
                        .timestamp()
                        < datetime.fromisoformat(old_checked_at).timestamp()
                    ):
                        stale_sources.add(source)
            preserve_sources = failed_sources | stale_sources
            merged_apps = [
                application for application in normalized_apps
                if application["source"] not in preserve_sources
            ]
            retained_apps = [
                application for application in latest["apps"]
                if application["source"] in preserve_sources
            ]
            merged_apps = merge_inventory_after_partial_failure(
                retained_apps,
                merged_apps,
                failed_sources,
            )
            identities = {
                (app["source"], app["package"], app["name"].casefold())
                for app in merged_apps
            }
            for application in retained_apps:
                if application["source"] not in stale_sources:
                    continue
                identity = (
                    application["source"],
                    application["package"],
                    application["name"].casefold(),
                )
                if identity not in identities:
                    merged_apps.append(application)
                    identities.add(identity)
            for application in normalized_apps:
                if application["source"] not in failed_sources:
                    continue
                identity = (
                    application["source"],
                    application["package"],
                    application["name"].casefold(),
                )
                if identity in identities:
                    continue
                retained = dict(application)
                retained["update_status"] = "Verificação necessária"
                retained["candidate_version"] = "—"
                merged_apps.append(retained)
                identities.add(identity)
            merged_apps.sort(
                key=lambda app: (app["name"].casefold(), app["package"].casefold()),
            )

            sources = self._sources_after_refresh(latest_sources, source_results)
            payload = {
                "version": _INVENTORY_CACHE_VERSION,
                "saved_at": datetime.now().astimezone().isoformat(),
                "apps": merged_apps,
                "sources": sources,
            }
            atomic_json_write(
                path, payload, label="inventário de aplicativos", mode=0o600,
            )
            return {
                "apps": merged_apps,
                "sources": sources,
                "saved_at": payload["saved_at"],
            }
        finally:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)


class InventoryLoadState:
    """Prevent duplicate inventory scans and ignore results after window closure."""

    def __init__(self):
        self._lock = threading.Lock()
        self.loading = False
        self.loaded = False
        self.closed = False
        self.cancel_event = threading.Event()

    def begin(self, *, force=False):
        with self._lock:
            if self.closed or self.loading or (self.loaded and not force):
                return False
            self.loading = True
            self.cancel_event.clear()
            return True

    def finish(self, *, completed=False):
        with self._lock:
            self.loading = False
            self.loaded = self.loaded or completed

    def close(self):
        with self._lock:
            self.closed = True
            self.cancel_event.set()


def apt_upgrade_command(package):
    """Build a safe APT command for one or more already-installed packages."""
    packages = (package,) if isinstance(package, str) else tuple(package)
    if not packages or any(
        not isinstance(item, str) or not _APT_PACKAGE_NAME.fullmatch(item)
        for item in packages
    ):
        raise ValueError("Identificador de pacote APT inválido.")
    return [
        "pkexec", "apt-get", "-o", "Dpkg::Use-Pty=0",
        "install", "--only-upgrade", "-y", *packages,
    ]


def flatpak_upgrade_command(applications):
    """Build a Flatpak-only update command for validated application IDs."""
    applications = (applications,) if isinstance(applications, str) else tuple(applications)
    if not applications or any(
        not isinstance(item, str)
        or not re.fullmatch(r"[A-Za-z0-9._-]+", item)
        for item in applications
    ):
        raise ValueError("Identificador de aplicativo Flatpak inválido.")
    return [
        "flatpak", "update", "--noninteractive", "--assumeyes",
        *applications,
    ]


def snap_upgrade_command(snaps):
    """Build a Snap-only update command for validated snap package names."""
    snaps = (snaps,) if isinstance(snaps, str) else tuple(snaps)
    if not snaps or any(
        not isinstance(item, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", item)
        for item in snaps
    ):
        raise ValueError("Identificador de pacote Snap inválido.")
    return ["pkexec", "snap", "refresh", *snaps]


def parse_package_activity(command, line):
    """Return a display name and status for a package-manager progress line."""
    if "apt-get" in command:
        match = _APT_PACKAGE_ACTIVITY.match(line.strip())
        if match:
            action = "Configurando" if match.group("action") == "Setting up" else "Instalando"
            return (
                match.group("package").split(":", 1)[0],
                action,
                match.group("version") or "",
            )
    if "flatpak" in command:
        match = _FLATPAK_PACKAGE_ACTIVITY.match(line.strip())
        if match:
            name = f"Flatpak · {match.group('ref')} ({match.group('branch')})"
            return name, "Atualizando", ""
    return None


def estimate_remaining_seconds(elapsed_seconds, completed, total):
    """Estimate remaining package work from observed completed packages."""
    if completed <= 0 or total <= completed:
        return None
    return max(0, round(elapsed_seconds / completed * (total - completed)))


def run_streaming_command(command, *, env, timeout, on_output):
    """Run a command while forwarding output lines, enforcing a wall-clock timeout."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
        start_new_session=True,
    )
    output_lines = []
    lines = queue.Queue()

    def read_output():
        try:
            for line in process.stdout:
                lines.put(line)
        finally:
            lines.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    finished_reading = False
    while not finished_reading:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            reader.join(timeout=1)
            raise subprocess.TimeoutExpired(command, timeout, output="".join(output_lines))
        try:
            line = lines.get(timeout=min(0.5, remaining))
        except queue.Empty:
            continue
        if line is None:
            finished_reading = True
            continue
        output_lines.append(line)
        on_output(line)
    return process.wait(), "".join(output_lines)


def parse_apt_upgradable(output):
    """Return package name, installed version, and candidate version from APT."""
    packages = []
    for line in output.splitlines():
        match = _APT_UPGRADE_LINE.search(line)
        if match:
            packages.append((
                match.group("package"),
                match.group("installed").strip(),
                match.group("candidate"),
            ))
    return packages


def _flatpak_refs(output):
    refs = {}
    for line in output.splitlines():
        fields = line.split("\t") if "\t" in line else line.split()
        if not fields or fields[0].lower() == "ref":
            continue
        ref = fields[0]
        if ref.startswith(("app/", "runtime/")):
            ref = ref.split("/", 1)[1]
        if "/" not in ref:
            continue
        version = fields[1].strip() if len(fields) > 1 else ""
        commit = fields[2].strip() if len(fields) > 2 else ""
        refs[ref] = (version, commit)
    return refs


def parse_flatpak_upgradable(updates_output, installed_output):
    """Return Flatpak ref name, installed version, and available version."""
    installed = _flatpak_refs(installed_output)
    packages = []
    for ref, (candidate, candidate_commit) in _flatpak_refs(updates_output).items():
        ref_parts = ref.split("/")
        name = f"{ref_parts[0]} ({ref_parts[-1]})"
        installed_version, installed_commit = installed.get(ref, ("", ""))
        if candidate and candidate == installed_version and candidate_commit != installed_commit:
            candidate = f"{candidate} (nova revisão)"
        elif not candidate and candidate_commit:
            candidate = f"Nova revisão {candidate_commit[:12]}"
        packages.append((
            f"Flatpak · {name}",
            installed_version or "—",
            candidate or "Nova versão",
        ))
    return packages
