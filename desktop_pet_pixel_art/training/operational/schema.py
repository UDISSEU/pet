"""Esquema JSONL versionado, com rejeição conservadora de dados sensíveis."""
import re

SECRET = re.compile(r"(?i)(password|senha|token|cookie|api[_ -]?key|secret)\s*[:=]")
REQUIRED = {"id", "schema_version", "user_request", "context", "intent", "plan", "tools", "tool_arguments", "expected_result", "verification", "risk", "requires_confirmation", "confirmation_policy", "success_condition", "possible_failures", "recovery", "source", "human_review", "split"}

def validate_record(row):
    if not isinstance(row, dict) or set(row) != REQUIRED:
        raise ValueError("campos JSONL incompatíveis com schema 1.0.0")
    if row["schema_version"] != "1.0.0" or row["split"] not in {"train", "evaluation"}:
        raise ValueError("versão ou split inválido")
    if row["risk"] not in {"low", "medium", "high", "unknown"} or type(row["requires_confirmation"]) is not bool:
        raise ValueError("classificação de risco inválida")
    text = repr(row)
    if SECRET.search(text):
        raise ValueError("possível dado secreto detectado")
    if not isinstance(row["tools"], list) or not isinstance(row["tool_arguments"], dict):
        raise ValueError("ferramentas ou argumentos inválidos")
    return row
