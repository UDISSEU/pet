"""Opt-in local integration test; run only against an already installed Ollama model."""
import os
import time
import unittest

from aurova_ai.actions import ActionResult, Tool, ToolDispatcher, ToolRegistry
from ai.model_router import ModelRouter
from providers.tool_contract import ProviderTurn, ToolCall, dispatch_tool_calls
from aurova_ai.operational_loop import run_operational_loop


def _model_turn(router, messages, prompt, tools, turn_number):
    started = time.monotonic()
    roles = [message.get("role", "?") for message in messages]
    try:
        turn = router.generate_turn(messages, prompt, tools=tools)
    except Exception as exc:
        elapsed = time.monotonic() - started
        print(f"OLLAMA_TURN turn={turn_number} roles={roles!r} messages={len(messages)} "
              f"tools={len(tools)} proposed=0 dispatched=0 results=0 "
              f"inference_seconds={elapsed:.2f} cancel=false response=error "
              f"termination={type(exc).__name__}")
        raise
    elapsed = time.monotonic() - started
    response = "tool_calls" if turn.tool_calls else ("text" if turn.text.strip() else "empty")
    print(f"OLLAMA_TURN turn={turn_number} roles={roles!r} messages={len(messages)} "
          f"tools={len(tools)} proposed={len(turn.tool_calls)} dispatched=0 results=0 "
          f"inference_seconds={elapsed:.2f} cancel=false response={response} termination=provider_return")
    return turn


def _dispatch_turn(turn, dispatcher, turn_number):
    result = dispatch_tool_calls(turn, dispatcher)
    states = ",".join(item.state for item in result.results)
    print(f"OLLAMA_DISPATCH turn={turn_number} proposed={len(turn.tool_calls)} "
          f"dispatched={sum(item.state in {'succeeded', 'failed'} for item in result.results)} "
          f"results={len(result.results)} states={states!r} cancel=false termination=continue")
    return result


class _AllowTestPermission:
    def allowed(self, _plugin, permission):
        return permission == "test.read"

    def require(self, _plugin, permission, *, confirmed=False):
        if permission != "test.read":
            raise PermissionError(permission)
        return True


class _ClockFixture(Tool):
    name = "test.clock"
    description = "Retorna um horário fictício definido pelo teste."

    def __init__(self):
        self.calls = 0

    def execute(self, _arguments):
        self.calls += 1
        return ActionResult(True, "Horário fictício consultado.", {"time": "07:45"})


class _FactsFixture(Tool):
    name = "test.facts"
    description = "Retorna um estado fictício definido pelo teste."

    def __init__(self, *, succeeds=True):
        self.calls = 0
        self.succeeds = succeeds

    def execute(self, _arguments):
        self.calls += 1
        if not self.succeeds:
            return ActionResult(False, "Ferramenta fictícia indisponível.", {})
        return ActionResult(True, "Estado fictício consultado.", {"status": "operacional"})


@unittest.skipUnless(os.environ.get("AUROVA_RUN_LIVE_OLLAMA") == "1",
                     "Defina AUROVA_RUN_LIVE_OLLAMA=1 para usar Ollama local já instalado")
