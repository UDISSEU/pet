"""Fluxo cognitivo offline com permissões, execução explícita e verificação."""

from dataclasses import dataclass, replace
import logging

from ..actions.results import ActionResult
from ..actions.tool_dispatcher import ToolDispatcher
from ..memory.episodic_memory import EpisodicMemory
from .decision_engine import Decision, DecisionEngine, DecisionKind
from .intent_classifier import Intent, IntentClassifier, IntentName
from .planner import Planner
from .result_validator import ResultValidator
from .task_state import CognitiveTask, TaskStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CognitiveResult:
    intent: Intent
    task: CognitiveTask
    decision: Decision
    relevant_memories: tuple = ()
    files_checked: bool = False
    inspection: ActionResult | None = None

    def to_dict(self):
        return {
            "intent": self.intent.name.value,
            "confidence": self.intent.confidence,
            "classification_source": self.intent.source,
            "goal": self.task.goal,
            "status": self.task.status.value,
            "steps": [
                {"id": s.step_id, "description": s.description,
                 "operation": s.operation, "has_side_effect": s.has_side_effect,
                 "requires_confirmation": s.requires_confirmation,
                 "depends_on": list(s.depends_on),
                 "parameters": dict(s.parameters)} for s in self.task.steps
            ],
            "clarification_question": self.task.clarification_question,
            "decision": self.decision.kind.value,
            "confirmation_required": self.decision.confirmation_required,
            "permissions_required": list(self.decision.permissions_required),
            "files_checked": self.files_checked,
            "inspection_summary": self.inspection.summary if self.inspection else None,
            "relevant_memory_ids": [m.memory_id for m in self.relevant_memories],
            "task_id": self.task.task_id,
        }


@dataclass(frozen=True)
class ExecutionResult:
    task_id: str
    status: TaskStatus
    message: str
    action_result: ActionResult | None = None
    verified: bool = False
    experience_recorded: bool = False


