import json
import urllib.error
import urllib.request

from config import HISTORY_PATH, OLLAMA_MODEL, OLLAMA_URL, SYSTEM_PROMPT


def load_history(path=HISTORY_PATH):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history(history, path=HISTORY_PATH):
    try:
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def ask_local_ai(history, model_name=OLLAMA_MODEL, url=OLLAMA_URL):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
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
