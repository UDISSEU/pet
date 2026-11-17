import json
import logging
from pathlib import Path
import urllib.error
import urllib.request

from assistant_actions import current_datetime_context
from config import HISTORY_PATH, OLLAMA_MODEL, OLLAMA_URL, SYSTEM_PROMPT
from json_persistence import (
    atomic_json_write,
    block_replacement,
    mark_valid,
    may_replace,
    preserve_corrupt_file,
    validate_storage_path,
)

logger = logging.getLogger(__name__)


def load_history(path=HISTORY_PATH):
    try:
        path = validate_storage_path(path, label="histórico da conversa")
    except OSError as exc:
        block_replacement(path, type(exc).__name__)
        return []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            block_replacement(path, type(exc).__name__)
            return []
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            preserve_corrupt_file(path, type(exc).__name__)
            return []
        if not isinstance(history, list):
            preserve_corrupt_file(path, "raiz JSON não é uma lista")
            return []
        mark_valid(path)
        return [
            message
            for message in history
            if isinstance(message, dict)
            and message.get("role") in ("user", "assistant")
            and isinstance(message.get("content"), str)
        ]
    mark_valid(path)
    return []


def save_history(history, path=HISTORY_PATH):
    try:
        path = validate_storage_path(path, label="histórico da conversa")
    except OSError as exc:
        block_replacement(path, type(exc).__name__)
        return False
    if not may_replace(path):
        logger.error("Gravação do histórico bloqueada para preservar %s", path.name)
        return False
    try:
        atomic_json_write(path, history, label="histórico da conversa")
    except (OSError, TypeError, ValueError) as exc:
        logger.warning("Não foi possível salvar o histórico em %s: %s", path, exc)
        return False
    return True


def ask_local_ai(history, model_name=OLLAMA_MODEL, url=OLLAMA_URL, memories=None):
    system_message = f"{SYSTEM_PROMPT}\n\n{current_datetime_context()}"
    memories = [item.strip() for item in (memories or []) if isinstance(item, str) and item.strip()]
    if memories:
        system_message += "\n\nMemórias escolhidas pelo usuário (use apenas quando forem relevantes):\n- " + "\n- ".join(memories)
    # Timestamps are local history metadata and are not part of Ollama's message schema.
    messages = [{"role": "system", "content": system_message}] + [
        {"role": message["role"], "content": message["content"]}
        for message in history
    ]
    payload = json.dumps({"model": model_name, "messages": messages, "stream": False}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return f"Erro {exc.code} do Ollama: {exc.read().decode('utf-8', errors='ignore')[:200]}"
    except urllib.error.URLError:
        return (
            "Não consegui falar com o Ollama. Confirme que ele está rodando "
            f"e que o modelo '{model_name}' foi baixado (ollama pull {model_name})."
        )
    return data.get("message", {}).get("content", "").strip() or "(resposta vazia)"
