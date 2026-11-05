"""Converte intenções reconhecidas em planos declarativos, sem executar operações."""

from .intent_classifier import Intent, IntentName
from .task_state import CognitiveTask, TaskStatus, TaskStep


class Planner:
    def plan(self, intent, *, context=None, memories=()):
        if not isinstance(intent, Intent):
            raise TypeError("intent deve ser Intent")
        context = context or {}
        memory_ids = tuple(
            record.memory_id for record in memories
            if isinstance(getattr(record, "memory_id", None), str)
        )
        if intent.name is IntentName.UNKNOWN or intent.confidence < 0.65:
            return CognitiveTask.create(
                intent=intent.name.value,
                goal="Esclarecer a solicitação",
                status=TaskStatus.NEEDS_CLARIFICATION,
                steps=(TaskStep(
                    "clarify", "Perguntar o que a pessoa deseja fazer.",
                ),),
                clarification_question="O que você gostaria que eu fizesse?",
                supporting_memory_ids=memory_ids,
            )
        if intent.name is IntentName.ORGANIZE_DOWNLOADS:
            target = context.get("downloads_path", "~/Downloads")
            if not isinstance(target, str) or len(target) > 512:
                target = "~/Downloads"
            return CognitiveTask.create(
                intent=intent.name.value,
                goal="Organizar os arquivos da pasta Downloads",
                status=TaskStatus.AWAITING_CONFIRMATION,
                steps=(
                    TaskStep(
                        "inspect", "Inspecionar os arquivos e preparar uma prévia.",
                        operation="files.preview_downloads",
                        parameters={"path": target},
                    ),
                    TaskStep(
                        "present_preview", "Apresentar as mudanças propostas para revisão.",
                        depends_on=("inspect",),
                    ),
                    TaskStep(
                        "confirm", "Solicitar confirmação explícita antes de mover arquivos.",
                        requires_confirmation=True,
                        depends_on=("present_preview",),
                    ),
                    TaskStep(
                        "organize", "Organizar os arquivos somente após a confirmação.",
                        operation="files.organize_downloads",
                        has_side_effect=True,
                        requires_confirmation=True,
                        parameters={"path": target},
                        depends_on=("confirm",),
                    ),
                    TaskStep(
                        "report", "Informar o resultado da organização.",
                        depends_on=("organize",),
                    ),
                ),
                supporting_memory_ids=memory_ids,
            )
        return CognitiveTask.create(
            intent=intent.name.value,
            goal="Esclarecer a solicitação",
            status=TaskStatus.NEEDS_CLARIFICATION,
            steps=(TaskStep("clarify", "Perguntar o que a pessoa deseja fazer."),),
            clarification_question="Ainda não sei como transformar esse pedido em etapas.",
            supporting_memory_ids=memory_ids,
        )
