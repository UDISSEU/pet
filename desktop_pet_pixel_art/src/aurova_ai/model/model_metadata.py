"""Metadados serializáveis de checkpoints experimentais."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path


@dataclass(frozen=True)
class ModelMetadata:
    format_version: int = 1
    architecture: str = "aurova-tiny-transformer-v1"
    created_at: str = ""
    tokenizer: str = "word-vocabulary-v1"
    training_steps: int = 0
    parameter_count: int = 0
    dataset_description: str = ""
    vocabulary: dict | None = None

    @classmethod
    def new(cls, **kwargs):
        return cls(created_at=datetime.now(timezone.utc).isoformat(), **kwargs)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        allowed = set(cls.__dataclass_fields__)
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("metadados inválidos")
        metadata = cls(**value)
        if metadata.format_version != 1 or metadata.training_steps < 0 or metadata.parameter_count < 0:
            raise ValueError("versão ou contagem de treinamento inválida")
        return metadata


class ModelHistory:
    """Histórico SQLite local. A base só é criada ao instanciar explicitamente."""

    def __init__(self, database_path, *, storage=None, max_database_bytes=8 * 1024 * 1024):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        if storage is None:
            from training.operational.storage import manager_for_training_path
            storage = manager_for_training_path(self.database_path)
        self.storage = storage
        self.max_database_bytes = max_database_bytes
        guard = storage.reserve_bytes(max_database_bytes) if storage is not None else _null_guard()
        with guard, sqlite3.connect(self.database_path) as connection:
            if storage is not None:
                pages = max(1, max_database_bytes // 4096)
                actual = connection.execute(f"PRAGMA max_page_count={pages}").fetchone()[0]
                if actual > pages:
                    raise OSError("histórico existente ultrapassa o limite de armazenamento reservado")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS training_runs (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    architecture TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    parameter_count INTEGER NOT NULL DEFAULT 0,
                    training_steps INTEGER NOT NULL,
                    final_loss REAL,
                    dataset_description TEXT NOT NULL
                )
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(training_runs)")}
            if "parameter_count" not in columns:
                connection.execute("ALTER TABLE training_runs ADD COLUMN parameter_count INTEGER NOT NULL DEFAULT 0")

    def record(self, config, metadata: ModelMetadata, final_loss=None):
        if metadata.training_steps < 0 or (final_loss is not None and final_loss < 0):
            raise ValueError("valores do histórico inválidos")
        if metadata.parameter_count not in (0, config.parameter_count):
            raise ValueError("contagem de parâmetros incompatível com a configuração")
        guard = self.storage.reserve_bytes(self.max_database_bytes) if self.storage is not None else _null_guard()
        with guard, sqlite3.connect(self.database_path) as connection:
            cursor = connection.execute(
                "INSERT INTO training_runs(created_at, architecture, config_json, parameter_count, training_steps, final_loss, dataset_description) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (metadata.created_at or datetime.now(timezone.utc).isoformat(), metadata.architecture,
                 json.dumps(config.to_dict(), sort_keys=True), metadata.parameter_count or config.parameter_count,
                 metadata.training_steps, final_loss,
                 metadata.dataset_description),
            )
            return cursor.lastrowid

    def list_runs(self, limit=50):
        if not 1 <= limit <= 500:
            raise ValueError("limit deve ficar entre 1 e 500")
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM training_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


class _null_guard:
    def __enter__(self): return self
    def __exit__(self, *_args): return False
