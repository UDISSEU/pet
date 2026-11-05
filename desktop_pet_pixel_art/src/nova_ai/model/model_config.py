"""Configuração JSON e orçamento de recursos do Nova Model 0.1."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModelConfig:
    vocab_size: int = 2000
    d_model: int = 64
    num_heads: int = 2
    num_layers: int = 2
    ff_multiplier: int = 4
    max_seq_len: int = 64
    batch_size: int = 1
    seed: int = 17

    def __post_init__(self):
        if not 1000 <= self.vocab_size <= 2000:
            raise ValueError("vocab_size deve ficar entre 1.000 e 2.000 tokens")
        if not 16 <= self.d_model <= 128 or not 1 <= self.num_heads <= 8 or not 1 <= self.num_layers <= 4:
            raise ValueError("d_model, cabeças ou camadas fora dos limites experimentais")
        if self.d_model % self.num_heads:
            raise ValueError("d_model deve ser divisível por num_heads")
        if not 1 <= self.ff_multiplier <= 4 or not 1 <= self.max_seq_len <= 64:
            raise ValueError("configuração fora dos limites experimentais (contexto até 64)")
        if self.batch_size != 1:
            raise ValueError("a primeira configuração suporta batch_size=1")
        if self.parameter_count > 300_000:
            raise ValueError("configuração excede o limite experimental de 300 mil parâmetros")

    @property
    def parameter_count(self) -> int:
        d = self.d_model
        # Embedding de saída compartilhado, bias de saída, posições e blocos Transformer.
        ff = d * self.ff_multiplier
        per_layer = 4 * d * d + 2 * d * ff + ff + 9 * d
        return self.vocab_size * d + self.vocab_size + self.max_seq_len * d + self.num_layers * per_layer

    @property
    def estimated_weight_bytes(self) -> int:
        return self.parameter_count * 4

    @property
    def estimated_training_bytes(self) -> int:
        """Estimativa conservadora para pesos, gradientes, Adam, ativações e runtime."""
        d, seq, heads = self.d_model, self.max_seq_len, self.num_heads
        activations = self.num_layers * self.batch_size * seq * (8 * d + heads * seq) * 4
        logits = self.batch_size * seq * self.vocab_size * 4
        return 4 * self.estimated_weight_bytes + 2 * (activations + logits) + 128 * 1024**2

    def to_dict(self):
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    def save_json(self, path):
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def from_json(cls, path):
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        allowed = set(cls.__dataclass_fields__)
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("arquivo de configuração contém campos inválidos")
        return cls(**value)

    def memory_preflight(self, *, reserve_bytes=256 * 1024**2):
        """Compara estimativa com RAM disponível; não aloca memória nem inicia treino."""
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("psutil é necessário para verificar a RAM disponível") from exc
        available = psutil.virtual_memory().available
        # Respeita também limites de cgroup (comuns em ambientes isolados).
        try:
            memory_max = Path("/sys/fs/cgroup/memory.max").read_text().strip()
            memory_current = int(Path("/sys/fs/cgroup/memory.current").read_text().strip())
            if memory_max != "max":
                available = min(available, max(0, int(memory_max) - memory_current))
        except (OSError, ValueError):
            pass
        required = self.estimated_training_bytes
        return {
            "available_bytes": available,
            "estimated_peak_bytes": required,
            "reserve_bytes": reserve_bytes,
            "safe_to_train": available >= required + reserve_bytes,
        }

    @staticmethod
    def ensure_memory_safe(*, minimum_available_bytes=192 * 1024**2):
        """Aborta operações de treino quando a memória livre atinge nível crítico."""
        try:
            import psutil
        except ImportError as exc:
            raise RuntimeError("psutil é necessário para proteger o treinamento por RAM") from exc
        available = psutil.virtual_memory().available
        try:
            memory_max = Path("/sys/fs/cgroup/memory.max").read_text().strip()
            memory_current = int(Path("/sys/fs/cgroup/memory.current").read_text().strip())
            if memory_max != "max":
                available = min(available, max(0, int(memory_max) - memory_current))
        except (OSError, ValueError):
            pass
        if available < minimum_available_bytes:
            raise MemoryError(f"treinamento interrompido: apenas {available} bytes disponíveis")
        return available
