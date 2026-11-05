"""Erros estáveis da Nova AI, sem expor detalhes privados por padrão."""


class NovaAIError(Exception):
    """Erro base com código estável e mensagem segura para a camada chamadora."""

    code = "nova_ai_error"

    def __init__(self, message="Falha na Nova AI", *, cause=None):
        super().__init__(message)
        self.cause = cause


class ConfigurationError(NovaAIError):
    code = "configuration_error"


class ComponentRegistrationError(NovaAIError):
    code = "component_registration_error"


class ComponentNotFoundError(NovaAIError):
    code = "component_not_found"


class InitializationError(NovaAIError):
    code = "initialization_error"


class ModelError(NovaAIError):
    code = "model_error"


class ToolError(NovaAIError):
    code = "tool_error"


def normalize_error(error):
    """Converte exceções inesperadas em erro público sem propagar seu texto."""
    if isinstance(error, NovaAIError):
        return error
    return NovaAIError("Falha interna na Nova AI", cause=error)
