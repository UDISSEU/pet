"""Priority-aware state coordinator for existing Nova poses and animations."""
from dataclasses import dataclass
from enum import Enum
import logging
import time

logger = logging.getLogger(__name__)


class PetState(str, Enum):
    IDLE = "idle"
    WALKING = "walk"
    RUNNING = "running"  # No dedicated running animation; intentionally unsupported.
    WAVING = "greeting"
    SITTING = "sitting"
    SLEEPING = "resting"
    TALKING = "talking"
    THINKING = "thinking"
    INTERACTING = "held"
    WORKING = "focused"
    CUSTOM = "custom"


@dataclass(frozen=True)
class StateTransition:
    previous: str
    current: str
    priority: int
    generation: int
    changed_at: float


class StateManager:
    """Coordinates state writes; callers retain rendering and Tk timer ownership."""
    TEMPORARY = {"greeting", "curious", "yawning", "celebrating", "cheering", "thumbs_up", "vanishing", "oops"}
    PRIORITY = {"shutdown": 100, "held": 80, "thinking": 60, "greeting": 50,
                "focused": 45, "sitting": 30, "walk": 20, "idle": 0}

    def __init__(self, initial="idle", on_change=None):
        self.current = str(initial)
        self.previous = None
        self.generation = 0
        self.priority = self.PRIORITY.get(self.current, 10)
        self.on_change = on_change
        self._temporary = None

    def transition(self, state, *, priority=None, force=False, temporary=False):
        state = state.value if isinstance(state, PetState) else str(state)
        if not state or state == "running":
            return False
        requested = self.PRIORITY.get(state, 40 if state in self.TEMPORARY else 10) if priority is None else int(priority)
        if state == self.current:
            return False
        if not force and self._temporary and requested < self.priority:
            return False
        if not force and requested < self.priority and self.current in self.TEMPORARY:
            return False
        old = self.current
        self.previous, self.current = old, state
        self.generation += 1
        self.priority = requested
        self._temporary = (old, self.generation) if temporary else None
        change = StateTransition(old, state, requested, self.generation, time.monotonic())
        if self.on_change:
            try:
                self.on_change(change)
            except Exception:
                logger.exception("Callback de transição de estado falhou")
        return True

    def restore(self, *, force=False):
        if not self._temporary:
            return False
        previous, generation = self._temporary
        if generation != self.generation:
            return False
        return self.transition(previous, force=True)

    def recover(self):
        self._temporary = None
        return self.transition("idle", force=True)
