"""Envelope estruturado retornado por ferramentas registradas."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ActionResult:
    success: bool
    summary: str
    data: dict = field(default_factory=dict)

    def __post_init__(self):
        if type(self.success) is not bool or not isinstance(self.summary, str):
            raise TypeError("ActionResult exige success bool e summary texto")
        if not isinstance(self.data, dict):
            raise TypeError("data deve ser um dicionário")
