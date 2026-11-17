"""Validação de planos e resultados antes de expô-los à camada chamadora."""

from .decision_engine import Decision, DecisionKind
from .intent_classifier import Intent, IntentName
from .task_state import CognitiveTask, TaskStatus
from ..actions.results import ActionResult


class ResultValidationError(ValueError):
    pass


class ResultValidator:
    _ALLOWED_OPERATIONS = {"files.preview_downloads", "files.organize_downloads"}
    _DESTRUCTIVE_PREFIXES = ("file.write", "file.move", "file.delete", "file.organize",
                             "system.", "package.install", "software.install")

    def validate_intent(self, intent):
        if not isinstance(intent, Intent):
            raise ResultValidationError("Intent inválida")
        if (
            not isinstance(intent.name, IntentName)
            or intent.source not in {"rules", "model"}
            or isinstance(intent.confidence, bool)
            or not isinstance(intent.confidence, (int, float))
            or not 0 <= intent.confidence <= 1
            or not isinstance(intent.entities, dict)
        ):
            raise ResultValidationError("Classificação fora dos limites")
        if intent.name is IntentName.ORGANIZE_DOWNLOADS:
            if intent.entities != {"target": "downloads"}:
                raise ResultValidationError("Alvo de organização inválido")
        elif intent.entities:
            raise ResultValidationError("Intenção desconhecida não pode conter alvos")
        return intent

    def validate_plan(self, intent, task, decision):
        self.validate_intent(intent)
        if (
            not isinstance(task, CognitiveTask)
            or not isinstance(decision, Decision)
            or not isinstance(decision.kind, DecisionKind)
        ):
            raise ResultValidationError("Resultado cognitivo inválido")
        if (
            task.intent != intent.name.value
            or not isinstance(task.status, TaskStatus)
            or not task.steps
            or len(task.steps) > 12
        ):
            raise ResultValidationError("Plano incompatível com a intenção")
        known_ids = set()
        for step in task.steps:
            if (not isinstance(step.step_id, str) or not step.step_id
                    or step.step_id in known_ids or not isinstance(step.description, str)
                    or type(step.has_side_effect) is not bool
                    or type(step.requires_confirmation) is not bool):
                raise ResultValidationError("Etapa malformada ou identificador repetido")
            dependencies = step.depends_on
            if (not isinstance(dependencies, tuple)
                    or any(dep not in known_ids for dep in dependencies)):
                raise ResultValidationError("Dependência ausente ou fora de ordem")
            if not isinstance(step.parameters, dict):
                raise ResultValidationError("Parâmetros de etapa inválidos")
            if step.operation is not None and step.operation not in self._ALLOWED_OPERATIONS:
                raise ResultValidationError("Plano contém uma operação não permitida")
            if step.has_side_effect and not step.requires_confirmation:
                raise ResultValidationError("Efeito colateral sem confirmação explícita")
            if step.operation == "files.preview_downloads" and step.has_side_effect:
                raise ResultValidationError("A prévia não pode alterar arquivos")
            if step.operation == "files.organize_downloads" and not step.has_side_effect:
                raise ResultValidationError("A organização precisa declarar efeito colateral")
            if step.operation and any(step.operation.startswith(p) for p in self._DESTRUCTIVE_PREFIXES):
                if not step.has_side_effect or not step.requires_confirmation:
                    raise ResultValidationError("Ação sensível precisa de aprovação explícita")
            known_ids.add(step.step_id)
        has_side_effect = any(step.has_side_effect for step in task.steps)
        if has_side_effect != decision.confirmation_required:
            raise ResultValidationError("Decisão de confirmação incompatível com o plano")
        if decision.kind is DecisionKind.REQUEST_PERMISSION:
            if not decision.permissions_required:
                raise ResultValidationError("Pedido de permissão sem permissões identificadas")
            return task
        if decision.kind is DecisionKind.BLOCKED:
            if not has_side_effect or decision.permissions_required:
                raise ResultValidationError("Bloqueio incompatível com o plano")
            return task
        if task.status is TaskStatus.NEEDS_CLARIFICATION:
            if decision.kind is not DecisionKind.ASK_CLARIFICATION:
                raise ResultValidationError("Plano incompleto precisa de esclarecimento")
        elif has_side_effect and decision.kind is not DecisionKind.REQUIRE_CONFIRMATION:
            raise ResultValidationError("Plano com efeitos precisa de confirmação")
        elif has_side_effect and task.status is not TaskStatus.AWAITING_CONFIRMATION:
            raise ResultValidationError("Plano com efeitos precisa aguardar confirmação")
        elif not has_side_effect and task.status is not TaskStatus.PLANNED:
            raise ResultValidationError("Plano sem efeitos deve estar pronto para apresentação")
        elif not has_side_effect and decision.kind is not DecisionKind.PRESENT_PLAN:
            raise ResultValidationError("Decisão incompatível com o plano")
        return task

    def validate_action_result(self, result):
        if not isinstance(result, ActionResult):
            raise ResultValidationError("Resultado de ação inválido")
        if type(result.success) is not bool or not isinstance(result.summary, str):
            raise ResultValidationError("Resultado de ação malformado")
        if not isinstance(result.data, dict):
            raise ResultValidationError("Dados do resultado inválidos")
        return result
