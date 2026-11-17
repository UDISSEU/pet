"""Decide se um plano está claro, requer esclarecimento ou confirmação."""

from dataclasses import dataclass
from enum import Enum

from .task_state import CognitiveTask, TaskStatus


class DecisionKind(str, Enum):
    ASK_CLARIFICATION = "ask_clarification"
    PRESENT_PLAN = "present_plan"
    REQUIRE_CONFIRMATION = "require_confirmation"
    REQUEST_PERMISSION = "request_permission"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    reason: str
    confirmation_required: bool = False
    permissions_required: tuple[str, ...] = ()


class DecisionEngine:
    def evaluate(self, task, *, missing_permissions=()):
        if not isinstance(task, CognitiveTask):
            raise TypeError("task deve ser CognitiveTask")
        if task.status is TaskStatus.NEEDS_CLARIFICATION:
            return Decision(
                DecisionKind.ASK_CLARIFICATION,
                "A intenção está ausente ou pouco confiante.",
            )
        if missing_permissions:
            return Decision(
                DecisionKind.REQUEST_PERMISSION,
                "A tarefa requer permissões que ainda não foram concedidas.",
                confirmation_required=any(step.has_side_effect for step in task.steps),
                permissions_required=tuple(missing_permissions),
            )
        if any(step.has_side_effect for step in task.steps):
            return Decision(
                DecisionKind.REQUIRE_CONFIRMATION,
                "O plano contém uma operação que altera arquivos.",
                confirmation_required=True,
            )
        return Decision(DecisionKind.PRESENT_PLAN, "O plano não contém efeitos colaterais.")
