#!/usr/bin/env python3
"""Run a small, manual-review response evaluation against local Ollama."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from ai.prompts import build_system_prompt  # noqa: E402
from providers.provider_factory import create_provider  # noqa: E402

CASES_PATH = ROOT / "evaluations" / "responses.json"


def load_cases(path=CASES_PATH):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("format_version") != 1:
        raise ValueError("Formato do conjunto de avaliações inválido.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("O conjunto de avaliações está vazio.")
    for case in cases:
        if not isinstance(case, dict) or not all(
            isinstance(case.get(field), str) and case[field].strip()
            for field in ("id", "prompt", "review")
        ):
            raise ValueError("Um caso de avaliação está incompleto.")
    return cases


def run_evaluation(*, model="llama3.2:1b", timeout=30, provider_factory=create_provider):
    if not 5 <= timeout <= 60:
        raise ValueError("O timeout deve ficar entre 5 e 60 segundos.")
    provider = provider_factory("ollama", {
        "ai_provider": "ollama",
        "ollama_model": model,
        "ai_timeout": timeout,
        "ollama_num_ctx": 512,
        "ollama_num_predict": 128,
        "ollama_num_threads": 1,
    })
    system_prompt = build_system_prompt()
    results = []
    for case in load_cases():
        started = time.perf_counter()
        try:
            answer = provider.generate(
                [{"role": "user", "content": case["prompt"]}],
                system_prompt,
                timeout=timeout,
            )
            error = None
        except Exception as exc:
            answer = None
            error = type(exc).__name__
        results.append({
            "id": case["id"],
            "prompt": case["prompt"],
            "review_criterion": case["review"],
            "answer": answer,
            "error_type": error,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "rating": None,
            "review_notes": "",
        })
    return {
        "format_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": "ollama-local",
        "model": model,
        "results": results,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-inference", action="store_true",
                        help="enviar os casos fixos ao Ollama local em execução")
    parser.add_argument("--model", default="llama3.2:1b")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path,
                        help="salvar o relatório JSON para revisão manual")
    args = parser.parse_args(argv)
    if not args.run_inference:
        parser.error("Use --run-inference para consultar explicitamente o Ollama local.")
    try:
        report = run_evaluation(model=args.model, timeout=args.timeout)
    except Exception as exc:
        parser.exit(1, f"Avaliação não concluída ({type(exc).__name__}).\n")
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
