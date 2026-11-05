"""Fachada do núcleo sem Tkinter, rede, modelos ou threads implícitos."""

from .config import NovaAIConfig
from .errors import InitializationError, normalize_error
from .registry import ComponentRegistry


class NovaAI:
    def __init__(self, config=None, registry=None):
        self.config = config if config is not None else NovaAIConfig()
        if not isinstance(self.config, NovaAIConfig):
            raise InitializationError("config deve ser uma instância de NovaAIConfig")
        self.registry = registry if registry is not None else ComponentRegistry(
            max_components=self.config.max_registered_components
        )
        if not isinstance(self.registry, ComponentRegistry):
            raise InitializationError("registry deve ser uma instância de ComponentRegistry")
        self._initialized = False
        self._started_components = set()

    @property
    def initialized(self):
        return self._initialized

    def initialize(self):
        """Valida composição local e marca o núcleo pronto; não inicia recursos externos."""
        self._initialized = True
        return self

    def register(self, name, component):
        if self._initialized:
            raise InitializationError("Não é possível registrar componentes após initialize()")
        return self.registry.register(name, component)

    def initialize_component(self, name):
        """Inicializa um componente explicitamente, sob demanda, sem descoberta automática."""
        if not self._initialized:
            raise InitializationError("Inicialize o núcleo antes de iniciar componentes")
        if name in self._started_components:
            return None
        component = self.registry.get(name)
        initialize = getattr(component, "initialize", None)
        if not callable(initialize):
            raise InitializationError(f"Componente não inicializável: {name}")
        try:
            result = initialize()
        except Exception as exc:
            raise InitializationError(
                f"Falha ao inicializar componente: {name}", cause=normalize_error(exc)
            ) from exc
        self._started_components.add(name)
        return result
