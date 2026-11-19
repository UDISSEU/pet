import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from training.operational.schema import validate_record
from training.operational.storage import LIMIT, StorageManager
from training.operational.benchmark import run
from training.operational.dispatcher_benchmark import run_dispatcher_benchmark
from training.operational.catalog import build_catalog
from aurova_ai.actions.action_validator import ActionValidator
from providers.tool_contract import ProviderTurn, ToolCall, ToolCallResult, parse_ollama_turn
from training.operational.dispatcher_benchmark import _environment

DATA = Path(__file__).parents[2] / "training" / "operational" / "data"

class OperationalPreparationTests(unittest.TestCase):
    def test_datasets_are_valid_and_separated(self):
        train=[json.loads(x) for x in (DATA/"train.jsonl").read_text().splitlines()]
        benchmark=[json.loads(x) for x in (DATA/"benchmark.jsonl").read_text().splitlines()]
        self.assertEqual(len(train),16); self.assertEqual(len(benchmark),50)
        self.assertTrue(all(validate_record(x)["split"]=="train" for x in train))
        self.assertTrue(all(validate_record(x)["split"]=="evaluation" for x in benchmark))
        self.assertFalse({x["id"] for x in train}&{x["id"] for x in benchmark})

    def test_fake_provider_runs_all_benchmark(self):
        result=run(DATA/"benchmark.jsonl")
        self.assertEqual(result["tasks"],50)
        self.assertTrue(all(v==50 for v in result["scores"].values()))

    def test_storage_measures_actual_bytes_and_blocks_overflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=StorageManager(Path(tmp)/"material",limit_bytes=10)
            manager.write_bytes("datasets/a.bin",b"123456")
            self.assertEqual(manager.report()["used_bytes"],6)
            with self.assertRaises(OSError): manager.write_bytes("models/b.bin",b"12345")
            with self.assertRaises(ValueError): StorageManager(Path(tmp)/"too-large",limit_bytes=LIMIT+1)

    def test_storage_copy_overwrite_inventory_and_missing_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"material"; manager=StorageManager(root,limit_bytes=40)
            source=Path(tmp)/"input.bin"; source.write_bytes(b"abc")
            manager.copy_file(source,"datasets/nested/copied.bin")
            self.assertEqual((root/"datasets/nested/copied.bin").read_bytes(),b"abc")
            manager.write_bytes("datasets/nested/copied.bin",b"12345")
            report=manager.report()
            row=next(x for x in report["files"] if x["file"]=="datasets/nested/copied.bin")
            self.assertEqual(row["size_bytes"],5); self.assertEqual(report["used_bytes"],5)

    def test_storage_failed_write_cleans_stage_and_can_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=StorageManager(Path(tmp)/"material",limit_bytes=20)
            with self.assertRaises(RuntimeError):
                with manager.open_text("datasets/partial.txt",max_bytes=10) as stream:
                    stream.write("partial")
                    raise RuntimeError("simulated disk failure")
            self.assertEqual(manager.report()["used_bytes"],0)
            manager.write_text("datasets/resumed.txt","ok")
            self.assertEqual(manager.report()["used_bytes"],2)

    def test_storage_serializes_concurrent_reservations(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=StorageManager(Path(tmp)/"material",limit_bytes=10)
            outcomes=[]
            def write(name):
                try: manager.write_bytes(name,b"123456"); outcomes.append("ok")
                except OSError: outcomes.append("blocked")
            threads=[threading.Thread(target=write,args=(f"datasets/{i}",)) for i in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertCountEqual(outcomes,["ok","blocked"])
            self.assertLessEqual(manager.report()["used_bytes"],10)

    def test_dispatcher_benchmark_uses_true_dispatcher_with_fake_tools(self):
        result=run_dispatcher_benchmark(DATA/"benchmark.jsonl")
        self.assertEqual(result["mode"],"dispatcher_simulated")
        self.assertEqual(result["metrics"]["dispatched"],30)
        self.assertEqual(result["metrics"]["simulated_success"],25)
        self.assertEqual(result["cognitive_pipeline"]["clarified"],5)
        self.assertEqual(result["cognitive_pipeline"]["verified"],5)
        self.assertTrue(all(result["simulated_capabilities"].values()))
        self.assertTrue(all(item["blocked"] for item in result["security_scenarios"].values() if "success" not in item))

    def test_canonical_dataset_builder_writes_through_storage_manager(self):
        from training.training_config import TrainingConfig
        from training.dataset_builder import DatasetBuilder
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"training"; manager=StorageManager(root)
            raw=root/"datasets/raw"; raw.mkdir(parents=True)
            source=raw/"seed.txt"
            manager.write_text(manager.relative_path(source),"\n".join(f"registro sintético número {i} para teste" for i in range(20))+"\n")
            config=TrainingConfig(dataset_root=root/"datasets",experiments_root=root/"experiments",
                                  checkpoints_root=root/"checkpoints",storage_root=root,run_name="unit")
            result=DatasetBuilder(config).build()
            self.assertTrue(result.train_path.is_file() and result.validation_path.is_file())
            self.assertGreater(manager.report()["used_bytes"],source.stat().st_size)

    def test_experiment_history_and_model_config_are_quota_managed(self):
        from aurova_ai.model.model_config import ModelConfig
        from aurova_ai.model.model_metadata import ModelHistory, ModelMetadata
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            root=Path(tmp)/"training"
            database=root/"experiments/run/history.sqlite3"
            history=ModelHistory(database)
            config=ModelConfig(vocab_size=1000)
            metadata=ModelMetadata.new(training_steps=0,parameter_count=config.parameter_count)
            history.record(config,metadata)
            config.save_json(root/"models/config.json")
            report=StorageManager(root).report()
            names={item["file"] for item in report["files"]}
            self.assertIn("experiments/run/history.sqlite3",names)
            self.assertIn("models/config.json",names)

    def test_structured_tool_call_requires_dispatcher_confirmation_and_has_continuation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/"files"; root.mkdir()
            state, _registry, _permissions, dispatcher, _policy = _environment(root,Path(temp)/"permissions.json")
            parsed=parse_ollama_turn({"message":{"content":"Vou abrir com autorização.","tool_calls":[
                {"id":"call-1","function":{"name":"apps.launch","arguments":{"app_id":"fake.desktop"}}}]}})
            self.assertEqual(parsed.text,"Vou abrir com autorização.")
            self.assertEqual(parsed.tool_calls[0].arguments,{"app_id":"fake.desktop"})
            from providers.tool_contract import dispatch_tool_calls
            pending=dispatch_tool_calls(parsed,dispatcher,approved=False)
            self.assertEqual(pending.results[0].state,"confirmation_required")
            self.assertEqual(state.get("launched",[]),[])
            done=dispatch_tool_calls(parsed,dispatcher,approved=True)
            self.assertEqual(done.results[0].state,"succeeded")
            self.assertTrue(done.continuation)
            messages=done.continuation_messages()
            self.assertEqual(messages[-1]["role"],"tool")
            batch=ProviderTurn(tool_calls=(ToolCall("a","apps.launch",{"app_id":"one.desktop"}),
                                           ToolCall("b","apps.launch",{"app_id":"two.desktop"})))
            batch_result=dispatch_tool_calls(batch,dispatcher,approved=True)
            self.assertTrue(all(item.state=="confirmation_required" for item in batch_result.results))
            self.assertEqual(len(state.get("launched",[])),1)
            unknown=dispatch_tool_calls(ProviderTurn(tool_calls=(ToolCall("u1","shell.run",{"command":"x"}),)),dispatcher)
            self.assertEqual(unknown.results[0].state,"failed")

    def test_ollama_continuation_maps_calls_and_results_to_chat_protocol(self):
        turn = ProviderTurn(
            text="",
            tool_calls=(
                ToolCall("clock-1", "system.clock", {}),
                ToolCall("apps-1", "apps.list", {}),
            ),
            results=(
                ToolCallResult("clock-1", "system.clock", "succeeded", {
                    "summary": "Horário consultado", "data": {"value": "13:20"},
                }),
                ToolCallResult("apps-1", "apps.list", "succeeded", {
                    "summary": "Consulta concluída", "data": "Nenhum aplicativo encontrado",
                }),
            ),
        )
        messages = turn.to_ollama_messages()
        self.assertEqual(messages[0], {
            "role": "assistant", "content": "", "tool_calls": [
                {"id": "clock-1", "function": {"name": "system.clock", "arguments": {}}},
                {"id": "apps-1", "function": {"name": "apps.list", "arguments": {}}},
            ],
        })
        self.assertEqual(messages[1], {
            "role": "tool", "tool_name": "system.clock", "tool_call_id": "clock-1",
            "content": '{"value":"13:20"}',
        })
        self.assertEqual(messages[2], {
            "role": "tool", "tool_name": "apps.list", "tool_call_id": "apps-1",
            "content": "Nenhum aplicativo encontrado",
        })
        self.assertEqual(turn.continuation_messages(), messages)

    def test_ollama_tool_call_turn_drops_unrelated_text_from_assistant_envelope(self):
        turn = ProviderTurn(text='```json {"name":"wrong"}```', tool_calls=(
            ToolCall("safe-1", "system.clock", {}),
        ))
        self.assertEqual(turn.to_ollama_messages()[0]["content"], "")

    def test_ollama_continuation_preserves_failure_empty_and_special_results(self):
        results = (
            ToolCallResult("failed-1", "system.clock", "failed", {"message": "Ferramenta indisponível"}),
            ToolCallResult("empty-1", "system.clock", "succeeded", {"data": {}}),
            ToolCallResult("special-1", "system.clock", "succeeded", {"data": "Ação: \"não\"\\nlinha 2"}),
        )
        messages = ProviderTurn(results=results).to_ollama_messages()
        self.assertIn("Tool status: failed", messages[1]["content"])
        self.assertIn("Ferramenta indisponível", messages[1]["content"])
        self.assertEqual(messages[2]["content"], "The tool succeeded but returned no data.")
        self.assertEqual(messages[3]["content"], 'Ação: "não"\\nlinha 2')

    def test_text_that_mentions_json_is_not_parsed_as_a_tool_call(self):
        turn = parse_ollama_turn({"message": {
            "content": '{"tool":"system.clock","arguments":{}}',
        }})
        self.assertEqual(turn.tool_calls, ())
        self.assertEqual(turn.text, '{"tool":"system.clock","arguments":{}}')

    def test_ollama_structured_method_parses_without_running_tools(self):
        from providers.ollama_provider import OllamaProvider
        from unittest import mock
        class Response:
            def __enter__(self): return self
            def __exit__(self,*_args): return False
            def read(self): return b'{"message":{"content":"","tool_calls":[{"function":{"name":"files.search","arguments":{"query":"x"}}}]}}'
        with mock.patch("providers.ollama_provider.urllib.request.urlopen",return_value=Response()) as open_url:
            turn=OllamaProvider().generate_turn([],"prompt",tools=[{"type":"function"}])
        self.assertEqual(turn.tool_calls[0].name,"files.search")
        self.assertIn(b'"tools"',open_url.call_args.args[0].data)

    def test_ollama_provider_preserves_system_prompt_and_full_tool_history(self):
        from providers.ollama_provider import OllamaProvider
        history = [
            {"role": "user", "content": "Que horas são?"},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "clock-7", "function": {"name": "system.clock", "arguments": {}},
            }]},
            {"role": "tool", "tool_name": "system.clock", "tool_call_id": "clock-7",
             "content": "07:45"},
        ]
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def read(self): return b'{"message":{"role":"assistant","content":"Sao 07:45."}}'
        with mock.patch("providers.ollama_provider.urllib.request.urlopen", return_value=Response()) as open_url:
            final = OllamaProvider().generate_turn(history, "Preserve a identidade Aurova.", tools=[])
        payload = json.loads(open_url.call_args.args[0].data)
        self.assertEqual(payload["messages"], [
            {"role": "system", "content": "Preserve a identidade Aurova."}, *history,
        ])
        self.assertEqual(final.text, "Sao 07:45.")
        self.assertEqual(len(payload["messages"]), 4)

    def test_ollama_structured_inference_discards_response_after_cancellation(self):
        import threading
        from providers.base_provider import ProviderCancelled
        from providers.ollama_provider import OllamaProvider
        cancel = threading.Event()
        class Response:
            def __enter__(self): return self
            def __exit__(self,*_args): return False
            def read(self):
                cancel.set()
                return b'{"message":{"content":"late answer"}}'
        with mock.patch("providers.ollama_provider.urllib.request.urlopen",return_value=Response()):
            with self.assertRaises(ProviderCancelled):
                OllamaProvider().generate_turn([],"prompt",tools=[],cancel_event=cancel)

    def test_ollama_skips_request_when_already_cancelled(self):
        import threading
        from providers.base_provider import ProviderCancelled
        from providers.ollama_provider import OllamaProvider
        cancel = threading.Event(); cancel.set()
        with mock.patch("providers.ollama_provider.urllib.request.urlopen") as open_url:
            with self.assertRaises(ProviderCancelled):
                OllamaProvider().generate_turn([],"prompt",tools=[],cancel_event=cancel)
        open_url.assert_not_called()

    def test_sensitive_data_and_shell_arguments_rejected(self):
        row=json.loads((DATA/"train.jsonl").read_text().splitlines()[0])
        row["context"]["note"]="api_key=private"
        with self.assertRaises(ValueError): validate_record(row)

    def test_catalog_matches_real_registry_and_shell_keys_are_rejected(self):
        catalog=build_catalog()
        self.assertEqual(len(catalog),13)
        self.assertEqual(len({item["name"] for item in catalog}),13)
        with self.assertRaises(ValueError): ActionValidator().validate("system.clock",{"command":"whoami"})

if __name__=="__main__": unittest.main()
