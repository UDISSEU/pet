"""Configuração pequena e validada para inicializar o núcleo sem side effects."""

from dataclasses import dataclass

from .errors import ConfigurationError


@dataclass(frozen=True)
class NovaAIConfig:
    """Limites conservadores; nenhum modelo ou processo é iniciado por padrão."""

    max_context_chars: int = 8_000
    max_memory_items: int = 32
    max_memory_item_chars: int = 1_000
    max_registered_components: int = 64
    load_model_on_start: bool = False
    start_training_on_start: bool = False

    def __post_init__(self):
        bounds = {
            "max_context_chars": (256, 32_000),
            "max_memory_items": (0, 256),
            "max_memory_item_chars": (64, 4_000),
            "max_registered_components": (1, 256),
        }
        for field_name, (minimum, maximum) in bounds.items():
            value = getattr(self, field_name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ConfigurationError(
                    f"{field_name} deve ser um inteiro entre {minimum} e {maximum}"
                )
        if type(self.load_model_on_start) is not bool:
            raise ConfigurationError("load_model_on_start deve ser booleano")
        if self.load_model_on_start:
            raise ConfigurationError(
                "Modelos devem ser carregados explicitamente após a inicialização"
            )
        if type(self.start_training_on_start) is not bool:
            raise ConfigurationError("start_training_on_start deve ser booleano")
        if self.start_training_on_start:
            raise ConfigurationError(
                "Treinamento não pode ser iniciado durante a inicialização do núcleo"
            )
