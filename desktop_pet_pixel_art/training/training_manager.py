"""Orquestra passos de treino somente quando run() é chamado explicitamente."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from nova_ai.model import ByteTokenizer, CheckpointStore, ModelHistory, ModelMetadata, Vocabulary

from .evaluation import evaluate
from .training_config import TrainingConfig


def _iter_records(path, *, max_line_bytes=4096):
    with Path(path).open("r", encoding="utf-8") as stream:
        while True:
            line = stream.readline(max_line_bytes + 1)
            if not line:
                return
            if len(line) > max_line_bytes and not line.endswith("\n"):
                raise ValueError("registro processado excede o limite de linha")
            record = json.loads(line)
            inputs, targets = record.get("input_ids"), record.get("target_ids")
            if not isinstance(inputs, list) or not isinstance(targets, list) or len(inputs) != len(targets):
                raise ValueError("registro de treino inválido")
            if not 1 <= len(inputs) <= 64:
                raise ValueError("sequência de treino fora dos limites")
            yield inputs, targets


class TrainingManager:
    def __init__(self, config: TrainingConfig, *, model=None):
        self.config = config
        self.model = model

    def _memory_preflight(self):
        result = self.config.model.memory_preflight(reserve_bytes=self.config.reserve_memory_bytes)
        if not result["safe_to_train"]:
            raise MemoryError(
                "treinamento bloqueado pelo preflight de RAM: "
                f"disponível={result['available_bytes']}, estimado={result['estimated_peak_bytes']}, "
                f"reserva={result['reserve_bytes']}"
            )
        return result

    def run(self):
        cfg = self.config
        train_path = cfg.processed_dir / "train.jsonl"
        validation_path = cfg.validation_dir / "validation.jsonl"
        vocab_path = cfg.processed_dir / "vocabulary.json"
        manifest_path = cfg.processed_dir / "manifest.json"
        for path in (train_path, validation_path, vocab_path, manifest_path):
            if not path.is_file():
                raise FileNotFoundError(f"dataset preparado ausente: {path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format_version") != 1 or manifest.get("run_name") != cfg.run_name:
            raise ValueError("manifest do dataset incompatível com a configuração")

        # O preflight ocorre antes de importar/inicializar PyTorch e de abrir datasets.
        initial_memory = self._memory_preflight()
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("PyTorch CPU é necessário; instale o extra de ML em ambiente isolado") from exc
        from nova_ai.model.transformer import TinyTransformer

        original_thread_count = torch.get_num_threads()
        self._memory_preflight()

        vocabulary = Vocabulary.from_dict(
            json.loads(vocab_path.read_text(encoding="utf-8")), max_size=cfg.model.vocab_size
        )
        if len(vocabulary) != cfg.model.vocab_size:
            raise ValueError("tamanho do vocabulário não corresponde ao modelo")
        tokenizer = ByteTokenizer(vocabulary)
        model = self.model or TinyTransformer(cfg.model)
        if model.config != cfg.model:
            raise ValueError("configuração do modelo carregado diverge do experimento")
        self._memory_preflight()
        optimizer = torch.optim.AdamW(model.parameters(), lr=cfg.learning_rate)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{timestamp}-{uuid.uuid4().hex[:8]}"
        experiment_dir = cfg.experiment_dir / run_id
        checkpoint_dir = cfg.checkpoint_dir / run_id
        experiment_dir.mkdir(parents=True, exist_ok=False)
        checkpoint_dir.mkdir(parents=True, exist_ok=False)
        events_path = experiment_dir / "metrics.jsonl"
        history = ModelHistory(experiment_dir / "history.sqlite3")
        stream = iter(_iter_records(train_path))
        last_loss = None
        last_validation = None
        checkpoints = []
        try:
            # Uma thread atende o limite de CPU da máquina alvo.
            if original_thread_count != cfg.cpu_threads:
                torch.set_num_threads(cfg.cpu_threads)
            with events_path.open("x", encoding="utf-8") as events:
                for step in range(1, cfg.max_steps + 1):
                    try:
                        input_values, target_values = next(stream)
                    except StopIteration:
                        stream = iter(_iter_records(train_path))
                        try:
                            input_values, target_values = next(stream)
                        except StopIteration as exc:
                            raise ValueError("dataset de treino vazio") from exc
                    input_ids = torch.tensor([input_values], dtype=torch.long, device="cpu")
                    target_ids = torch.tensor([target_values], dtype=torch.long, device="cpu")
                    last_loss = model.train_step(
                        input_ids,
                        target_ids,
                        optimizer,
                        reserve_memory_bytes=cfg.reserve_memory_bytes,
                        minimum_available_bytes=cfg.minimum_available_bytes,
                    )
                    event = {"step": step, "training_loss": last_loss}
                    if step % cfg.evaluation_interval == 0 or step == cfg.max_steps:
                        last_validation = evaluate(
                            model,
                            validation_path,
                            max_batches=cfg.evaluation_batches,
                            config=cfg.model,
                        )
                        event.update(last_validation)
                    should_checkpoint = step % cfg.checkpoint_interval == 0 or step == cfg.max_steps
                    if should_checkpoint:
                        metadata = ModelMetadata.new(
                            training_steps=step,
                            parameter_count=cfg.model.parameter_count,
                            dataset_description=str(manifest_path),
                            vocabulary=vocabulary.to_dict(),
                        )
                        checkpoint_path = checkpoint_dir / f"step-{step:08d}.pt"
                        CheckpointStore.save(checkpoint_path, model, metadata)
                        history.record(cfg.model, metadata, final_loss=last_loss)
                        checkpoints.append(str(checkpoint_path))
                    events.write(json.dumps(event, ensure_ascii=False) + "\n")
                    events.flush()
        finally:
            if torch.get_num_threads() != original_thread_count:
                torch.set_num_threads(original_thread_count)

        return {
            "run_id": run_id,
            "steps": cfg.max_steps,
            "training_loss": last_loss,
            "validation": last_validation,
            "preflight": initial_memory,
            "metrics_path": str(events_path),
            "checkpoints": checkpoints,
            "vocabulary_size": len(vocabulary),
            "parameter_count": cfg.model.parameter_count,
        }
