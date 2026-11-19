"""Dispatcher evaluation using the production registry/validator/dispatcher and fake tools."""
from pathlib import Path
import json
import tempfile

from permissions import PermissionManager
from aurova_ai.actions import (ActionRegistry, ActionResult, AuthorizationRequired,
                              CancellationToken, DirectoryAccessPolicy, Tool,
                              ToolDispatcher, ToolDispatchError)
from aurova_ai.cognition import CognitiveEngine, TaskStatus

PLUGIN = "aurova.benchmark"

class FakeSandboxTool(Tool):
    """Stateful fake: filesystem writes are confined to one TemporaryDirectory."""
    def __init__(self, name, permission, *, state, root, read_only=True, confirm=False):
        self.name, self.permission = name, permission
        self.state, self.root = state, Path(root)
        self.read_only, self.confirm = read_only, confirm
        self.description = "SIMULATED benchmark tool; not an Aurova production capability"

    def execute(self, arguments):
        if self.name == "files.search":
            query = arguments.get("query")
            if not isinstance(query, str) or not query:
                raise ValueError("query obrigatório")
            root = Path(arguments.get("root", self.root))
            return ActionResult(True, "Busca simulada concluída.", {
                "matches": sorted(p.name for p in root.iterdir() if query.casefold() in p.name.casefold())})
        if self.name == "files.list_directory":
            path = Path(arguments.get("directory", self.root))
            return ActionResult(True, "Listagem simulada concluída.", {"entries": sorted(p.name for p in path.iterdir())})
        if self.name == "files.preview_downloads":
            plan = [{"source": str(p), "destination": str(self.root / "Documentos" / p.name)}
                    for p in self.root.iterdir() if p.is_file()]
            self.state["plan"] = plan
            return ActionResult(True, "Prévia simulada.", {"plan": plan})
        if self.name == "files.organize_downloads":
            if arguments.get("plan") != self.state.get("plan"):
                raise ValueError("plano não corresponde à prévia simulada")
            moved = []
            for row in arguments["plan"]:
                source, destination = Path(row["source"]), Path(row["destination"])
                if source.parent != self.root or self.root not in destination.parents:
                    raise ValueError("caminho fora do sandbox")
                destination.parent.mkdir(exist_ok=True)
                source.replace(destination)
                moved.append(str(destination))
            return ActionResult(True, "Organização simulada em diretório temporário.", {"moved": moved})
        if self.name == "apps.list":
            return ActionResult(True, "Catálogo sintético.", {"apps": ["editor-fake.desktop"]})
        if self.name == "apps.launch":
            app_id = arguments.get("app_id")
            if not isinstance(app_id, str) or not app_id.endswith(".desktop"):
                raise ValueError("app_id inválido")
            self.state.setdefault("launched", []).append(app_id)
            return ActionResult(True, "Abertura simulada; nenhum aplicativo foi iniciado.", {"app_id": app_id})
        if self.name == "documents.read":
            key = arguments.get("document_id")
            if key not in self.state.get("documents", {}):
                return ActionResult(False, "Documento sintético inexistente.")
            return ActionResult(True, "Leitura simulada.", {"text": self.state["documents"][key]})
        if self.name == "spreadsheets.update":
            if not all(isinstance(arguments.get(k), str) for k in ("book_id", "cell", "value")):
                raise ValueError("book_id, cell e value são obrigatórios")
            self.state.setdefault("cells", {})[(arguments["book_id"], arguments["cell"])] = arguments["value"]
            return ActionResult(True, "Atualização simulada em memória.", {"cell": arguments["cell"]})
        if self.name == "sim.fail":
            raise RuntimeError("falha sintética")
        raise AssertionError("ferramenta falsa sem implementação")

