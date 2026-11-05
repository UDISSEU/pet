"""Tokenizador simples alinhado ao vocabulário local da Nova."""

from .vocabulary import Vocabulary


class ByteTokenizer:
    """Nome preservado por compatibilidade; a implementação atual é por palavras."""

    def __init__(self, vocabulary: Vocabulary | None = None):
        self.vocabulary = vocabulary or Vocabulary()

    def encode(self, text: str, *, add_special_tokens: bool = False) -> list[int]:
        return self.vocabulary.encode(text, add_bos=add_special_tokens, add_eos=add_special_tokens)

    def decode(self, token_ids) -> str:
        return self.vocabulary.decode(token_ids)
