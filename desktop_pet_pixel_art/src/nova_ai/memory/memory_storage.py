"""Persistência SQLite local, versionada e sem conexão a serviços externos."""

from contextlib import closing, contextmanager
import json
import os
import sqlite3
import stat
import tempfile
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

from json_persistence import ensure_private_directory, validate_storage_path

from .errors import (
    ConsentRequiredError,
    DuplicateMemoryError,
    MemoryNotFoundError,
    MemoryStorageError,
)

SCHEMA_VERSION = 4
APPLICATION_ID = 0x4E4F5641  # ASCII "NOVA"
_MEMORY_KINDS = "'episodic', 'semantic', 'procedural', 'preference', 'profile', 'project', 'conversation', 'learning'"


class _PinnedDirectoryConnection(sqlite3.Connection):
    def __init__(self, *args, directory_fd, **kwargs):
        super().__init__(*args, **kwargs)
        self._directory_fd = directory_fd

    def close(self):
        directory_fd = self._directory_fd
        self._directory_fd = None
        try:
            super().close()
        finally:
            if directory_fd is not None:
                os.close(directory_fd)


def _open_storage_directory(path, *, create=False, private=True):
    """Open a directory by walking from / without following replaceable symlinks."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise OSError("A plataforma não oferece abertura segura de diretórios")
    directory = Path(os.path.abspath(os.path.expanduser(str(path))))
    if ".." in directory.parts:
        raise OSError("O caminho do banco contém componentes inválidos")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    directory_fd = os.open(directory.anchor, flags)
    try:
        parts = directory.parts[1:]
        for index, name in enumerate(parts):
            try:
                child_fd = os.open(name, flags, dir_fd=directory_fd)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(name, 0o700, dir_fd=directory_fd)
                except FileExistsError:
                    pass
                child_fd = os.open(name, flags, dir_fd=directory_fd)

            try:
                info = os.fstat(child_fd)
                if not stat.S_ISDIR(info.st_mode):
                    raise OSError(
                        "O caminho do banco contém um componente que não é diretório"
                    )
                is_final = index == len(parts) - 1
                mode = stat.S_IMODE(info.st_mode)
                if mode & 0o022 and not info.st_mode & stat.S_ISVTX:
                    raise OSError(
                        "O caminho do banco atravessa um diretório gravável por terceiros"
                    )
                if is_final and private:
                    if info.st_uid != os.geteuid():
                        raise OSError(
                            "O diretório do banco precisa pertencer ao usuário atual"
                        )
                    os.fchmod(child_fd, 0o700)
                    if stat.S_IMODE(os.fstat(child_fd).st_mode) != 0o700:
                        raise OSError("Não foi possível restringir o diretório do banco")
            except BaseException:
                os.close(child_fd)
                raise

            os.close(directory_fd)
            directory_fd = child_fd

        if private:
            info = os.fstat(directory_fd)
            if (info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o700):
                raise OSError("O diretório do banco não é privado para o usuário atual")
        return directory_fd
    except BaseException:
        os.close(directory_fd)
        raise


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize(content):
    folded = unicodedata.normalize("NFKD", content.casefold())
    unaccented = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(unaccented.split())


class MemoryStorage:
    """Banco próprio da Nova; mantém memória local, perfis e contexto de conversas."""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else (
            Path.home() / ".config" / "desktop_pet" / "nova_memory.sqlite3"
        )
        self.corrupt_backup_path = None
        validate_storage_path(self.path, label="banco de memória")
        try:
            directory_fd = _open_storage_directory(self.path.parent, create=True)
            os.close(directory_fd)
        except OSError as exc:
            raise MemoryStorageError(
                "Não foi possível proteger o diretório do banco de memória", cause=exc
            ) from exc
        self._create_secure_file()
        self._prepare_database()

    def _create_secure_file(self):
        created = False
        descriptor = None
        directory_fd = None
        try:
            directory_fd = _open_storage_directory(self.path.parent)
            try:
                descriptor = os.open(
                    self.path.name,
                    os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                created = True
            except FileExistsError:
                descriptor = os.open(
                    self.path.name,
                    os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=directory_fd,
                )
            file_stat = os.fstat(descriptor)
            if (not stat.S_ISREG(file_stat.st_mode)
                    or file_stat.st_uid != os.geteuid()
                    or file_stat.st_nlink != 1):
                raise OSError("O banco de memória precisa ser um arquivo regular")
            os.fchmod(descriptor, 0o600)
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
                raise OSError("Não foi possível restringir as permissões do banco")
        except OSError as exc:
            if created:
                try:
                    os.unlink(self.path.name, dir_fd=directory_fd)
                except OSError:
                    pass
            raise MemoryStorageError(
                "Não foi possível proteger o arquivo privado de memória", cause=exc
            ) from exc
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if directory_fd is not None:
                os.close(directory_fd)

    @staticmethod
    def _connect_file(path, *, read_only=False, private_directory=False):
        path = validate_storage_path(path, label="banco de memória")
        directory_fd = _open_storage_directory(
            path.parent, private=private_directory
        )
        file_descriptor = None
        connection = None
        state = {}
        try:
            open_flags = (os.O_RDONLY if read_only else os.O_RDWR)
            file_descriptor = os.open(
                path.name,
                open_flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            )
            opened_stat = os.fstat(file_descriptor)
            if (not stat.S_ISREG(opened_stat.st_mode)
                    or opened_stat.st_uid != os.geteuid()
                    or opened_stat.st_nlink != 1):
                raise OSError("O banco precisa ser um arquivo regular do usuário atual")
            if private_directory and stat.S_IMODE(opened_stat.st_mode) != 0o600:
                raise OSError("As permissões do banco de memória não são privadas")

            sqlite_path = Path(f"/proc/self/fd/{directory_fd}/{path.name}")
            if not sqlite_path.parent.is_dir():
                raise OSError("O sistema não oferece o acesso SQLite por diretório fixado")
            mode = "ro" if read_only else "rw"
            uri = f"{sqlite_path.as_uri()}?mode={mode}"

            def connection_factory(*args, **kwargs):
                connection = _PinnedDirectoryConnection(
                    *args, directory_fd=directory_fd, **kwargs
                )
                state["connection"] = connection
                return connection

            connection = sqlite3.connect(
                uri, uri=True, timeout=2.0, factory=connection_factory
            )
            current_stat = os.stat(
                path.name, dir_fd=directory_fd, follow_symlinks=False
            )
            if (not stat.S_ISREG(current_stat.st_mode)
                    or (current_stat.st_dev, current_stat.st_ino)
                    != (opened_stat.st_dev, opened_stat.st_ino)):
                raise OSError("O arquivo do banco foi substituído durante a abertura")
            directory_fd = None
            connection.row_factory = sqlite3.Row
            return connection
        except BaseException:
            opened_connection = connection or state.get("connection")
            if opened_connection is not None:
                opened_connection.close()
                directory_fd = None
            raise
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            if directory_fd is not None:
                os.close(directory_fd)

    def _connect(self, *, read_only=False):
        connection = self._connect_file(
            self.path, read_only=read_only, private_directory=True
        )
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 2000")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA secure_delete = ON")
            return connection
        except BaseException:
            connection.close()
            raise

    def _table_columns(self, connection, table_name):
        rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row[1] for row in rows}

    def _prepare_database(self):
        validate_storage_path(self.path, label="banco de memória")
        if self.path.exists():
            try:
                with closing(self._connect()) as connection:
                    check = connection.execute("PRAGMA quick_check").fetchone()[0]
                    if check != "ok":
                        raise sqlite3.DatabaseError("integrity check failed")
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
                    if version not in (0, 1, 2, 3, SCHEMA_VERSION):
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
                    if version in (1, 2):
                        try:
                            self._migrate_v1_v3(connection, version)
                            version = 3
                        except sqlite3.DatabaseError as exc:
                            raise MemoryStorageError(
                                "Não foi possível migrar o banco de memória", cause=exc
                            ) from exc
                    if version == 3:
                        try:
                            self._migrate_v3_v4(connection)
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
                self._create_schema(connection)
                connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
        except (sqlite3.DatabaseError, OSError) as exc:
            raise MemoryStorageError("Não foi possível inicializar o banco de memória", cause=exc) from exc

    def _create_schema(self, connection):
        connection.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT,
                access_level TEXT NOT NULL DEFAULT 'user'
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                summary TEXT,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived','deleted')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(id, user_id)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY(conversation_id, user_id)
                    REFERENCES conversations(id, user_id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS preferences (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, key)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','archived')),
                priority INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                due_at TEXT,
                UNIQUE(id, user_id)
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                occurred_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                relevant INTEGER NOT NULL DEFAULT 1 CHECK(relevant IN (0, 1)),
                metadata TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS personality_history (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                behavior TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'system'
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS permissions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                permission TEXT NOT NULL,
                granted INTEGER NOT NULL DEFAULT 1 CHECK(granted IN (0, 1)),
                scope TEXT NOT NULL DEFAULT 'global',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT,
                UNIQUE(user_id, permission, scope)
            )"""
        )
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
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                conversation_id TEXT,
                project_id TEXT,
                category TEXT NOT NULL DEFAULT 'general',
                priority INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                UNIQUE(user_id, kind, normalized_content),
                FOREIGN KEY(conversation_id, user_id)
                    REFERENCES conversations(id, user_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id, user_id)
                    REFERENCES projects(id, user_id) ON DELETE CASCADE
            )"""
        )
        for column_name, definition in (
            ("user_id", "TEXT REFERENCES users(id) ON DELETE SET NULL"),
            ("conversation_id", "TEXT REFERENCES conversations(id) ON DELETE SET NULL"),
            ("project_id", "TEXT REFERENCES projects(id) ON DELETE SET NULL"),
            ("category", "TEXT NOT NULL DEFAULT 'general'"),
            ("priority", "INTEGER NOT NULL DEFAULT 0"),
            ("is_active", "INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1))"),
        ):
            columns = self._table_columns(connection, "memories")
            if column_name not in columns:
                connection.execute(f"ALTER TABLE memories ADD COLUMN {column_name} {definition}")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS memories_kind_updated "
            "ON memories(kind, updated_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS memories_user_category "
            "ON memories(user_id, category, updated_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS conversations_user_updated "
            "ON conversations(user_id, updated_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS messages_conversation_created "
            "ON messages(conversation_id, created_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS projects_user_status "
            "ON projects(user_id, status, updated_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS events_user_occurred "
            "ON events(user_id, occurred_at DESC)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS permissions_user_scope "
            "ON permissions(user_id, permission, scope)"
        )
        if not self._table_columns(connection, "users"):
            return
        default_user = connection.execute(
            "SELECT id FROM users WHERE profile_id = 'legacy'"
        ).fetchone()
        if default_user is None:
            connection.execute(
                "INSERT OR IGNORE INTO users (id, profile_id, name, created_at, updated_at, access_level) VALUES (?, ?, ?, ?, ?, ?)",
                ("legacy", "legacy", "Perfil principal", _utc_now(), _utc_now(), "admin"),
            )
        connection.execute(
            "UPDATE memories SET user_id = 'legacy' WHERE user_id IS NULL AND NOT EXISTS (SELECT 1 FROM users WHERE users.id = 'legacy')"
        )
        connection.execute(
            "UPDATE memories SET user_id = 'legacy' WHERE user_id IS NULL"
        )

    def _migrate_v1_v3(self, connection, version):
        """Migrates from v1/v2 to the expanded SQLite schema while keeping the legacy memory table."""
        connection.execute("BEGIN IMMEDIATE")
        if version == 1:
            connection.execute("ALTER TABLE memories RENAME TO memories_v1")
            connection.execute(
                """CREATE TABLE memories (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK(kind IN ('episodic','semantic','procedural','preference','profile','project','conversation','learning')),
                    content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 8000),
                    normalized_content TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(length(source) BETWEEN 1 AND 128),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
                    relevance REAL NOT NULL CHECK(relevance BETWEEN 0 AND 1),
                    consent_granted INTEGER NOT NULL CHECK(consent_granted = 1),
                    provenance TEXT NOT NULL CHECK(provenance IN ('user_provided','inference','uncertain','system_observation')),
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
        for table_name, query in (
            ("users", """CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL UNIQUE, name TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, metadata TEXT, access_level TEXT NOT NULL DEFAULT 'user')"""),
            ("conversations", """CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, title TEXT NOT NULL, summary TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived','deleted')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""),
            ("messages", """CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK(role IN ('user','assistant','system')), content TEXT NOT NULL, created_at TEXT NOT NULL, metadata TEXT)"""),
            ("preferences", """CREATE TABLE IF NOT EXISTS preferences (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, key TEXT NOT NULL, value TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'general', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(user_id, key))"""),
            ("projects", """CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, description TEXT, status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused','completed','archived')), priority INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, due_at TEXT)"""),
            ("events", """CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, type TEXT NOT NULL, title TEXT NOT NULL, description TEXT, occurred_at TEXT NOT NULL, created_at TEXT NOT NULL, relevant INTEGER NOT NULL DEFAULT 1 CHECK(relevant IN (0, 1)), metadata TEXT)"""),
            ("personality_history", """CREATE TABLE IF NOT EXISTS personality_history (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, behavior TEXT NOT NULL, summary TEXT NOT NULL, created_at TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'system')"""),
            ("permissions", """CREATE TABLE IF NOT EXISTS permissions (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, permission TEXT NOT NULL, granted INTEGER NOT NULL DEFAULT 1 CHECK(granted IN (0, 1)), scope TEXT NOT NULL DEFAULT 'global', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, metadata TEXT, UNIQUE(user_id, permission, scope))"""),
        ):
            connection.execute(query)
        connection.execute(
            "INSERT OR IGNORE INTO users (id, profile_id, name, created_at, updated_at, access_level) VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy", "legacy", "Perfil principal", _utc_now(), _utc_now(), "admin"),
        )
        columns = self._table_columns(connection, "memories")
        for column_name, definition in (
            ("user_id", "TEXT REFERENCES users(id) ON DELETE SET NULL"),
            ("conversation_id", "TEXT REFERENCES conversations(id) ON DELETE SET NULL"),
            ("project_id", "TEXT REFERENCES projects(id) ON DELETE SET NULL"),
            ("category", "TEXT NOT NULL DEFAULT 'general'"),
            ("priority", "INTEGER NOT NULL DEFAULT 0"),
            ("is_active", "INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1))"),
        ):
            if column_name not in columns:
                connection.execute(f"ALTER TABLE memories ADD COLUMN {column_name} {definition}")
        connection.execute("UPDATE memories SET user_id = 'legacy', category = 'general', priority = 0, is_active = 1 WHERE user_id IS NULL")
        connection.execute("PRAGMA user_version = 3")
        connection.commit()

    def _migrate_v3_v4(self, connection):
        connection.execute("BEGIN IMMEDIATE")
        now = _utc_now()
        connection.execute(
            "INSERT OR IGNORE INTO users (id, profile_id, name, created_at, updated_at, access_level) "
            "VALUES ('legacy', 'legacy', 'Perfil principal', ?, ?, 'admin')",
            (now, now),
        )
        connection.execute(
            "UPDATE memories SET user_id = 'legacy' WHERE user_id IS NULL"
        )
        connection.execute(
            "UPDATE messages SET user_id = (SELECT user_id FROM conversations "
            "WHERE conversations.id = messages.conversation_id) "
            "WHERE EXISTS (SELECT 1 FROM conversations "
            "WHERE conversations.id = messages.conversation_id) "
            "AND user_id != (SELECT user_id FROM conversations "
            "WHERE conversations.id = messages.conversation_id)"
        )
        connection.execute(
            "UPDATE memories SET conversation_id = NULL WHERE conversation_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM conversations WHERE conversations.id = memories.conversation_id "
            "AND conversations.user_id = memories.user_id)"
        )
        connection.execute(
            "UPDATE memories SET project_id = NULL WHERE project_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM projects WHERE projects.id = memories.project_id "
            "AND projects.user_id = memories.user_id)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS conversations_id_user "
            "ON conversations(id, user_id)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS projects_id_user ON projects(id, user_id)"
        )
        if connection.execute(
            "SELECT 1 FROM memories WHERE consent_granted != 1 LIMIT 1"
        ).fetchone():
            raise MemoryStorageError(
                "A migração encontrou memórias sem consentimento explícito; "
                "o banco original foi preservado sem alterações"
            )

        connection.execute("ALTER TABLE messages RENAME TO messages_v3")
        connection.execute(
            """CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY(conversation_id, user_id)
                    REFERENCES conversations(id, user_id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            "INSERT INTO messages SELECT * FROM messages_v3"
        )
        connection.execute("DROP TABLE messages_v3")

        connection.execute("ALTER TABLE memories RENAME TO memories_v3")
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
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                conversation_id TEXT,
                project_id TEXT,
                category TEXT NOT NULL DEFAULT 'general',
                priority INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
                UNIQUE(user_id, kind, normalized_content),
                FOREIGN KEY(conversation_id, user_id)
                    REFERENCES conversations(id, user_id) ON DELETE CASCADE,
                FOREIGN KEY(project_id, user_id)
                    REFERENCES projects(id, user_id) ON DELETE CASCADE
            )"""
        )
        connection.execute(
            """INSERT INTO memories (
                id, kind, content, normalized_content, source, created_at, updated_at,
                confidence, relevance, consent_granted, provenance, expires_at, user_id,
                conversation_id, project_id, category, priority, is_active
            ) SELECT id, kind, content, normalized_content, source, created_at, updated_at,
                confidence, relevance, consent_granted, provenance, expires_at, user_id,
                conversation_id, project_id, category, priority, is_active FROM memories_v3"""
        )
        connection.execute("DROP TABLE memories_v3")
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
        connection = None
        try:
            connection = self._connect(read_only=True)
            yield connection
        except sqlite3.DatabaseError as exc:
            raise MemoryStorageError("Falha ao consultar o banco de memória", cause=exc) from exc
        finally:
            if connection is not None:
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

    @staticmethod
    def _coerce_kind(kind):
        if hasattr(kind, "value"):
            return str(kind.value)
        return str(kind)

    def list_tables(self):
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return [row[0] for row in rows]

    def _resolve_user_id(self, user_id):
        if user_id is None:
            user_id = "legacy"
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("user_id deve ser informado")
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT id FROM users WHERE id = ? OR profile_id = ?",
                (user_id, user_id),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("Perfil não encontrado")
        return row[0]

    def ensure_user(self, profile_id, *, name="Perfil", metadata=None):
        value = str(profile_id)
        if not value.strip():
            raise ValueError("profile_id não pode ficar vazio")
        now = _utc_now()
        with self._write_connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ? OR profile_id = ?",
                (value, value),
            ).fetchone()
            if row is None:
                user_id = value
                connection.execute(
                    "INSERT INTO users (id, profile_id, name, created_at, updated_at, metadata, access_level) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, value, str(name).strip() or "Perfil", now, now, json.dumps(metadata) if metadata is not None else None, "user"),
                )
                return self._record(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
            updated_name = str(name).strip() or row["name"]
            connection.execute(
                "UPDATE users SET name = ?, updated_at = ?, metadata = ? WHERE id = ?",
                (updated_name, now, json.dumps(metadata) if metadata is not None else row["metadata"], row["id"]),
            )
            return self._record(connection.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone())

    def get_user(self, profile_id):
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id = ? OR profile_id = ?",
                (profile_id, profile_id),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("Perfil não encontrado")
        return self._record(row)

    def list_users(self):
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM users ORDER BY created_at DESC"
            ).fetchall()
        return [self._record(row) for row in rows]

    def adopt_legacy_profile(self, profile_id, *, name):
        if not isinstance(profile_id, str) or not profile_id or profile_id == "legacy":
            raise ValueError("profile_id inválido para adoção")
        with self._read_connection() as connection:
            other_users = connection.execute(
                "SELECT id FROM users WHERE id NOT IN ('legacy', ?) LIMIT 1",
                (profile_id,),
            ).fetchone()
        if other_users is not None:
            return False
        profile = self.ensure_user(profile_id, name=name)
        tables = (
            "conversations", "messages", "memories", "projects", "preferences",
            "events", "personality_history", "permissions",
        )
        with self._write_connection() as connection:
            other_users = connection.execute(
                "SELECT id FROM users WHERE id NOT IN ('legacy', ?) LIMIT 1",
                (profile["id"],),
            ).fetchone()
            if other_users is not None:
                return False
            profile_has_data = any(
                connection.execute(
                    f"SELECT 1 FROM {table} WHERE user_id = ? LIMIT 1", (profile["id"],)
                ).fetchone()
                for table in tables
            )
            if profile_has_data:
                return False
            legacy_exists = connection.execute(
                "SELECT 1 FROM users WHERE id = 'legacy'"
            ).fetchone()
            if legacy_exists is None:
                return True
            connection.execute("PRAGMA defer_foreign_keys = ON")
            for table in tables:
                connection.execute(
                    f"UPDATE {table} SET user_id = ? WHERE user_id = 'legacy'",
                    (profile["id"],),
                )
            connection.execute("DELETE FROM users WHERE id = 'legacy'")
        return True

    def has_other_user_data(self, user_id):
        user_key = self._resolve_user_id(user_id)
        tables = (
            "conversations", "messages", "memories", "projects", "preferences",
            "events", "personality_history", "permissions",
        )
        with self._read_connection() as connection:
            for table in tables:
                if connection.execute(
                    f"SELECT 1 FROM {table} WHERE user_id != ? LIMIT 1", (user_key,)
                ).fetchone():
                    return True
        return False

    def create_conversation(
        self, user_id, title, *, summary=None, status="active", consent_granted=False
    ):
        if consent_granted is not True:
            raise ConsentRequiredError("A gravação de conversas exige consentimento explícito")
        user_key = self._resolve_user_id(user_id)
        conversation_id = uuid.uuid4().hex
        now = _utc_now()
        with self._write_connection() as connection:
            connection.execute(
                "INSERT INTO conversations (id, user_id, title, summary, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (conversation_id, user_key, str(title).strip(), summary, status, now, now),
            )
        return conversation_id

    def get_conversation(self, conversation_id, *, user_id="legacy"):
        user_key = self._resolve_user_id(user_id)
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_key),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("Conversa não encontrada")
        return self._record(row)

    def list_conversations(self, user_id="legacy"):
        query = "SELECT * FROM conversations WHERE user_id = ?"
        params = [self._resolve_user_id(user_id)]
        query += " ORDER BY updated_at DESC"
        with self._read_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._record(row) for row in rows]

    def add_message(
        self, conversation_id, user_id, role, content, *, metadata=None,
        consent_granted=False,
    ):
        if consent_granted is not True:
            raise ConsentRequiredError("A gravação de mensagens exige consentimento explícito")
        user_key = self._resolve_user_id(user_id)
        message_id = uuid.uuid4().hex
        now = _utc_now()
        with self._write_connection() as connection:
            conversation = connection.execute(
                "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
                (conversation_id, user_key),
            ).fetchone()
            if conversation is None:
                raise MemoryNotFoundError("Conversa não encontrada para este perfil")
            connection.execute(
                "INSERT INTO messages (id, conversation_id, user_id, role, content, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (message_id, conversation_id, user_key, role, content, now, json.dumps(metadata) if metadata is not None else None),
            )
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id),
            )
        return message_id

    def get_message(self, message_id, *, user_id="legacy"):
        user_key = self._resolve_user_id(user_id)
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM messages WHERE id = ? AND user_id = ?",
                (message_id, user_key),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("Mensagem não encontrada")
        return self._record(row)

    def list_messages(self, conversation_id, *, user_id="legacy", limit=100):
        user_key = self._resolve_user_id(user_id)
        self.get_conversation(conversation_id, user_id=user_key)
        with self._read_connection() as connection:
            rows = connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? AND user_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (conversation_id, user_key, limit),
            ).fetchall()
        return [self._record(row) for row in rows]

    def create_memory(
        self, user_id, *, kind, category="general", content, source="user",
        confidence=0.8, relevance=0.8, consent_granted=False, provenance="user_provided",
        project_id=None, conversation_id=None, expires_at=None, memory_id=None,
    ):
        if consent_granted is not True:
            raise ConsentRequiredError("A gravação exige consentimento explícito")
        user_key = self._resolve_user_id(user_id)
        normalized_kind = self._coerce_kind(kind)
        record = {
            "id": memory_id or uuid.uuid4().hex,
            "kind": normalized_kind,
            "content": str(content),
            "source": str(source),
            "confidence": float(confidence),
            "relevance": float(relevance),
            "consent_granted": True,
            "provenance": provenance,
            "expires_at": expires_at,
            "user_id": user_key,
            "project_id": project_id,
            "conversation_id": conversation_id,
            "category": category,
            "priority": 0,
            "is_active": 1,
        }
        now = _utc_now()
        with self._write_connection() as connection:
            connection.execute(
                """INSERT INTO memories (
                    id, kind, content, normalized_content, source, created_at, updated_at,
                    confidence, relevance, consent_granted, provenance, expires_at,
                    user_id, conversation_id, project_id, category, priority, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["id"], record["kind"], record["content"], _normalize(record["content"]),
                    record["source"], now, now, record["confidence"], record["relevance"],
                    1 if record["consent_granted"] else 0, record["provenance"], record["expires_at"],
                    record["user_id"], record["conversation_id"], record["project_id"],
                    record["category"], record["priority"], record["is_active"],
                ),
            )
        return record["id"]

    def get_memory(self, memory_id, *, user_id="legacy"):
        user_key = self._resolve_user_id(user_id)
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ? AND user_id = ?",
                (memory_id, user_key),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("Memória não encontrada")
        return self._record(row)

    def update_memory(self, memory_id, *, user_id="legacy", content=None, category=None, project_id=None, conversation_id=None,
                      relevance=None, confidence=None, expires_at=None, is_active=None, source=None,
                      consent_granted=False):
        if consent_granted is not True:
            raise ConsentRequiredError("A atualização exige consentimento explícito")
        user_key = self._resolve_user_id(user_id)
        current = self.get_memory(memory_id, user_id=user_key)
        now = _utc_now()
        next_content = current["content"] if content is None else str(content)
        next_source = current["source"] if source is None else str(source)
        next_category = current["category"] if category is None else str(category)
        next_project = current["project_id"] if project_id is None else project_id
        next_conversation = current["conversation_id"] if conversation_id is None else conversation_id
        next_relevance = current["relevance"] if relevance is None else float(relevance)
        next_confidence = current["confidence"] if confidence is None else float(confidence)
        next_expires = current["expires_at"] if expires_at is None else expires_at
        next_active = current["is_active"] if is_active is None else int(bool(is_active))
        with self._write_connection() as connection:
            cursor = connection.execute(
                """UPDATE memories SET content = ?, normalized_content = ?, source = ?, updated_at = ?,
                confidence = ?, relevance = ?, expires_at = ?, project_id = ?, conversation_id = ?,
                category = ?, is_active = ? WHERE id = ? AND user_id = ?""",
                (
                    next_content, _normalize(next_content), next_source, now, next_confidence,
                    next_relevance, next_expires, next_project, next_conversation, next_category,
                    next_active, memory_id, user_key,
                ),
            )
            if cursor.rowcount == 0:
                raise MemoryNotFoundError("Memória não encontrada")
        return self.get_memory(memory_id, user_id=user_key)

    def list_memories(self, user_id="legacy", *, kind=None, category=None, limit=50, include_expired=False):
        query = "SELECT * FROM memories WHERE user_id = ?"
        params = [self._resolve_user_id(user_id)]
        if kind is not None:
            query += " AND kind = ?"
            params.append(self._coerce_kind(kind))
        if category is not None:
            query += " AND category = ?"
            params.append(str(category))
        if not include_expired:
            query += " AND (expires_at IS NULL OR expires_at > ?)"
            params.append(_utc_now())
        query += " ORDER BY relevance DESC, confidence DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        with self._read_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._record(row) for row in rows]

    def delete_memory(self, memory_id, *, user_id="legacy"):
        user_key = self._resolve_user_id(user_id)
        with self._write_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE id = ? AND user_id = ?", (memory_id, user_key)
            )
            if cursor.rowcount == 0:
                raise MemoryNotFoundError("Memória não encontrada")
        return True

    def create_project(self, user_id, name, description="", *, status="active", priority=0,
                       due_at=None, consent_granted=False):
        if consent_granted is not True:
            raise ConsentRequiredError("A gravação de projetos exige consentimento explícito")
        user_key = self._resolve_user_id(user_id)
        project_id = uuid.uuid4().hex
        now = _utc_now()
        with self._write_connection() as connection:
            connection.execute(
                "INSERT INTO projects (id, user_id, name, description, status, priority, created_at, updated_at, due_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, user_key, str(name), description, status, int(priority), now, now, due_at),
            )
        return project_id

    def list_projects(self, user_id="legacy"):
        query = "SELECT * FROM projects WHERE user_id = ?"
        params = [self._resolve_user_id(user_id)]
        query += " ORDER BY updated_at DESC"
        with self._read_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._record(row) for row in rows]

    def set_preference(self, user_id, key, value, *, category="general", consent_granted=False):
        if consent_granted is not True:
            raise ConsentRequiredError("A gravação de preferências exige consentimento explícito")
        user_key = self._resolve_user_id(user_id)
        now = _utc_now()
        with self._write_connection() as connection:
            row = connection.execute(
                "SELECT * FROM preferences WHERE user_id = ? AND key = ?",
                (user_key, str(key)),
            ).fetchone()
            if row is None:
                preference_id = uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO preferences (id, user_id, key, value, category, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (preference_id, user_key, str(key), str(value), category, now, now),
                )
            else:
                connection.execute(
                    "UPDATE preferences SET value = ?, category = ?, updated_at = ? WHERE id = ?",
                    (str(value), category, now, row["id"]),
                )
        return self.list_preferences(user_key)

    def list_preferences(self, user_id="legacy"):
        query = "SELECT * FROM preferences WHERE user_id = ?"
        params = [self._resolve_user_id(user_id)]
        query += " ORDER BY updated_at DESC"
        with self._read_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._record(row) for row in rows]

    def create_event(self, user_id, event_type, title, description="", *, occurred_at=None,
                     relevant=True, metadata=None, consent_granted=False):
        if consent_granted is not True:
            raise ConsentRequiredError("A gravação de eventos exige consentimento explícito")
        user_key = self._resolve_user_id(user_id)
        event_id = uuid.uuid4().hex
        now = _utc_now()
        with self._write_connection() as connection:
            connection.execute(
                "INSERT INTO events (id, user_id, type, title, description, occurred_at, created_at, relevant, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, user_key, str(event_type), str(title), description, occurred_at or now, now, 1 if relevant else 0, json.dumps(metadata) if metadata is not None else None),
            )
        return event_id

    def list_events(self, user_id="legacy", *, limit=50):
        query = "SELECT * FROM events WHERE user_id = ?"
        params = [self._resolve_user_id(user_id)]
        query += " ORDER BY occurred_at DESC LIMIT ?"
        params.append(limit)
        with self._read_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._record(row) for row in rows]

    def record_personality_history(self, user_id, behavior, summary, *, source="system",
                                   consent_granted=False):
        if consent_granted is not True:
            raise ConsentRequiredError("A gravação do histórico exige consentimento explícito")
        user_key = self._resolve_user_id(user_id)
        history_id = uuid.uuid4().hex
        now = _utc_now()
        with self._write_connection() as connection:
            connection.execute(
                "INSERT INTO personality_history (id, user_id, behavior, summary, created_at, source) VALUES (?, ?, ?, ?, ?, ?)",
                (history_id, user_key, str(behavior), str(summary), now, str(source)),
            )
        return history_id

    def list_personality_history(self, user_id="legacy", *, limit=20):
        query = "SELECT * FROM personality_history WHERE user_id = ?"
        params = [self._resolve_user_id(user_id)]
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._read_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._record(row) for row in rows]

    def set_permission(self, user_id, permission, granted=True, *, scope="global", metadata=None):
        user_key = self._resolve_user_id(user_id)
        now = _utc_now()
        with self._write_connection() as connection:
            row = connection.execute(
                "SELECT * FROM permissions WHERE user_id = ? AND permission = ? AND scope = ?",
                (user_key, str(permission), str(scope)),
            ).fetchone()
            if row is None:
                permission_id = uuid.uuid4().hex
                connection.execute(
                    "INSERT INTO permissions (id, user_id, permission, granted, scope, created_at, updated_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (permission_id, user_key, str(permission), 1 if granted else 0, str(scope), now, now, json.dumps(metadata) if metadata is not None else None),
                )
            else:
                connection.execute(
                    "UPDATE permissions SET granted = ?, updated_at = ?, metadata = ? WHERE id = ?",
                    (1 if granted else 0, now, json.dumps(metadata) if metadata is not None else row["metadata"], row["id"]),
                )
        return self.list_permissions(user_key)

    def list_permissions(self, user_id="legacy"):
        query = "SELECT * FROM permissions WHERE user_id = ?"
        params = [self._resolve_user_id(user_id)]
        query += " ORDER BY updated_at DESC"
        with self._read_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._record(row) for row in rows]

    def insert(self, record):
        if record.get("consent_granted") is not True:
            raise ConsentRequiredError("A gravação exige consentimento explícito")
        user_key = self._resolve_user_id(record.get("user_id", "legacy"))
        now = _utc_now()
        with self._write_connection() as connection:
            connection.execute(
                """INSERT INTO memories (
                    id, kind, content, normalized_content, source, created_at, updated_at,
                    confidence, relevance, consent_granted, provenance, expires_at,
                    user_id, conversation_id, project_id, category, priority, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["id"], record["kind"], record["content"],
                    _normalize(record["content"]), record["source"], now, now,
                    record["confidence"], record["relevance"],
                    1, record["provenance"], record.get("expires_at"), user_key,
                    record.get("conversation_id"), record.get("project_id"),
                    record.get("category", "general"), record.get("priority", 0),
                    1 if record.get("is_active", 1) else 0,
                ),
            )
        return self.get(record["id"], user_id=user_key)

    def get(self, memory_id, *, user_id="legacy"):
        user_key = self._resolve_user_id(user_id)
        with self._read_connection() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ? AND user_id = ?",
                (memory_id, user_key),
            ).fetchone()
        if row is None:
            raise MemoryNotFoundError("Memória não encontrada")
        return self._record(row)

    def find_duplicate(self, kind, content, *, user_id="legacy", exclude_id=None):
        user_key = self._resolve_user_id(user_id)
        sql = "SELECT * FROM memories WHERE user_id = ? AND kind = ? AND normalized_content = ?"
        values = [user_key, kind, _normalize(content)]
        if exclude_id is not None:
            sql += " AND id != ?"
            values.append(exclude_id)
        with self._read_connection() as connection:
            row = connection.execute(sql, values).fetchone()
        return self._record(row)

    def search(self, *, user_id="legacy", kind=None, terms=(), limit=100):
        user_key = self._resolve_user_id(user_id)
        sql = "SELECT * FROM memories WHERE user_id = ? AND (expires_at IS NULL OR expires_at > ?)"
        clauses = []
        values = [user_key, _utc_now()]
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

    def update(self, memory_id, *, user_id="legacy", content, source, confidence,
               relevance, consent=False, provenance=None, expires_at=None):
        if consent is not True:
            raise ConsentRequiredError("A atualização exige consentimento explícito")
        user_key = self._resolve_user_id(user_id)
        with self._write_connection() as connection:
            cursor = connection.execute(
                """UPDATE memories SET content = ?, normalized_content = ?, source = ?,
                    updated_at = ?, confidence = ?, relevance = ?, provenance = ?, expires_at = ?
                          WHERE id = ? AND user_id = ?""",
                (content, _normalize(content), source, _utc_now(), confidence, relevance,
                      provenance, expires_at, memory_id, user_key),
            )
            if cursor.rowcount == 0:
                raise MemoryNotFoundError("Memória não encontrada")
        return self.get(memory_id, user_id=user_key)

    def purge_expired(self, *, user_id=None):
        now = _utc_now()
        user_key = self._resolve_user_id(user_id) if user_id is not None else None
        with self._write_connection() as connection:
            if user_key is None:
                cursor = connection.execute(
                    "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?",
                    (now,),
                )
            else:
                cursor = connection.execute(
                    "DELETE FROM memories WHERE user_id = ? AND expires_at IS NOT NULL "
                    "AND expires_at <= ?",
                    (user_key, now),
                )
        return cursor.rowcount

    def delete(self, memory_id, *, user_id="legacy"):
        user_key = self._resolve_user_id(user_id)
        with self._write_connection() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE id = ? AND user_id = ?",
                (memory_id, user_key),
            )
            if cursor.rowcount == 0:
                raise MemoryNotFoundError("Memória não encontrada")
        return True

    def backup_to(self, destination, *, user_id=None):
        user_key = self._resolve_user_id(user_id) if user_id is not None else None
        destination = validate_storage_path(destination, label="backup de memória")
        if destination == self.path:
            raise MemoryStorageError("O destino do backup deve ser outro arquivo")
        try:
            directory_fd = _open_storage_directory(
                destination.parent, create=True
            )
            os.close(directory_fd)
        except OSError as exc:
            raise MemoryStorageError(
                "Não foi possível proteger o diretório do backup da memória", cause=exc
            ) from exc
        temporary = None
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
            )
            temporary = Path(temporary_name)
            try:
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
            with self._read_connection() as source, closing(sqlite3.connect(str(temporary))) as target:
                target.execute("PRAGMA foreign_keys = ON")
                source.backup(target)
                if user_key is not None:
                    target.execute("BEGIN IMMEDIATE")
                    target.execute("DELETE FROM users WHERE id != ?", (user_key,))
                target.commit()
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise sqlite3.DatabaseError("backup integrity check failed")
                if target.execute("PRAGMA foreign_key_check").fetchall():
                    raise sqlite3.DatabaseError("backup foreign key check failed")

            with temporary.open("rb") as backup_file:
                os.fsync(backup_file.fileno())
            os.link(temporary, destination, follow_symlinks=False)
            temporary.unlink()
            return destination
        except (OSError, sqlite3.DatabaseError, MemoryStorageError) as exc:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise MemoryStorageError("Não foi possível criar o backup da memória", cause=exc) from exc

    def restore_from(self, source, *, user_id=None, keep_backup=True):
        user_key = self._resolve_user_id(user_id) if user_id is not None else None
        if user_key is not None and self.has_other_user_data(user_key):
            raise MemoryStorageError(
                "Restauração recusada: o arquivo atual contém dados de outro perfil"
            )
        source = validate_storage_path(source, label="restauração do banco de memória")
        if source == self.path:
            raise MemoryStorageError("A origem da restauração deve ser outro arquivo")
        temporary = None
        backup_target = None
        replaced = False
        try:
            with closing(self._connect_file(source, read_only=True)) as source_db:
                integrity = source_db.execute("PRAGMA quick_check").fetchone()[0]
                foreign_key_errors = source_db.execute(
                    "PRAGMA foreign_key_check"
                ).fetchall()
                application_id = source_db.execute("PRAGMA application_id").fetchone()[0]
                version = source_db.execute("PRAGMA user_version").fetchone()[0]
                if integrity != "ok" or foreign_key_errors or application_id != APPLICATION_ID:
                    raise MemoryStorageError("O arquivo de restauração não é um backup válido da Nova")
                if version not in (1, 2, 3, SCHEMA_VERSION):
                    raise MemoryStorageError("Versão do backup não suportada")

                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=self.path.parent,
                    prefix=f".{self.path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    os.fchmod(handle.fileno(), 0o600)
                with closing(sqlite3.connect(str(temporary), timeout=2.0)) as candidate_db:
                    source_db.backup(candidate_db)
                    candidate_db.commit()
            candidate_storage = MemoryStorage(temporary)
            if user_key is not None:
                try:
                    candidate_storage._resolve_user_id(user_key)
                except MemoryNotFoundError:
                    if not candidate_storage.adopt_legacy_profile(user_key, name=user_key):
                        raise MemoryStorageError("O backup não pertence a este perfil")
                with candidate_storage._write_connection() as connection:
                    connection.execute("DELETE FROM users WHERE id != ?", (user_key,))
            if candidate_storage.health_snapshot()["status"] != "healthy":
                raise MemoryStorageError("O backup não passou na verificação de integridade")

            if self.path.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
                backup_dir = self.path.parent / "backups"
                backup_target = backup_dir / (
                    f"{self.path.stem}-pre-restore-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3"
                )
                self.backup_to(backup_target, user_id=user_key)

            directory_fd = _open_storage_directory(self.path.parent)
            try:
                os.replace(
                    temporary.name, self.path.name,
                    src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                )
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            temporary = None
            replaced = True
            if self.health_snapshot()["status"] != "healthy":
                raise MemoryStorageError(
                    "O banco restaurado não passou na verificação de integridade"
                )
            if not keep_backup and backup_target is not None:
                backup_target.unlink(missing_ok=True)
                backup_target = None
            self.corrupt_backup_path = None
            return self.path
        except (OSError, sqlite3.DatabaseError, MemoryStorageError, ValueError) as exc:
            if replaced and backup_target is not None and backup_target.exists():
                try:
                    os.replace(backup_target, self.path)
                    backup_target = None
                except OSError as rollback_error:
                    exc = MemoryStorageError(
                        "A restauração falhou e a cópia anterior permanece em "
                        f"{backup_target}; não foi possível revertê-la",
                        cause=rollback_error,
                    )
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)
            raise MemoryStorageError("Não foi possível restaurar o backup da memória", cause=exc) from exc

    def create_managed_backup(self, backup_dir=None, *, retain=10, max_age_days=90,
                              user_id=None):
        backup_dir = Path(backup_dir) if backup_dir is not None else self.path.parent / "backups"
        backup_dir = validate_storage_path(backup_dir, label="diretório de backups")
        ensure_private_directory(backup_dir, label="diretório de backups")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        destination = backup_dir / f"{self.path.stem}-{stamp}-{uuid.uuid4().hex[:8]}.sqlite3"
        created = self.backup_to(destination, user_id=user_id)
        self.rotate_backups(backup_dir, retain=retain, max_age_days=max_age_days)
        return created

    def rotate_backups(self, backup_dir=None, *, retain=10, max_age_days=90, now=None):
        if type(retain) is not int or not 1 <= retain <= 100:
            raise ValueError("retain deve estar entre 1 e 100")
        if type(max_age_days) is not int or not 1 <= max_age_days <= 3650:
            raise ValueError("max_age_days deve estar entre 1 e 3650")
        backup_dir = Path(backup_dir) if backup_dir is not None else self.path.parent / "backups"
        backup_dir = validate_storage_path(backup_dir, label="diretório de backups")
        if not backup_dir.exists():
            return []
        now = now or datetime.now(timezone.utc).timestamp()
        candidates = []
        pattern = f"{self.path.stem}-*.sqlite3"
        for path in backup_dir.glob(pattern):
            try:
                validate_storage_path(path, label="backup de memória")
                mode = path.lstat().st_mode
            except OSError:
                continue
            if not stat.S_ISREG(mode):
                continue
            candidates.append((path, path.stat().st_mtime))
        candidates.sort(key=lambda item: item[1], reverse=True)
        cutoff = now - max_age_days * 86400
        removed = []
        for index, (path, modified_at) in enumerate(candidates):
            if modified_at < cutoff or index >= retain:
                path.unlink()
                removed.append(path)
        return removed

    def list_managed_backups(self, backup_dir=None, *, limit=10):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit deve estar entre 1 e 100")
        backup_dir = Path(backup_dir) if backup_dir is not None else self.path.parent / "backups"
        backup_dir = validate_storage_path(backup_dir, label="diretório de backups")
        if not backup_dir.exists():
            return []
        candidates = []
        for path in backup_dir.glob(f"{self.path.stem}-*.sqlite3"):
            try:
                validate_storage_path(path, label="backup de memória")
                if stat.S_ISREG(path.lstat().st_mode):
                    candidates.append((path, path.stat().st_mtime))
            except OSError:
                continue
        candidates.sort(key=lambda item: item[1], reverse=True)
        return [path for path, _modified_at in candidates[:limit]]

    def count_expired(self, *, user_id=None):
        with self._read_connection() as connection:
            query = "SELECT COUNT(*) FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?"
            params = [_utc_now()]
            if user_id is not None:
                query += " AND user_id = ?"
                params.append(self._resolve_user_id(user_id))
            return connection.execute(query, params).fetchone()[0]

    def health_snapshot(self):
        path = self.path
        try:
            file_stat = path.stat() if path.exists() else None
        except OSError:
            file_stat = None
        tables = []
        data = {
            "database_path": str(path),
            "schema_version": SCHEMA_VERSION,
            "database_size_bytes": file_stat.st_size if file_stat is not None else 0,
            "modified_at": file_stat.st_mtime if file_stat is not None else None,
            "is_writable": bool(
                path.exists() and os.access(path, os.W_OK)
                or path.parent.exists() and os.access(path.parent, os.W_OK)
            ),
            "tables": tables,
            "corrupt_backup_preserved": self.corrupt_backup_path is not None,
            "integrity_check": "unknown",
            "user_version": 0,
            "application_id": 0,
            "status": "unknown",
        }
        try:
            with self._read_connection() as connection:
                tables = [
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                    ).fetchall()
                ]
                data["tables"] = tables
                data["integrity_check"] = connection.execute("PRAGMA quick_check").fetchone()[0]
                data["user_version"] = connection.execute("PRAGMA user_version").fetchone()[0]
                data["application_id"] = connection.execute("PRAGMA application_id").fetchone()[0]
        except (sqlite3.DatabaseError, OSError, MemoryStorageError):
            data["status"] = "degraded"
            return data

        data["status"] = "healthy" if (
            data["integrity_check"] == "ok"
            and data["application_id"] == APPLICATION_ID
            and data["user_version"] == SCHEMA_VERSION
        ) else "degraded"
        return data

    def export_json(self, destination, *, kind=None, user_id="legacy"):
        user_key = self._resolve_user_id(user_id)
        destination = validate_storage_path(destination, label="exportação de memória")
        ensure_private_directory(destination.parent, label="diretório da exportação de memória")
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
                sql = "SELECT * FROM memories WHERE user_id = ? AND " \
                    "(expires_at IS NULL OR expires_at > ?)"
                values = (user_key, _utc_now())
                if kind is not None:
                    sql += " AND kind = ?"
                    values = (user_key, _utc_now(), kind)
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
