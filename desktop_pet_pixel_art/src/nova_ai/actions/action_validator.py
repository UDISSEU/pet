"""Validação genérica de argumentos antes de despachar uma ferramenta."""

from pathlib import Path
import math
import os
import stat


class ActionValidationError(ValueError):
    pass


class ActionValidator:
    _FORBIDDEN_KEYS = {
        "command", "cmd", "command_line", "commandline", "shell", "shell_command",
        "exec", "executable", "argv", "script", "script_path",
    }

    def validate(self, action, arguments):
        if not isinstance(action, str) or not action or len(action) > 120:
            raise ActionValidationError("Identificador de ação inválido")
        if not isinstance(arguments, dict) or len(arguments) > 32:
            raise ActionValidationError("Argumentos devem ser um objeto limitado")
        self._validate_value(arguments, depth=0)
        return arguments

    def _validate_value(self, value, *, depth):
        if depth > 5:
            raise ActionValidationError("Argumentos excedem a profundidade permitida")
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > 80:
                    raise ActionValidationError("Chave de argumento inválida")
                if key.casefold() in self._FORBIDDEN_KEYS:
                    raise ActionValidationError("Execução de comandos não é suportada")
                self._validate_value(child, depth=depth + 1)
        elif isinstance(value, (list, tuple)):
            if len(value) > 500:
                raise ActionValidationError("Lista de argumentos excede o limite")
            for child in value:
                self._validate_value(child, depth=depth + 1)
        elif isinstance(value, str):
            if len(value) > 4_096 or "\x00" in value:
                raise ActionValidationError("Texto de argumento inválido")
        elif type(value) is float and not math.isfinite(value):
            raise ActionValidationError("Número não finito não é permitido")
        elif value is not None and type(value) not in {bool, int, float}:
            if not isinstance(value, Path):
                raise ActionValidationError("Tipo de argumento não suportado")


class DirectoryAccessPolicy:
    """Allowlist de raízes de diretório por integração/plugin local."""

    def __init__(self, authorized_roots=None):
        default = {"nova.core": (Path.home() / "Downloads",)}
        self._roots = {}
        configured = default if authorized_roots is None else authorized_roots
        for plugin, roots in configured.items():
            for root in roots:
                requested = Path(root).expanduser().absolute()
                if self.has_symlink_component(requested):
                    continue
                if requested.is_dir():
                    self._roots.setdefault(plugin, []).append(requested)

    def authorize(self, plugin_id, directory):
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise ActionValidationError("Plugin inválido para autorização de diretório")
        requested = Path(directory).expanduser()
        if (not requested.is_absolute() or ".." in requested.parts
                or self.has_symlink_component(requested) or not requested.exists()
                or not requested.is_dir()):
            raise ActionValidationError("Somente diretórios existentes podem ser autorizados")
        root = requested.absolute()
        roots = self._roots.setdefault(plugin_id, [])
        if root not in roots:
            roots.append(root)
        return root

    def require(self, plugin_id, directory):
        if not isinstance(directory, (str, Path)) or not str(directory).strip():
            raise ActionValidationError("Diretório não informado")
        requested = Path(directory).expanduser()
        if self.has_symlink_component(requested):
            raise ActionValidationError("Acesso a links simbólicos não é permitido")
        if not requested.is_absolute() or ".." in requested.parts:
            raise ActionValidationError("Caminho de diretório malformado")
        candidate = requested.absolute()
        for root in self._roots.get(plugin_id, ()):
            if candidate == root or root in candidate.parents:
                return candidate
        raise ActionValidationError("Diretório não autorizado para esta ferramenta")

    @staticmethod
    def has_symlink_component(path):
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = candidate.absolute()
        if ".." in candidate.parts:
            return True
        current = Path(candidate.anchor)
        for component in candidate.parts[1:]:
            current = current / component
            try:
                mode = os.lstat(current).st_mode
            except FileNotFoundError:
                # Missing descendants cannot currently be symlinks; continue
                # checking any existing ancestor on subsequent iterations.
                continue
            except OSError:
                return True
            if stat.S_ISLNK(mode):
                return True
        return False
