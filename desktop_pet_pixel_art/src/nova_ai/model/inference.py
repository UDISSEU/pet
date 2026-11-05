"""Inferência local explícita; exige checkpoint e nunca carrega pesos sozinha."""

from ..core.errors import ModelError
from .base import Model
from .checkpoints import CheckpointStore
from .model_config import ModelConfig
from .tokenizer import ByteTokenizer
from .transformer import TinyTransformer
from .vocabulary import Vocabulary


class TinyModelInference(Model):
    def __init__(self, model: TinyTransformer, tokenizer: ByteTokenizer | None = None, *, trained=False):
        self.model = model
        self.tokenizer = tokenizer or ByteTokenizer(Vocabulary(max_size=model.config.vocab_size))
        if len(self.tokenizer.vocabulary) != self.model.config.vocab_size:
            raise ValueError("tamanho do vocabulário incompatível com o modelo")
        self.trained = trained

    @classmethod
    def from_checkpoint(cls, path, config: ModelConfig | None = None, tokenizer: ByteTokenizer | None = None):
        use_checkpoint_vocabulary = tokenizer is None
        instance = cls(TinyTransformer(config), tokenizer)
        try:
            metadata = CheckpointStore.load(path, instance.model)
            if metadata.training_steps < 1:
                raise ValueError("checkpoint não registra etapas de treinamento")
            if use_checkpoint_vocabulary:
                if metadata.vocabulary is None:
                    raise ValueError("checkpoint não contém vocabulário/tokenizador")
                instance.tokenizer = ByteTokenizer(Vocabulary.from_dict(
                    metadata.vocabulary, max_size=instance.model.config.vocab_size
                ))
        except Exception as exc:
            raise ModelError(f"não foi possível carregar checkpoint: {exc}") from exc
        instance.trained = True
        return instance

    def generate(self, messages, *, max_new_tokens=32):
        if not self.trained:
            raise ModelError("modelo ainda não treinado: carregue um checkpoint explicitamente")
        if not 1 <= max_new_tokens <= 64:
            raise ModelError("max_new_tokens deve estar entre 1 e 64")
        prompt = "\n".join(str(m.get("content", "")) for m in messages if isinstance(m, dict))
        ids = self.tokenizer.encode(prompt)[-self.model.config.max_seq_len:]
        prompt_length = len(ids)
        if not ids:
            ids = [self.tokenizer.vocabulary.BOS]
            prompt_length = 1
        try:
            import torch
        except ImportError as exc:
            raise ModelError("PyTorch CPU não está instalado") from exc
        self.model.eval()
        for _ in range(max_new_tokens):
            context = ids[-self.model.config.max_seq_len:]
            with torch.inference_mode():
                logits = self.model(torch.tensor([context], dtype=torch.long))[0, -1]
                logits[:4] = float("-inf")
                logits[self.tokenizer.vocabulary.active_size:] = float("-inf")
            next_id = int(logits.argmax())
            if next_id in (self.tokenizer.vocabulary.PAD, self.tokenizer.vocabulary.BOS,
                           self.tokenizer.vocabulary.EOS):
                break
            ids.append(next_id)
        return self.tokenizer.decode(ids[prompt_length:])
