"""Tipos de tarefa e etapas planejadas; este módulo não executa ações."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import uuid


class TaskStatus(str, Enum):
    NEEDS_CLARIFICATION = "needs_clarification"
    PLANNED = "planned"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_PERMISSION = "awaiting_permission"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNVERIFIED = "unverified"
    CANCELLED = "cancelled"


# Public synonym: the persisted/current task state is its lifecycle status.
TaskState = TaskStatus


@dataclass(frozen=True)
class TaskStep:
    step_id: str
    description: str
    operation: str | None = None
    has_side_effect: bool = False
    requires_confirmation: bool = False
    parameters: dict = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class CognitiveTask:
    task_id: str
    intent: str
    goal: str
    status: TaskStatus
    steps: tuple[TaskStep, ...]
    clarification_question: str | None = None
    supporting_memory_ids: tuple[str, ...] = ()
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    @classmethod
    def create(cls, *, intent, goal, status, steps, clarification_question=None,
               supporting_memory_ids=()):
        return cls(
            task_id=uuid.uuid4().hex,
            intent=intent,
            goal=goal,
            status=status,
            steps=tuple(steps),
            clarification_question=clarification_question,
            supporting_memory_ids=tuple(supporting_memory_ids),
        )
