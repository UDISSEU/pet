"""Command construction and output parsing for supported package managers."""

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
_FLATPAK_ID = re.compile(r"^[A-Za-z0-9._-]+$")
_SNAP_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def apt_upgrade_command(package):
    """Build an APT command for one or more validated packages."""
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
    """Build a Flatpak update command for validated application IDs."""
    applications = (applications,) if isinstance(applications, str) else tuple(applications)
    if not applications or any(
        not isinstance(item, str) or not _FLATPAK_ID.fullmatch(item)
        for item in applications
    ):
        raise ValueError("Identificador de aplicativo Flatpak inválido.")
    return ["flatpak", "update", "--noninteractive", "--assumeyes", *applications]


def snap_upgrade_command(snaps):
    """Build a Snap update command for validated package names."""
    snaps = (snaps,) if isinstance(snaps, str) else tuple(snaps)
    if not snaps or any(
        not isinstance(item, str) or not _SNAP_NAME.fullmatch(item)
        for item in snaps
    ):
        raise ValueError("Identificador de pacote Snap inválido.")
    return ["pkexec", "snap", "refresh", *snaps]


def parse_package_activity(command, line):
    """Translate supported package-manager progress lines for the UI."""
    command_text = " ".join(command) if not isinstance(command, str) else command
    if "apt-get" in command_text:
        match = _APT_PACKAGE_ACTIVITY.match(line.strip())
        if match:
            action = "Configurando" if match.group("action") == "Setting up" else "Instalando"
            return (
                match.group("package").split(":", 1)[0],
                action,
                match.group("version") or "",
            )
    if "flatpak" in command_text:
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
    """Run a command, forward output, and enforce a wall-clock timeout."""
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
    """Return Flatpak app IDs, installed versions, and available versions."""
    installed = _flatpak_refs(installed_output)
    packages = []
    for ref, (candidate, candidate_commit) in _flatpak_refs(updates_output).items():
        ref_parts = ref.split("/")
        name = f"{ref_parts[0]} ({ref_parts[-1]})"
        installed_version, installed_commit = installed.get(ref, ("", ""))
        if candidate and candidate == installed_version and candidate_commit != installed_commit:
            candidate = f"{candidate} (nova revisão)"
        elif not candidate and candidate_commit:
            candidate = f"Revisão {candidate_commit[:12]}"
        packages.append((
            f"Flatpak · {name}",
            installed_version or "—",
            candidate or "Versão disponível",
        ))
    return packages
