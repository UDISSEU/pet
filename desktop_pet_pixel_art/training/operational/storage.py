"""Quota serializada entre processos para escritas no diretório gerenciado."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading

LIMIT = 50 * 1024**3
DEFAULT_BUDGETS = {"models": 10, "datasets": 8, "checkpoints": 8, "evaluation": 4, "cache": 5, "reserve": 15}
_THREAD_LOCK = threading.RLock()
_LOCK_STATE = threading.local()

def manager_for_training_path(path):
    """Find the enclosing `training/` root; return None for unrelated application data."""
    candidate = Path(path).absolute()
    for parent in (candidate, *candidate.parents):
        if parent.name == "training":
            return StorageManager(parent)
    return None

class StorageLimitError(OSError):
    """A escrita excederia a quota máxima gerenciada."""

class _QuotaWriter:
    def __init__(self, stream, *, maximum, encoding, on_write=None):
        self._stream, self._maximum, self._encoding = stream, maximum, encoding
        self._on_write = on_write
        self._written = 0

    def write(self, value):
        if isinstance(value, str):
            size = len(value.encode(self._encoding))
        elif isinstance(value, (bytes, bytearray, memoryview)):
            size = len(value)
        else:
            raise TypeError("write exige texto ou bytes")
        if self._written + size > self._maximum:
            raise StorageLimitError("arquivo excede a reserva de escrita autorizada")
        result = self._stream.write(value)
        self._written += size
        if self._on_write is not None:
            self._on_write(size)
        return result

    def __enter__(self):
        self._stream.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self._stream.__exit__(exc_type, exc, traceback)

    def __getattr__(self, name):
        return getattr(self._stream, name)

class StorageManager:
    """Limita gravações encaminhadas pelo manager; não intercepta o filesystem global."""
    def __init__(self, root, *, limit_bytes=LIMIT, budgets_gb=None):
        self.root = Path(root).absolute()
        self.limit_bytes = int(limit_bytes)
        self.budgets_gb = dict(budgets_gb or DEFAULT_BUDGETS)
        self._reservations = {}
        if self.limit_bytes <= 0 or self.limit_bytes > LIMIT or sum(self.budgets_gb.values()) != 50:
            raise ValueError("O teto deve ficar entre 1 byte e 50 GiB e os orçamentos somar 50 GB")

    def _target(self, relative):
        candidate = Path(relative)
        target = candidate.absolute() if candidate.is_absolute() else (self.root / candidate).absolute()
        if target == self.root or self.root not in target.parents:
            raise ValueError("destino fora do diretório dedicado")
        if self.root.exists() and self.root.is_symlink():
            raise ValueError("a raiz de armazenamento não pode ser link simbólico")
        current = self.root
        for part in target.relative_to(self.root).parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise ValueError("diretórios de armazenamento não podem ser links simbólicos")
        if target.is_symlink():
            raise ValueError("destino de armazenamento não pode ser link simbólico")
        return target

    def relative_path(self, path):
        """Return checked path relative to the managed root."""
        return self._target(path).relative_to(self.root)

    def _size(self):
        total = 0
        if self.root.exists():
            for path in self.root.rglob("*"):
                if path.is_symlink() or not path.is_file() or path.name == ".storage.lock":
                    continue
                total += path.stat().st_size
        return total

    @contextmanager
    def _exclusive(self):
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / ".storage.lock"
        key = str(lock_path)
        state = getattr(_LOCK_STATE, "locks", {})
        if key in state:
            state[key]["depth"] += 1
            try:
                yield
            finally:
                state[key]["depth"] -= 1
            return
        _THREAD_LOCK.acquire()
        try:
            lock = lock_path.open("a+b")
        except Exception:
            _THREAD_LOCK.release()
            raise
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        state[key] = {"depth": 1, "lock": lock}
        _LOCK_STATE.locks = state
        try:
            yield
        finally:
            del state[key]
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            lock.close()
            _THREAD_LOCK.release()

    def report(self):
        with self._exclusive():
            files = self.inventory()
            used = sum(row["size_bytes"] for row in files)
            return {"root": str(self.root), "limit_bytes": self.limit_bytes,
                    "used_bytes": used, "remaining_bytes": max(0, self.limit_bytes-used),
                    "budgets_gb": self.budgets_gb, "files": files}

    def inventory(self):
        categories = {"datasets": "datasets", "validation": "datasets", "checkpoints": "checkpoints",
                      "adapters": "adapters", "models": "models", "cache": "cache",
                      "evaluation": "evaluation", "experiments": "evaluation"}
        rows = []
        if not self.root.exists():
            return rows
        for path in sorted(self.root.rglob("*")):
            if path.is_symlink() or not path.is_file() or path.name == ".storage.lock":
                continue
            rel = path.relative_to(self.root)
            category = next((categories[p.casefold()] for p in rel.parts if p.casefold() in categories), "other")
            if rel.parts[:2] == ("operational", "data"):
                category = "evaluation" if path.name == "benchmark.jsonl" else "datasets"
            elif rel.parts and rel.parts[0] == "operational-material":
                category = "cache"
            origin = ("user-supplied-or-preexisting" if category == "datasets" and "raw" in rel.parts
                      else "generated-or-preexisting" if category != "other" else "repository-or-preexisting")
            version = None
            if path.suffix.casefold() in {".json", ".jsonl"}:
                try:
                    with path.open("r", encoding="utf-8") as stream:
                        first = stream.readline(16_384)
                    item = json.loads(first)
                    version = item.get("schema_version", item.get("format_version", item.get("version"))) if isinstance(item, dict) else None
                except (OSError, UnicodeError, ValueError):
                    version = None
            purpose = {"datasets":"training/validation dataset or corpus", "evaluation":"benchmark/metrics/history",
                       "checkpoints":"checkpoint weights", "models":"model weights/export", "adapters":"adapter weights",
                       "cache":"inference/training cache", "other":"training source/configuration"}[category]
            rows.append({"file": str(rel), "category": category, "size_bytes": path.stat().st_size,
                         "origin": origin, "version": version, "purpose": purpose})
        return rows

    @contextmanager
    def open_binary(self, relative, *, max_bytes):
        with self._managed_open(relative, max_bytes=max_bytes, binary=True, encoding=None) as stream:
            yield stream

    @contextmanager
    def reserve_bytes(self, max_bytes):
        """Reserve headroom while a bounded external writer (for example SQLite) runs."""
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("max_bytes deve ser inteiro não negativo")
        with self._exclusive():
            used = self._size()
            reserved = sum(self._reservations.values())
            if used + reserved + max_bytes > self.limit_bytes:
                raise StorageLimitError(
                    f"reserva bloqueada: uso {used} + reservas {reserved} + "
                    f"nova reserva {max_bytes} excede teto {self.limit_bytes} bytes"
                )
            key = object()
            self._reservations[key] = max_bytes
            try:
                yield
            finally:
                self._reservations.pop(key, None)

    @contextmanager
    def open_text(self, relative, *, max_bytes, encoding="utf-8"):
        with self._managed_open(relative, max_bytes=max_bytes, binary=False, encoding=encoding) as stream:
            yield stream

    @contextmanager
    def _managed_open(self, relative, *, max_bytes, binary, encoding):
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("max_bytes deve ser inteiro não negativo")
        target = self._target(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage_dir = self.root / ".staging"
        stage_dir.mkdir(exist_ok=True)
        temporary = None
        with self._exclusive():
            used = self._size()
            reserved = sum(self._reservations.values())
            if used + reserved + max_bytes > self.limit_bytes:
                raise StorageLimitError(
                    f"gravação bloqueada: uso atual {used} bytes + reservas {reserved} bytes "
                    f"+ nova reserva {max_bytes} bytes "
                    f"ultrapassaria o teto de {self.limit_bytes} bytes"
                )
            reservation_id = object()
            self._reservations[reservation_id] = max_bytes
            fd, temporary = tempfile.mkstemp(prefix="write-", dir=stage_dir)
            try:
                raw = os.fdopen(fd, "wb" if binary else "w", **({} if binary else {"encoding": encoding}))
                def account(size):
                    self._reservations[reservation_id] -= size
                managed = _QuotaWriter(raw, maximum=max_bytes, encoding=encoding or "utf-8", on_write=account)
                with managed as stream:
                    yield stream
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                temporary = None
            finally:
                self._reservations.pop(reservation_id, None)
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)

    def write_bytes(self, relative, data):
        if not isinstance(data, bytes):
            raise TypeError("data deve ser bytes")
        with self.open_binary(relative, max_bytes=len(data)) as stream:
            stream.write(data)
        return self._target(relative)

    def write_text(self, relative, data, *, encoding="utf-8"):
        if not isinstance(data, str):
            raise TypeError("data deve ser str")
        with self.open_text(relative, max_bytes=len(data.encode(encoding)), encoding=encoding) as stream:
            stream.write(data)
        return self._target(relative)

    def copy_file(self, source, relative, *, max_bytes=None, chunk_size=1024*1024):
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise ValueError("a origem da cópia deve ser arquivo regular, sem symlink")
        size = source.stat().st_size
        if max_bytes is None:
            max_bytes = size
        if size > max_bytes:
            raise StorageLimitError("cópia excede o limite reservado")
        with source.open("rb") as input_stream, self.open_binary(relative, max_bytes=max_bytes) as output:
            while True:
                chunk = input_stream.read(chunk_size)
                if not chunk:
                    break
                output.write(chunk)
        return self._target(relative)

    def record(self):
        previous = None
        for _ in range(4):
            report = self.report()
            content = json.dumps(report, indent=2)+"\n"
            self.write_text("storage_usage.json", content)
            updated = self.report()
            if updated["used_bytes"] == report["used_bytes"] and len(content.encode("utf-8")) == (self.root/"storage_usage.json").stat().st_size:
                return updated
            previous = updated
        return previous
