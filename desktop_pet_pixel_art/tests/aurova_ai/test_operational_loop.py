import unittest
import threading

from aurova_ai.actions import ActionResult, Tool, ToolDispatcher, ToolRegistry
from aurova_ai.operational_loop import (
    ContinuityDecision, DecisionKind, build_operational_plan, classify_request,
    run_operational_loop,
)
from providers.tool_contract import ProviderTurn, ToolCall


class AllowPermissions:
    def allowed(self, _plugin, permission):
        return permission in {"test.read", "test.write"}

    def require(self, _plugin, permission, *, confirmed=False):
        if not self.allowed(_plugin, permission):
            raise PermissionError(permission)
        if permission == "test.write" and not confirmed:
            raise PermissionError("confirmation required")
        return True


class GrantablePermissions(AllowPermissions):
    def __init__(self):
        self.grants = set()

    def allowed(self, _plugin, permission):
        return permission in self.grants

    def authorize(self, _plugin, permission, *, confirmed=False):
        if permission == "test.write" and not confirmed:
            return False
        self.grants.add(permission)
        return True


class FakeTool(Tool):
    def __init__(self, name, *, succeeds=True, on_execute=None):
        self.name = name
        self.description = f"fake {name}"
        self.succeeds = succeeds
        self.executions = 0
        self.on_execute = on_execute

    def execute(self, arguments):
        self.executions += 1
        if self.on_execute is not None:
            self.on_execute()
        return ActionResult(self.succeeds, "verified fake result", {"value": arguments.get("value", "ok")})


class ScriptedRouter:
    def __init__(self, *turns):
        self.turns = list(turns)
        self.messages = []

    def generate_turn(self, messages, _prompt, *, tools=(), cancel_event=None):
        self.messages.append((list(messages), list(tools)))
        if cancel_event is not None and cancel_event.is_set():
            from providers.base_provider import ProviderCancelled
            raise ProviderCancelled("cancelled")
        return self.turns.pop(0)


def schema(name):
    return {"type": "function", "function": {"name": name,
            "description": name, "parameters": {"type": "object", "properties": {}}}}


def setup_dispatcher(*, write=False, succeeds=True):
    registry = ToolRegistry()
    tool = FakeTool("test.write" if write else "test.read", succeeds=succeeds)
    registry.register_tool(tool, permission="test.write" if write else "test.read",
                           read_only=not write, requires_confirmation=write)
    return ToolDispatcher(registry, AllowPermissions()), tool


