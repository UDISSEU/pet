"""Interfaces de modelo com importação tardia do runtime experimental PyTorch."""

from importlib import import_module

__all__ = [
    "Model", "CheckpointStore", "TinyModelInference", "ModelConfig", "ModelHistory",
    "ModelMetadata", "ByteTokenizer", "TinyTransformer", "Vocabulary",
]

_EXPORTS = {
    "Model": (".base", "Model"),
    "CheckpointStore": (".checkpoints", "CheckpointStore"),
    "TinyModelInference": (".inference", "TinyModelInference"),
    "ModelConfig": (".model_config", "ModelConfig"),
    "ModelHistory": (".model_metadata", "ModelHistory"),
    "ModelMetadata": (".model_metadata", "ModelMetadata"),
    "ByteTokenizer": (".tokenizer", "ByteTokenizer"),
    "TinyTransformer": (".transformer", "TinyTransformer"),
    "Vocabulary": (".vocabulary", "Vocabulary"),
}


def __getattr__(name):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
