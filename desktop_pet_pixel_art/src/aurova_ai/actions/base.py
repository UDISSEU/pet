"""Interface abstrata para ferramentas sem execução implícita de ações."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import threading
import time

from ..core.errors import ToolError


class ToolCancelled(ToolError):
    code = "tool_cancelled"


class ToolTimedOut(ToolError):
    code = "tool_timeout"


class CancellationToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self):
        return self._event.is_set()


@dataclass(frozen=True)
class ToolContext:
    cancellation: CancellationToken
    deadline: float

    def checkpoint(self):
        if self.cancellation.cancelled:
            raise ToolCancelled("Ação cancelada")
        if time.monotonic() >= self.deadline:
            raise ToolTimedOut("Tempo limite da ferramenta excedido")


class Tool(ABC):
    name = ""
    description = ""

    @abstractmethod
    def execute(self, arguments):
        """Executa argumentos validados pela integração chamadora."""

    def execute_with_context(self, arguments, context):
        context.checkpoint()
        result = self.execute(arguments)
        context.checkpoint()
        return result


__all__ = ["Tool", "ToolError", "ToolContext", "CancellationToken", "ToolCancelled", "ToolTimedOut"]
