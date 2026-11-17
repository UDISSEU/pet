"""Leitura e gravação explícitas de checkpoints PyTorch em CPU."""

import json
import os
from pathlib import Path

from .model_metadata import ModelMetadata
from .vocabulary import Vocabulary


class CheckpointStore:
    MAX_FILE_BYTES = 64 * 1024 * 1024

    @classmethod
    def save(cls, path, model, metadata: ModelMetadata | None = None):
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("PyTorch CPU é necessário para salvar checkpoints") from exc
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        meta = metadata or ModelMetadata.new()
        metadata_values = meta.to_dict()
        if metadata_values["parameter_count"] not in (0, model.config.parameter_count):
            raise ValueError("contagem de parâmetros dos metadados incompatível")
        metadata_values["parameter_count"] = model.config.parameter_count
        payload = {
            "format_version": 1,
            "metadata_json": json.dumps(metadata_values, ensure_ascii=False),
            "model_config_json": json.dumps(model.config.to_dict(), sort_keys=True),
            "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        }
        temporary = destination.with_name(destination.name + ".tmp")
        try:
            with temporary.open("wb") as stream:
                torch.save(payload, stream)
                stream.flush()
                os.fsync(stream.fileno())
            if temporary.stat().st_size > cls.MAX_FILE_BYTES:
                raise ValueError("checkpoint excede o limite de tamanho")
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    @classmethod
    def load(cls, path, model):
        try:
            import torch
        except ImportError as exc:
            raise RuntimeError("PyTorch CPU é necessário para carregar checkpoints") from exc
        source = Path(path)
        if source.stat().st_size > cls.MAX_FILE_BYTES:
            raise ValueError("checkpoint excede o limite de tamanho")
        try:
            payload = torch.load(source, map_location="cpu", weights_only=True)
        except TypeError as exc:
            raise RuntimeError("esta versão do PyTorch não oferece carregamento weights_only seguro") from exc
        if not isinstance(payload, dict) or payload.get("format_version") != 1:
            raise ValueError("formato de checkpoint inválido")
        if payload.get("model_config_json") != json.dumps(model.config.to_dict(), sort_keys=True):
            raise ValueError("configuração do checkpoint incompatível com o modelo")
        metadata = ModelMetadata.from_dict(json.loads(payload["metadata_json"]))
        if metadata.vocabulary is not None:
            Vocabulary.from_dict(metadata.vocabulary, max_size=model.config.vocab_size)
            if len(metadata.vocabulary.get("tokens", [])) != model.config.vocab_size:
                raise ValueError("vocabulário do checkpoint incompatível com o modelo")
        model.load_state_dict(payload["state_dict"], strict=True)
        return metadata
