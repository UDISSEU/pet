"""Bounded factual context and privacy-preserving action history for Meu Computador."""

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from computer_diagnostics import NetworkSampler, SystemHealthSampler
from computer_maintenance import analyze_cleanup, collect_logs, inspect_disks
from computer_services import collect_overview, collect_storage_overview
from performance_monitor import performance_context
from startup_manager import discover_startup_entries
from json_persistence import ensure_private_directory, validate_storage_path

MAX_ACTIONS = 500
MAX_CONTEXT_CHARS = 12_000


def default_action_history_path():
    return Path.home() / ".local/state/desktop_pet/computer_actions.sqlite3"


class ActionHistoryStore:
    """Bounded local history; stores action metadata, never request text or arguments."""

    def __init__(self, path=None, *, limit=MAX_ACTIONS):
        self.path = Path(path or default_action_history_path())
        self.limit = max(10, min(MAX_ACTIONS, int(limit)))
        self._lock = threading.RLock()
        ensure_private_directory(self.path.parent, label="histórico de ações")
        validate_storage_path(self.path, label="histórico de ações")
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
            os.close(fd)
        info = self.path.lstat()
        if not self.path.is_file() or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise PermissionError("Histórico de ações inválido ou inseguro.")
        os.chmod(self.path, 0o600)
        with self._session() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY, action TEXT NOT NULL, status TEXT NOT NULL,
                origin TEXT NOT NULL, result TEXT NOT NULL, error_code TEXT,
                created_at TEXT NOT NULL)""")
            db.execute("CREATE INDEX IF NOT EXISTS actions_created ON actions(id DESC)")

    @contextmanager
    def _session(self):
        db = sqlite3.connect(self.path, timeout=2)
        try:
            db.execute("PRAGMA busy_timeout=2000")
            with db:
                yield db
        finally:
            db.close()

    def record(self, action, status, *, origin="Nova", result="", error_code=None):
        status = {"succeeded": "Concluída", "failed": "Falhou",
                  "cancelled": "Cancelada", "timeout": "Falhou"}.get(status, status)
        if status == "Falhou" and error_code == "authorization_required":
            status = "Aguardando autorização"
        allowed = {"Concluída", "Em andamento", "Cancelada", "Falhou", "Aguardando autorização"}
        if status not in allowed:
            raise ValueError("Estado de ação inválido.")
        result = result or "Ação registrada pela Nova."
        row = (str(action)[:100], status, str(origin)[:60], str(result)[:240],
               None if error_code is None else str(error_code)[:80],
               datetime.now(timezone.utc).isoformat(timespec="seconds"))
        with self._lock, self._session() as db:
            cursor = db.execute("INSERT INTO actions(action,status,origin,result,error_code,created_at) VALUES(?,?,?,?,?,?)", row)
            db.execute("DELETE FROM actions WHERE id NOT IN (SELECT id FROM actions ORDER BY id DESC LIMIT ?)", (self.limit,))
            return cursor.lastrowid

    def list(self, *, limit=200):
        with self._lock, self._session() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT action,status,origin,result,error_code,created_at FROM actions ORDER BY id DESC LIMIT ?",
                (max(1, min(self.limit, int(limit))),))]

    def update(self, entry_id, status, *, result="", error_code=None):
        allowed = {"Concluída", "Em andamento", "Cancelada", "Falhou", "Aguardando autorização"}
        if status not in allowed:
            raise ValueError("Estado de ação inválido.")
        with self._lock, self._session() as db:
            db.execute("UPDATE actions SET status=?,result=?,error_code=? WHERE id=?",
                       (status, str(result)[:240], None if error_code is None else str(error_code)[:80], int(entry_id)))


def _selected_sources(question):
    q = question.casefold()
    selected = {"hardware", "alerts", "performance"}
    if any(term in question.casefold() for term in ("lento", "travando", "processo", "consumindo", "consome", "maior uso", "diagnóstico", "diagnostico")):
        selected.add("system")
    keywords = {
        "applications": ("aplicativo", "aplicativos", "programa", "instalado", "atualização", "atualizações", "atualiza"),
        "startup": ("inicializa", "iniciam", "iniciar", "boot", "abertura do sistema"),
        "storage": ("armazenamento", "espaço", "disco", "pasta", "cache", "limpeza"),
        "network": ("rede", "conexão", "internet", "wi-fi", "wifi", "conectividade"),
        "smart": ("smart", "saúde do disco", "falha de disco", "meus discos", "discos", "integridade do disco"),
        "logs": ("log", "erro", "falha", "aviso", "serviço"),
        "cleanup": ("limpar", "limpeza", "temporário", "cache"),
    }
    for source, terms in keywords.items():
        if any(term in q for term in terms):
            selected.add(source)
    return selected


def collect_computer_context(question="", *, performance_store=None, system_monitor=None, cancel_event=None):
    """Collect only relevant existing read-only services; failures stay source-local."""
    try:
        from autonomy import find_installed_apps
    except Exception:
        find_installed_apps = None
    context = {"schema": "nova-computer-context.v1", "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sources": {}, "limitations": [
        "Dados são amostras locais coletadas agora; valores ausentes não significam estado saudável.",
        "Causas sugeridas são hipóteses, salvo evidência explicitamente observada.",
    ]}
    selected = _selected_sources(question)
    def cancelled():
        return bool(cancel_event is not None and cancel_event.is_set())

    def collect(name, function):
        try:
            context["sources"][name] = {"state": "available", "data": function()}
        except Exception as exc:
            context["sources"][name] = {"state": "unavailable", "reason": type(exc).__name__}

    collect("hardware", lambda: {k: v for k, v in collect_overview().items()
                                  if k not in ("hostname",)})
    if cancelled():
        context["cancelled"] = True
        return context
    if "system" in selected:
        collect("system", lambda: _health_snapshot(system_monitor))
        if cancelled():
            context["cancelled"] = True
            return context
    if "applications" in selected:
        if find_installed_apps is None:
            context["sources"]["applications"] = {"state": "unavailable", "reason": "service_unavailable"}
        else:
            collect("applications", lambda: _applications(find_installed_apps, cancel_event))
    if cancelled():
        context["cancelled"] = True
        return context
    if "startup" in selected:
        collect("startup", lambda: [{"name": r["name"], "state": r["state"], "kind": r["kind"]}
                                     for r in discover_startup_entries()[:100]])
    if cancelled():
        context["cancelled"] = True
        return context
    if "storage" in selected:
        collect("storage", lambda: _storage())
    if cancelled():
        context["cancelled"] = True
        return context
    if "network" in selected:
        collect("network", lambda: _network())
    if cancelled():
        context["cancelled"] = True
        return context
    if "smart" in selected:
        collect("smart", lambda: _smart())
    if cancelled():
        context["cancelled"] = True
        return context
    if "logs" in selected:
        collect("logs", lambda: _logs())
    if cancelled():
        context["cancelled"] = True
        return context
    if "cleanup" in selected:
        collect("cleanup", lambda: _cleanup())
    if performance_store is not None:
        collect("performance", lambda: performance_context(performance_store, hours=24))
        collect("alerts", lambda: performance_store.alerts(limit=20))
    else:
        context["sources"]["performance"] = {"state": "unavailable", "reason": "history_unavailable"}
        context["sources"]["alerts"] = {"state": "unavailable", "reason": "history_unavailable"}
    if cancelled():
        context["cancelled"] = True
    serialized = json.dumps(context, ensure_ascii=False, default=str)
    if len(serialized) > MAX_CONTEXT_CHARS:
        context["sources"] = {key: _compact_source(value) for key, value in context["sources"].items()}
        serialized = json.dumps(context, ensure_ascii=False, default=str)
        for key in reversed(tuple(context["sources"])):
            if len(serialized) <= MAX_CONTEXT_CHARS:
                break
            context["sources"].pop(key, None)
            serialized = json.dumps(context, ensure_ascii=False, default=str)
        context["truncated"] = True
    return context


def _applications(discover, cancel_event=None):
    from system_updates import build_installed_app_inventory, query_installed_app_sources
    launchers = discover()
    queried = query_installed_app_sources(launchers, cancel_event=cancel_event)
    inventory = build_installed_app_inventory(
        launchers, queried["package_versions"], queried["package_owners"],
        queried["flatpak_output"], apt_upgradable=queried["apt_upgradable"],
        flatpak_update_output=queried["flatpak_update_output"],
        snap_output=queried["snap_output"], snap_update_output=queried["snap_update_output"],
        checked_sources=queried["checked_sources"],
        apt_owners_checked=queried["apt_owners_checked"],
        apt_applications=queried["apt_applications"],
        snap_applications=queried["snap_applications"],
    )
    return {
        "count": len(inventory),
        "items": [{key: item.get(key) for key in
                   ("name", "version", "source", "candidate_version", "update_status")}
                  for item in inventory[:40]],
        "sources": {source: {"inventory_complete": data["inventory_complete"],
                             "updates_complete": data["updates_complete"],
                             "metadata_stale": data.get("metadata_stale", False)}
                    for source, data in queried["source_results"].items()},
        "unavailable_sources": [source for source, data in queried["source_results"].items()
                                if not data["inventory_complete"] or not data["updates_complete"]],
    }


def _health_snapshot(system_monitor):
    snapshot = SystemHealthSampler(process_limit=8).sample(system_monitor)
    return {
        key: snapshot.get(key) for key in (
            "cpu_percent", "memory_percent", "memory_used", "memory_total",
            "memory_available", "disk_percent", "disk_free", "disk_total",
            "temperature_c", "issues", "timestamp",
        )
    } | {"processes": [
        {key: row.get(key) for key in ("name", "pid", "cpu_percent", "memory_bytes", "memory_percent")}
        for row in snapshot.get("processes", ())[:8]
    ]}


def _storage():
    info = collect_storage_overview()
    return {key: info.get(key) for key in ("total", "used", "free", "percent")}


def _network():
    info = NetworkSampler(history_limit=2).sample()
    return {key: info.get(key) for key in ("connection_state", "internet_state", "active_interfaces", "connected_interfaces", "gateway", "dns_servers")}


def _smart():
    info = inspect_disks()
    return {"state": info.get("state"), "reason": info.get("reason"), "devices": [
        {key: disk.get(key) for key in ("name", "model", "vendor", "capacity_bytes", "smart_state", "temperature_c", "wear", "indicators", "detail")}
        for disk in info.get("devices", ())[:16]]}


def _logs():
    rows = collect_logs(max_records=100)
    return {"count": len(rows), "recent": [{key: row.get(key) for key in ("date", "severity", "category")} for row in rows[:10]]}


def _cleanup():
    data = analyze_cleanup(max_entries=500, max_seconds=2)
    return {"count": len(data.get("items", ())), "complete": data.get("complete"), "items": [
        {key: item.get(key) for key in ("category", "bytes", "reason")} for item in data.get("items", ())[:20]]}


def _compact_source(source):
    data = source.get("data")
    if isinstance(data, list):
        source["data"] = data[:10]
    elif isinstance(data, dict):
        for key, value in list(data.items()):
            if isinstance(value, list):
                data[key] = value[:10]
            elif isinstance(value, str):
                data[key] = value[:240]
    return source


def consultant_context_memory(context):
    """Serialize current context as bounded, clearly labeled untrusted evidence."""
    data = json.dumps(context, ensure_ascii=False, default=str)
    if len(data) > MAX_CONTEXT_CHARS:
        def shrink(value):
            if isinstance(value, str): return value[:240]
            if isinstance(value, list): return [shrink(item) for item in value[:5]]
            if isinstance(value, dict): return {str(k)[:80]: shrink(v) for k, v in list(value.items())[:20]}
            return value
        data = json.dumps(shrink(context), ensure_ascii=False, default=str)
    if len(data) > MAX_CONTEXT_CHARS:
        data = json.dumps({"schema": "nova-computer-context.v1", "truncated": True}, ensure_ascii=False)
    return "[Dados observados do computador, coletados para esta pergunta; campos ausentes ou indisponíveis não devem ser inferidos] " + data
