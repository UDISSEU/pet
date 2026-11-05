"""Testes da memória persistente usando apenas bancos temporários locais."""

import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
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


if __name__ == "__main__":
    unittest.main()
