"""Provider-neutral structure for proposed tool calls; contains no executor."""
from dataclasses import dataclass, field
import json
import uuid

@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict
    state: str = "requested"

    def __post_init__(self):
        if not isinstance(self.call_id, str) or not self.call_id or len(self.call_id) > 128:
            raise ValueError("call_id inválido")
        if not isinstance(self.name, str) or not self.name or len(self.name) > 120:
            raise ValueError("nome de ferramenta inválido")
        if not isinstance(self.arguments, dict) or self.state not in {"requested", "validated", "rejected"}:
            raise ValueError("chamada estruturada inválida")

@dataclass(frozen=True)
class ToolCallResult:
    call_id: str
    name: str
    state: str
    result: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.state not in {"succeeded", "failed", "denied", "confirmation_required", "cancelled"}:
            raise ValueError("estado de resultado inválido")
        if not isinstance(self.result, dict):
            raise ValueError("resultado estruturado inválido")

@dataclass(frozen=True)
class ProviderTurn:
    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    results: tuple[ToolCallResult, ...] = ()
    continuation: bool = False

    def __post_init__(self):
        if not isinstance(self.text, str) or len(self.tool_calls) > 8:
            raise ValueError("turno do provider inválido")
        ids = [call.call_id for call in self.tool_calls]
        if len(ids) != len(set(ids)):
            raise ValueError("call_id duplicado no mesmo turno")

    def append_results(self, results):
        return ProviderTurn(self.text, self.tool_calls, tuple(results), bool(results))

    def to_ollama_messages(self):
        """Map this provider-neutral turn to Ollama's chat-history protocol."""
        # Tool-call turns may also contain malformed prose (for example JSON
        # copied from a schema); it is not needed to bind tool results and can
        # mislead the model during the next operational stage.
        assistant = {"role": "assistant", "content": "" if self.tool_calls else self.text}
        if self.tool_calls:
            assistant["tool_calls"] = [
                {"id": call.call_id,
                 "function": {"name": call.name, "arguments": call.arguments}}
                for call in self.tool_calls
            ]
        messages = [assistant]
        for result in self.results:
            messages.append({
                "role": "tool",
                "tool_name": result.name,
                "tool_call_id": result.call_id,
                "content": _ollama_tool_result_content(result),
            })
        return messages

    def continuation_messages(self):
        """Backward-compatible name; operational code should use the explicit mapping."""
        return self.to_ollama_messages()


def _ollama_tool_result_content(result):
    """Encode the actual result compactly; never relabel a failed tool as success."""
    details = result.result
    if result.state != "succeeded":
        reason = details.get("message") or details.get("error_code") or details.get("summary")
        if reason is None and details:
            reason = json.dumps(details, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return f"Tool status: {result.state}." + (f" Reason: {reason}" if reason else "")
    if "data" in details:
        value = details["data"]
        if value is None or value == "" or value == {} or value == []:
            return "The tool succeeded but returned no data."
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    summary = details.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return "The tool succeeded but returned no data."

def parse_ollama_turn(response):
    message = response.get("message") if isinstance(response, dict) else None
    if not isinstance(message, dict):
        raise ValueError("resposta Ollama inválida")
    text = message.get("content", "")
    calls = message.get("tool_calls", [])
    if not isinstance(text, str) or not isinstance(calls, list) or len(calls) > 8:
        raise ValueError("conteúdo de resposta Ollama inválido")
    parsed = []
    for call in calls:
        function = call.get("function") if isinstance(call, dict) else None
        if not isinstance(function, dict):
            raise ValueError("tool_call sem função")
        name, arguments = function.get("name"), function.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ValueError("nome ou argumentos de tool_call inválidos")
        parsed.append(ToolCall(str(call.get("id") or uuid.uuid4().hex), name, arguments))
    return ProviderTurn(text, tuple(parsed))

def dispatch_tool_calls(turn, dispatcher, *, approved=False, approvals=None, cancellation=None):
    """Validate names/arguments and delegate permission/confirmation to dispatcher."""
    from aurova_ai.actions import AuthorizationRequired
    results = []
    approvals = approvals if isinstance(approvals, dict) else {}
    for call in turn.tool_calls:
        # A blanket approval cannot authorize a batch of model-proposed actions.
        call_approved = approvals.get(call.call_id, approved if len(turn.tool_calls) == 1 else False)
        try:
            dispatcher.registry.get(call.name)
            dispatcher.validator.validate(call.name, call.arguments)
            action = dispatcher.dispatch(call.name, dict(call.arguments), approved=call_approved is True,
                                         cancellation=cancellation)
            results.append(ToolCallResult(call.call_id, call.name,
                "succeeded" if action.success else "failed",
                {"summary": action.summary, "data": action.data}))
        except AuthorizationRequired as exc:
            state = "confirmation_required" if "aprovação" in str(exc).casefold() else "denied"
            results.append(ToolCallResult(call.call_id, call.name, state, {"message": str(exc)}))
        except Exception as exc:
            results.append(ToolCallResult(call.call_id, call.name, "failed",
                                          {"error_code": getattr(exc, "code", type(exc).__name__)}))
    return turn.append_results(results)
