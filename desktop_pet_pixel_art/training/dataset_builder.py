"""Valida e converte arquivos locais para sequências JSONL limitadas."""

import argparse
import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from nova_ai.model import ByteTokenizer, Vocabulary

from .training_config import TrainingConfig


@dataclass(frozen=True)
class DatasetBuildResult:
    run_name: str
    train_path: Path
    validation_path: Path
    vocabulary_path: Path
    manifest_path: Path
    accepted_documents: int
    training_sequences: int
    validation_sequences: int
    skipped_duplicates: int
    skipped_invalid: int


class DatasetBuilder:
    """Lê um registro por vez; fontes aceitas são .txt e .jsonl dentro de datasets/raw."""

    def __init__(self, config: TrainingConfig):
        self.config = config

    def _source_files(self, sources=None):
        raw_dir = self.config.raw_dir
        if not raw_dir.is_dir():
            raise FileNotFoundError(f"crie e preencha primeiro o diretório de fontes: {raw_dir}")
        root = raw_dir.resolve(strict=True)
        candidates = (list(sources) if sources is not None else
                      sorted(path for path in root.iterdir()
                             if path.suffix.casefold() in (".txt", ".jsonl")))
        files = []
        for candidate in candidates:
            path = Path(candidate)
            if not path.is_absolute():
                path = raw_dir / path
            if path.is_symlink():
                raise ValueError(f"links simbólicos não são aceitos como fontes: {path.name}")
            resolved = path.resolve(strict=True)
            if resolved.parent != root or not resolved.is_file():
                raise ValueError("cada fonte deve ser um arquivo regular diretamente em datasets/raw")
            if resolved.suffix.casefold() not in (".txt", ".jsonl"):
                raise ValueError(f"extensão não suportada: {resolved.suffix}")
            files.append(resolved)
        if not files:
            raise ValueError(f"nenhum arquivo .txt ou .jsonl encontrado em {raw_dir}")
        return files

    def _iter_bounded_lines(self, stream):
        limit = self.config.max_line_chars
        while True:
            line = stream.readline(limit + 2)
            if not line:
                return
            if len(line) > limit + 1 and not line.endswith("\n"):
                while line and not line.endswith("\n"):
                    line = stream.readline(limit + 2)
                yield None
            else:
                yield line

    def _iter_texts(self, files, stats):
        for path in files:
            is_jsonl = path.suffix.casefold() == ".jsonl"
            try:
                with path.open("r", encoding="utf-8", errors="strict") as stream:
                    for line in self._iter_bounded_lines(stream):
                        if stats["scanned_records"] >= self.config.max_scanned_records:
                            return
                        stats["scanned_records"] += 1
                        if line is None:
                            stats["skipped_invalid"] += 1
                            continue
                        try:
                            if is_jsonl:
                                record = json.loads(line)
                                text = record.get("text") if isinstance(record, dict) else None
                                if not isinstance(text, str):
                                    raise ValueError("JSONL requer campo text textual")
                            else:
                                text = line
                        except (json.JSONDecodeError, ValueError, AttributeError):
                            stats["skipped_invalid"] += 1
                            continue
                        text = " ".join(text.split())
                        if len(text) < 2 or len(text) > self.config.max_line_chars:
                            stats["skipped_invalid"] += 1
                            continue
                        yield text
            except UnicodeDecodeError:
                stats["skipped_invalid"] += 1

    @staticmethod
    def _iter_plain_text(path):
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                yield line.rstrip("\n")

    def _encode_split(self, source_path, destination_path, tokenizer):
        sequence_count = 0
        context = self.config.model.max_seq_len
        with source_path.open("r", encoding="utf-8") as source, destination_path.open("w", encoding="utf-8") as output:
            for line in source:
                text = line.rstrip("\n")
                ids = tokenizer.encode(text, add_special_tokens=True)
                for start in range(0, max(0, len(ids) - 1), context):
                    chunk = ids[start:start + context + 1]
                    if len(chunk) < 2:
                        continue
                    record = {"input_ids": chunk[:-1], "target_ids": chunk[1:]}
                    output.write(json.dumps(record, separators=(",", ":")) + "\n")
                    sequence_count += 1
        return sequence_count

    def build(self, sources=None):
        files = self._source_files(sources)
        cfg = self.config
        final_train_dir = cfg.processed_dir
        final_validation_dir = cfg.validation_dir
        final_vocab = final_train_dir / "vocabulary.json"
        final_manifest = final_train_dir / "manifest.json"
        if final_train_dir.exists() or final_validation_dir.exists():
            raise FileExistsError(
                "esta execução já tem saídas; mude run_name para preservar e separar os resultados existentes"
            )

        dataset_root = cfg.dataset_root
        processed_parent = dataset_root / "processed"
        validation_parent = dataset_root / "validation"
        processed_parent.mkdir(parents=True, exist_ok=True)
        validation_parent.mkdir(parents=True, exist_ok=True)
        stats = {"skipped_invalid": 0, "skipped_duplicates": 0,
                 "accepted_documents": 0, "scanned_records": 0}
        seen_hashes = set()

        with tempfile.TemporaryDirectory(prefix=".dataset-stage-", dir=dataset_root) as temp_name:
            stage_root = Path(temp_name)
            stage_train_dir = stage_root / "processed"
            stage_validation_dir = stage_root / "validation"
            stage_train_dir.mkdir()
            stage_validation_dir.mkdir()
            train_text = stage_root / "train.txt"
            validation_text = stage_root / "validation.txt"
            train_text.touch()
            validation_text.touch()
            train_docs = validation_docs = 0

            with train_text.open("w", encoding="utf-8") as train_out, validation_text.open("w", encoding="utf-8") as validation_out:
                for text in self._iter_texts(files, stats):
                    if stats["accepted_documents"] >= cfg.max_examples:
                        break
                    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    if digest in seen_hashes:
                        stats["skipped_duplicates"] += 1
                        continue
                    seen_hashes.add(digest)
                    index = stats["accepted_documents"]
                    use_validation = (
                        cfg.validation_percent > 0
                        and (index == 0 or (train_docs > 0 and int(digest[:8], 16) % 100 < cfg.validation_percent))
                    )
                    if use_validation:
                        validation_out.write(text + "\n")
                        validation_docs += 1
                    else:
                        train_out.write(text + "\n")
                        train_docs += 1
                    stats["accepted_documents"] += 1

            if not train_docs or not validation_docs:
                raise ValueError("são necessários pelo menos dois textos únicos para treino e validação")

            vocabulary = Vocabulary.build(
                self._iter_plain_text(train_text), max_size=cfg.model.vocab_size
            )
            tokenizer = ByteTokenizer(vocabulary)
            vocabulary_path = stage_train_dir / "vocabulary.json"
            vocabulary_path.write_text(
                json.dumps(vocabulary.to_dict(), ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            train_path = stage_train_dir / "train.jsonl"
            validation_path = stage_validation_dir / "validation.jsonl"
            train_sequences = self._encode_split(train_text, train_path, tokenizer)
            validation_sequences = self._encode_split(validation_text, validation_path, tokenizer)
            if not train_sequences or not validation_sequences:
                raise ValueError("os textos não produziram sequências tokenizadas suficientes")

            manifest = {
                "format_version": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "run_name": cfg.run_name,
                "source_files": [path.name for path in files],
                "accepted_documents": stats["accepted_documents"],
                "scanned_records": stats["scanned_records"],
                "training_documents": train_docs,
                "validation_documents": validation_docs,
                "training_sequences": train_sequences,
                "validation_sequences": validation_sequences,
                "skipped_duplicates": stats["skipped_duplicates"],
                "skipped_invalid": stats["skipped_invalid"],
                "vocabulary_size": len(vocabulary),
                "active_vocabulary_size": vocabulary.active_size,
                "context_tokens": cfg.model.max_seq_len,
            }
            (stage_train_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            os.replace(stage_train_dir, final_train_dir)
            os.replace(stage_validation_dir, final_validation_dir)

        return DatasetBuildResult(
            run_name=cfg.run_name,
            train_path=final_train_dir / "train.jsonl",
            validation_path=final_validation_dir / "validation.jsonl",
            vocabulary_path=final_vocab,
            manifest_path=final_manifest,
            accepted_documents=stats["accepted_documents"],
            training_sequences=train_sequences,
            validation_sequences=validation_sequences,
            skipped_duplicates=stats["skipped_duplicates"],
            skipped_invalid=stats["skipped_invalid"],
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Valida e prepara corpus local da Nova")
    parser.add_argument("--config", default="training/training_config.json")
    parser.add_argument("--sources", nargs="*", help="arquivos .txt/.jsonl dentro de datasets/raw")
    args = parser.parse_args(argv)
    config = TrainingConfig.from_json(args.config)
    result = DatasetBuilder(config).build(args.sources)
    print(json.dumps({key: str(value) if isinstance(value, Path) else value
                      for key, value in asdict(result).items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
