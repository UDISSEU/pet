"""Validação de benchmark sem Ollama; falso provider reproduz respostas de referência."""
import json
from pathlib import Path
from .schema import validate_record

class ReferenceFakeProvider:
    def respond(self, record):
        return {"tools": record["tools"], "arguments": record["tool_arguments"],
                "clarification": record["intent"] == "clarify", "success": record["success_condition"]}

def run(path, provider=None):
    provider = provider or ReferenceFakeProvider()
    records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    scores = {key: 0 for key in ("interpretation", "tool_selection", "arguments", "planning", "permissions", "completion", "verification", "recovery")}
    for row in records:
        validate_record(row)
        got = provider.respond(row)
        scores["interpretation"] += got["clarification"] == (row["intent"] == "clarify")
        scores["tool_selection"] += got["tools"] == row["tools"]
        scores["arguments"] += got["arguments"] == row["tool_arguments"]
        scores["planning"] += bool(row["plan"])
        scores["permissions"] += not row["requires_confirmation"] or row["risk"] != "high" or row["confirmation_policy"] == "explicit"
        scores["completion"] += bool(row["success_condition"])
        scores["verification"] += bool(row["verification"])
        scores["recovery"] += bool(row["recovery"])
    return {"provider": type(provider).__name__, "tasks": len(records), "scores": scores,
            "max_scores": {key: len(records) for key in scores}}
