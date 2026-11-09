"""Testes da memória persistente usando apenas bancos temporários locais."""

import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import threading
import unittest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nova_ai.memory import (
    EpisodicMemory,
    MemoryKind,
    MemoryManager,
    MemoryStorage,
    PreferenceMemory,
    ProceduralMemory,
    SemanticMemory,
)
from nova_ai.memory.errors import (
    ConsentRequiredError,
    DuplicateMemoryError,
    MemoryNotFoundError,
    SensitiveInformationError,
)


class MemorySystemTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "nova-memory.sqlite3"
        self.manager = MemoryManager(MemoryStorage(self.database))

    def tearDown(self):
        self.temporary.cleanup()

    def test_sqlite_schema_supports_full_local_memory_model(self):
        storage = self.manager.storage
        user = storage.ensure_user("profile-alpha", name="Alice")
        project_id = storage.create_project(
            user["profile_id"], "Nova IA", "Ajustes e memória local.", status="active"
        )
        conversation_id = storage.create_conversation(
            user["profile_id"], "Sessão 1", summary="Resumo inicial"
        )
        message_id = storage.add_message(
            conversation_id, user["profile_id"], "user", "Quero preferências discretas."
        )
        memory_id = storage.create_memory(
            user["profile_id"], kind="preference", category="communication",
            content="Preferência: notificações discretas.", source="user",
            confidence=0.96, relevance=0.9, consent_granted=True,
            provenance="user_provided", project_id=project_id,
            conversation_id=conversation_id,
        )
        self.assertEqual(storage.get_user(user["profile_id"])["name"], "Alice")
        self.assertEqual(storage.get_message(message_id)["role"], "user")
        self.assertEqual(storage.get_memory(memory_id)["category"], "communication")
        self.assertEqual(storage.list_conversations(user["profile_id"])[0]["title"], "Sessão 1")
        self.assertEqual(storage.list_projects(user["profile_id"])[0]["name"], "Nova IA")
        storage.set_preference(user["profile_id"], "communication.style", "discreet")
        self.assertTrue(storage.list_preferences(user["profile_id"]))

    def test_consent_is_required_and_preference_is_not_saved_without_it(self):
        preferences = PreferenceMemory(self.manager)
        with self.assertRaises(ConsentRequiredError):
            self.manager.storage.insert({
                "id": "unchecked", "kind": "preference", "content": "silent",
                "source": "user", "confidence": 1.0, "relevance": 1.0,
            })
        with self.assertRaises(ConsentRequiredError):
            preferences.set_preference(
                "Você prefere notificações discretas.", consent_confirmed=False
            )
        self.assertEqual(self.manager.search("notificações"), [])

        saved = preferences.set_preference(
            "Você prefere notificações discretas.", consent_confirmed=True
        )
        self.assertEqual(saved.kind, MemoryKind.PREFERENCE)
        self.assertTrue(saved.consent_granted)
        found = preferences.recall("Como prefiro minhas notificações?")
        self.assertEqual(found[0].content, "Você prefere notificações discretas.")

    def test_persists_across_manager_restart_with_type_source_and_dates(self):
        record = SemanticMemory(self.manager).add_fact(
            "A Nova funciona offline.", source="user-confirmed", consent=True,
            confidence=0.95, relevance=0.7,
        )
        reopened = MemoryManager(MemoryStorage(self.database))
        loaded = reopened.get(record.memory_id)
        self.assertEqual(loaded.content, "A Nova funciona offline.")
        self.assertEqual(loaded.kind, MemoryKind.SEMANTIC)
        self.assertEqual(loaded.source, "user-confirmed")
        self.assertEqual(loaded.confidence, 0.95)
        self.assertEqual(loaded.relevance, 0.7)
        self.assertTrue(loaded.created_at)
        self.assertTrue(loaded.updated_at)

    def test_all_user_categories_preserve_provenance_and_expiration(self):
        for kind in ("profile", "project", "conversation", "learning"):
            with self.subTest(kind=kind):
                saved = self.manager.add(
                    kind, f"Projeto {kind}: preferência local", consent=True,
                    provenance="user_provided", expires_in_days=30,
                )
                self.assertEqual(saved.kind.value, kind)
                self.assertEqual(saved.provenance, "user_provided")
                self.assertIsNotNone(saved.expires_at)
        uncertain = self.manager.add(
            "learning", "Talvez o usuário prefira temas claros.", consent=True,
            provenance="uncertain",
        )
        self.assertEqual(self.manager.get(uncertain.memory_id).provenance, "uncertain")

    def test_expired_records_are_hidden_and_purged(self):
        saved = self.manager.add(
            "conversation", "Reunião temporária amanhã", consent=True,
            expires_in_days=1,
        )
        self.manager.storage.update(
            saved.memory_id, content=saved.content, source=saved.source,
            confidence=saved.confidence, relevance=saved.relevance, consent=True,
            provenance=saved.provenance, expires_at="2000-01-01T00:00:00+00:00",
        )
        self.assertEqual(self.manager.search("reunião temporária"), [])
        self.assertEqual(self.manager.storage.purge_expired(), 1)

    def test_update_changes_provenance_and_expiration_after_explicit_consent(self):
        saved = self.manager.add("project", "Projeto Nova: ativo", consent=True)
        updated = self.manager.update(
            saved.memory_id, content="Projeto Nova: pausado", consent=True,
            provenance="user_provided", expires_in_days=14,
        )
        self.assertEqual(updated.provenance, "user_provided")
        self.assertIsNotNone(updated.expires_at)

    def test_conflict_detection_suggests_same_subject_without_overwriting(self):
        saved = self.manager.add("profile", "Cidade: Belém", consent=True)
        conflicts = self.manager.find_conflicts("profile", "Cidade: Manaus")
        self.assertEqual([row.memory_id for row in conflicts], [saved.memory_id])
        self.assertEqual(self.manager.get(saved.memory_id).content, "Cidade: Belém")

    def test_schema_v1_is_migrated_without_losing_existing_memory(self):
        legacy = self.root / "legacy-v1.sqlite3"
        connection = sqlite3.connect(legacy)
        connection.executescript("""
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL CHECK(kind IN ('episodic','semantic','procedural','preference')),
                content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 8000),
                normalized_content TEXT NOT NULL,
                source TEXT NOT NULL CHECK(length(source) BETWEEN 1 AND 128),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
                relevance REAL NOT NULL CHECK(relevance BETWEEN 0 AND 1),
                consent_granted INTEGER NOT NULL CHECK(consent_granted = 1),
                UNIQUE(kind, normalized_content)
            );
            INSERT INTO memories VALUES (
                'legacy', 'semantic', 'Nova funciona offline', 'nova funciona offline',
                'user', '2025-01-01T00:00:00+00:00', '2025-01-01T00:00:00+00:00',
                0.8, 0.8, 1
            );
            PRAGMA application_id = 1313822273;
            PRAGMA user_version = 1;
        """)
        connection.close()
        migrated = MemoryManager(MemoryStorage(legacy))
        record = migrated.get("legacy")
        self.assertEqual(record.content, "Nova funciona offline")
        self.assertEqual(record.provenance, "user_provided")
        self.assertIsNone(record.expires_at)
        self.assertEqual(migrated.add("project", "Projeto X", consent=True).kind.value, "project")

    def test_all_memory_categories_are_supported_without_executing_procedures(self):
        episodic = EpisodicMemory(self.manager).record_event(
            "A Nova concluiu uma sessão de foco.", consent=True
        )
        semantic = SemanticMemory(self.manager).add_fact("A Nova é local.", consent=True)
        procedural = ProceduralMemory(self.manager).add_procedure(
            "Antes de organizar arquivos, mostrar uma prévia.", consent=True
        )
        self.assertEqual(
            {episodic.kind, semantic.kind, procedural.kind},
            {MemoryKind.EPISODIC, MemoryKind.SEMANTIC, MemoryKind.PROCEDURAL},
        )
        self.assertEqual(len(self.manager.search("prévia", kind="procedural")), 1)

    def test_duplicate_detection_is_type_scoped_and_normalizes_case_spacing(self):
        original = self.manager.add(
            "preference", "Notificações discretas", consent=True
        )
        duplicate = self.manager.add(
            "preference", "  NOTIFICAÇÕES   DISCRETAS ", consent=True
        )
        self.assertEqual(original.memory_id, duplicate.memory_id)
        self.assertEqual(len(self.manager.search("notificações")), 1)
        self.assertIsNotNone(self.manager.find_duplicate("preference", "notificações discretas"))
        other_type = self.manager.add("semantic", "Notificações discretas", consent=True)
        self.assertNotEqual(original.memory_id, other_type.memory_id)

    def test_update_changes_content_metadata_and_rejects_collision(self):
        first = self.manager.add("semantic", "Nova usa janela desktop.", consent=True)
        second = self.manager.add("semantic", "Nova tem animações.", consent=True)
        updated = self.manager.update(
            first.memory_id, content="Nova usa interface desktop.", source="confirmed",
            confidence=0.9, relevance=0.95, consent=True,
        )
        self.assertEqual(updated.source, "confirmed")
        self.assertEqual(updated.confidence, 0.9)
        self.assertEqual(updated.relevance, 0.95)
        with self.assertRaises(DuplicateMemoryError):
            self.manager.update(
                first.memory_id, content=second.content, consent=True
            )
        with self.assertRaises(ConsentRequiredError):
            self.manager.update(first.memory_id, relevance=0.1)

    def test_search_filters_by_type_and_orders_by_relevance(self):
        low = self.manager.add(
            "semantic", "Notificações discretas são agradáveis.", consent=True,
            relevance=0.3, confidence=0.5,
        )
        high = self.manager.add(
            "preference", "Notificações discretas são importantes.", consent=True,
            relevance=0.9, confidence=1.0,
        )
        results = self.manager.search_scored("notificacoes discretas", limit=10)
        self.assertEqual(results[0].memory.memory_id, high.memory_id)
        self.assertEqual(
            [item.kind for item in self.manager.search("discretas", kind="preference")],
            [MemoryKind.PREFERENCE],
        )
        self.assertNotEqual(low.memory_id, high.memory_id)

    def test_delete_requires_an_existing_record_and_removes_it(self):
        record = self.manager.add("episodic", "Conversa autorizada.", consent=True)
        self.assertTrue(self.manager.delete(record.memory_id))
        with self.assertRaises(MemoryNotFoundError):
            self.manager.get(record.memory_id)
        with self.assertRaises(MemoryNotFoundError):
            self.manager.delete(record.memory_id)

    def test_credential_like_values_are_rejected(self):
        for text in (
            "senha: segredo123",
            "Minha API key é abcdef123456",
            "Bearer abc.def.ghi",
            "-----BEGIN PRIVATE KEY-----",
            "sk-" + "a" * 24,
        ):
            with self.subTest(text=text), self.assertRaises(SensitiveInformationError):
                self.manager.add("semantic", text, consent=True)
        self.assertEqual(self.manager.search(), [])

    def test_backup_can_be_reopened_and_json_export_is_readable(self):
        record = self.manager.add("preference", "Notificações discretas.", consent=True)
        backup = self.root / "backup" / "memory-copy.sqlite3"
        self.manager.backup(backup)
        restored = MemoryManager(MemoryStorage(backup))
        self.assertEqual(restored.get(record.memory_id).content, record.content)

        export = self.root / "export" / "memory.json"
        self.manager.export_json(export, kind=MemoryKind.PREFERENCE)
        document = json.loads(export.read_text(encoding="utf-8"))
        self.assertEqual(document["format_version"], 1)
        self.assertEqual(document["memories"][0]["id"], record.memory_id)
        self.assertEqual(document["memories"][0]["kind"], "preference")

    def test_corrupt_database_is_preserved_and_store_recovers_empty(self):
        corrupt = self.root / "corrupt.sqlite3"
        contents = b"this is not a sqlite database"
        corrupt.write_bytes(contents)
        storage = MemoryStorage(corrupt)
        self.assertIsNotNone(storage.corrupt_backup_path)
        self.assertEqual(storage.corrupt_backup_path.read_bytes(), contents)
        manager = MemoryManager(storage)
        saved = manager.add("semantic", "Banco recuperado.", consent=True)
        self.assertEqual(manager.get(saved.memory_id).content, "Banco recuperado.")

    def test_refuses_to_modify_an_unrelated_existing_sqlite_database(self):
        from nova_ai.memory.errors import MemoryStorageError

        unrelated = self.root / "unrelated.sqlite3"
        with sqlite3.connect(unrelated) as connection:
            connection.execute("CREATE TABLE application_data (value TEXT)")
            connection.execute("INSERT INTO application_data VALUES ('keep')")
        with self.assertRaises(MemoryStorageError):
            MemoryStorage(unrelated)
        with sqlite3.connect(unrelated) as connection:
            self.assertEqual(
                connection.execute("SELECT value FROM application_data").fetchone()[0],
                "keep",
            )
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        self.assertEqual(tables, {"application_data"})

    def test_offline_process_can_write_and_retrieve_without_provider_or_network(self):
        script = """
import sys, urllib.request
urllib.request.urlopen = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('network used'))
from nova_ai.memory import MemoryManager, MemoryStorage
manager = MemoryManager(MemoryStorage(sys.argv[1]))
record = manager.add('preference', 'Notificações discretas.', consent=True)
assert manager.search('notificacoes')[0].memory_id == record.memory_id
assert not any(name == 'providers' or name.startswith('providers.') for name in sys.modules)
"""
        env = dict(os.environ, PYTHONPATH=str(SRC))
        subprocess.run(
            [sys.executable, "-c", script, str(self.root / "offline.sqlite3")],
            cwd=SRC.parent, env=env, check=True, capture_output=True, text=True,
        )

    def test_concurrent_writes_coalesce_duplicate_memory_records(self):
        manager = MemoryManager(MemoryStorage(self.root / "concurrent.sqlite3"))
        errors = []

        def worker():
            try:
                manager.add("profile", "Preferência de foco: silêncio.", consent=True)
            except Exception as exc:  # pragma: no cover - aggregate failure diagnostics
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertFalse(errors)
        self.assertEqual(len(manager.search("silêncio", kind="profile")), 1)

    def test_backup_restore_round_trip_and_health_snapshot(self):
        primary = MemoryManager(MemoryStorage(self.root / "primary.sqlite3"))
        record = primary.add("semantic", "A Nova preserva o histórico local.", consent=True)

        backup = self.root / "backups" / "memory-backup.sqlite3"
        primary.backup(backup)

        restored_path = self.root / "restored.sqlite3"
        restored = MemoryStorage(restored_path)
        restored.restore_from(backup)

        reopened = MemoryManager(restored)
        self.assertEqual(reopened.get(record.memory_id).content, record.content)
        self.assertEqual(reopened.get(record.memory_id).kind.value, "semantic")

        snapshot = reopened.health_snapshot()
        self.assertEqual(snapshot["schema_version"], 3)
        self.assertGreaterEqual(snapshot["database_size_bytes"], 1)
        self.assertIn("memories", snapshot["tables"])

    def test_restore_rejects_unrelated_database_without_changing_live_data(self):
        storage = MemoryStorage(self.root / "active.sqlite3")
        manager = MemoryManager(storage)
        record = manager.add("semantic", "Banco ativo permanece protegido.", consent=True)
        invalid_backup = self.root / "unrelated.sqlite3"
        with sqlite3.connect(invalid_backup) as connection:
            connection.execute("CREATE TABLE unrelated (value TEXT)")
            connection.execute("INSERT INTO unrelated VALUES ('not Nova')")

        from nova_ai.memory.errors import MemoryStorageError
        with self.assertRaises(MemoryStorageError):
            storage.restore_from(invalid_backup)

        self.assertEqual(manager.get(record.memory_id).content, record.content)

    def test_managed_backup_rotation_retains_count_and_ignores_other_files(self):
        storage = MemoryStorage(self.root / "retention.sqlite3")
        backup_dir = self.root / "backups"
        other_file = backup_dir / "unrelated.sqlite3"
        backup_dir.mkdir()
        other_file.write_text("keep", encoding="utf-8")

        created = [
            storage.create_managed_backup(backup_dir, retain=10, max_age_days=90)
            for _ in range(3)
        ]
        aged_backup = backup_dir / "retention-aged.sqlite3"
        storage.backup_to(aged_backup)
        os.utime(aged_backup, (0, 0))
        linked_backup = backup_dir / "retention-linked.sqlite3"
        linked_backup.symlink_to(other_file)
        removed = storage.rotate_backups(backup_dir, retain=2, max_age_days=90)

        retained = storage.list_managed_backups(backup_dir, limit=10)
        self.assertEqual(len(retained), 2)
        self.assertEqual(len(removed), 2)
        self.assertIn(aged_backup, removed)
        self.assertTrue(all(path.exists() for path in created if path not in removed))
        self.assertEqual(other_file.read_text(encoding="utf-8"), "keep")
        self.assertTrue(linked_backup.is_symlink())

    def test_maintenance_report_is_read_only_until_maintenance_runs(self):
        manager = MemoryManager(MemoryStorage(self.root / "maintenance.sqlite3"))
        record = manager.add(
            "learning", "A Nova deve observar as preferências do usuário.",
            consent=True, expires_in_days=1,
        )
        manager.storage.update(
            record.memory_id, content=record.content, source=record.source,
            confidence=record.confidence, relevance=record.relevance, consent=True,
            provenance=record.provenance, expires_at="2000-01-01T00:00:00+00:00",
        )

        report = manager.maintenance_report()
        self.assertIn("database", report)
        self.assertIn("tables", report["database"])
        self.assertIn("backup_dir", report)
        self.assertTrue(report["database"]["is_writable"])
        self.assertEqual(report["expired_records_pending"], 1)
        self.assertEqual(manager.storage.count_expired(), 1)

        result = manager.run_maintenance(create_backup=True, retain=2, max_age_days=90)
        self.assertEqual(result["expired_records_purged"], 1)
        self.assertTrue(Path(result["backup_created"]).is_file())
        self.assertEqual(manager.storage.count_expired(), 0)

    def test_health_diagnostic_does_not_recreate_a_missing_database(self):
        storage = MemoryStorage(self.root / "removed.sqlite3")
        storage.path.unlink()

        snapshot = storage.health_snapshot()

        self.assertEqual(snapshot["status"], "degraded")
        self.assertFalse(storage.path.exists())


if __name__ == "__main__":
    unittest.main()
