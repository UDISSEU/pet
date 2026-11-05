"""Despacho controlado: valida entrada, reconsulta permissões e registra resultado."""

from ..core.errors import ToolError
from .action_log import ActionLog
from .action_validator import ActionValidator, DirectoryAccessPolicy
from .base import CancellationToken, ToolContext, ToolCancelled, ToolTimedOut
from .results import ActionResult
import time


class ToolDispatchError(ToolError):
    code = "tool_dispatch_error"


class AuthorizationRequired(ToolDispatchError):
    code = "authorization_required"


class ToolDispatcher:
    def __init__(self, registry, permissions, *, plugin_id="nova.core",
                 validator=None, action_log=None, directory_policy=None):
        self.registry = registry
        self.permissions = permissions
        self.plugin_id = plugin_id
        self.validator = validator or ActionValidator()
        self.action_log = action_log or ActionLog()
        self.directory_policy = (directory_policy if directory_policy is not None else
                                 getattr(registry, "directory_policy", None) or DirectoryAccessPolicy())

    def dispatch(self, name, arguments=None, *, approved=False, cancellation=None):
        arguments = {} if arguments is None else arguments
        if cancellation is None:
            cancellation = CancellationToken()
        elif not isinstance(cancellation, CancellationToken):
            raise TypeError("cancellation deve ser CancellationToken")
        started = time.monotonic()
        try:
            definition = self.registry.get(name)
            if definition.source != "local":
                raise ToolDispatchError("Ferramentas externas não são executadas no dispatcher local")
            self.validator.validate(name, arguments)
            context = ToolContext(cancellation, started + definition.timeout_seconds)
            context.checkpoint()
            permissions = (definition.permission, *getattr(definition, "additional_permissions", ()))
            missing = tuple(permission for permission in permissions
                            if not self.permissions.allowed(self.plugin_id, permission))
            if missing:
                raise AuthorizationRequired("A ferramenta requer permissões ainda não concedidas")
            if definition.requires_confirmation and approved is not True:
                raise AuthorizationRequired("Ação aguarda aprovação explícita")
            for permission in permissions:
                self.permissions.require(
                    self.plugin_id, permission,
                    confirmed=bool(approved and definition.requires_confirmation),
                )
            for key in ("root", "directory"):
                if key in arguments:
                    arguments[key] = str(self.directory_policy.require(self.plugin_id, arguments[key]))
            result = definition.tool.execute_with_context(dict(arguments), context)
            if not isinstance(result, ActionResult):
                raise ToolDispatchError("Ferramenta retornou resultado inválido")
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            outcome = "cancelled" if isinstance(exc, ToolCancelled) else (
                "timeout" if isinstance(exc, ToolTimedOut) else "failed"
            )
            self.action_log.record(name, outcome, error_code=code)
            if isinstance(exc, ToolDispatchError):
                raise
            raise ToolDispatchError("Ação não executada; verifique permissões e argumentos.", cause=exc) from exc
        self.action_log.record(name, "succeeded" if result.success else "failed")
        return result
