"""Safe commands and metadata helpers for managing installed applications."""

import os
import re
import shutil
import subprocess
from pathlib import Path


_APT_ID = re.compile(r"^[a-z0-9][a-z0-9+.-]*(?::[a-z0-9-]+)?$")
_FLATPAK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SNAP_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _manager_reference(app):
    if not isinstance(app, dict):
        raise ValueError("Aplicativo inválido.")
    source = app.get("source")
    reference = app.get("package")
    if not isinstance(reference, str) or reference in ("", "—"):
        raise ValueError("O aplicativo não tem identificador gerenciado confiável.")
    pattern = {"APT/DEB": _APT_ID, "Flatpak": _FLATPAK_ID, "Snap": _SNAP_ID}.get(source)
    if pattern is None or not pattern.fullmatch(reference):
        raise ValueError("Esta origem não permite uma operação gerenciada segura.")
    return source, reference


def build_update_command(app):
    source, reference = _manager_reference(app)
    if source == "APT/DEB":
        return ["pkexec", "apt-get", "-o", "Dpkg::Use-Pty=0",
                "install", "--only-upgrade", "-y", reference]
    if source == "Flatpak":
        return ["flatpak", "update", "--noninteractive", "--assumeyes", reference]
    return ["pkexec", "snap", "refresh", reference]


def build_update_all_commands(apps):
    """Build grouped commands only from currently listed installed apps."""
    grouped = {"APT/DEB": [], "Flatpak": [], "Snap": []}
    for app in apps:
        source, reference = _manager_reference(app)
        if source not in grouped:
            raise ValueError("A lista inclui um aplicativo sem gerenciador confiável.")
        if reference not in grouped[source]:
            grouped[source].append(reference)
    commands = []
    for source, references in grouped.items():
        if not references:
            continue
        if source == "APT/DEB":
            commands.append(["pkexec", "apt-get", "-o", "Dpkg::Use-Pty=0",
                             "install", "--only-upgrade", "-y", *references])
        elif source == "Flatpak":
            commands.append(["flatpak", "update", "--noninteractive", "--assumeyes", *references])
        else:
            commands.append(["pkexec", "snap", "refresh", *references])
    return commands


def build_uninstall_command(app):
    source, reference = _manager_reference(app)
    if source == "APT/DEB":
        return ["pkexec", "apt-get", "-o", "Dpkg::Use-Pty=0", "remove", "-y", "--", reference]
    if source == "Flatpak":
        return ["flatpak", "uninstall", "--noninteractive", "--assumeyes",
                "--no-related", reference]
    return ["pkexec", "snap", "remove", reference]


def preview_uninstall(app, *, run=subprocess.run, env=None, timeout=60):
    """Return a non-privileged removal preview for APT; explain other managers."""
    source, reference = _manager_reference(app)
    if source == "APT/DEB":
        command = ["apt-get", "-s", "remove", "--", reference]
        result = run(command, capture_output=True, text=True, timeout=timeout,
                     check=False, env=env)
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode:
            raise RuntimeError(output.strip() or "O APT não conseguiu simular a remoção.")
        removals = []
        for line in output.splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[0] in ("Remv", "Purg"):
                removals.append(fields[1])
        return {"manager": source, "reference": reference,
                "packages": removals or [reference],
                "details": output[-12000:],
                "personal_data": "O APT simula pacotes que seriam removidos; arquivos pessoais não são incluídos."}
    if source == "Flatpak":
        return {"manager": source, "reference": reference, "packages": [reference],
                "details": "A remoção usa --no-related para não remover runtimes relacionados automaticamente.",
                "personal_data": "Preferências e arquivos pessoais não são apagados pela Nova."}
    return {"manager": source, "reference": reference, "packages": [reference],
            "details": "O Snap remove os dados internos do aplicativo e normalmente salva um snapshot local por até 31 dias. A Nova não usa --purge.",
            "personal_data": "Confirme a remoção sabendo que os dados internos do Snap serão removidos do uso ativo."}