class LiveOllamaOperationalTests(unittest.TestCase):
    def test_integrated_two_tool_plan_continue_and_evidence_based_finalization(self):
        model = os.environ.get("AUROVA_OLLAMA_MODEL", "llama3.2:1b")
        router = ModelRouter({
            "ai_provider": "ollama", "ollama_model": model, "ai_timeout": 25,
            "ollama_num_ctx": 768, "ollama_num_predict": 64, "ollama_num_threads": 1,
        })
        registry = ToolRegistry()
        facts, clock = _FactsFixture(), _ClockFixture()
        registry.register_tool(facts, permission="test.read", read_only=True)
        registry.register_tool(clock, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, _AllowTestPermission())
        schemas = [{"type": "function", "function": {
            "name": tool.name, "description": tool.description,
            "parameters": {"type": "object", "properties": {}, "required": [],
                           "additionalProperties": False},
        }} for tool in (facts, clock)]

        class TimedRouter:
            def __init__(self, underlying):
                self.underlying = underlying
                self.samples = []

            def generate_turn(self, messages, prompt, *, tools=(), cancel_event=None):
                started = time.monotonic()
                turn = self.underlying.generate_turn(messages, prompt, tools=tools,
                                                     cancel_event=cancel_event)
                self.samples.append((len(tools), time.monotonic() - started,
                                     len(turn.tool_calls), bool(turn.text.strip()),
                                     turn.text.strip()[:100]))
                return turn

        timed = TimedRouter(router)
        answer = run_operational_loop(
            router=timed,
            messages=[{"role": "user", "content":
                       "Consulte test.facts e test.clock e informe os dois resultados."}],
            system_prompt=("Use os resultados efetivos das ferramentas. Responda em português, "
                           "sem inventar dados."),
            tools=schemas, dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny",
            max_iterations=4, max_calls=4, timeout_seconds=90,
        )
        print(f"OLLAMA_LIVE_INTEGRATED model={model} turns={timed.samples!r} "
              f"facts_calls={facts.calls} clock_calls={clock.calls} answer={answer!r}")
        self.assertEqual((facts.calls, clock.calls), (1, 1))
        self.assertEqual([sample[0] for sample in timed.samples], [1, 1, 0])
        self.assertIn("operacional", answer.casefold())
        self.assertIn("07:45", answer)

    def test_text_tool_call_dispatch_and_final_answer(self):
        model = os.environ.get("AUROVA_OLLAMA_MODEL", "llama3.2:1b")
        router = ModelRouter({
            "ai_provider": "ollama", "ollama_model": model, "ai_timeout": 25,
            "ollama_num_ctx": 512, "ollama_num_predict": 48, "ollama_num_threads": 1,
        })
        started = time.monotonic()
        text_reply = router.generate([{"role": "user", "content": "Responda apenas OK."}],
                                     "Responda brevemente.")
        text_elapsed = time.monotonic() - started
        print(f"OLLAMA_TURN turn=0 roles=['user'] messages=1 tools=0 proposed=0 dispatched=0 "
              f"results=0 inference_seconds={text_elapsed:.2f} cancel=false response=text "
              f"termination=provider_return")
        self.assertTrue(text_reply.strip())

        registry = ToolRegistry()
        fixture = _ClockFixture()
        registry.register_tool(fixture, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, _AllowTestPermission())
        schemas = [{"type": "function", "function": {
            "name": "test.clock", "description": fixture.description,
            "parameters": {"type": "object", "properties": {},
                           "required": [], "additionalProperties": False},
        }}]
        user_message = {"role": "user", "content": "Que horas são? Consulte test.clock."}
        started = time.monotonic()
        proposed = _model_turn(router, [user_message],
            "Use a ferramenta test.clock exatamente uma vez. Não invente horários.", schemas, 1)
        proposal_elapsed = time.monotonic() - started
        self.assertEqual(len(proposed.tool_calls), 1,
                         f"Resposta não estruturada não é uma tool call: {proposed.text!r}")
        self.assertEqual(proposed.tool_calls[0].name, "test.clock")
        self.assertEqual(proposed.tool_calls[0].arguments, {})
        dispatched = _dispatch_turn(proposed, dispatcher, 1)
        self.assertEqual(dispatched.results[0].state, "succeeded")
        self.assertEqual(fixture.calls, 1)

        started = time.monotonic()
        final = _model_turn(router,
            [user_message, *dispatched.to_ollama_messages()],
            "A mensagem role=tool é o resultado efetivo da ferramenta. Use exatamente o campo time "
            "que ela contém e não use argumentos, não invente nem altere o horário. Se não houver "
            "horário no resultado, diga que não foi possível obtê-lo. Não solicite outra ferramenta.",
            schemas, 2,
        )
        final_elapsed = time.monotonic() - started
        answer = final.text.strip()
        print(f"OLLAMA_LIVE model={model} text_seconds={text_elapsed:.2f} "
              f"proposal_seconds={proposal_elapsed:.2f} final_seconds={final_elapsed:.2f} "
              f"fake_tool_calls={fixture.calls} tool_history="
              f"{dispatched.to_ollama_messages()!r} answer={answer!r}")
        self.assertFalse(final.tool_calls, "Ollama solicitou outra ferramenta após receber o resultado")
        self.assertEqual(fixture.calls, 1, "Ollama não emitiu uma tool call estruturada válida")
        self.assertIn("07:45", answer)

    def test_sequential_tool_results_remain_distinct(self):
        model = os.environ.get("AUROVA_OLLAMA_MODEL", "llama3.2:1b")
        router = ModelRouter({
            "ai_provider": "ollama", "ollama_model": model, "ai_timeout": 25,
            "ollama_num_ctx": 768, "ollama_num_predict": 72, "ollama_num_threads": 1,
        })
        registry = ToolRegistry()
        facts, clock = _FactsFixture(), _ClockFixture()
        registry.register_tool(facts, permission="test.read", read_only=True)
        registry.register_tool(clock, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, _AllowTestPermission())
        schemas = {tool.name: {"type": "function", "function": {
            "name": tool.name, "description": tool.description,
            "parameters": {"type": "object", "properties": {}, "required": [],
                           "additionalProperties": False},
        }} for tool in (facts, clock)}
        instructions = (
            "Use somente a ferramenta solicitada na última mensagem do usuário. "
            "Não invente resultados nem responda antes de chamar a ferramenta."
        )
        history = [{"role": "user", "content": "Consulte test.facts uma vez."}]
        first = _model_turn(router, history, instructions, [schemas["test.facts"]], 1)
        self.assertEqual([(call.name, call.arguments) for call in first.tool_calls],
                         [("test.facts", {})], f"Resposta não estruturada: {first.text!r}")
        first_result = _dispatch_turn(first, dispatcher, 1)
        self.assertEqual(first_result.results[0].state, "succeeded")
        history.extend(first_result.to_ollama_messages())
        history.append({"role": "user", "content": "Agora consulte test.clock uma vez."})

        second = _model_turn(router, history, instructions, [schemas["test.clock"]], 2)
        self.assertEqual([(call.name, call.arguments) for call in second.tool_calls],
                         [("test.clock", {})], f"Resposta não estruturada: {second.text!r}")
        second_result = _dispatch_turn(second, dispatcher, 2)
        self.assertEqual(second_result.results[0].state, "succeeded")
        history.extend(second_result.to_ollama_messages())
        history.append({"role": "user", "content": "Resuma os dois resultados."})

        final = _model_turn(router,
            history,
            "As duas mensagens role=tool são os resultados efetivos das chamadas anteriores. "
            "Agora responda ao usuário em português, sem solicitar outra ferramenta. Informe status "
            "e horário exatamente. Não confunda chamadas nem invente dados.",
            list(schemas.values()), 3,
        )
        answer = final.text.strip()
        print(f"OLLAMA_LIVE_SEQUENTIAL model={model} calls={facts.calls + clock.calls} answer={answer!r}")
        self.assertFalse(final.tool_calls)
        self.assertEqual((facts.calls, clock.calls), (1, 1))
        self.assertIn("operacional", answer.casefold())
        self.assertIn("07:45", answer)

    def test_failed_fake_tool_is_reported_as_failure_in_real_continuation(self):
        model = os.environ.get("AUROVA_OLLAMA_MODEL", "llama3.2:1b")
        router = ModelRouter({
            "ai_provider": "ollama", "ollama_model": model, "ai_timeout": 25,
            "ollama_num_ctx": 512, "ollama_num_predict": 56, "ollama_num_threads": 1,
        })
        registry = ToolRegistry()
        fixture = _FactsFixture(succeeds=False)
        registry.register_tool(fixture, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, _AllowTestPermission())
        schemas = [{"type": "function", "function": {
            "name": fixture.name, "description": fixture.description,
            "parameters": {"type": "object", "properties": {}, "required": [],
                           "additionalProperties": False},
        }}]
        user = {"role": "user", "content": "Consulte test.facts e informe o resultado."}
        # Isolate real-model interpretation of a failure result from tool-call selection.
        # Selection is independently tested in test_text_tool_call_dispatch_and_final_answer.
        proposal = ProviderTurn(tool_calls=(ToolCall("failure-facts-1", "test.facts", {}),))
        failed = _dispatch_turn(proposal, dispatcher, 1)
        self.assertEqual(failed.results[0].state, "failed")
        final = _model_turn(router,
            [user, *failed.to_ollama_messages()],
            "O resultado role=tool indica falha. Informe que a ferramenta está indisponível; "
            "não diga que está operacional e não invente resultado.", schemas, 2,
        )
        answer = final.text.strip()
        print(f"OLLAMA_LIVE_FAILURE model={model} result=failed answer={answer!r}")
        self.assertFalse(final.tool_calls)
        self.assertRegex(answer.casefold(),
                         r"indispon|falh|não foi possível|nao foi possivel|não consegui|nao consegui|"
                         r"não pude verificar|nao pude verificar|não foi disponível|nao foi dispon|derrota")
        self.assertNotIn("operacional", answer.casefold())

    def test_empty_fake_tool_result_is_not_presented_as_success(self):
        model = os.environ.get("AUROVA_OLLAMA_MODEL", "llama3.2:1b")
        router = ModelRouter({
            "ai_provider": "ollama", "ollama_model": model, "ai_timeout": 25,
            "ollama_num_ctx": 512, "ollama_num_predict": 56, "ollama_num_threads": 1,
        })
        registry = ToolRegistry()

        class EmptyFacts(_FactsFixture):
            def execute(self, _arguments):
                self.calls += 1
                return ActionResult(True, "", {})

        fixture = EmptyFacts()
        registry.register_tool(fixture, permission="test.read", read_only=True)
        dispatcher = ToolDispatcher(registry, _AllowTestPermission())
        schema = {"type": "function", "function": {
            "name": fixture.name, "description": fixture.description,
            "parameters": {"type": "object", "properties": {}, "required": [],
                           "additionalProperties": False},
        }}
        # The live model must still select the registered tool. The loop blocks
        # finalization after the empty result, before generated prose can invent it.
        started = time.monotonic()
        answer = run_operational_loop(
            router=router,
            messages=[{"role": "user", "content": "Consulte test.facts e informe o resultado."}],
            system_prompt="Use a ferramenta indicada; não invente dados.", tools=[schema],
            dispatcher=dispatcher, confirm=lambda _call, **_kwargs: "deny",
            max_iterations=3, timeout_seconds=75,
        )
        elapsed = time.monotonic() - started
        print(f"OLLAMA_LIVE_EMPTY model={model} seconds={elapsed:.2f} calls={fixture.calls} "
              f"answer={answer!r}")
        self.assertEqual(fixture.calls, 1)
        self.assertIn("resultado vazio", answer.casefold())
        self.assertNotIn("operacional", answer.casefold())


if __name__ == "__main__":
    unittest.main()
