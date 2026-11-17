"""Registro explícito e leve de componentes; não descobre nem inicia plugins."""

from .errors import ComponentNotFoundError, ComponentRegistrationError


class ComponentRegistry:
    def __init__(self, *, max_components=64):
        if type(max_components) is not int or max_components < 1:
            raise ComponentRegistrationError("max_components deve ser um inteiro positivo")
        self._max_components = max_components
        self._components = {}

    def register(self, name, component):
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ComponentRegistrationError("Nome do componente inválido")
        if component is None:
            raise ComponentRegistrationError("Componente não pode ser None")
        if name in self._components:
            raise ComponentRegistrationError(f"Componente já registrado: {name}")
        if len(self._components) >= self._max_components:
            raise ComponentRegistrationError("Limite de componentes registrados atingido")
        self._components[name] = component
        return component

    def get(self, name):
        try:
            return self._components[name]
        except KeyError as exc:
            raise ComponentNotFoundError(f"Componente não encontrado: {name}") from exc

    def contains(self, name):
        return name in self._components

    def names(self):
        return tuple(self._components)

    def __len__(self):
        return len(self._components)
