"""Package-manager update parsing, progress estimation, and command streaming."""

import os
import queue
import re
import signal
import subprocess
import threading
import time


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


def run_inventory_query(command, *, timeout, env=None, allow_partial=False):
    """Run one inventory source without making other sources depend on it."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout,
            check=False, env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc)
    if result.returncode and not (allow_partial and result.returncode == 1):
        return "", result.stderr.strip() or f"o comando terminou com código {result.returncode}"
    return result.stdout, None


def parse_flatpak_installed(output):
    """Return installed Flatpak application IDs with versions and remotes."""
    installed = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if not fields or fields[0].strip().lower() == "application":
            continue
        application = fields[0].strip()
        if not application or "." not in application:
            continue
        installed[application] = (
            fields[1].strip() if len(fields) > 1 else "",
            fields[2].strip() if len(fields) > 2 else "",
        )
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
    snap_update_output="", checked_sources=(),
):
    """Combine desktop launchers with package versions and known update status."""
    flatpak_apps = parse_flatpak_installed(flatpak_output)
    flatpak_updates = parse_flatpak_upgradable_apps(flatpak_update_output)
    snap_apps = parse_snap_installed(snap_output)
    snap_updates = parse_snap_upgradable(snap_update_output)
    apt_updates = {
        package: candidate for package, _installed, candidate in apt_upgradable
    }
    checked_sources = set(checked_sources)
    inventory = []
    seen = set()
    for application in applications:
        name = application.get("name", "").strip()
        desktop_file = application.get("desktop_file", "")
        if not name or not desktop_file:
            continue
        flatpak_id = desktop_file.rsplit("/", 1)[-1].removesuffix(".desktop")
        package = package_owners.get(desktop_file, "")
        command = application.get("command", "").casefold()
        candidate = None
        if flatpak_id in flatpak_apps or "/flatpak/" in desktop_file:
            version, remote = flatpak_apps.get(flatpak_id, ("", ""))
            origin = f"Flatpak · {remote}" if remote else "Flatpak"
            package = flatpak_id
            source = "Flatpak"
            candidate = flatpak_updates.get(flatpak_id)
        elif package:
            version = (
                package_versions.get(package)
                or package_versions.get(package.split(":", 1)[0])
                or ""
            )
            origin = "APT/DEB"
            source = "APT/DEB"
            candidate = (
                apt_updates.get(package)
                or apt_updates.get(package.split(":", 1)[0])
            )
        elif (
            desktop_file.startswith("/var/lib/snapd/desktop/applications/")
            or command.startswith("/snap/")
        ):
            snap_name = flatpak_id.split("_", 1)[0]
            if snap_name not in snap_apps and command.startswith("/snap/"):
                snap_name = command.split("/", 3)[2]
            package = snap_name
            version = snap_apps.get(package, "")
            origin = "Snap"
            source = "Snap"
            candidate = snap_updates.get(package) if package else None
        elif ".appimage" in command or ".appimage" in desktop_file.casefold():
            version = ""
            origin = "AppImage / arquivo local"
            source = "AppImage"
        else:
            version = ""
            origin = "Manual / origem não identificada"
            source = "Manual/outro"

        if candidate:
            update_status = "Atualização disponível"
        elif source in checked_sources:
            update_status = "Atualizado"
        elif source in ("AppImage", "Manual/outro"):
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
    return sorted(inventory, key=lambda item: (item["name"].casefold(), item["package"].casefold()))


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