def resolve_executable(app, *, which=shutil.which):
    """Resolve an executable without executing an app-provided command string."""
    if not isinstance(app, dict):
        return None
    source = app.get("source")
    if source == "AppImage":
        path = Path(str(app.get("package", "")))
        try:
            if (path.is_absolute() and path.suffix.casefold() == ".appimage"
                    and not path.is_symlink() and path.is_file() and os.access(path, os.X_OK)):
                return str(path.resolve())
        except OSError:
            pass
        return None
    command = app.get("command", "")
    if not isinstance(command, str):
        return None
    import shlex
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv:
        return None
    return which(argv[0])


def open_installed_application(app, *, popen=subprocess.Popen, which=shutil.which,
                               env=None):
    """Open a discovered desktop entry through GIO, or a validated inventoried AppImage."""
    if not isinstance(app, dict):
        raise ValueError("Aplicativo inválido.")
    if app.get("source") == "AppImage":
        executable = resolve_executable(app, which=which)
        if executable is None:
            raise ValueError("O AppImage não existe ou não é executável.")
        return popen([executable], close_fds=True, env=env)

    desktop_file = Path(str(app.get("desktop_file", "")))
    if not desktop_file.is_absolute() or desktop_file.is_symlink() or not desktop_file.is_file():
        raise ValueError("O atalho não está disponível ou é inseguro.")
    allowed_roots = []
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(os.pathsep)
    allowed_roots.extend([data_home / "applications", *(Path(item) / "applications" for item in data_dirs if item)])
    allowed_roots.extend([
        Path.home() / ".local/share/flatpak/exports/share/applications",
        Path("/var/lib/flatpak/exports/share/applications"),
        Path("/var/lib/snapd/desktop/applications"),
    ])
    resolved = desktop_file.resolve()
    if not any(_within(resolved, root) for root in allowed_roots):
        raise ValueError("O atalho não pertence aos diretórios conhecidos de aplicativos.")
    gio = which("gio")
    if not gio:
        raise FileNotFoundError("O utilitário GIO não está disponível.")
    return popen([gio, "launch", str(resolved)], close_fds=True, env=env)


def _within(path, root):
    try:
        path.relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def display_location(app, *, which=shutil.which):
    if not isinstance(app, dict):
        return "Não disponível"
    executable = resolve_executable(app, which=which)
    desktop_file = app.get("desktop_file", "")
    if isinstance(desktop_file, str) and desktop_file.startswith("appstream:"):
        desktop_file = ""
    return executable or app.get("location") or desktop_file or "Não disponível"


def resolve_icon_path(app):
    """Resolve a desktop icon only inside standard XDG icon locations."""
    if not isinstance(app, dict):
        return None
    icon = app.get("icon")
    if not isinstance(icon, str) or not icon:
        return None
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    data_dirs = os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(os.pathsep)
    roots = [data_home / "icons", *(Path(item) / "icons" for item in data_dirs if item), Path("/usr/share/pixmaps")]
    candidate = Path(icon)
    if candidate.is_absolute():
        paths = [candidate]
    else:
        if Path(icon).name != icon:
            return None
        paths = [root / f"{icon}{suffix}" for root in roots
                 for suffix in ("", ".png", ".xpm", ".gif")]
        paths.extend(
            root / theme / size / "apps" / f"{icon}{suffix}"
            for root in roots for theme in ("hicolor", "Adwaita")
            for size in ("scalable", "256x256", "128x128", "64x64", "48x48", "32x32", "24x24")
            for suffix in (".png", ".xpm", ".gif")
        )
    for path in paths:
        try:
            resolved = path.resolve(strict=True)
            if (path.is_symlink() or not resolved.is_file()
                    or not any(_within(resolved, root) for root in roots)):
                continue
            return resolved
        except OSError:
            continue
    return None
