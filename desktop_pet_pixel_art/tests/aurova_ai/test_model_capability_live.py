"""Repeatable, direct Ollama capability evaluation; no operational loop or real tools."""
import json
import os
import time
import unittest

from ai.model_router import ModelRouter
from providers.tool_contract import ProviderTurn, ToolCall, ToolCallResult


def _schema(name, description, properties=None, required=()):
    return {"type": "function", "function": {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties or {},
                       "required": list(required), "additionalProperties": False},
    }}


def _kind(turn):
    if turn.tool_calls:
        return "tool_calls"
    if turn.text.strip():
        return "json_text" if "{" in turn.text or "```" in turn.text else "text"
    return "empty"


@unittest.skipUnless(os.environ.get("AUROVA_RUN_LIVE_OLLAMA") == "1",
                     "Defina AUROVA_RUN_LIVE_OLLAMA=1 para avaliar modelos locais instalados")
class LiveModelCapabilityEvaluation(unittest.TestCase):
    """Model-only tests. A failed model response is a measurement, not a test error."""

    @classmethod
    def setUpClass(cls):
        cls.model = os.environ.get("AUROVA_OLLAMA_MODEL", "llama3.2:1b")
        cls.router = ModelRouter({
            "ai_provider": "ollama", "ollama_model": cls.model, "ai_timeout": 25,
            "ollama_num_ctx": 512, "ollama_num_predict": 48, "ollama_num_threads": 1,
        })
        cls.rows = []

    def _turn(self, case, repeat, prompt, schemas, expected_name=None, expected_args=None,
              *, messages=None):
        started = time.monotonic()
        error = None
        try:
            turn = self.router.generate_turn(
                messages or [{"role": "user", "content": prompt}],
                "Use only the offered tool schemas. Make a structured tool call when requested. "
                "Do not write JSON as prose and do not invent tools or argument values.",
                tools=schemas,
            )
            duration = time.monotonic() - started
            kind = _kind(turn)
            calls = [{"name": call.name, "arguments": call.arguments} for call in turn.tool_calls]
            names = [call.name for call in turn.tool_calls]
            matching = [call for call in turn.tool_calls if call.name == expected_name]
            args_valid = (matching[0].arguments == expected_args) if expected_name and len(matching) == 1 else None
            selection_valid = (len(turn.tool_calls) == 1 and names == [expected_name]) \
                if expected_name else None
            invented = any(name not in {schema["function"]["name"] for schema in schemas} for name in names)
            row = {
                "case": case, "repeat": repeat, "seconds": round(duration, 2),
                "schema_count": len(schemas), "response": kind, "calls": calls,
                "args_valid": args_valid, "selection_valid": selection_valid,
                "invented_tool": invented,
                "text": turn.text.strip()[:1200], "error": None,
            }
        except Exception as exc:
            row = {
                "case": case, "repeat": repeat, "seconds": round(time.monotonic() - started, 2),
                "schema_count": len(schemas), "response": "provider_error",
                "calls": [], "args_valid": None, "selection_valid": None,
                "invented_tool": False,
                "text": "", "error": type(exc).__name__,
            }
        self.rows.append(row)
        print("MODEL_EVAL " + json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)
        return row

    def _run_repeats(self, case, prompt, schemas, expected_name, expected_args, count):
        return [self._turn(case, repeat, prompt, schemas, expected_name, expected_args)
                for repeat in range(1, count + 1)]

    def test_isolated_schema_and_selection_matrix(self):
        no_args = _schema("test.facts", "Return the current operational status.")
        required_arg = _schema("test.lookup", "Look up the requested record.",
                               {"query": {"type": "string"}}, ("query",))
        two_args = _schema("test.convert", "Convert a quantity between units.", {
            "value": {"type": "number"}, "unit": {"type": "string"},
        }, ("value", "unit"))
        short_desc = _schema("test.action", "Call this tool.")
        detailed_desc = _schema("test.action", (
            "Use this read-only fixture to retrieve the status record requested by the user. "
            "It accepts no arguments and returns only a synthetic test result."
        ))
        clock = _schema("test.clock", "Return a synthetic clock value.")

        # Five repetitions of each essential argument-shape/selection scenario.
        self._run_repeats("no_arguments", "Call test.facts exactly once.",
                          [no_args], "test.facts", {}, 5)
        self._run_repeats("one_required_argument",
                          'Call test.lookup with query "status".',
                          [required_arg], "test.lookup", {"query": "status"}, 5)
        self._run_repeats("two_required_arguments",
                          'Call test.convert with value 3 and unit "kg".',
                          [two_args], "test.convert", {"value": 3, "unit": "kg"}, 5)
        self._turn("short_description", "single", "Call test.action exactly once.",
                   [short_desc], "test.action", {})
        self._turn("detailed_description", "single", "Call test.action exactly once.",
                   [detailed_desc], "test.action", {})
        self._run_repeats("choose_one_of_two",
                          "Call test.facts exactly once. Do not call test.clock.",
                          [no_args, clock], "test.facts", {}, 5)
        # Model failures are recorded; the harness only asserts it completed its
        # planned observations and never promotes text into a structured call.
        self.assertEqual(len(self.rows), 22)

    def _grounding_fixture(self, case, repeat, result, call_name, schemas_for_final):
        tool_schema = next(schema for schema in schemas_for_final
                           if schema["function"]["name"] == call_name)
        proposed = self._turn(case + "_proposal", repeat,
                              f"Call {call_name} exactly once.", [tool_schema], call_name, {})
        if (proposed["response"] != "tool_calls" or proposed["args_valid"] is not True
                or proposed["selection_valid"] is not True):
            return None
        call = ToolCall(f"{case}-{repeat}", call_name, {})
        tool_result = ToolCallResult(call.call_id, call.name, "succeeded", {"data": result})
        history = [
            {"role": "user", "content": f"Use {call_name} and report its result."},
            *ProviderTurn(tool_calls=(call,), results=(tool_result,)).to_ollama_messages(),
        ]
        final = self._turn(case + "_final", repeat,
                           "Report exactly the value returned by the tool; do not invent data.",
                           schemas_for_final, messages=history)
        final["grounded"] = all(value in final["text"] for value in
                                (str(v) for v in result.values()))
        return final

    def test_single_tool_result_grounding_repeated(self):
        facts = _schema("test.facts", "Return synthetic operational facts.")
        outcomes = [self._grounding_fixture("ground_one_tool", i,
                    {"status": "operacional"}, "test.facts", [facts]) for i in range(1, 6)]
        self.assertEqual(len(outcomes), 5)
        successes = sum(bool(outcome and outcome.get("grounded")) for outcome in outcomes)
        print(f"MODEL_EVAL_SUMMARY case=ground_one_tool_grounded successes={successes}/5",
              flush=True)

    def _two_tool_sequence(self, case, repeat, first_schemas, decision_schemas, final_schemas):
        facts = _schema("test.facts", "Return the synthetic status: operational.")
        clock = _schema("test.clock", "Return the synthetic time: 07:45.")
        values = {"test.facts": {"status": "operacional"},
                  "test.clock": {"time": "07:45"}}
        history = [{"role": "user", "content":
                    "Obtain both the test.facts status and test.clock time, then report both."}]
        seen = set()
        for step, name in enumerate(("test.facts", "test.clock"), start=1):
            candidates = first_schemas if step == 1 else decision_schemas
            if step == 2:
                history.append({"role": "user", "content":
                                "Now call test.clock exactly once, then report both results."})
            row = self._turn(case + f"_step_{step}", repeat,
                             f"Call {name} exactly once now. Do not call another tool yet.",
                             candidates, name, {},
                             messages=history)
            if (row["response"] != "tool_calls" or row["args_valid"] is not True
                    or row["selection_valid"] is not True):
                return False
            call = ToolCall(f"{case}-{repeat}-{step}", name, {})
            result = ToolCallResult(call.call_id, name, "succeeded", {"data": values[name]})
            history.extend(ProviderTurn(tool_calls=(call,), results=(result,)).to_ollama_messages())
            seen.add(name)
        final = self._turn(case + "_final", repeat,
            "Summarize both tool results exactly. Do not invent missing values.", final_schemas,
            messages=history)
        return (seen == set(values) and final["response"] in {"text", "json_text"}
                and "operacional" in final["text"].casefold() and "07:45" in final["text"])

    def test_two_tool_continuation_with_full_catalog_after_seeded_first_result(self):
        """Isolate C's decision turn; the first fixture result is deliberately seeded."""
        facts = _schema("test.facts", "Return the synthetic status: operational.")
        clock = _schema("test.clock", "Return the synthetic time: 07:45.")
        outcomes = []
        for repeat in range(1, 6):
            first = ToolCall(f"seed-facts-{repeat}", "test.facts", {})
            first_result = ToolCallResult(first.call_id, first.name, "succeeded",
                                          {"data": {"status": "operacional"}})
            history = [
                {"role": "user", "content":
                 "Get both test.facts and test.clock results, then report them."},
                *ProviderTurn(tool_calls=(first,), results=(first_result,)).to_ollama_messages(),
                {"role": "user", "content":
                 "The test.facts result is available. Continue with test.clock exactly once."},
            ]
            row = self._turn("schemas_during_decision_after_seeded_result", repeat,
                             "Use the existing result and call test.clock exactly once.",
                             [facts, clock], "test.clock", {}, messages=history)
            success = (row["response"] == "tool_calls" and row["args_valid"] is True
                       and row["selection_valid"] is True)
            if success:
                clock_call = ToolCall(f"seed-clock-{repeat}", "test.clock", {})
                clock_result = ToolCallResult(clock_call.call_id, clock_call.name, "succeeded",
                                              {"data": {"time": "07:45"}})
                history.extend(ProviderTurn(tool_calls=(clock_call,),
                                            results=(clock_result,)).to_ollama_messages())
                final = self._turn("schemas_during_decision_final", repeat,
                    "Summarize the two returned results exactly.", [facts, clock], messages=history)
                success = (final["response"] in {"text", "json_text"}
                           and "operacional" in final["text"].casefold()
                           and "07:45" in final["text"])
            outcomes.append(bool(success))
        print(f"MODEL_EVAL_SUMMARY case=schemas_during_decision_after_seeded_result "
              f"successes={sum(outcomes)}/5", flush=True)

    def test_two_tool_grounding_modes(self):
        facts = _schema("test.facts", "Return the synthetic status: operational.")
        clock = _schema("test.clock", "Return the synthetic time: 07:45.")
        modes = (
            ("sequence_reduced", [facts], [clock], [facts, clock]),
            ("final_without_schemas", [facts], [clock], []),
        )
        outcomes = {}
        for name, first_schemas, decision_schemas, final_schemas in modes:
            repeats = 5
            outcomes[name] = [self._two_tool_sequence(
                              name, repeat, first_schemas, decision_schemas, final_schemas)
                              for repeat in range(1, repeats + 1)]
            print(f"MODEL_EVAL_SUMMARY case={name} successes={sum(outcomes[name])}/"
                  f"{len(outcomes[name])}", flush=True)
        self.assertEqual(len(outcomes), len(modes))


if __name__ == "__main__":
    unittest.main()
