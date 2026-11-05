"""Testes do modelo experimental executáveis com unittest."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from nova_ai.core.errors import ModelError
from nova_ai.model import (
    ByteTokenizer,
    CheckpointStore,
    ModelConfig,
    ModelHistory,
    ModelMetadata,
    TinyModelInference,
    TinyTransformer,
    Vocabulary,
)


class ModelConfigTests(unittest.TestCase):
    def test_default_parameter_count_and_json_round_trip(self):
        config = ModelConfig()
        self.assertEqual(config.parameter_count, 234_064)
        self.assertGreaterEqual(config.parameter_count, 100_000)
        self.assertLessEqual(config.parameter_count, 300_000)
        self.assertEqual(
            ModelConfig.from_json(Path("src/nova_ai/model/nova_model_config.json")), config
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            config.save_json(path)
            self.assertEqual(ModelConfig.from_json(path), config)

    def test_vocab_build_and_token_round_trip(self):
        vocab = Vocabulary.build(["Nova aprende. Nova pensa!"], max_size=1000)
        tokenizer = ByteTokenizer(vocab)
        encoded = tokenizer.encode("Nova aprende.")
        self.assertEqual(len(vocab), 1000)
        self.assertEqual(tokenizer.decode(encoded), "nova aprende.")


@unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch CPU não está instalado")
class ModelLifecycleTests(unittest.TestCase):
    def test_forward_loss_train_step_checkpoint_and_generation(self):
        import psutil
        import torch

        config = ModelConfig(vocab_size=1000)
        preflight = config.memory_preflight()
        self.assertTrue(preflight["safe_to_train"], preflight)
        process = psutil.Process()
        rss_before = process.memory_info().rss
        model = TinyTransformer(config)
        self.assertEqual(sum(p.numel() for p in model.parameters()), config.parameter_count)

        inputs = torch.tensor([[4, 5, 6, 7, 8, 9]], dtype=torch.long)
        targets = torch.tensor([[5, 6, 7, 8, 9, 10]], dtype=torch.long)
        self.assertTrue(torch.isfinite(model.next_token_loss(inputs, targets)))
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        loss = model.train_step(inputs, targets, optimizer)
        self.assertGreater(loss, 0.0)
        measured_rss_delta = process.memory_info().rss - rss_before
        self.assertGreater(measured_rss_delta, 0)
        self.assertLess(measured_rss_delta, 1024**3)

        vocabulary = Vocabulary.build(["Nova aprende linguagem."], max_size=1000)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "nova_model.pt"
            metadata = ModelMetadata.new(
                training_steps=1,
                parameter_count=config.parameter_count,
                vocabulary=vocabulary.to_dict(),
            )
            CheckpointStore.save(checkpoint, model, metadata)
            loaded_metadata = CheckpointStore.load(checkpoint, TinyTransformer(config))
            self.assertEqual(loaded_metadata.training_steps, 1)
            generated_model = TinyModelInference.from_checkpoint(checkpoint, config)
            generated = generated_model.generate([{"content": "Nova"}], max_new_tokens=2)
            self.assertIsInstance(generated, str)
            self.assertLessEqual(len(generated_model.tokenizer.encode(generated)), 2)
            history = ModelHistory(Path(directory) / "history.sqlite3")
            history.record(config, metadata, final_loss=loss)
            self.assertEqual(history.list_runs()[0]["parameter_count"], config.parameter_count)

    def test_real_peak_memory_under_one_gib_for_small_smoke_step(self):
        import resource
        import torch

        model = TinyTransformer(ModelConfig(vocab_size=1000))
        sample = torch.tensor([[4, 5, 6, 7]], dtype=torch.long)
        loss = model(sample).sum()
        loss.backward()
        peak_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        self.assertGreater(loss.item(), 0)
        self.assertLess(peak_bytes, 1024**3)


class OptionalDependencyTests(unittest.TestCase):
    @unittest.skipIf(importlib.util.find_spec("torch"), "PyTorch is installed")
    def test_missing_torch_fails_clearly_without_breaking_package_import(self):
        with self.assertRaisesRegex(ModelError, "PyTorch CPU não está instalado"):
            TinyTransformer()


if __name__ == "__main__":
    unittest.main()