class CognitiveEngine:
    """Não instancia interface, provedor, ferramenta ou processo implicitamente."""

    _OPERATIONS = {
        "files.preview_downloads": "file.read",
        "files.organize_downloads": "file.organize",
    }

    def __init__(self, *, model=None, memory=None, actions=None, permissions=None,
                 result_verifier=None, plugin_id="nova.core", classifier=None,
                 planner=None, decision_engine=None, validator=None, dispatcher=None,
                 action_log=None):
        self.model = model
        self.memory = memory
        self.actions = actions
        self.permissions = permissions
        self.dispatcher = dispatcher
        if self.dispatcher is None and actions is not None and permissions is not None:
            self.dispatcher = ToolDispatcher(
                actions, permissions, plugin_id=plugin_id, action_log=action_log
            )
        self.result_verifier = result_verifier
        self.plugin_id = plugin_id
        self.classifier = classifier if classifier is not None else IntentClassifier()
        self.planner = planner if planner is not None else Planner()
        self.decision_engine = decision_engine if decision_engine is not None else DecisionEngine()
        self.validator = validator if validator is not None else ResultValidator()

    def interpret(self, request, *, context=None):
        if not isinstance(request, str) or not request.strip() or len(request) > 4_000:
            raise ValueError("A solicitação deve ter entre 1 e 4000 caracteres")
        safe_context = self._context(context)
        try:
            memories = tuple(self.memory.search(request, limit=4)) if self.memory is not None else ()
            intent = self.classifier.classify(request, model=self.model)
            self.validator.validate_intent(intent)
            task = self.planner.plan(intent, context=safe_context, memories=memories)
        except Exception:
            logger.exception("Falha ao interpretar e planejar solicitação")
            raise

        missing = self._missing_permissions(task)
        # Inspeciona somente com permissão e ferramenta explicitamente registradas.
        inspection = None
        files_checked = False
        if intent.name is IntentName.ORGANIZE_DOWNLOADS and not missing:
            inspection = self._inspect(task)
            files_checked = inspection is not None and inspection.success

        decision = self.decision_engine.evaluate(task, missing_permissions=missing)
        if (intent.name is IntentName.ORGANIZE_DOWNLOADS and not missing
                and not files_checked):
            decision = Decision(
                DecisionKind.BLOCKED,
                "Não foi possível verificar os arquivos com uma ferramenta autorizada.",
                confirmation_required=True,
            )
        self.validator.validate_plan(intent, task, decision)
        return CognitiveResult(intent, task, decision, memories, files_checked, inspection)

    def execute(self, prepared, *, approved=False, memory_consent=False, cancellation=None):
        """Executa só plano aprovado; requer permissão reconsultada e verificador."""
        if not isinstance(prepared, CognitiveResult):
            raise TypeError("prepared deve ser CognitiveResult")
        if prepared.task.status is TaskStatus.CANCELLED:
            return ExecutionResult(prepared.task.task_id, TaskStatus.CANCELLED,
                                   "A tarefa foi cancelada.")
        if approved is not True:
            return ExecutionResult(prepared.task.task_id, TaskStatus.AWAITING_CONFIRMATION,
                                   "Aguardando aprovação explícita da tarefa.")
        task = prepared.task
        if (prepared.decision.kind is not DecisionKind.REQUIRE_CONFIRMATION
                or prepared.decision.permissions_required
                or not prepared.files_checked):
            status = (TaskStatus.AWAITING_PERMISSION
                      if prepared.decision.permissions_required
                      or prepared.decision.kind is DecisionKind.REQUEST_PERMISSION
                      else TaskStatus.FAILED)
            return ExecutionResult(task.task_id, status,
                                   "A verificação dos arquivos ou as permissões necessárias estão pendentes.")
        operation = "files.organize_downloads"
        step = next((s for s in task.steps if s.operation == operation), None)
        if step is None:
            return ExecutionResult(task.task_id, TaskStatus.FAILED,
                                   "Não há uma ação de organização aprovada neste plano.")
        try:
            definition = self.actions.get(operation) if self.actions is not None else None
            if definition is None or self.permissions is None:
                return ExecutionResult(task.task_id, TaskStatus.AWAITING_PERMISSION,
                                       "Ação ou gerenciador de permissões indisponível.")
            if definition.read_only or not definition.requires_confirmation:
                return ExecutionResult(task.task_id, TaskStatus.FAILED,
                                       "Metadados de segurança da ação são inválidos.")
            if definition.permission != self._OPERATIONS[operation]:
                return ExecutionResult(task.task_id, TaskStatus.FAILED,
                                       "A permissão registrada não corresponde à ação.")
            if self.dispatcher is None:
                return ExecutionResult(task.task_id, TaskStatus.AWAITING_PERMISSION,
                                       "Despachante seguro de ferramentas indisponível.")
            # Parameters supplied by a planner never control the action name or
            # destination paths; only the authenticated read-only preview does.
            arguments = {}
            if (prepared.inspection is not None
                    and isinstance(prepared.inspection.data.get("plan"), list)):
                arguments["plan"] = prepared.inspection.data["plan"]
            result = self.dispatcher.dispatch(
                operation, arguments, approved=True, cancellation=cancellation
            )
            self.validator.validate_action_result(result)
        except Exception as exc:
            # Evita transformar erro interno em alegação de sucesso.
            logger.exception("Falha ao executar ação cognitiva")
            cause = getattr(exc, "cause", None)
            if cancellation is not None and cancellation.cancelled:
                return ExecutionResult(task.task_id, TaskStatus.CANCELLED,
                                       "A tarefa foi cancelada; movimentos já feitos foram revertidos.")
            return ExecutionResult(task.task_id, TaskStatus.FAILED,
                                   f"A execução falhou ({type(exc).__name__}).")

        verified = False
        if result.success and self.result_verifier is not None:
            try:
                verified = self.result_verifier(operation, result, dict(step.parameters)) is True
            except Exception:
                logger.exception("Verificador rejeitou ou não conseguiu validar o resultado")
                verified = False
        if not result.success:
            status, message = TaskStatus.FAILED, "A ferramenta informou que a ação falhou."
        elif not verified:
            status, message = TaskStatus.UNVERIFIED, "A ação ocorreu, mas o resultado não foi verificado."
        else:
            status, message = TaskStatus.SUCCEEDED, result.summary or "Tarefa concluída e verificada."

        recorded = self._record_experience(status, consent=memory_consent)
        return ExecutionResult(task.task_id, status, message, result, verified, recorded)

    def _missing_permissions(self, task):
        required = {self._OPERATIONS[s.operation] for s in task.steps
                    if s.operation in self._OPERATIONS}
        if not required:
            return ()
        if self.permissions is None:
            return tuple(sorted(required))
        return tuple(sorted(p for p in required
                            if not self.permissions.allowed(self.plugin_id, p)))

    def _inspect(self, task):
        if self.actions is None:
            return None
        operation = "files.preview_downloads"
        if not self.actions.contains(operation):
            return None
        definition = self.actions.get(operation)
        if (not definition.read_only or definition.permission != self._OPERATIONS[operation]
                or self.permissions is None
                or not self.permissions.allowed(self.plugin_id, definition.permission)):
            return None
        try:
            if self.dispatcher is None:
                return None
            result = self.dispatcher.dispatch(
                operation,
                dict(next(s for s in task.steps if s.operation == operation).parameters),
            )
        except Exception:
            logger.exception("Falha ao inspecionar arquivos para a prévia")
            return None
        return result if isinstance(result, ActionResult) else None

    def _record_experience(self, status, *, consent):
        if consent is not True or self.memory is None:
            return False
        try:
            EpisodicMemory(self.memory).record_event(
                f"Tarefa de organização de Downloads: {status.value}.",
                source="nova_ai.cognition", consent=True,
            )
            return True
        except Exception:
            logger.exception("Não foi possível registrar experiência consentida")
            return False

    @staticmethod
    def cancel(prepared):
        """Retorna uma cópia cancelada; nenhuma operação é executada."""
        if not isinstance(prepared, CognitiveResult):
            raise TypeError("prepared deve ser CognitiveResult")
        task = replace(prepared.task, status=TaskStatus.CANCELLED)
        decision = Decision(DecisionKind.BLOCKED, "Tarefa cancelada.")
        return replace(prepared, task=task, decision=decision)

    @staticmethod
    def _context(context):
        if context is None:
            return {}
        if not isinstance(context, dict):
            raise ValueError("context deve ser um dicionário")
        path = context.get("downloads_path")
        return {"downloads_path": path} if isinstance(path, str) and 0 < len(path) <= 512 else {}
