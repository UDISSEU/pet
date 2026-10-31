"""Parsing helpers for the APT maintenance screens."""

import re
import subprocess


def run_commands(commands, env, timeout=600):
    """Run a fixed command sequence, stopping at the first failure."""
    output = []
    try:
        for command in commands:
            completed = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout,
                check=False, env=env,
            )
            details = (completed.stdout or "") + (completed.stderr or "")
            if details.strip():
                output.append(details.strip())
            if completed.returncode != 0:
                error = details.strip() or f"O comando terminou com código {completed.returncode}."
                return "\n\n".join(output), error
    except subprocess.TimeoutExpired:
        return "\n\n".join(output), "A operação demorou demais e foi interrompida."
    except OSError as exc:
        return "\n\n".join(output), f"Não consegui iniciar a ação: {exc}"
    return "\n\n".join(output), None


def parse_upgradable_packages(output):
    """Return package, installed version, and candidate version rows from apt."""
    packages = []
    for line in output.splitlines():
        if "upgradable" not in line.lower() or "/" not in line:
            continue
        fields = line.split()
        if len(fields) < 2:
            continue
        name = fields[0].split("/", 1)[0]
        candidate = fields[1]
        match = re.search(r"\[upgradable from: ([^\]]+)\]", line)
        installed = match.group(1) if match else ""
        packages.append((name, installed, candidate))
    return packages


def parse_removable_packages(output):
    """Return package rows from apt-get's simulated autoremove output."""
    packages = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] in ("Remv", "Purg"):
            version = fields[2].strip("[]") if len(fields) >= 3 else ""
            packages.append((fields[1], version, "Será removido"))
    return packages
