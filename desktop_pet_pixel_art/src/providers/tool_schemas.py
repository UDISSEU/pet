"""JSON schemas published to inference providers; execution remains elsewhere."""

def _object(properties=None, required=()):
    return {"type":"object", "properties":properties or {}, "required":list(required), "additionalProperties":False}

_SCHEMAS = {
 "system.clock": _object(), "system.monitor": _object(), "files.search": _object({"root":{"type":"string"},"query":{"type":"string","minLength":1},"limit":{"type":"integer","minimum":1,"maximum":100}},("query",)),
 "files.list_directory": _object({"directory":{"type":"string"},"limit":{"type":"integer","minimum":1,"maximum":200}},("directory",)),
 "files.preview_downloads": _object({"path":{"type":"string"}}),
 "files.organize_downloads": _object({"plan":{"type":"array","maxItems":500,"items":{"type":"object"}}},("plan",)),
 "files.organize.undo": _object({"undo_mapping":{"type":"array","maxItems":500,"items":{"type":"object"}}},("undo_mapping",)),
 "apps.list": _object(), "apps.launch": _object({"app_id":{"type":"string","pattern":"^[A-Za-z0-9_.-]{1,160}\\.desktop$"}},("app_id",)),
 "reminders.list": _object(), "reminders.create": _object({"text":{"type":"string","maxLength":500},"due_at":{"type":"string"}},("text","due_at")),
 "reminders.cancel": _object({"reminder_id":{"type":"string"}},("reminder_id",)),
 "reminders.reactivate": _object({"reminder_id":{"type":"string"}},("reminder_id",)),
}

def build_tool_schemas(registry):
    """Only exposes names already registered by the local production registry."""
    result=[]
    for name in registry.names():
        if name not in _SCHEMAS:
            continue
        definition=registry.get(name)
        result.append({"type":"function","function":{"name":name,
                       "description":definition.tool.description,"parameters":_SCHEMAS[name]}})
    return result
