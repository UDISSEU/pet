"""Cenários offline de interpretação, planejamento e guarda de execução."""

from pathlib import Path
import sys
import unittest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nova_ai.actions import ActionRegistry, ActionResult, Tool
from nova_ai.cognition import (
    CognitiveEngine, DecisionKind, Intent, IntentName, ResultValidationError,
    ResultValidator, TaskStatus,
)


class Permissions:
    def __init__(self, granted=()):
        self.granted = set(granted)

    def allowed(self, plugin, permission):
        return permission in self.granted

    def require(self, plugin, permission, *, confirmed=False):
        if permission not in self.granted:
            raise PermissionError(permission)
        if permission == "file.organize" and not confirmed:
            raise PermissionError("confirmation required")
        return True


class PreviewTool(Tool):
    def __init__(self):
        self.calls = 0

    def execute(self, arguments):
        self.calls += 1
        return ActionResult(True, "Prévia verificada", {"items": 2})


class OrganizeTool(Tool):
    def __init__(self):
        self.calls = 0

    def execute(self, arguments):
        self.calls += 1
        return ActionResult(True, "Organização executada", {"moved": 2})


def actions_for(preview=None, organize=None):
    registry = ActionRegistry()
    registry.register("files.preview_downloads", preview or PreviewTool(),
                      permission="file.read", read_only=True)
    registry.register("files.organize_downloads", organize or OrganizeTool(),
                      permission="file.organize", read_only=False,
                      requires_confirmation=True)
    return registry


class CognitionTests(unittest.TestCase):
    def test_simple_known_request_becomes_structured_plan(self):
        result = CognitiveEngine().interpret("Nova, organize meus arquivos de Downloads.")
        self.assertEqual(result.intent.name, IntentName.ORGANIZE_DOWNLOADS)
        self.assertEqual(result.decision.kind, DecisionKind.REQUEST_PERMISSION)
        self.assertEqual(result.decision.permissions_required, ("file.organize", "file.read"))

    def test_multistep_plan_declares_ordered_dependencies(self):
        engine = CognitiveEngine(
            actions=actions_for(),
            permissions=Permissions({"file.read", "file.organize"}),
        )
        result = engine.interpret("Organize meus Downloads")
        self.assertTrue(result.files_checked)
        steps = {step.step_id: step for step in result.task.steps}
        self.assertEqual(steps["present_preview"].depends_on, ("inspect",))
        self.assertEqual(steps["confirm"].depends_on, ("present_preview",))
        self.assertEqual(steps["organize"].depends_on, ("confirm",))
        self.assertEqual(steps["report"].depends_on, ("organize",))

    def test_invalid_request_is_rejected_and_unknown_is_clarified(self):
        engine = CognitiveEngine()
        with self.assertRaises(ValueError):
            engine.interpret("   ")
        result = engine.interpret("Conte uma curiosidade")
        self.assertEqual(result.decision.kind, DecisionKind.ASK_CLARIFICATION)
        self.assertEqual(result.task.status, TaskStatus.NEEDS_CLARIFICATION)

    def test_cancelled_task_cannot_reach_executor(self):
        organizer = OrganizeTool()
        engine = CognitiveEngine(
            actions=actions_for(organize=organizer),
            permissions=Permissions({"file.read", "file.organize"}),
            result_verifier=lambda *_: True,
        )
        prepared = engine.interpret("Organize meus Downloads")
        cancelled = engine.cancel(prepared)
        outcome = engine.execute(cancelled, approved=True)
        self.assertEqual(outcome.status, TaskStatus.CANCELLED)
        self.assertEqual(organizer.calls, 0)

    def test_missing_authorization_blocks_execution(self):
        organizer = OrganizeTool()
        engine = CognitiveEngine(
            actions=actions_for(organize=organizer), permissions=Permissions(),
        )
        prepared = engine.interpret("Organize meus Downloads")
        outcome = engine.execute(prepared, approved=True)
        self.assertEqual(prepared.decision.kind, DecisionKind.REQUEST_PERMISSION)
        self.assertEqual(outcome.status, TaskStatus.AWAITING_PERMISSION)
        self.assertEqual(organizer.calls, 0)

    def test_execution_requires_confirmation_and_independent_verification(self):
        organizer = OrganizeTool()
        engine = CognitiveEngine(
            actions=actions_for(organize=organizer),
            permissions=Permissions({"file.read", "file.organize"}),
        )
        prepared = engine.interpret("Organize meus Downloads")
        unverified = engine.execute(prepared, approved=True)
        self.assertEqual(unverified.status, TaskStatus.UNVERIFIED)
        self.assertFalse(unverified.verified)

        verified_engine = CognitiveEngine(
            actions=actions_for(),
            permissions=Permissions({"file.read", "file.organize"}),
            result_verifier=lambda operation, result, params: result.data.get("moved") == 2,
        )
        verified_prepared = verified_engine.interpret("Organize meus Downloads")
        verified = verified_engine.execute(verified_prepared, approved=True)
        self.assertEqual(verified.status, TaskStatus.SUCCEEDED)
        self.assertTrue(verified.verified)

    def test_plan_rejects_forward_or_missing_dependency(self):
        engine = CognitiveEngine()
        prepared = engine.interpret("Organize meus Downloads")
        steps = list(prepared.task.steps)
        steps[0] = steps[0].__class__(
            steps[0].step_id, steps[0].description, steps[0].operation,
            steps[0].has_side_effect, steps[0].requires_confirmation,
            steps[0].parameters, ("later-step",),
        )
        invalid = prepared.task.__class__(
            prepared.task.task_id, prepared.task.intent, prepared.task.goal,
            prepared.task.status, tuple(steps), prepared.task.clarification_question,
            prepared.task.supporting_memory_ids, prepared.task.created_at,
        )
        with self.assertRaises(ResultValidationError):
            ResultValidator().validate_plan(prepared.intent, invalid, prepared.decision)


if __name__ == "__main__":
    unittest.main()
