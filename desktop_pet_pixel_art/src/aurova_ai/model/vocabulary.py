"""Vocabulário de palavras e pontuação construído explicitamente a partir de texto."""

import re
from collections import Counter


class Vocabulary:
    PAD, UNK, BOS, EOS = range(4)
    SPECIALS = ("<pad>", "<unk>", "<bos>", "<eos>")
    TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)

    def __init__(self, tokens=None, *, max_size=2000):
        if tokens is None:
            tokens = [*self.SPECIALS, *(f"<unused_{index}>" for index in range(max_size - len(self.SPECIALS)))]
        else:
            tokens = list(tokens)
        if tokens[:4] != list(self.SPECIALS) or len(tokens) > max_size or len(set(tokens)) != len(tokens):
            raise ValueError("vocabulário inválido")
        self.tokens = tokens
        self.ids = {token: index for index, token in enumerate(tokens)}
        self.active_size = next((index for index, token in enumerate(tokens) if token.startswith("<unused_")), len(tokens))

    def __len__(self):
        return len(self.tokens)

    @classmethod
    def build(cls, texts, *, max_size=2000, min_frequency=1):
        if not 1000 <= max_size <= 2000:
            raise ValueError("max_size deve ficar entre 1.000 e 2.000")
        capacity = max_size - len(cls.SPECIALS)
        counts = Counter()
        # Aceita iteradores de linhas/documentos e limita cardinalidade em RAM.
        for text in texts:
            for match in cls.TOKEN_PATTERN.finditer(str(text)):
                token = match.group(0).casefold()
                if token in counts or len(counts) < capacity:
                    counts[token] += 1
        tokens = sorted((word for word, count in counts.items() if count >= min_frequency),
                        key=lambda word: (-counts[word], word))[:capacity]
        tokens = [*cls.SPECIALS, *tokens]
        tokens.extend(f"<unused_{index}>" for index in range(max_size - len(tokens)))
        return cls(tokens, max_size=max_size)

    def encode(self, text, *, add_bos=False, add_eos=False):
        ids = [self.ids.get(token.casefold(), self.UNK) for token in self.TOKEN_PATTERN.findall(text)]
        return ([self.BOS] if add_bos else []) + ids + ([self.EOS] if add_eos else [])

    def decode(self, ids):
        parts = [self.tokens[index] if 0 <= int(index) < len(self.tokens) else "<unk>"
                 for index in ids]
        parts = [token for token in parts if token not in self.SPECIALS]
        text = " ".join(parts)
        return re.sub(r"\s+([,.;:!?%)\]}])", r"\1", re.sub(r"([(\[{])\s+", r"\1", text))

    def to_dict(self):
        return {"version": 1, "tokens": self.tokens}

    @classmethod
    def from_dict(cls, value, *, max_size=2000):
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("formato de vocabulário inválido")
        return cls(value.get("tokens"), max_size=max_size)
