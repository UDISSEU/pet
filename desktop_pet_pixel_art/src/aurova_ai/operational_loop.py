"""Bounded provider-to-dispatcher loop used by desktop conversation requests."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import logging
import re
import threading
import time
import unicodedata

from aurova_ai.actions import CancellationToken
from providers.base_provider import ProviderCancelled
from providers.tool_contract import ProviderTurn, ToolCallResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestClassification:
    category: str
    requires_clarification: bool = False


class DecisionKind(str, Enum):
    CONTINUE = "continue"
    FINALIZE = "finalize"
    CLARIFY = "clarify"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class OperationalStep:
    tool_name: str
    purpose: str
    completion_criterion: str = "resultado bem-sucedido e não vazio"

    def __post_init__(self):
        if not all(isinstance(value, str) and value.strip() for value in
                   (self.tool_name, self.purpose, self.completion_criterion)):
            raise ValueError("etapa operacional inválida")


@dataclass(frozen=True)
class OperationalPlan:
    objective: str
    steps: tuple[OperationalStep, ...]
    mode: str = "guided"

    def __post_init__(self):
        if not isinstance(self.objective, str) or not self.objective.strip():
            raise ValueError("objetivo operacional inválido")
        if not isinstance(self.steps, tuple) or any(not isinstance(step, OperationalStep)
                                                     for step in self.steps):
            raise ValueError("etapas do plano inválidas")
        if len({step.tool_name for step in self.steps}) != len(self.steps):
            raise ValueError("ferramenta repetida no plano")
        if self.mode not in {"guided", "model_led"}:
            raise ValueError("modo de plano inválido")


@dataclass(frozen=True)
class ContinuityDecision:
    kind: DecisionKind
    reason: str
    pending_tools: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.kind, DecisionKind) or not self.reason:
            raise ValueError("decisão operacional inválida")
        if not isinstance(self.pending_tools, tuple):
            raise ValueError("etapas pendentes inválidas")
        if any(not isinstance(name, str) or not name for name in self.pending_tools):
            raise ValueError("etapas pendentes inválidas")


def build_operational_plan(text, tools):
    """Build a bounded plan from registered schemas and explicit request cues.

    Exact tool mentions are authoritative for small integration fixtures. For the
    production catalog, only the narrow, reviewed query cues below are mapped.
    Other supported task requests retain model-led selection over the catalog.
    """
    normalized = unicodedata.normalize("NFKD", str(text).casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    schemas = [item for item in tools if isinstance(item, dict)
               and isinstance(item.get("function"), dict)
               and isinstance(item["function"].get("name"), str)]
    names = [item["function"]["name"] for item in schemas]
    mentioned = [name for name in names if name.casefold() in normalized]
    cues = (
        ("system.clock", r"\b(?:hora|horario|horas)\b"),
        ("system.monitor", r"\b(?:estado do sistema|estado operacional|saude do sistema)\b"),
        ("apps.list", r"\b(?:quais aplicativos|quais apps|lista de aplicativos|apps instalados)\b"),
        ("files.search", r"\b(?:procure|procurar|busque|buscar|pesquise|pesquisar)\b"),
        ("files.list_directory", r"\b(?:liste|listar|conteudo da pasta|arquivos da pasta)\b"),
        ("reminders.list", r"\b(?:meus lembretes|liste os lembretes|listar lembretes)\b"),
    )
    selected = list(mentioned)
    for name, pattern in cues:
        if name in names and re.search(pattern, normalized) and name not in selected:
            selected.append(name)
    # Keep the order in which explicit tool names occur in the request; semantic
    # cues follow catalog order. The next pending stage is exposed by itself.
    if mentioned:
        positions = {name: normalized.find(name.casefold()) for name in mentioned}
        selected.sort(key=lambda name: positions.get(name, len(normalized)))
    if selected:
        steps = tuple(OperationalStep(name, f"obter a informação de {name}") for name in selected)
        return OperationalPlan(str(text)[:500], steps, "guided")
    return OperationalPlan(str(text).strip()[:500] or "solicitação operacional", (), "model_led")


def _has_evidence(result):
    if result.state != "succeeded":
        return False
    if "data" in result.result:
        return result.result.get("data") not in (None, "", {}, [])
    summary = result.result.get("summary")
    return isinstance(summary, str) and bool(summary.strip())


class _LoopCancellationToken(CancellationToken):
    def __init__(self, request_event):
        super().__init__()
        self.request_event = request_event

    @property
    def cancelled(self):
        return super().cancelled or bool(
            self.request_event is not None and self.request_event.is_set()
        )


_QUERY_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"\b(?:que horas|que hora|qual horario|qual e o horario|"
    r"voce sabe me dizer (?:o )?horario|pode me dizer (?:o )?horario|"
    r"veja (?:pra mim )?que horas)\b",
    r"\b(?:quais aplicativos|quais apps|quais arquivos|liste|listar|mostre|mostrar|"
    r"consulte|consultar|verifique|verificar|procure|procurar|busque|buscar|localize|localizar)\b",
))
_TASK_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"\b(?:organize|organizar|organiza|arrume|arrumar|separe|separar|"
    r"crie|criar|cancele|cancelar|reative|reativar|abra|abrir|deixar|deixe)\b",
    r"\b(?:quero|preciso|gostaria)\b.*\b(?:organizar|separar|criar|abrir|deixar)\b",
))
_UNSUPPORTED_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"\b(?:terminal|shell|comando de sistema|execute comando|rode comando|"
    r"mouse|teclado|captura de tela|screenshot|edite? (?:uma? )?(?:planilha|documento))\b",
))
_AMBIGUOUS_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"\b(?:organize|organizar|separe|separar|arrume|arrumar)\s+(?:isso|aquilo|"
    r"meus arquivos|meus documentos|os documentos)\b",
))
_VAGUE_PATTERNS = tuple(re.compile(pattern) for pattern in (
    r"\b(?:faca isso|faz isso|me ajude com isso|resolva isso)\b",
))


def classify_request(text: str, *, cognitive_classifier=None) -> RequestClassification:
    """Return conversation/query/task/ambiguous/unsupported without inventing tools."""
    if not isinstance(text, str) or not text.strip() or len(text) > 4_000:
        return RequestClassification("ambiguous", True)
    normalized = unicodedata.normalize("NFKD", text.casefold()) if isinstance(text, str) else ""
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    if any(pattern.search(normalized) for pattern in _UNSUPPORTED_PATTERNS):
        return RequestClassification("unsupported")
    if any(pattern.search(normalized) for pattern in _AMBIGUOUS_PATTERNS):
        return RequestClassification("task", True)
    if any(pattern.search(normalized) for pattern in _VAGUE_PATTERNS):
        return RequestClassification("ambiguous", True)
    if cognitive_classifier is not None:
        try:
            intent = cognitive_classifier.classify(text)
            if getattr(getattr(intent, "name", None), "value", None) == "organize_downloads":
                return RequestClassification("task")
        except Exception:
            logger.exception("Classificação cognitiva existente falhou; usando roteamento conservador")
    if any(pattern.search(normalized) for pattern in _QUERY_PATTERNS):
        return RequestClassification("query")
    if any(pattern.search(normalized) for pattern in _TASK_PATTERNS):
        missing_target = bool(re.search(
            r"\b(?:organize|organizar|separe|separar|arrume|arrumar)\b.*"
            r"\b(?:meus arquivos|meus documentos|os documentos|arquivos)\b", normalized
        )) and "downloads" not in normalized
        missing_reminder_details = "lembrete" in normalized and not re.search(
            r"\b(?:amanha|hoje|segunda|terca|quarta|quinta|sexta|sabado|domingo|\d{1,2}:\d{2}|\d{1,2}/\d{1,2})\b",
            normalized,
        )
        missing_app = bool(re.search(r"\b(?:abra|abrir)\b.*\b(?:aplicativo|app)\b", normalized)) and not re.search(
            r"\b(?:chrome|firefox|navegador|calculadora|terminal|editor)\b", normalized
        )
        return RequestClassification("task", missing_target or missing_reminder_details or missing_app)
    return RequestClassification("conversation")


def _error_result(call, state, message):
    return ToolCallResult(call.call_id, call.name, state, {"message": message})


def run_operational_loop(*, router, messages, system_prompt, tools, dispatcher,
                         confirm, permission_manager=None, cancel_event=None, max_iterations=4,
                         max_calls=6, timeout_seconds=90):
    """Run proposals only through the real dispatcher; confirmation is call-scoped."""
    if not 1 <= max_iterations <= 8 or not 1 <= max_calls <= 12:
        raise ValueError("Limites do loop fora do intervalo permitido")
    deadline = time.monotonic() + min(max(float(timeout_seconds), 1), 120)
    cancellation = _LoopCancellationToken(cancel_event)
    turns = list(messages)
    request_text = next((item.get("content", "") for item in reversed(turns)
                         if isinstance(item, dict) and item.get("role") == "user"), "")
    plan = build_operational_plan(request_text, tools)
    seen = set()
    call_count = 0
    dispatch_count = 0
    completed = []
    no_progress_count = 0

    def _pending_steps():
        done = {item.name for item in completed if _has_evidence(item)}
        return tuple(step.tool_name for step in plan.steps if step.tool_name not in done)

    def _dispatch(call, *, approved=False):
        nonlocal dispatch_count
        dispatcher.registry.get(call.name)
        dispatcher.validator.validate(call.name, call.arguments)
        dispatch_count += 1
        action = dispatcher.dispatch(call.name, dict(call.arguments), approved=approved,
                                     cancellation=cancellation)
        return ToolCallResult(call.call_id, call.name,
            "succeeded" if action.success else "failed",
            {"summary": action.summary, "data": action.data})

    def _approved_dispatch(call):
        decision = confirm(call, timeout_seconds=max(0, deadline - time.monotonic()))
        if decision == "approve" and time.monotonic() < deadline and not (
                cancel_event is not None and cancel_event.is_set()):
            try:
                return _dispatch(call, approved=True)
            except Exception as exc:
                return _error_result(call, "failed", getattr(exc, "code", type(exc).__name__))
        if decision == "cancel" or (cancel_event is not None and cancel_event.is_set()):
            cancellation.cancel()
            return _error_result(call, "cancelled", "A pessoa cancelou a solicitação.")
        return _error_result(call, "denied", "A pessoa não autorizou a ação.")

    for turn_number in range(1, max_iterations + 1):
        if (cancel_event is not None and cancel_event.is_set()) or time.monotonic() >= deadline:
            logger.info(
                "Operational loop turn=%d termination=cancelled_or_timeout messages=%d history_messages=%d tools=%d cancel=%s",
                turn_number, len(turns) + 1, len(turns), len(tools), bool(cancel_event and cancel_event.is_set()),
            )
            return "A solicitação foi cancelada ou excedeu o tempo limite; não vou declarar conclusão."
        inference_started = time.monotonic()
        pending = _pending_steps()
        if plan.mode == "guided":
            active_tools = ([schema for schema in tools
                             if schema.get("function", {}).get("name") == pending[0]]
                            if pending else [])
        else:
            done_names = {item.name for item in completed if _has_evidence(item)}
            active_tools = [schema for schema in tools
                            if schema.get("function", {}).get("name") not in done_names]
        phase = "execution" if active_tools or plan.mode == "model_led" else "finalization"
        phase_prompt = system_prompt + (
            "\n\nFase operacional: " + phase + ". "
            + ("Use somente a ferramenta disponível para a etapa atual e não responda antes de executá-la."
               if phase == "execution" else
               "As ferramentas foram encerradas após validação das etapas e evidências. Responda apenas "
               "com os resultados recebidos e informe claramente qualquer ausência.")
        )
        if phase == "execution" and pending:
            phase_prompt += (f" Chame a ferramenta {pending[0]} exatamente uma vez. "
                             "Use argumentos conforme o schema; não responda antes da chamada.")
            if plan.mode == "guided":
                turns.append({"role": "user", "content":
                    f"Agora consulte {pending[0]} exatamente uma vez. Não invente resultados."})
        try:
            turn = router.generate_turn(turns, phase_prompt, tools=active_tools,
                                       cancel_event=cancel_event)
        except ProviderCancelled:
            decision = ContinuityDecision(DecisionKind.BLOCKED, "inferência cancelada")
            logger.info("Operational decision=%s phase=%s reason=%s",
                        decision.kind.value, phase, decision.reason)
            logger.info(
                "Operational loop turn=%d messages=%d history_messages=%d tools=%d proposed=0 dispatched=0 "
                "results=0 inference_seconds=%.3f cancel=true response=cancelled termination=provider_cancelled",
                turn_number, len(turns) + 1, len(turns), len(active_tools), time.monotonic() - inference_started,
            )
            return "A solicitação foi cancelada durante a inferência; nenhuma nova ferramenta será executada."
        except Exception:
            decision = ContinuityDecision(DecisionKind.BLOCKED, "falha ou timeout durante inferência")
            logger.info("Operational decision=%s phase=%s reason=%s",
                        decision.kind.value, phase, decision.reason)
            logger.info(
                "Operational loop turn=%d messages=%d history_messages=%d tools=%d proposed=0 dispatched=0 "
                "results=0 inference_seconds=%.3f cancel=%s response=error termination=provider_error",
                turn_number, len(turns) + 1, len(turns), len(active_tools), time.monotonic() - inference_started,
                bool(cancel_event and cancel_event.is_set()),
            )
            raise
        inference_seconds = time.monotonic() - inference_started
        if cancel_event is not None and cancel_event.is_set():
            logger.info(
                "Operational loop turn=%d messages=%d history_messages=%d tools=%d proposed=0 dispatched=0 "
                "results=0 inference_seconds=%.3f cancel=true response=discarded termination=cancelled_after_provider",
                turn_number, len(turns) + 1, len(turns), len(active_tools), inference_seconds,
            )
            return "A solicitação foi cancelada durante a inferência; nenhuma nova ferramenta será executada."
        if not isinstance(turn, ProviderTurn):
            raise TypeError("O provider retornou um turno operacional inválido")
        response_kind = "tool_calls" if turn.tool_calls else ("text" if turn.text.strip() else "empty")
        logger.info(
            "Operational loop turn=%d messages=%d history_messages=%d tools=%d proposed=%d dispatched=0 results=0 "
            "inference_seconds=%.3f cancel=false response=%s",
            turn_number, len(turns) + 1, len(turns), len(active_tools), len(turn.tool_calls), inference_seconds, response_kind,
        )
        if not turn.tool_calls:
            failures = [item for item in completed if not _has_evidence(item)]
            if failures:
                decision = ContinuityDecision(DecisionKind.BLOCKED, "há etapa sem evidência válida")
                logger.info("Operational decision=%s reason=%s", decision.kind.value, decision.reason)
                logger.info("Operational loop turn=%d termination=tool_failure failures=%d",
                            turn_number, len(failures))
                return "Não concluí a operação: " + "; ".join(
                    f"{item.name}: {item.result.get('message', item.state)}" for item in failures
                )
            pending = _pending_steps()
            if pending:
                no_progress_count += 1
                if no_progress_count >= 2:
                    decision = ContinuityDecision(DecisionKind.BLOCKED,
                        "o provider não emitiu a chamada estruturada exigida", pending)
                    logger.info("Operational decision=%s pending=%d", decision.kind.value,
                                len(decision.pending_tools))
                    return "Não concluí a operação: o provedor não executou a ferramenta exigida."
                decision = ContinuityDecision(DecisionKind.CONTINUE,
                    "há etapas planejadas sem resultado", pending)
                logger.info("Operational decision=%s pending=%d", decision.kind.value, len(pending))
                continue
            if turn.text.strip():
                if not any(_has_evidence(item) for item in completed):
                    decision = ContinuityDecision(DecisionKind.CLARIFY,
                        "não há evidência operacional para responder")
                    logger.info("Operational decision=%s reason=%s", decision.kind.value, decision.reason)
                    return "Preciso de mais detalhes ou de uma consulta autorizada para responder com segurança."
                decision = ContinuityDecision(DecisionKind.FINALIZE,
                    "etapas planejadas concluídas com evidências válidas")
                logger.info("Operational decision=%s reason=%s", decision.kind.value, decision.reason)
                logger.info("Operational loop turn=%d termination=final_text", turn_number)
                return turn.text.strip()
            decision = ContinuityDecision(DecisionKind.BLOCKED, "provider não produziu chamada nem resposta")
            logger.info("Operational decision=%s reason=%s", decision.kind.value, decision.reason)
            logger.info("Operational loop turn=%d termination=empty_final", turn_number)
            return "Não recebi uma resposta final válida do provedor."

        if phase == "finalization":
            decision = ContinuityDecision(DecisionKind.BLOCKED,
                "provider propôs ferramenta após a finalização validada")
            logger.info("Operational decision=%s reason=%s", decision.kind.value, decision.reason)
            return "Não concluí a resposta: o provedor solicitou outra ferramenta após o encerramento das etapas."

        results = []
        dispatches_before_turn = dispatch_count
        stop_batch = False
        for call in turn.tool_calls:
            if stop_batch:
                result = _error_result(call, "denied", "Chamada não executada após decisão negativa anterior.")
                results.append(result)
                completed.append(result)
                continue
            call_count += 1
            active_names = {schema.get("function", {}).get("name") for schema in active_tools}
            if active_names and call.name not in active_names:
                result = _error_result(call, "failed", "Ferramenta fora do plano da etapa atual.")
                results.append(result)
                completed.append(result)
                continue
            if call_count > max_calls:
                result = _error_result(call, "failed", "Limite de chamadas por solicitação atingido.")
                results.append(result)
                completed.append(result)
                continue
            fingerprint = (call.name, json.dumps(call.arguments, sort_keys=True, ensure_ascii=False))
            if fingerprint in seen:
                result = _error_result(call, "failed", "Chamada repetida bloqueada.")
                results.append(result)
                completed.append(result)
                continue
            seen.add(fingerprint)
            if (cancel_event is not None and cancel_event.is_set()) or time.monotonic() >= deadline:
                cancellation.cancel()
                results.append(_error_result(call, "cancelled", "Solicitação cancelada ou expirada."))
                continue
            from aurova_ai.actions import AuthorizationRequired
            try:
                result = _dispatch(call)
            except AuthorizationRequired as exc:
                if "permissões ainda não concedidas" in str(exc).casefold():
                    definition = dispatcher.registry.get(call.name)
                    missing = tuple(permission for permission in
                                    (definition.permission, *definition.additional_permissions)
                                    if not dispatcher.permissions.allowed(dispatcher.plugin_id, permission))
                    decision = confirm(call, permissions=missing,
                                       timeout_seconds=max(0, deadline - time.monotonic()))
                    if decision == "cancel" or (cancel_event is not None and cancel_event.is_set()):
                        cancellation.cancel()
                        result = _error_result(call, "cancelled", "A solicitação foi cancelada.")
                    elif decision != "approve":
                        result = _error_result(call, "denied", "A permissão não foi concedida.")
                    elif permission_manager is None:
                        result = _error_result(call, "denied", "Não há gerenciador de permissões disponível.")
                    elif time.monotonic() >= deadline:
                        cancellation.cancel()
                        result = _error_result(call, "cancelled", "O pedido de permissão expirou.")
                    else:
                        try:
                            for permission in missing:
                                if not permission_manager.authorize(
                                        dispatcher.plugin_id, permission, confirmed=True):
                                    raise PermissionError(permission)
                        except Exception as permission_exc:
                            result = _error_result(call, "denied",
                                                   getattr(permission_exc, "code", "permission_failed"))
                        else:
                            try:
                                result = _dispatch(call)
                            except AuthorizationRequired as retry_exc:
                                if "aprovação" in str(retry_exc).casefold():
                                    result = _approved_dispatch(call)
                                else:
                                    result = _error_result(call, "denied", "Permissão ausente ou revogada.")
                            except Exception as execution_exc:
                                result = _error_result(call, "failed",
                                                       getattr(execution_exc, "code", type(execution_exc).__name__))
                elif "aprovação" in str(exc).casefold():
                    result = _approved_dispatch(call)
                else:
                    result = _error_result(call, "denied", "Permissão ausente ou revogada.")
            except Exception as exc:
                result = _error_result(call, "failed", getattr(exc, "code", type(exc).__name__))
            results.append(result)
            completed.append(result)
            logger.info("Tool call operacional %s terminou em %s", call.name, result.state)
            if result.state == "denied":
                stop_batch = True
            if result.state == "cancelled":
                return "Cancelei a solicitação; não vou continuar executando ações."
            if cancel_event is not None and cancel_event.is_set():
                cancellation.cancel()
                return "Solicitação cancelada durante a ferramenta; nenhuma nova ação será iniciada."
        turns.extend(turn.to_ollama_messages())
        turns.extend(ProviderTurn(results=tuple(results)).to_ollama_messages()[1:])
        logger.info(
            "Operational loop turn=%d dispatcher_calls=%d results=%s cancel=%s termination=continue",
            turn_number, dispatch_count - dispatches_before_turn,
            ",".join(item.state for item in results), bool(cancel_event and cancel_event.is_set()),
        )
        if any(not _has_evidence(item) for item in results):
            decision = ContinuityDecision(DecisionKind.BLOCKED,
                "uma ferramenta falhou ou não retornou evidência", _pending_steps())
            logger.info("Operational decision=%s pending=%d", decision.kind.value,
                        len(decision.pending_tools))
            details = "; ".join(
                f"{item.name}: {item.result.get('message') or ('resultado vazio' if item.state == 'succeeded' else item.state)}"
                for item in results if not _has_evidence(item)
            )
            return "Não concluí a operação: " + (details or "uma ferramenta retornou resultado vazio.")
        no_progress_count = 0
        pending = _pending_steps()
        decision = ContinuityDecision(
            DecisionKind.CONTINUE if pending or plan.mode == "model_led" else DecisionKind.FINALIZE,
            "etapas ainda pendentes" if pending or plan.mode == "model_led"
            else "todas as etapas planejadas têm evidência válida", pending,
        )
        logger.info("Operational decision=%s pending=%d", decision.kind.value,
                    len(decision.pending_tools))

    logger.info("Operational loop termination=iteration_limit turns=%d calls=%d", max_iterations, call_count)
    return "A solicitação atingiu o limite de etapas. Não consigo confirmar que foi concluída."
