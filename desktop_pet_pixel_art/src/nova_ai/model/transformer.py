"""Transformer decoder-only em PyTorch, carregado apenas quando instanciado."""

from ..core.errors import ModelError
from .model_config import ModelConfig

try:
    import torch
    from torch import nn
    from torch.nn import functional as F
except ImportError:  # permite importar o restante da arquitetura sem PyTorch instalado
    torch = None
    nn = None
    F = None


if nn is not None:
    class _DecoderLayer(nn.Module):
        def __init__(self, config):
            super().__init__()
            d = config.d_model
            self.attention = nn.MultiheadAttention(d, config.num_heads, batch_first=True, dropout=0.0)
            self.norm1 = nn.LayerNorm(d)
            self.feed_forward = nn.Sequential(
                nn.Linear(d, d * config.ff_multiplier), nn.GELU(), nn.Linear(d * config.ff_multiplier, d)
            )
            self.norm2 = nn.LayerNorm(d)

        def forward(self, x, causal_mask):
            attended, _ = self.attention(x, x, x, attn_mask=causal_mask, need_weights=False)
            x = self.norm1(x + attended)
            return self.norm2(x + self.feed_forward(x))


    class TinyTransformer(nn.Module):
        """Modelo didático pequeno; pesos aleatórios não constituem um modelo treinado."""

        def __init__(self, config: ModelConfig | None = None):
            super().__init__()
            self.config = config or ModelConfig()
            with torch.random.fork_rng(devices=[]):
                torch.manual_seed(self.config.seed)
                self.token_embedding = nn.Embedding(self.config.vocab_size, self.config.d_model)
                self.position_embedding = nn.Embedding(self.config.max_seq_len, self.config.d_model)
                self.layers = nn.ModuleList(_DecoderLayer(self.config) for _ in range(self.config.num_layers))
                self.output_bias = nn.Parameter(torch.zeros(self.config.vocab_size))
                self.apply(self._initialize)
                # Projeção de saída compartilha pesos com embedding.

        @staticmethod
        def _initialize(module):
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)

        def forward(self, token_ids):
            if token_ids.device.type != "cpu":
                raise ValueError("este experimento usa apenas CPU; GPU Intel não foi habilitada")
            if token_ids.dtype != torch.long:
                raise ValueError("token_ids deve usar dtype torch.long")
            if token_ids.ndim != 2 or token_ids.shape[1] == 0 or token_ids.shape[1] > self.config.max_seq_len:
                raise ValueError("entrada deve ter formato [batch, sequência] com até 64 tokens")
            positions = torch.arange(token_ids.shape[1], device=token_ids.device)
            x = self.token_embedding(token_ids) + self.position_embedding(positions)[None, :, :]
            length = token_ids.shape[1]
            mask = torch.triu(torch.ones(length, length, dtype=torch.bool, device=token_ids.device), diagonal=1)
            for layer in self.layers:
                x = layer(x, mask)
            return F.linear(x, self.token_embedding.weight, self.output_bias)

        def next_token_loss(self, input_ids, target_ids, *, active_vocab_size=None):
            if input_ids.shape != target_ids.shape or input_ids.ndim != 2:
                raise ValueError("entrada e alvos precisam ter a mesma forma [batch, sequência]")
            logits = self(input_ids)
            if active_vocab_size is not None:
                if not 4 <= active_vocab_size <= self.config.vocab_size:
                    raise ValueError("active_vocab_size incompatível com o vocabulário do modelo")
                logits[..., active_vocab_size:] = float("-inf")
                if target_ids.max() >= active_vocab_size:
                    raise ValueError("alvo usa token inativo do vocabulário")
            return F.cross_entropy(logits.reshape(-1, self.config.vocab_size), target_ids.reshape(-1))

        def train_step(self, input_ids, target_ids, optimizer, *, reserve_memory_bytes=256 * 1024**2,
                       minimum_available_bytes=192 * 1024**2, active_vocab_size=None):
            """Executa um passo FP32 em CPU; não cria datasets nem inicia loops de treino."""
            if any(parameter.device.type != "cpu" for parameter in self.parameters()):
                raise RuntimeError("treinamento em GPU está desabilitado nesta fase")
            preflight = self.config.memory_preflight(reserve_bytes=reserve_memory_bytes)
            if not preflight["safe_to_train"]:
                raise MemoryError(
                    "treinamento cancelado pelo preflight de memória: "
                    f"disponível={preflight['available_bytes']}, "
                    f"estimado={preflight['estimated_peak_bytes']}, "
                    f"reserva={preflight['reserve_bytes']}"
                )
            if input_ids.device.type != "cpu" or target_ids.device.type != "cpu":
                raise ValueError("lote de treinamento deve estar na CPU")
            if input_ids.shape != target_ids.shape or input_ids.ndim != 2:
                raise ValueError("entrada e alvos precisam ter a mesma forma [batch, sequência]")
            if input_ids.shape[0] != self.config.batch_size:
                raise ValueError("lote incompatível com batch_size configurado")
            if input_ids.dtype != torch.long or target_ids.dtype != torch.long:
                raise ValueError("tokens devem usar dtype torch.long")
            if any(parameter.dtype != torch.float32 for parameter in self.parameters()):
                raise ValueError("este experimento exige precisão FP32")
            self.train()
            optimizer.zero_grad(set_to_none=True)
            loss = self.next_token_loss(input_ids, target_ids, active_vocab_size=active_vocab_size)
            if not torch.isfinite(loss):
                raise FloatingPointError("loss não finita; passo de treinamento cancelado")
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.parameters(), max_norm=1.0)
            self.config.ensure_memory_safe(minimum_available_bytes=minimum_available_bytes)
            optimizer.step()
            return float(loss.detach().item())

else:
    class TinyTransformer:  # fallback para instalação sem dependência obrigatória na inicialização
        def __init__(self, config: ModelConfig | None = None):
            self.config = config or ModelConfig()
            raise ModelError("PyTorch CPU não está instalado; instale-o para instanciar o modelo experimental")

        def forward(self, token_ids):  # pragma: no cover - caminho de dependência ausente
            raise ModelError("PyTorch CPU não está instalado")
