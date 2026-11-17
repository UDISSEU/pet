"""Erros estáveis da Aurova AI, sem expor detalhes privados por padrão."""


class AurovaAIError(Exception):
    """Erro base com código estável e mensagem segura para a camada chamadora."""

    code = "aurova_ai_error"

    def __init__(self, message="Falha na Aurova AI", *, cause=None):
        super().__init__(message)
        self.cause = cause


class ConfigurationError(AurovaAIError):
    code = "configuration_error"


class ComponentRegistrationError(AurovaAIError):
    code = "component_registration_error"


class ComponentNotFoundError(AurovaAIError):
    code = "component_not_found"


class InitializationError(AurovaAIError):
    code = "initialization_error"


class ModelError(AurovaAIError):
    code = "model_error"


class ToolError(AurovaAIError):
    code = "tool_error"


def normalize_error(error):
    """Converte exceções inesperadas em erro público sem propagar seu texto."""
    if isinstance(error, AurovaAIError):
        return error
    return AurovaAIError("Falha interna na Aurova AI", cause=error)


NovaAIError = AurovaAIError
