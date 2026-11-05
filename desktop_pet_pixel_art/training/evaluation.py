"""Avaliação em fluxo com limite explícito de exemplos e memória."""

import json
import math
from pathlib import Path

from nova_ai.model.model_config import ModelConfig


def _iter_records(path, max_line_bytes=4096):
    with Path(path).open("r", encoding="utf-8") as stream:
        while True:
            line = stream.readline(max_line_bytes + 1)
            if not line:
                return
            if len(line) > max_line_bytes and not line.endswith("\n"):
                raise ValueError("registro de avaliação excede o limite de linha")
            record = json.loads(line)
            inputs, targets = record.get("input_ids"), record.get("target_ids")
            if not isinstance(inputs, list) or not isinstance(targets, list) or len(inputs) != len(targets):
                raise ValueError("sequência inválida no dataset de avaliação")
            if not 1 <= len(inputs) <= 64:
                raise ValueError("tamanho de sequência inválido na avaliação")
            yield inputs, targets


def evaluate(model, dataset_path, *, max_batches=16, config: ModelConfig | None = None,
             active_vocab_size=None):
    """Calcula média da loss em até max_batches; nunca materializa o dataset inteiro."""
    import torch

    model_config = config or model.config
    model_config.ensure_memory_safe()
    previous_mode = model.training
    model.eval()
    total = 0.0
    count = 0
    try:
        with torch.inference_mode():
            for inputs, targets in _iter_records(dataset_path):
                model_config.ensure_memory_safe()
                input_ids = torch.tensor([inputs], dtype=torch.long, device="cpu")
                target_ids = torch.tensor([targets], dtype=torch.long, device="cpu")
                loss = model.next_token_loss(
                    input_ids, target_ids, active_vocab_size=active_vocab_size
                )
                value = float(loss.item())
                if not math.isfinite(value):
                    raise FloatingPointError("loss inválida durante avaliação")
                total += value
                count += 1
                if count >= max_batches:
                    break
    finally:
        model.train(previous_mode)
    if not count:
        raise ValueError("dataset de avaliação vazio")
    return {"validation_loss": total / count, "batches": count}