class OperationalLoopTests(unittest.TestCase):
    def test_plan_and_decision_contract_are_structured_and_validated(self):
        plan = build_operational_plan("Consulte test.facts e test.clock", [
            schema("test.facts"), schema("test.clock"), schema("test.extra")])
        self.assertEqual([step.tool_name for step in plan.steps], ["test.facts", "test.clock"])
        decision = ContinuityDecision(DecisionKind.CONTINUE, "segunda etapa pendente",
                                      ("test.clock",))
        self.assertEqual(decision.kind.value, "continue")
        with self.assertRaises(ValueError):
            ContinuityDecision("finalize", "sem enum")
        with self.assertRaises(ValueError):
            ContinuityDecision(DecisionKind.CONTINUE, "lista mutável", ["test.clock"])

    def test_guided_multi_tool_exposes_only_current_schema_and_finalizes_without_schemas(self):
        registry = ToolRegistry()
        facts, clock = FakeTool("test.facts"), FakeTool("test.clock")
        registry.register_tool(facts, permission="test.read", read_only=True)
        registry.register_tool(clock, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, AllowPermissions())
        router = ScriptedRouter(
            ProviderTurn(tool_calls=(ToolCall("facts-1", "test.facts", {"value": "operacional"}),)),
            ProviderTurn(tool_calls=(ToolCall("clock-1", "test.clock", {"value": "07:45"}),)),
            ProviderTurn(text="Estado: operacional. Horário: 07:45."),
        )
        answer = run_operational_loop(router=router,
            messages=[{"role": "user", "content": "Consulte test.facts e test.clock"}],
            system_prompt="", tools=[schema("test.facts"), schema("test.clock"), schema("test.extra")],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny")
        self.assertEqual(answer, "Estado: operacional. Horário: 07:45.")
        self.assertEqual([len(item[1]) for item in router.messages], [1, 1, 0])
        self.assertEqual((facts.executions, clock.executions), (1, 1))

    def test_empty_tool_result_blocks_finalization(self):
        registry = ToolRegistry()

        class EmptyTool(FakeTool):
            def execute(self, _arguments):
                self.executions += 1
                return ActionResult(True, "", {})

        empty = EmptyTool("test.facts")
        registry.register_tool(empty, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, AllowPermissions())
        router = ScriptedRouter(ProviderTurn(tool_calls=(ToolCall("empty-1", "test.facts", {}),)),
                                ProviderTurn(text="Inventado."))
        answer = run_operational_loop(router=router,
            messages=[{"role": "user", "content": "Consulte test.facts"}],
            system_prompt="", tools=[schema("test.facts")], dispatcher=dispatcher,
            confirm=lambda _call, **_kwargs: "deny")
        self.assertIn("resultado vazio", answer.casefold())
        self.assertEqual(len(router.messages), 1)

    def test_proposal_outside_current_plan_is_never_dispatched(self):
        registry = ToolRegistry()
        facts, clock = FakeTool("test.facts"), FakeTool("test.clock")
        registry.register_tool(facts, permission="test.read", read_only=True)
        registry.register_tool(clock, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, AllowPermissions())
        router = ScriptedRouter(ProviderTurn(tool_calls=(ToolCall("wrong-stage", "test.clock", {}),)))
        answer = run_operational_loop(router=router,
            messages=[{"role": "user", "content": "Consulte test.facts"}],
            system_prompt="", tools=[schema("test.facts"), schema("test.clock")],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny")
        self.assertIn("fora do plano", answer.casefold())
        self.assertEqual((facts.executions, clock.executions), (0, 0))

    def test_conversation_classifier_keeps_greetings_and_questions_on_text_path(self):
        self.assertEqual(classify_request("Olá!").category, "conversation")
        self.assertEqual(classify_request("Como você está?").category, "conversation")
        self.assertEqual(classify_request("Me conte uma curiosidade.").category, "conversation")

    def test_query_phrasings_are_equivalent_and_tasks_request_clarification_when_needed(self):
        for phrasing in ("Veja que horas são.", "Você sabe me dizer o horário?",
                         "Que horas temos agora?"):
            with self.subTest(phrasing=phrasing):
                self.assertEqual(classify_request(phrasing).category, "query")
        for phrasing in ("Quero organizar meus arquivos.", "Separe meus documentos."):
            with self.subTest(phrasing=phrasing):
                category = classify_request(phrasing)
                self.assertEqual(category.category, "task")
                self.assertTrue(category.requires_clarification)
        self.assertEqual(classify_request(
            "Preciso deixar minha pasta Downloads organizada."
        ).category, "task")
        from aurova_ai.cognition import IntentClassifier, IntentName, Planner
        intent = IntentClassifier().classify("Preciso deixar minha pasta Downloads organizada.")
        self.assertIs(intent.name, IntentName.ORGANIZE_DOWNLOADS)
        planned = Planner().plan(intent)
        self.assertEqual(planned.intent, IntentName.ORGANIZE_DOWNLOADS.value)
        self.assertTrue(any(step.operation == "files.preview_downloads" for step in planned.steps))
        self.assertEqual(classify_request("Faça isso.").category, "ambiguous")
        self.assertEqual(classify_request("Execute um comando no terminal.").category, "unsupported")

    def test_single_query_runs_through_real_dispatcher_and_returns_provider_final(self):
        dispatcher, tool = setup_dispatcher()
        call = ToolCall("call-1", "test.read", {"value": "12:30"})
        router = ScriptedRouter(ProviderTurn(tool_calls=(call,)), ProviderTurn(text="São 12:30."))
        answer = run_operational_loop(router=router, messages=[{"role":"user","content":"Que horas são?"}],
            system_prompt="", tools=[], dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny")
        self.assertEqual(answer, "São 12:30.")
        self.assertEqual(tool.executions, 1)
        self.assertEqual(router.messages[1][0][-1]["role"], "tool")
        self.assertEqual(router.messages[1][0][-1]["tool_call_id"], "call-1")

    def test_turn_diagnostics_record_metadata_without_message_content(self):
        dispatcher, _tool = setup_dispatcher()
        router = ScriptedRouter(
            ProviderTurn(tool_calls=(ToolCall("diag-1", "test.read", {"value": "private-argument"}),)),
            ProviderTurn(text="Pronto."),
        )
        with self.assertLogs("aurova_ai.operational_loop", level="INFO") as captured:
            run_operational_loop(
                router=router, messages=[{"role": "user", "content": "private-user-content"}],
                system_prompt="private-system-prompt", tools=[], dispatcher=dispatcher,
                confirm=lambda _call, **_kwargs: "deny",
            )
        diagnostic = "\n".join(captured.output)
        self.assertIn("turn=1 messages=2 history_messages=1 tools=0 proposed=1", diagnostic)
        self.assertIn("dispatcher_calls=1 results=succeeded", diagnostic)
        self.assertIn("turn=2 messages=4 history_messages=3 tools=0 proposed=0", diagnostic)
        self.assertIn("response=text", diagnostic)
        self.assertIn("termination=final_text", diagnostic)
        self.assertNotIn("private-user-content", diagnostic)
        self.assertNotIn("private-system-prompt", diagnostic)
        self.assertNotIn("private-argument", diagnostic)

    def test_two_sequential_calls_preserve_tool_results_and_context(self):
        registry = ToolRegistry()
        status_tool, clock_tool = FakeTool("test.status"), FakeTool("test.clock")
        registry.register_tool(status_tool, permission="test.read", read_only=True)
        registry.register_tool(clock_tool, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, AllowPermissions())
        first = ToolCall("call-1", "test.status", {"value":"operacional"})
        second = ToolCall("call-2", "test.clock", {"value":"07:45"})
        router = ScriptedRouter(ProviderTurn(tool_calls=(first,)), ProviderTurn(tool_calls=(second,)),
                                ProviderTurn(text="Estado: operacional. Horário: 07:45."))
        answer = run_operational_loop(router=router, messages=[{"role":"user","content":"Liste os dados"}],
            system_prompt="", tools=[], dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny")
        self.assertIn("operacional", answer)
        self.assertIn("07:45", answer)
        self.assertEqual((status_tool.executions, clock_tool.executions), (1, 1))
        self.assertTrue(any(message.get("tool_call_id") == "call-1"
                            for message in router.messages[1][0]))
        self.assertTrue(any(message.get("tool_call_id") == "call-2"
                            for message in router.messages[2][0]))
        self.assertEqual(router.messages[1][0][0], {
            "role": "user", "content": "Liste os dados",
        })
        self.assertEqual(router.messages[2][0][0], {
            "role": "user", "content": "Liste os dados",
        })
        for history in (router.messages[1][0], router.messages[2][0]):
            assistant_calls = [message for message in history
                               if message.get("role") == "assistant" and message.get("tool_calls")]
            tool_results = [message for message in history if message.get("role") == "tool"]
            self.assertEqual(len(assistant_calls), len(tool_results))
            for assistant_call, tool_result in zip(assistant_calls, tool_results):
                self.assertEqual(assistant_call["tool_calls"][0]["id"], tool_result["tool_call_id"])
                self.assertEqual(assistant_call["tool_calls"][0]["function"]["name"],
                                 tool_result["tool_name"])
        first_history, second_history = router.messages[1][0], router.messages[2][0]
        self.assertEqual(first_history[-1]["content"], '{"value":"operacional"}')
        self.assertEqual(second_history[-1]["content"], '{"value":"07:45"}')

    def test_failed_tools_cannot_be_reported_as_success_after_final_text(self):
        registry = ToolRegistry()
        status_tool, clock_tool = FakeTool("test.status", succeeds=False), FakeTool("test.clock", succeeds=False)
        registry.register_tool(status_tool, permission="test.read", read_only=True)
        registry.register_tool(clock_tool, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, AllowPermissions())
        router = ScriptedRouter(
            ProviderTurn(tool_calls=(ToolCall("bad-status", "test.status", {}),
                                    ToolCall("bad-clock", "test.clock", {}))),
            ProviderTurn(text="Tudo foi concluído com sucesso."),
        )
        answer = run_operational_loop(
            router=router, messages=[{"role": "user", "content": "Consulte status e horário"}],
            system_prompt="", tools=[], dispatcher=dispatcher,
            confirm=lambda _call, **_kwargs: "deny",
        )
        self.assertIn("não concluí", answer.casefold())
        self.assertNotIn("Tudo foi concluído", answer)
        self.assertEqual((status_tool.executions, clock_tool.executions), (1, 1))

    def test_confirmation_is_call_scoped_and_denial_never_executes(self):
        dispatcher, tool = setup_dispatcher(write=True)
        call = ToolCall("sensitive-1", "test.write", {"value":"change"})
        router = ScriptedRouter(ProviderTurn(tool_calls=(call,)), ProviderTurn(text="Negada."))
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda requested, **_kwargs: "deny" if requested.call_id == "sensitive-1" else "approve")
        self.assertIn("não concluí", answer.casefold())
        self.assertEqual(tool.executions, 0)

    def test_approval_rechecks_permission_in_real_dispatcher(self):
        dispatcher, tool = setup_dispatcher(write=True)
        call = ToolCall("sensitive-2", "test.write", {"value":"change"})
        router = ScriptedRouter(ProviderTurn(tool_calls=(call,)), ProviderTurn(text="Feito."))
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda requested, **_kwargs: "approve" if requested.call_id == call.call_id else "deny")
        self.assertEqual(answer, "Feito.")
        self.assertEqual(tool.executions, 1)

    def test_denial_stops_later_calls_in_same_provider_batch(self):
        registry = ToolRegistry()
        protected = FakeTool("test.write")
        harmless = FakeTool("test.read")
        registry.register_tool(protected, permission="test.write", read_only=False,
                               requires_confirmation=True)
        registry.register_tool(harmless, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, AllowPermissions())
        turn = ProviderTurn(tool_calls=(ToolCall("deny-1", "test.write", {}),
                                        ToolCall("after-1", "test.read", {})))
        router = ScriptedRouter(turn, ProviderTurn(text="Tudo concluído."))
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny")
        self.assertIn("não concluí", answer.casefold())
        self.assertEqual(protected.executions, 0)
        self.assertEqual(harmless.executions, 0)

    def test_missing_permission_and_mutation_need_separate_explicit_approvals(self):
        registry = ToolRegistry()
        tool = FakeTool("test.write")
        registry.register_tool(tool, permission="test.write", read_only=False,
                               requires_confirmation=True)
        permissions = GrantablePermissions()
        dispatcher = ToolDispatcher(registry, permissions)
        call = ToolCall("grant-1", "test.write", {})
        router = ScriptedRouter(ProviderTurn(tool_calls=(call,)), ProviderTurn(text="Feito."))
        prompts = []

        def approve(call, permissions=(), **_kwargs):
            prompts.append((call.call_id, tuple(permissions)))
            return "approve"

        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=approve, permission_manager=permissions)
        self.assertEqual(answer, "Feito.")
        self.assertEqual(tool.executions, 1)
        self.assertEqual(prompts, [("grant-1", ("test.write",)), ("grant-1", ())])

    def test_repeated_call_is_blocked_before_second_execution(self):
        dispatcher, tool = setup_dispatcher()
        call = ToolCall("repeat-1", "test.read", {"value":"same"})
        router = ScriptedRouter(ProviderTurn(tool_calls=(call,)), ProviderTurn(tool_calls=(
            ToolCall("repeat-2", "test.read", {"value":"same"}),)), ProviderTurn(text="Done"))
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny")
        self.assertIn("repetida", answer.casefold())
        self.assertEqual(tool.executions, 1)

    def test_unknown_tool_fails_closed_and_response_does_not_claim_success(self):
        dispatcher, _tool = setup_dispatcher()
        call = ToolCall("unknown-1", "test.unregistered", {})
        router = ScriptedRouter(ProviderTurn(tool_calls=(call,)), ProviderTurn(text="Concluído com sucesso."))
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny")
        self.assertIn("não concluí", answer.casefold())

    def test_loop_iteration_limit_stops_provider_cycle(self):
        dispatcher, _tool = setup_dispatcher()
        turns = [ProviderTurn(tool_calls=(ToolCall(f"call-{i}", "test.read", {"value":str(i)}),))
                 for i in range(4)]
        router = ScriptedRouter(*turns)
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny", max_iterations=2)
        self.assertIn("limite de etapas", answer.casefold())
        self.assertEqual(len(router.messages), 2)

    def test_cancelled_request_does_not_contact_provider_or_dispatch(self):
        dispatcher, tool = setup_dispatcher()
        cancel = threading.Event()
        cancel.set()
        router = ScriptedRouter(ProviderTurn(text="Não deveria ser chamado"))
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny", cancel_event=cancel)
        self.assertIn("cancelada", answer.casefold())
        self.assertEqual(router.messages, [])
        self.assertEqual(tool.executions, 0)

    def test_repeated_cancel_signal_is_idempotent(self):
        dispatcher, tool = setup_dispatcher()
        cancel = threading.Event()
        cancel.set()
        cancel.set()
        router = ScriptedRouter(ProviderTurn(text="Não deveria ser chamado"))
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny", cancel_event=cancel)
        self.assertIn("cancelada", answer.casefold())
        self.assertEqual(router.messages, [])
        self.assertEqual(tool.executions, 0)

    def test_cancel_during_provider_wait_discards_tool_proposal(self):
        dispatcher, tool = setup_dispatcher()
        cancel = threading.Event()

        class CancelWhileGenerating(ScriptedRouter):
            def generate_turn(self, messages, prompt, *, tools=(), cancel_event=None):
                cancel.set()
                return ProviderTurn(tool_calls=(ToolCall("late-call", "test.read", {}),))

        router = CancelWhileGenerating()
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny", cancel_event=cancel)
        self.assertIn("cancelada durante a inferência", answer.casefold())
        self.assertEqual(tool.executions, 0)

    def test_cancel_during_confirmation_prevents_approved_dispatch(self):
        dispatcher, tool = setup_dispatcher(write=True)
        cancel = threading.Event()
        call = ToolCall("cancel-confirm", "test.write", {})
        router = ScriptedRouter(ProviderTurn(tool_calls=(call,)))

        def cancel_at_prompt(_call, **_kwargs):
            cancel.set()
            return "approve"

        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=cancel_at_prompt, cancel_event=cancel)
        self.assertIn("cancelei", answer.casefold())
        self.assertEqual(tool.executions, 0)

    def test_cancel_during_tool_execution_blocks_later_batch_calls(self):
        cancel = threading.Event()
        registry = ToolRegistry()
        first = FakeTool("test.read", on_execute=cancel.set)
        second = FakeTool("test.other")
        registry.register_tool(first, permission="test.read", read_only=True)
        registry.register_tool(second, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, AllowPermissions())
        router = ScriptedRouter(ProviderTurn(tool_calls=(
            ToolCall("cancel-running", "test.read", {}),
            ToolCall("cancel-later", "test.other", {}),
        )))
        answer = run_operational_loop(router=router, messages=[], system_prompt="", tools=[],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny", cancel_event=cancel)
        self.assertIn("durante a ferramenta", answer.casefold())
        self.assertEqual(first.executions, 1)
        self.assertEqual(second.executions, 0)


if __name__ == "__main__":
    unittest.main()
