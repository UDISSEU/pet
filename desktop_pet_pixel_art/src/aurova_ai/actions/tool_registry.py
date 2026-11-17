"""Registro de ferramentas locais com política explícita por capacidade."""

from .registry import ActionRegistry
from .action_validator import DirectoryAccessPolicy


class ToolRegistry(ActionRegistry):
    """Mantém compatibilidade com ActionRegistry e oferece registro declarativo."""

    def __init__(self, *, directory_policy=None):
        super().__init__()
        self.directory_policy = directory_policy or DirectoryAccessPolicy()

    def register_tool(self, tool, *, permission, read_only, requires_confirmation=False,
                      additional_permissions=(), timeout_seconds=5.0, source="local"):
        definition = self.register(
            tool.name, tool, permission=permission, read_only=read_only,
            requires_confirmation=requires_confirmation,
            additional_permissions=additional_permissions,
            timeout_seconds=timeout_seconds, source=source,
        )
        return definition


def create_default_tool_registry(*, reminder_store=None, system_monitor=None,
                                 directory_policy=None):
    """Monta ferramentas locais sem executá-las nem iniciar processos."""
    from .app_launcher import AppCatalogTool, AppLauncherTool
    from .file_manager import (
        DirectoryListTool, FileOrganizerPreviewTool, FileOrganizerTool, FileSearchTool,
        UndoFileOrganizationTool,
    )
    from .reminders import (
        ReminderCancelTool, ReminderCreateTool, ReminderListTool, ReminderReactivateTool,
    )
    from .system_monitor import ClockTool, SystemMonitorTool

    registry = ToolRegistry(directory_policy=directory_policy)
    tools = (
        (ClockTool(), "system.clock.read", True, False, ()),
        (SystemMonitorTool(system_monitor), "system.cpu.read", True, False,
         ("system.memory.read", "system.disk.read"), 3.0),
        (FileSearchTool(registry.directory_policy), "file.read", True, False, ()),
        (DirectoryListTool(registry.directory_policy), "file.read", True, False, ()),
        (FileOrganizerPreviewTool(), "file.read", True, False, ()),
        (FileOrganizerTool(), "file.organize", False, True, ("file.read",), 30.0),
        (UndoFileOrganizationTool(), "file.move", False, True, ("file.read",), 30.0),
        (AppCatalogTool(), "system.app.read", True, False, ()),
        (AppLauncherTool(), "system.app.launch", False, True, (), 12.0),
        (ReminderListTool(reminder_store), "reminder.read", True, False, ()),
        (ReminderCreateTool(reminder_store), "reminder.write", False, True, ()),
        (ReminderCancelTool(reminder_store), "reminder.write", False, True, ()),
        (ReminderReactivateTool(reminder_store), "reminder.write", False, True, ()),
    )
    for spec in tools:
        tool, permission, read_only, confirm, additional, *timeout = spec
        registry.register_tool(
            tool, permission=permission, read_only=read_only,
            requires_confirmation=confirm, additional_permissions=additional,
            timeout_seconds=timeout[0] if timeout else 5.0,
        )
    return registry
