"""Lembretes locais simples, persistentes e canceláveis pelo mesmo módulo."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid

from .base import Tool
from .results import ActionResult


class ReminderStore:
    def __init__(self, path=None):
        self._lock = threading.RLock()
        self._custom_path = path is not None
        self.path = Path(path) if path else (
            Path.home() / ".local/share/nova_ai/reminders.json"
        )

    def list(self):
        with self._lock:
            return self._list()

    def _list(self):
        self._ensure_safe_path()
        if self.path.is_symlink():
            raise ValueError("Arquivo de lembretes não pode ser link simbólico")
        if self.path.exists() and self.path.stat().st_size > 2_000_000:
            raise ValueError("Arquivo de lembretes excede o limite")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if not isinstance(data, list) or any(not self._valid(row) for row in data):
            raise ValueError("Armazenamento de lembretes inválido; dados preservados")
        return data

    def create(self, text, due_at):
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 500:
            raise ValueError("Texto do lembrete inválido")
        if not isinstance(due_at, str) or len(due_at) > 40:
            raise ValueError("Data do lembrete inválida")
        due = datetime.fromisoformat(due_at)
        if due.tzinfo is None:
            raise ValueError("Data deve conter fuso horário")
        row = {"id": uuid.uuid4().hex, "text": text.strip(),
               "due_at": due.astimezone(timezone.utc).isoformat(timespec="seconds"),
               "status": "active"}
        with self._lock:
            rows = self._list()
            if len(rows) >= 1_000:
                raise ValueError("Limite local de lembretes atingido")
            rows.append(row)
            self._save(rows)
        return row

    def cancel(self, reminder_id):
        with self._lock:
            rows = self._list()
            found = False
            for row in rows:
                if row["id"] == reminder_id and row["status"] == "active":
                    row["status"] = "cancelled"
                    found = True
            if not found:
                raise KeyError("Lembrete ativo não encontrado")
            self._save(rows)

    def reactivate(self, reminder_id):
        with self._lock:
            rows = self._list()
            found = False
            for row in rows:
                if row["id"] == reminder_id and row["status"] == "cancelled":
                    row["status"] = "active"
                    found = True
            if not found:
                raise KeyError("Lembrete cancelado não encontrado")
            self._save(rows)

    def _save(self, rows):
        self._ensure_safe_path()
        if self.path.is_symlink():
            raise ValueError("Arquivo de lembretes não pode ser link simbólico")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".reminders-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(rows, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _valid(row):
        return (isinstance(row, dict) and set(row) == {"id", "text", "due_at", "status"}
                and isinstance(row["id"], str) and isinstance(row["text"], str)
                and isinstance(row["due_at"], str)
                and isinstance(row["status"], str)
                and row["status"] in {"active", "cancelled"})

    def _ensure_safe_path(self):
        if self._custom_path:
            return
        home = Path.home().resolve()
        parent = self.path.parent.resolve()
        if parent != home and home not in parent.parents:
            raise ValueError("Armazenamento de lembretes deve permanecer na pasta pessoal")


class ReminderListTool(Tool):
    name = "reminders.list"
    description = "Lista lembretes locais sem modificá-los."

    def __init__(self, store=None):
        self.store = store or ReminderStore()

    def execute(self, arguments):
        if arguments:
            raise ValueError("A lista não aceita argumentos")
        rows = self.store.list()
        return ActionResult(True, f"{len(rows)} lembrete(s) registrados.", {"reminders": rows})


class ReminderCreateTool(Tool):
    name = "reminders.create"
    description = "Cria lembrete local que pode ser cancelado depois."

    def __init__(self, store=None):
        self.store = store or ReminderStore()

    def execute(self, arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"text", "due_at"}:
            raise ValueError("Informe texto e data do lembrete")
        row = self.store.create(arguments["text"], arguments["due_at"])
        return ActionResult(True, "Lembrete criado e cancelável.", {"reminder": row})


class ReminderCancelTool(Tool):
    name = "reminders.cancel"
    description = "Cancela logicamente um lembrete sem apagar o histórico."

    def __init__(self, store=None):
        self.store = store or ReminderStore()

    def execute(self, arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"reminder_id"}:
            raise ValueError("Informe o identificador do lembrete")
        self.store.cancel(arguments["reminder_id"])
        return ActionResult(True, "Lembrete cancelado.")


class ReminderReactivateTool(Tool):
    name = "reminders.reactivate"
    description = "Reativa um lembrete cancelado, sem recriá-lo."

    def __init__(self, store=None):
        self.store = store or ReminderStore()

    def execute(self, arguments):
        if not isinstance(arguments, dict) or set(arguments) != {"reminder_id"}:
            raise ValueError("Informe o identificador do lembrete")
        self.store.reactivate(arguments["reminder_id"])
        return ActionResult(True, "Lembrete reativado.")
