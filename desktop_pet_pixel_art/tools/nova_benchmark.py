#!/usr/bin/env python3
"""Measure one explicit local Ollama request; never downloads or trains a model."""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from providers.ollama_provider import OllamaProvider  # noqa: E402


class Sampler:
    def __init__(self, interval=0.25):
        self.interval = interval
        self.stop_event = threading.Event()
        self.samples = []
        self.peak_ollama_rss = 0
        self.peak_ollama_threads = 0
        self.initial_ollama_rss = self._ollama_rss()
        self.thread = threading.Thread(target=self._run, name="nova-benchmark-sampler", daemon=True)

    @staticmethod
    def _ollama_processes():
        found = []
        for process in psutil.process_iter(("name", "cmdline", "memory_info", "num_threads")):
            try:
                name = (process.info.get("name") or "").casefold()
                command = " ".join(process.info.get("cmdline") or []).casefold()
                if "ollama" in name or "ollama runner" in command:
                    found.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found

    @classmethod
    def _ollama_rss(cls):
        total = 0
        for process in cls._ollama_processes():
            try:
                total += process.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return total

    def start(self):
        self.thread.start()

    def _run(self):
        while not self.stop_event.wait(self.interval):
            cpu = psutil.cpu_percent(interval=None)
            processes = self._ollama_processes()
            rss = threads = 0
            for process in processes:
                try:
                    rss += process.memory_info().rss
                    threads += process.num_threads()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.samples.append(cpu)
            self.peak_ollama_rss = max(self.peak_ollama_rss, rss)
            self.peak_ollama_threads = max(self.peak_ollama_threads, threads)

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="llama3.2:1b")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--run-inference", action="store_true",
                        help="run exactly one short inference against localhost Ollama")
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    args = parser.parse_args()
    if not 5 <= args.timeout <= 60:
        parser.error("--timeout deve ficar entre 5 e 60 segundos")

    started = time.perf_counter()
    memory_before = psutil.virtual_memory().available
    sampler = Sampler()
    sampler.start()
    provider = OllamaProvider(
        model=args.model, timeout=args.timeout,
        num_ctx=512, num_predict=32, num_threads=1, keep_alive="30s",
    )
    provider_ready_at = None
    inference_seconds = None
    response_chars = None
    status, error = "not_run", None
    if args.run_inference:
        try:
            provider.test_connection(timeout=min(args.timeout, 8))
            provider_ready_at = time.perf_counter()
            answer = provider.generate(
                [{"role": "user", "content": "Responda em até uma frase: Nova offline."}],
                "Responda com clareza e brevidade.", timeout=args.timeout,
            )
            inference_seconds = round(time.perf_counter() - provider_ready_at, 3)
            response_chars = len(answer)
            status = "success"
        except Exception as exc:
            status = "failed"
            error = type(exc).__name__
    sampler.stop()
    processes = Sampler._ollama_processes()
    try:
        ollama_status = subprocess.run(
            ["ollama", "ps"], check=False, capture_output=True, text=True,
            timeout=5, env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                            "HOME": str(Path.home()),
                            "OLLAMA_HOST": "http://127.0.0.1:11434"},
        )
        ollama_ps = ollama_status.stdout.strip() if ollama_status.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        ollama_ps = None
    report = {
        "provider": "ollama-local",
        "model": args.model,
        "status": status,
        "error_type": error,
        "run_inference": args.run_inference,
        "startup_and_probe_seconds": round((provider_ready_at or time.perf_counter()) - started, 3),
        "inference_seconds": inference_seconds,
        "response_characters": response_chars,
        "ram_available_before_bytes": memory_before,
        "ram_available_after_bytes": psutil.virtual_memory().available,
        "ollama_rss_before_bytes": sampler.initial_ollama_rss,
        "ollama_rss_peak_sampled_bytes": sampler.peak_ollama_rss,
        "ollama_threads_peak_sampled": sampler.peak_ollama_threads,
        "ollama_processes_after": len(processes),
        "ollama_status": ollama_ps,
        "host_cpu_percent_average_sampled": round(
            sum(sampler.samples) / len(sampler.samples), 1
        ) if sampler.samples else None,
        "host_cpu_percent_peak_sampled": round(max(sampler.samples), 1)
        if sampler.samples else None,
        "python_process_rss_bytes": psutil.Process().memory_info().rss,
        "python_threads": psutil.Process().num_threads(),
        "checkpoint_bytes": sum(
            path.stat().st_size for path in (ROOT / "training" / "checkpoints").rglob("*")
            if path.is_file()
        ) if (ROOT / "training" / "checkpoints").exists() else 0,
        "cpu_count": os.cpu_count(),
        "platform": platform.platform(),
        "notes": "One local request only; no remote provider, training, or download.",
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if status in {"success", "not_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
