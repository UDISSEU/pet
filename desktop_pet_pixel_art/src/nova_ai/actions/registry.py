"""Registro explícito de ferramentas, permissões e efeitos colaterais."""

from dataclasses import dataclass

from ..core.errors import NovaAIError
from .base import Tool


class ActionRegistryError(NovaAIError):
    code = "action_registry_error"


class ActionNotFoundError(ActionRegistryError):
    code = "action_not_found"


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    tool: Tool
    permission: str
    read_only: bool
    requires_confirmation: bool
    additional_permissions: tuple[str, ...] = ()
    timeout_seconds: float = 5.0
    source: str = "local"


class ActionRegistry:
    def __init__(self):
        self._actions = {}

    def register(self, name, tool, *, permission, read_only, requires_confirmation=False,
                 additional_permissions=(), timeout_seconds=5.0, source="local"):
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ActionRegistryError("Nome de ação inválido")
        if not isinstance(tool, Tool):
            raise ActionRegistryError("Ação precisa implementar Tool")
        if not isinstance(permission, str) or not permission.strip():
            raise ActionRegistryError("Ação precisa declarar uma permissão")
        if (not isinstance(additional_permissions, (tuple, list))
                or any(not isinstance(item, str) or not item.strip()
                       for item in additional_permissions)):
            raise ActionRegistryError("Permissões adicionais inválidas")
        if type(read_only) is not bool or type(requires_confirmation) is not bool:
            raise ActionRegistryError("Metadados de segurança inválidos")
        if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
                or not 0.05 <= timeout_seconds <= 60):
            raise ActionRegistryError("timeout_seconds deve estar entre 0.05 e 60")
        if source != "local":
            raise ActionRegistryError("Plugins externos usam o runtime isolado de plugins")
        if read_only and requires_confirmation:
            raise ActionRegistryError("Ação somente leitura não pode exigir confirmação de mudança")
        if not read_only and not requires_confirmation:
            raise ActionRegistryError("Ação com efeitos colaterais exige confirmação")
        if name in self._actions:
            raise ActionRegistryError(f"Ação já registrada: {name}")
        definition = ActionDefinition(name, tool, permission, read_only,
                                      requires_confirmation, tuple(additional_permissions),
                                      float(timeout_seconds), source)
        self._actions[name] = definition
        return definition

    def get(self, name):
        try:
            return self._actions[name]
        except KeyError as exc:
            raise ActionNotFoundError(f"Ação não registrada: {name}") from exc

    def contains(self, name):
        return name in self._actions

    def names(self):
        return tuple(self._actions)