def _environment(root, permission_path, *, deny=()):
    state = {"documents": {"doc-1": "texto sintético"}}
    registry = ActionRegistry()
    specs = [
        ("files.search", "file.read", True, False),
        ("files.list_directory", "file.read", True, False),
        ("files.preview_downloads", "file.read", True, False),
        ("files.organize_downloads", "file.organize", False, True),
        ("apps.list", "system.app.read", True, False),
        ("apps.launch", "system.app.launch", False, True),
        ("documents.read", "file.read", True, False),
        ("spreadsheets.update", "file.write", False, True),
        ("sim.fail", "file.read", True, False),
    ]
    for name, permission, readonly, confirm in specs:
        tool = FakeSandboxTool(name, permission, state=state, root=root, read_only=readonly, confirm=confirm)
        registry.register(name, tool, permission=permission, read_only=readonly,
                          requires_confirmation=confirm)
    policy = DirectoryAccessPolicy({PLUGIN: (root,)})
    permissions = PermissionManager(path=permission_path)
    for _name, permission, _readonly, _confirm in specs:
        if permission not in deny:
            permissions.authorize(PLUGIN, permission, confirmed=True)
    dispatcher = ToolDispatcher(registry, permissions, plugin_id=PLUGIN, directory_policy=policy)
    return state, registry, permissions, dispatcher, policy

