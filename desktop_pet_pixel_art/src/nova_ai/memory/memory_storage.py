"""Persistência SQLite local, versionada e sem conexão a serviços externos."""

from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from datetime import datetime, timezone
import unicodedata

from .errors import (
    ConsentRequiredError,
    DuplicateMemoryError,
    MemoryNotFoundError,
    MemoryStorageError,
)

SCHEMA_VERSION = 2
APPLICATION_ID = 0x4E4F5641  # ASCII "NOVA"
_MEMORY_KINDS = "'episodic', 'semantic', 'procedural', 'preference', 'profile', 'project', 'conversation', 'learning'"


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize(content):
    folded = unicodedata.normalize("NFKD", content.casefold())
    unaccented = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(unaccented.split())


class MemoryStorage:
    """Banco próprio da Nova; não abre nem migra os JSON/bancos do app legado."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else (
            Path.home() / ".config" / "desktop_pet" / "nova_memory.sqlite3"
        )
        self.corrupt_backup_path = None
        if self.path.is_symlink():
            raise MemoryStorageError("O banco de memória não pode ser um link simbólico")
        if self.path.parent.exists() and self.path.parent.is_symlink():
            raise MemoryStorageError("O diretório do banco de memória não pode ser um link simbólico")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink():
            raise MemoryStorageError("O diretório do banco de memória não pode ser um link simbólico")
        self._create_secure_file()
        self._prepare_database()

    def _create_secure_file(self):
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return
        except OSError as exc:
            raise MemoryStorageError(
                "Não foi possível criar o arquivo privado de memória", cause=exc
            ) from exc
        else:
            os.close(descriptor)

    def _connect(self):
        connection = sqlite3.connect(str(self.path), timeout=2.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 2000")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    def _prepare_database(self):
        if self.path.exists():
            try:
                with closing(self._connect()) as connection:
                    check = connection.execute("PRAGMA quick_check").fetchone()[0]
                    if check != "ok":
                        raise sqlite3.DatabaseError("integrity check failed")
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
                    if version not in (0, 1, SCHEMA_VERSION):
                        raise MemoryStorageError("Versão do banco de memória não suportada")
                    application_id = connection.execute(
                        "PRAGMA application_id"
                    ).fetchone()[0]
                    if application_id not in (0, APPLICATION_ID):
                        raise MemoryStorageError("O arquivo não pertence ao banco de memória da Nova")
                    if application_id == 0:
                        tables = connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table' "
                            "AND name NOT LIKE 'sqlite_%'"
                        ).fetchall()
                        if tables:
                            raise MemoryStorageError(
                                "Recusando inicializar sobre um banco SQLite existente"
                            )
                    if version == 1:
                        try:
                            self._migrate_v1(connection)
                        except sqlite3.DatabaseError as exc:
                            raise MemoryStorageError(
                                "Não foi possível migrar o banco de memória", cause=exc
                            ) from exc
            except MemoryStorageError:
                raise
            except sqlite3.DatabaseError as exc:
                self.corrupt_backup_path = self._preserve_corrupt_database()
                if self.corrupt_backup_path is None:
                    raise MemoryStorageError(
                        "Banco de memória corrompido e não foi possível preservá-lo", cause=exc
                    ) from exc
                self._create_secure_file()
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    f"""CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL CHECK(kind IN ({_MEMORY_KINDS})),
                        content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 8000),
                        normalized_content TEXT NOT NULL,
                        source TEXT NOT NULL CHECK(length(source) BETWEEN 1 AND 128),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
                        relevance REAL NOT NULL CHECK(relevance BETWEEN 0 AND 1),
                        consent_granted INTEGER NOT NULL CHECK(consent_granted = 1),
                        provenance TEXT NOT NULL CHECK(provenance IN (
                            'user_provided', 'inference', 'uncertain', 'system_observation'
                        )),
                        expires_at TEXT,
                        UNIQUE(kind, normalized_content)
                    )"""
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS memories_kind_updated "
                    "ON memories(kind, updated_at DESC)"
                )
                connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except (sqlite3.DatabaseError, OSError) as exc:
            raise MemoryStorageError("Não foi possível inicializar o banco de memória", cause=exc) from exc

    @staticmethod
    def _migrate_v1(connection):
        """Expand categories and metadata transactionally while preserving records."""
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ALTER TABLE memories RENAME TO memories_v1")
        connection.execute(
            f"""CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ({_MEMORY_KINDS})),
                content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 8000),
                normalized_content TEXT NOT NULL,
                source TEXT NOT NULL CHECK(length(source) BETWEEN 1 AND 128),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
                relevance REAL NOT NULL CHECK(relevance BETWEEN 0 AND 1),
                consent_granted INTEGER NOT NULL CHECK(consent_granted = 1),
                provenance TEXT NOT NULL CHECK(provenance IN (
                    'user_provided', 'inference', 'uncertain', 'system_observation'
                )),
                expires_at TEXT,
                UNIQUE(kind, normalized_content)
            )"""
        )
        connection.execute(
            """INSERT INTO memories (
                id, kind, content, normalized_content, source, created_at, updated_at,
                confidence, relevance, consent_granted, provenance, expires_at
            ) SELECT id, kind, content, normalized_content, source, created_at, updated_at,
                confidence, relevance, consent_granted,
                CASE WHEN source IN ('user', 'user-confirmed') THEN 'user_provided'
                     ELSE 'system_observation' END, NULL FROM memories_v1"""
        )
        connection.execute("DROP TABLE memories_v1")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS memories_kind_updated ON memories(kind, updated_at DESC)"
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()

    def _preserve_corrupt_database(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        candidate = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        suffix = 1
        while candidate.exists():
            candidate = self.path.with_name(f"{self.path.name}.corrupt-{stamp}-{suffix}")
            suffix += 1
        try:
            os.replace(self.path, candidate)
            return candidate
        except OSError:
            return None

    @contextmanager
    def _read_connection(self):
        connection = self._connect()
        try:
            yield connection
        except sqlite3.DatabaseError as exc:
            raise MemoryStorageError("Falha ao consultar o banco de memória", cause=exc) from exc
        finally:
            connection.close()

    @contextmanager
    def _write_connection(self):
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            if "memories.kind, memories.normalized_content" in str(exc):
                raise DuplicateMemoryError("Já existe uma memória equivalente") from exc
            raise MemoryStorageError("Registro de memória inválido", cause=exc) from exc
        except sqlite3.DatabaseError as exc:
            connection.rollback()
            raise MemoryStorageError("Falha ao gravar no banco de memória", cause=exc) from exc
        finally:
            connection.close()

    @staticmethod
    def _record(row):
        if row is None:
            return None
        return dict(row)

    def insert(self, record):
        if record.get("consent_granted") is not True:
            raise ConsentRequiredError("A gravação exige consentimento explícito")
        now = _utc_now()
        with self._write_connection() as connection:
            connection.execute(
                """INSERT INTO memories (
                    id, kind, content, normalized_content, source, created_at, updated_at,
                    confidence, relevance, consent_granted, provenance, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                (
                    record["id"], record["kind"], record["content"],
                    _normalize(record["content"]), record["source"], now, now,
                    record["confidence"], record["relevance"], record["provenance"],
                    record.get("expires_at"),
                ),
            )
        return self.get(record["id"])

    def get(self, memory_id):
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("Memória não encontrada")
        return self._record(row)

    def find_duplicate(self, kind, content, *, exclude_id=None):
        sql = "SELECT * FROM memories WHERE kind = ? AND normalized_content = ?"
        values = [kind, _normalize(content)]
        if exclude_id is not None:
            sql += " AND id != ?"
            values.append(exclude_id)
        with self._read_connection() as connection:
            row = connection.execute(sql, values).fetchone()
        return self._record(row)

    def search(self, *, kind=None, terms=(), limit=100):
        sql = "SELECT * FROM memories WHERE (expires_at IS NULL OR expires_at > ?)"
        clauses = []
        values = [_utc_now()]
        if kind is not None:
            clauses.append("kind = ?")
            values.append(kind)
        for term in terms:
            clauses.append("normalized_content LIKE ? ESCAPE '\\'")
            escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.append(f"%{escaped}%")
        if clauses:
            sql += " AND " + " AND ".join(clauses)
        sql += " ORDER BY relevance DESC, confidence DESC, updated_at DESC LIMIT ?"
        values.append(limit)
        with self._read_connection() as connection:
            rows = connection.execute(sql, values).fetchall()
        return [self._record(row) for row in rows]

    def update(self, memory_id, *, content, source, confidence, relevance, consent=False,
               provenance=None, expires_at=None):
        if consent is not True:
            raise ConsentRequiredError("A atualização exige consentimento explícito")
        with self._write_connection() as connection:
            cursor = connection.execute(
                """UPDATE memories SET content = ?, normalized_content = ?, source = ?,
                    updated_at = ?, confidence = ?, relevance = ?, provenance = ?, expires_at = ?
                    WHERE id = ?""",
                (content, _normalize(content), source, _utc_now(), confidence, relevance,
                 provenance, expires_at, memory_id),
            )
            if cursor.rowcount == 0:
                raise MemoryNotFoundError("Memória não encontrada")
        return self.get(memory_id)

    def purge_expired(self):
        now = _utc_now()
        with self._write_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)
            )
        return cursor.rowcount

    def delete(self, memory_id):
        with self._write_connection() as connection:
            cursor = connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            if cursor.rowcount == 0:
                raise MemoryNotFoundError("Memória não encontrada")
        return True

    def backup_to(self, destination):
        destination = Path(destination)
        if destination.resolve() == self.path.resolve():
            raise MemoryStorageError("O destino do backup deve ser outro arquivo")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
            )
            os.close(fd)
            temporary = Path(temporary_name)
            with self._read_connection() as source, closing(sqlite3.connect(str(temporary))) as target:
                source.backup(target)
                target.commit()
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            return destination
        except (OSError, sqlite3.DatabaseError, MemoryStorageError) as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise MemoryStorageError("Não foi possível criar o backup da memória", cause=exc) from exc

    def export_json(self, destination, *, kind=None):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=destination.parent,
                prefix=f".{destination.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write('{\n  "format_version": 1,\n  "exported_at": ')
                json.dump(_utc_now(), handle, ensure_ascii=False)
                handle.write(',\n  "memories": [')
                sql = "SELECT * FROM memories WHERE (expires_at IS NULL OR expires_at > ?)"
                values = (_utc_now(),)
                if kind is not None:
                    sql += " AND kind = ?"
                    values = (_utc_now(), kind)
                sql += " ORDER BY created_at, id"
                with self._read_connection() as connection:
                    cursor = connection.execute(sql, values)
                    first = True
                    for row in cursor:
                        handle.write("\n    " if first else ",\n    ")
                        json.dump(dict(row), handle, ensure_ascii=False)
                        first = False
                if not first:
                    handle.write("\n  ")
                handle.write("]\n}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, destination)
            return destination
        except (OSError, TypeError, ValueError, MemoryStorageError) as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise MemoryStorageError("Não foi possível exportar as memórias", cause=exc) from exc
