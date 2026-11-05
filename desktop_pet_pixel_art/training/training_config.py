"""Configuração local e limitada para o pipeline experimental."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from nova_ai.model.model_config import ModelConfig


@dataclass(frozen=True)
class TrainingConfig:
    model: ModelConfig = field(default_factory=ModelConfig)
    dataset_root: Path = Path("training/datasets")
    experiments_root: Path = Path("training/experiments")
    checkpoints_root: Path = Path("training/checkpoints")
    run_name: str = "nova_model_0_1"
    validation_percent: int = 10
    max_examples: int = 5000
    max_scanned_records: int = 25_000
    max_line_chars: int = 8192
    max_steps: int = 100
    evaluation_interval: int = 25
    evaluation_batches: int = 16
    checkpoint_interval: int = 25
    learning_rate: float = 0.001
    cpu_threads: int = 1
    reserve_memory_bytes: int = 256 * 1024**2
    minimum_available_bytes: int = 192 * 1024**2

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.run_name) or self.run_name in (".", ".."):
            raise ValueError("run_name deve ser um nome simples, sem caminhos")
        if not 5 <= self.validation_percent <= 40:
            raise ValueError("validation_percent deve ficar entre 5 e 40")
        if not 2 <= self.max_examples <= 20_000:
            raise ValueError("max_examples deve ficar entre 2 e 20.000")
        if not self.max_examples <= self.max_scanned_records <= 100_000:
            raise ValueError("max_scanned_records deve ficar entre max_examples e 100.000")
        if not 32 <= self.max_line_chars <= 8192:
            raise ValueError("max_line_chars deve ficar entre 32 e 8.192")
        if not 1 <= self.max_steps <= 100_000:
            raise ValueError("max_steps deve ficar entre 1 e 100.000")
        if self.evaluation_interval < 1 or self.checkpoint_interval < 1:
            raise ValueError("intervalos de avaliação e checkpoint devem ser positivos")
        if not 1 <= self.evaluation_batches <= 128:
            raise ValueError("evaluation_batches deve ficar entre 1 e 128")
        if not 0 < self.learning_rate <= 0.01:
            raise ValueError("learning_rate deve ficar entre 0 e 0,01")
        if self.cpu_threads != 1:
            raise ValueError("a primeira fase mantém exatamente uma thread CPU")
        if not 64 * 1024**2 <= self.reserve_memory_bytes <= 1024**3:
            raise ValueError("reserva de RAM deve ficar entre 64 MiB e 1 GiB")
        if not 128 * 1024**2 <= self.minimum_available_bytes <= self.reserve_memory_bytes:
            raise ValueError("limite mínimo de RAM deve ficar entre 128 MiB e a reserva")

    @property
    def raw_dir(self):
        return self.dataset_root / "raw"

    @property
    def processed_dir(self):
        return self.dataset_root / "processed" / self.run_name

    @property
    def validation_dir(self):
        return self.dataset_root / "validation" / self.run_name

    @property
    def experiment_dir(self):
        return self.experiments_root / self.run_name

    @property
    def checkpoint_dir(self):
        return self.checkpoints_root / self.run_name

    def to_dict(self):
        return {
            "model": self.model.to_dict(),
            "dataset_root": str(self.dataset_root),
            "experiments_root": str(self.experiments_root),
            "checkpoints_root": str(self.checkpoints_root),
            "run_name": self.run_name,
            "validation_percent": self.validation_percent,
            "max_examples": self.max_examples,
            "max_scanned_records": self.max_scanned_records,
            "max_line_chars": self.max_line_chars,
            "max_steps": self.max_steps,
            "evaluation_interval": self.evaluation_interval,
            "evaluation_batches": self.evaluation_batches,
            "checkpoint_interval": self.checkpoint_interval,
            "learning_rate": self.learning_rate,
            "cpu_threads": self.cpu_threads,
            "reserve_memory_bytes": self.reserve_memory_bytes,
            "minimum_available_bytes": self.minimum_available_bytes,
        }

    @classmethod
    def from_json(cls, path):
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        allowed = set(cls.__dataclass_fields__)
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("arquivo de treinamento contém campos inválidos")
        value["model"] = ModelConfig(**value.get("model", {}))
        for key in ("dataset_root", "experiments_root", "checkpoints_root"):
            if key in value:
                value[key] = Path(value[key])
        return cls(**value)

    def save_json(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