def run_dispatcher_benchmark(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    with tempfile.TemporaryDirectory(prefix="aurova-dispatch-bench-") as temp:
        root = Path(temp) / "files"
        root.mkdir()
        for i in range(10):
            (root / f"exemplo-{i}.txt").write_text(f"fixture {i}", encoding="utf-8")
        state, registry, permissions, dispatcher, _policy = _environment(root, Path(temp)/"permissions.json")
        metrics = {key: 0 for key in ("tasks", "dispatched", "simulated_success", "verified", "confirmation_required", "unsupported_declared", "blocked")}
        planning_rows = [row for row in rows if row["context"].get("category") == "planning"]
        cognitive = _run_cognitive_planning(planning_rows, root, Path(temp)/"cognitive-permissions.json")
        metrics["dispatched"] += cognitive["tool_calls"]
        metrics["simulated_success"] += cognitive["executed_successfully"]
        metrics["verified"] += cognitive["verified"]
        metrics["confirmation_required"] += cognitive["confirmation_requests"]
        for row in rows:
            metrics["tasks"] += 1
            if row["context"].get("category") == "planning":
                if row["intent"] == "clarify":
                    metrics["unsupported_declared"] += 1
                continue
            if not row["tools"]:
                metrics["unsupported_declared"] += 1
                continue
            name = row["tools"][0]
            arguments = row["tool_arguments"].get(name, {})
            if name == "files.search":
                arguments = {**arguments, "root": str(root)}
            if name == "files.preview_downloads":
                result = dispatcher.dispatch(name, arguments)
            else:
                definition = registry.get(name)
                if definition.requires_confirmation:
                    metrics["confirmation_required"] += 1
                    try:
                        dispatcher.dispatch(name, arguments, approved=False)
                    except AuthorizationRequired:
                        pass
                    else:
                        raise AssertionError("dispatcher aceitou mutação sem confirmação")
                result = dispatcher.dispatch(name, arguments, approved=definition.requires_confirmation)
            metrics["dispatched"] += 1
            metrics["simulated_success"] += result.success is True
            metrics["verified"] += result.success is True and isinstance(result.data, dict)
        security = run_security_scenarios()
        metrics["blocked"] = sum(item["blocked"] for item in security.values())
        simulated = run_simulated_capability_scenarios()
        return {"mode": "dispatcher_simulated", "provider": "none; fixed fixtures; no model competence measured",
                "tools": "fake, isolated TemporaryDirectory and in-memory app/document/sheet state",
                "metrics": metrics, "security_scenarios": security,
                "simulated_capabilities": simulated, "cognitive_pipeline": cognitive}

def _run_cognitive_planning(rows, root, permission_path):
    state, registry, permissions, dispatcher, _policy = _environment(root, permission_path)
    engine = CognitiveEngine(actions=registry, permissions=permissions,
        plugin_id=PLUGIN,
        result_verifier=lambda _operation, result, _params: all(Path(p).is_file() for p in result.data.get("moved", [])))
    report={"tasks":len(rows),"interpreted":0,"planned":0,"clarified":0,
            "confirmation_requests":0,"tool_calls":0,"executed_successfully":0,"verified":0}
    for row in rows:
        prepared=engine.interpret(row["user_request"])
        report["interpreted"] += 1
        report["planned"] += bool(prepared.task.steps)
        if prepared.task.status is TaskStatus.NEEDS_CLARIFICATION:
            report["clarified"] += bool(prepared.task.clarification_question)
            continue
        waiting=engine.execute(prepared,approved=False)
        if waiting.status is TaskStatus.AWAITING_CONFIRMATION:
            report["confirmation_requests"] += 1
        outcome=engine.execute(prepared,approved=True)
        report["tool_calls"] += 2 # read-only preview plus confirmed mutation
        report["executed_successfully"] += outcome.status is TaskStatus.SUCCEEDED
        report["verified"] += outcome.verified is True
    return report

def run_simulated_capability_scenarios():
    with tempfile.TemporaryDirectory(prefix="aurova-fake-capabilities-") as temp:
        root = Path(temp)/"files"; root.mkdir()
        (root/"nota.txt").write_text("conteúdo fictício", encoding="utf-8")
        state, _registry, _permissions, dispatcher, _policy = _environment(root, Path(temp)/"permissions.json")
        found = dispatcher.dispatch("files.search", {"query":"nota", "root":str(root)}).data["matches"]
        listed = dispatcher.dispatch("files.list_directory", {"directory":str(root)}).data["entries"]
        preview = dispatcher.dispatch("files.preview_downloads", {}).data["plan"]
        organized = dispatcher.dispatch("files.organize_downloads", {"plan":preview}, approved=True)
        apps = dispatcher.dispatch("apps.list", {}).data["apps"]
        launched = dispatcher.dispatch("apps.launch", {"app_id":"editor-fake.desktop"}, approved=True)
        document = dispatcher.dispatch("documents.read", {"document_id":"doc-1"}).data["text"]
        sheet = dispatcher.dispatch("spreadsheets.update", {"book_id":"book-1", "cell":"A1", "value":"42"}, approved=True)
        return {"files_search": found == ["nota.txt"], "directory_list": "nota.txt" in listed,
                "organize_temp_files": organized.success and not (root/"nota.txt").exists(),
                "apps_catalog": "editor-fake.desktop" in apps,
                "app_open_is_simulated": launched.success and state["launched"] == ["editor-fake.desktop"],
                "document_read_simulated": document == "texto sintético",
                "spreadsheet_update_in_memory": sheet.success and state["cells"][("book-1","A1")] == "42"}

def run_security_scenarios():
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="aurova-dispatch-security-") as temp:
        root = Path(temp)/"root"; root.mkdir()
        outside = Path(temp)/"outside"; outside.mkdir()
        state, registry, permissions, dispatcher, policy = _environment(root, Path(temp)/"permissions.json")
        def blocked(name, action):
            try: action()
            except Exception: outcomes[name] = {"blocked": True, "error": type(__import__('sys').exc_info()[1]).__name__}
            else: outcomes[name] = {"blocked": False, "error": None}
        blocked("unknown_tool", lambda: dispatcher.dispatch("shell.run", {"command":"echo nope"}))
        blocked("invalid_arguments", lambda: dispatcher.dispatch("files.search", {"query": 4}))
        blocked("unauthorized_path", lambda: dispatcher.dispatch("files.search", {"root":str(outside),"query":"x"}))
        link = root/"outside-link"
        try: link.symlink_to(outside, target_is_directory=True)
        except OSError: outcomes["symlink"] = {"blocked": True, "error":"symlink creation unavailable"}
        else: blocked("symlink", lambda: dispatcher.dispatch("files.search", {"root":str(link),"query":"x"}))
        _s, _r, _p, denied_dispatcher, _pol = _environment(root, Path(temp)/"denied.json", deny=("file.read",))
        blocked("permission_denied", lambda: denied_dispatcher.dispatch("files.search", {"query":"x"}))
        blocked("confirmation", lambda: dispatcher.dispatch("apps.launch", {"app_id":"fake.desktop"}, approved=False))
        token = CancellationToken(); token.cancel()
        blocked("cancelled", lambda: dispatcher.dispatch("files.search", {"query":"x"}, cancellation=token))
        blocked("tool_failure", lambda: dispatcher.dispatch("sim.fail", {}))
        blocked("shell_argument", lambda: dispatcher.dispatch("files.search", {"query":"x", "command":"id"}))
        blocked("unregistered_destructive", lambda: dispatcher.dispatch("system.delete", {"path":"/tmp/x"}, approved=True))
        result = dispatcher.dispatch("apps.launch", {"app_id":"fake.desktop"}, approved=True)
        outcomes["confirmed_fake_app"] = {"blocked": False, "success": result.success, "no_real_launch": state["launched"] == ["fake.desktop"]}
    return outcomes
