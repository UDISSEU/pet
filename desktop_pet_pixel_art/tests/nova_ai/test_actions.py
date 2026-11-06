"""Testes locais das ferramentas com diretórios temporários e sem efeitos no host."""

from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nova_ai.actions import (
    ActionLog, ActionResult, ActionValidationError, AuthorizationRequired,
    CancellationToken, DirectoryAccessPolicy, DirectoryListTool,
    FileSearchTool, Tool, ToolDispatcher, ToolDispatchError, ToolRegistry,
    ActionRegistryError, AppLauncherTool, ReminderStore, create_default_tool_registry,
    FileOrganizerPreviewTool, FileOrganizerTool, UndoFileOrganizationTool,
    ToolTimedOut,
)


class PermissionStub:
    def __init__(self, granted=()):
        self.granted = set(granted)

    def allowed(self, plugin, permission):
        return permission in self.granted

    def require(self, plugin, permission, *, confirmed=False):
        if permission not in self.granted:
            raise PermissionError(permission)
        if permission in {"file.write", "file.move", "file.delete", "file.organize",
                          "system.app.launch", "reminder.write"} and not confirmed:
            raise PermissionError("confirmation required")


class EchoTool(Tool):
    name = "test.echo"

    def execute(self, arguments):
        return ActionResult(True, "ok", arguments)


class FailureTool(Tool):
    name = "test.failure"

    def execute(self, arguments):
        raise RuntimeError("private detail")


class SlowTool(Tool):
    name = "test.slow"

    def execute(self, arguments):
        time.sleep(0.12)
        return ActionResult(True, "finished")


class CooperativeTool(Tool):
    name = "test.cooperative"

    def __init__(self):
        self.started = threading.Event()

    def execute(self, arguments):
        raise AssertionError("dispatcher must call contextual method")

    def execute_with_context(self, arguments, context):
        self.started.set()
        while True:
            context.checkpoint()
            time.sleep(0.005)


class ActionSystemTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "allowed"
        self.root.mkdir()
        self.policy = DirectoryAccessPolicy({"nova.core": (self.root,)})
        self.registry = ToolRegistry(directory_policy=self.policy)
        self.log = ActionLog(limit=20)

    def tearDown(self):
        self.temp.cleanup()

    def test_authorized_tool_executes_and_is_logged(self):
        self.registry.register("test.echo", EchoTool(), permission="file.read", read_only=True)
        dispatcher = ToolDispatcher(
            self.registry, PermissionStub({"file.read"}), action_log=self.log,
        )
        result = dispatcher.dispatch("test.echo", {"value": "ok"})
        self.assertTrue(result.success)
        self.assertEqual(self.log.entries()[-1].outcome, "succeeded")

    def test_missing_permission_denies_before_tool_execution(self):
        tool = EchoTool()
        self.registry.register("test.echo", tool, permission="file.read", read_only=True)
        dispatcher = ToolDispatcher(self.registry, PermissionStub(), action_log=self.log)
        with self.assertRaises(AuthorizationRequired):
            dispatcher.dispatch("test.echo", {})
        self.assertEqual(self.log.entries()[-1].outcome, "failed")

    def test_permission_is_checked_before_touching_requested_directory(self):
        self.registry.register("files.search", FileSearchTool(self.policy),
                               permission="file.read", read_only=True)
        dispatcher = ToolDispatcher(self.registry, PermissionStub(), action_log=self.log)
        absent = Path(self.temp.name) / "not-authorized-or-existing"
        with self.assertRaises(AuthorizationRequired):
            dispatcher.dispatch("files.search", {"root": str(absent), "query": "x"})

    def test_shell_arguments_are_rejected_and_failure_is_logged(self):
        self.registry.register("test.echo", EchoTool(), permission="file.read", read_only=True)
        dispatcher = ToolDispatcher(self.registry, PermissionStub({"file.read"}),
                                    action_log=self.log)
        with self.assertRaises(ToolDispatchError):
            dispatcher.dispatch("test.echo", {"shell_command": "rm -rf /"})
        self.assertEqual(self.log.entries()[-1].outcome, "failed")

    def test_tool_failure_is_sanitized_and_logged(self):
        self.registry.register("test.failure", FailureTool(), permission="file.read",
                               read_only=True)
        dispatcher = ToolDispatcher(self.registry, PermissionStub({"file.read"}),
                                    action_log=self.log)
        with self.assertRaises(ToolDispatchError) as caught:
            dispatcher.dispatch("test.failure")
        self.assertNotIn("private detail", str(caught.exception))
        self.assertEqual(self.log.entries()[-1].outcome, "failed")

    def test_path_traversal_and_unapproved_directory_are_rejected(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        tool = FileSearchTool(self.policy)
        with self.assertRaises(ActionValidationError):
            tool.execute({"root": str(outside), "query": "report"})
        with self.assertRaises(ActionValidationError):
            self.policy.require("nova.core", self.root / ".." / "outside")
        with self.assertRaises(ActionValidationError):
            DirectoryListTool(self.policy).execute({"directory": str(outside)})

    def test_file_search_and_directory_listing_work_in_authorized_root(self):
        (self.root / "quarterly-report.txt").write_text("data", encoding="utf-8")
        search = FileSearchTool(self.policy).execute({"root": str(self.root), "query": "report"})
        listing = DirectoryListTool(self.policy).execute({"directory": str(self.root)})
        self.assertEqual(len(search.data["files"]), 1)
        self.assertEqual(listing.data["entries"][0]["name"], "quarterly-report.txt")

    def test_confirmation_is_required_for_reversible_mutation(self):
        self.registry.register("test.echo", EchoTool(), permission="file.move",
                               read_only=False, requires_confirmation=True)
        dispatcher = ToolDispatcher(self.registry, PermissionStub({"file.move"}),
                                    action_log=self.log)
        with self.assertRaises(AuthorizationRequired):
            dispatcher.dispatch("test.echo", {})
        self.assertTrue(dispatcher.dispatch("test.echo", {}, approved=True).success)

    def test_timeout_is_enforced_and_recorded(self):
        self.registry.register("test.slow", SlowTool(), permission="file.read", read_only=True,
                               timeout_seconds=0.05)
        dispatcher = ToolDispatcher(self.registry, PermissionStub({"file.read"}),
                                    action_log=self.log)
        with self.assertRaises(ToolDispatchError) as caught:
            dispatcher.dispatch("test.slow")
        self.assertIsInstance(caught.exception.cause, ToolTimedOut)
        self.assertEqual(self.log.entries()[-1].outcome, "timeout")

    def test_running_tool_can_be_cancelled_cooperatively(self):
        tool = CooperativeTool()
        self.registry.register("test.cooperative", tool, permission="file.read", read_only=True,
                               timeout_seconds=4)
        dispatcher = ToolDispatcher(self.registry, PermissionStub({"file.read"}),
                                    action_log=self.log)
        token = CancellationToken()
        outcomes = []

        def run():
            try:
                dispatcher.dispatch("test.cooperative", cancellation=token)
            except ToolDispatchError as error:
                outcomes.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(tool.started.wait(1))
        token.cancel()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(self.log.entries()[-1].outcome, "cancelled")

    def test_external_plugin_source_is_not_accepted_by_local_registry(self):
        with self.assertRaises(ActionRegistryError):
            self.registry.register("test.echo", EchoTool(), permission="file.read",
                                   read_only=True, source="plugin")

    def test_installed_app_requires_approval_and_uses_fixed_launcher(self):
        import nova_ai.actions.app_launcher as launcher_module

        app_dir = Path(self.temp.name) / "applications"
        app_dir.mkdir()
        (app_dir / "example.desktop").write_text(
            "[Desktop Entry]\nType=Application\nName=Example\nExec=example\n",
            encoding="utf-8",
        )
        gio = Path(self.temp.name) / "gio"
        gio.touch()
        class Process:
            returncode = 0
            def poll(self):
                return 0

        self.registry.register("apps.launch", AppLauncherTool(), permission="system.app.launch",
                               read_only=False, requires_confirmation=True)
        dispatcher = ToolDispatcher(
            self.registry, PermissionStub({"system.app.launch"}), action_log=self.log,
        )
        with mock.patch.object(launcher_module, "_APP_DIRS", (app_dir,)), \
                mock.patch.object(launcher_module, "_GIO", gio), \
                mock.patch.object(launcher_module.subprocess, "Popen", return_value=Process()) as popen:
            with self.assertRaises(AuthorizationRequired):
                dispatcher.dispatch("apps.launch", {"app_id": "example.desktop"})
            self.assertFalse(popen.called)
            result = dispatcher.dispatch("apps.launch", {"app_id": "example.desktop"},
                                         approved=True)
        self.assertTrue(result.success)
        self.assertEqual(popen.call_args.args[0][0], str(gio))
        self.assertFalse(popen.call_args.kwargs["shell"])

    def test_reminder_state_is_local_and_reversible_without_deleting_history(self):
        store = ReminderStore(Path(self.temp.name) / "nova" / "reminders.json")
        row = store.create("Revisar relatório", "2030-01-01T09:30:00-03:00")
        store.cancel(row["id"])
        self.assertEqual(store.list()[0]["status"], "cancelled")
        store.reactivate(row["id"])
        self.assertEqual(store.list()[0]["status"], "active")

    def test_file_organization_can_be_undone_without_deleting_file_content(self):
        import nova_ai.actions.file_manager as file_module

        source = self.root / "notes.txt"
        source.write_text("keep me", encoding="utf-8")
        registry = ToolRegistry(directory_policy=self.policy)
        registry.register("files.preview_downloads", FileOrganizerPreviewTool(),
                          permission="file.read", read_only=True)
        registry.register("files.organize_downloads", FileOrganizerTool(),
                          permission="file.organize", read_only=False,
                          requires_confirmation=True)
        registry.register("files.organize.undo", UndoFileOrganizationTool(),
                          permission="file.move", read_only=False,
                          requires_confirmation=True)
        dispatcher = ToolDispatcher(
            registry, PermissionStub({"file.read", "file.organize", "file.move"}),
            action_log=self.log,
        )
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            preview = dispatcher.dispatch("files.preview_downloads")
            organized = dispatcher.dispatch(
                "files.organize_downloads", {"plan": preview.data["plan"]}, approved=True,
            )
            self.assertFalse(source.exists())
            undo = dispatcher.dispatch(
                "files.organize.undo", {"undo_mapping": organized.data["undo_mapping"]},
                approved=True,
            )
        self.assertTrue(undo.success)
        self.assertEqual(source.read_text(encoding="utf-8"), "keep me")

    def _preview_for(self, root, names):
        import nova_ai.actions.file_manager as file_module

        for name in names:
            (root / name).write_text(name, encoding="utf-8")
        with mock.patch.object(file_module, "_downloads_root", return_value=root):
            return FileOrganizerPreviewTool().execute({}).data["plan"]

    def test_downloads_root_symlink_is_rejected(self):
        import nova_ai.actions.file_manager as file_module

        real = Path(self.temp.name) / "real-downloads"
        real.mkdir()
        link = Path(self.temp.name) / "Downloads"
        link.symlink_to(real, target_is_directory=True)
        with mock.patch.object(file_module.Path, "home", return_value=Path(self.temp.name)):
            with self.assertRaises((OSError, ValueError)):
                file_module._downloads_root()

    def test_category_directory_symlink_is_rejected(self):
        import nova_ai.actions.file_manager as file_module

        source = self.root / "report.pdf"
        source.write_text("document", encoding="utf-8")
        external = Path(self.temp.name) / "external"
        external.mkdir()
        (self.root / "Documentos").symlink_to(external, target_is_directory=True)
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            with self.assertRaises(ValueError):
                FileOrganizerPreviewTool().execute({})
        self.assertTrue(source.exists())

    def test_incomplete_downloads_preview_is_marked_blocked(self):
        import nova_ai.actions.file_manager as file_module

        for index in range(501):
            (self.root / f"document-{index:03}.txt").write_text("content", encoding="utf-8")
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            preview = FileOrganizerPreviewTool().execute({})

        self.assertFalse(preview.success)
        self.assertTrue(preview.data["limit_reached"])
        self.assertEqual(len(preview.data["plan"]), 500)
        self.assertIn("bloqueada", preview.summary)

    def test_external_destination_and_traversal_plan_are_rejected(self):
        import nova_ai.actions.file_manager as file_module

        plan = self._preview_for(self.root, ["safe.txt"])
        external = Path(self.temp.name) / "outside.txt"
        forged = dict(plan[0], destination=str(external))
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            with self.assertRaises(ValueError):
                FileOrganizerTool().execute({"plan": [forged]})
            forged = dict(plan[0], source=str(self.root / ".." / "outside.txt"))
            with self.assertRaises(ValueError):
                FileOrganizerTool().execute({"plan": [forged]})

    def test_replacing_source_with_symlink_invalidates_plan(self):
        import nova_ai.actions.file_manager as file_module

        plan = self._preview_for(self.root, ["safe.txt"])
        replacement = Path(self.temp.name) / "replacement.txt"
        replacement.write_text("outside", encoding="utf-8")
        (self.root / "safe.txt").unlink()
        (self.root / "safe.txt").symlink_to(replacement)
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            with self.assertRaises(ValueError):
                FileOrganizerTool().execute({"plan": plan})
        self.assertEqual(replacement.read_text(encoding="utf-8"), "outside")

    def test_removed_source_between_preview_and_execution_is_rejected(self):
        import nova_ai.actions.file_manager as file_module

        plan = self._preview_for(self.root, ["safe.txt"])
        (self.root / "safe.txt").unlink()
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            with self.assertRaises(ValueError):
                FileOrganizerTool().execute({"plan": plan})
        self.assertFalse((self.root / "Documentos" / "safe.txt").exists())

    def test_category_replaced_with_symlink_after_preview_is_rejected(self):
        import nova_ai.actions.file_manager as file_module

        plan = self._preview_for(self.root, ["safe.txt"])
        external = Path(self.temp.name) / "external-after-preview"
        external.mkdir()
        (self.root / "Documentos").symlink_to(external, target_is_directory=True)
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            with self.assertRaises(ValueError):
                FileOrganizerTool().execute({"plan": plan})
        self.assertTrue((self.root / "safe.txt").exists())
        self.assertEqual(list(external.iterdir()), [])

    def test_existing_destination_is_not_overwritten(self):
        import nova_ai.actions.file_manager as file_module

        plan = self._preview_for(self.root, ["safe.txt"])
        category = self.root / "Documentos"
        category.mkdir()
        existing = category / "safe.txt"
        existing.write_text("keep", encoding="utf-8")
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            with self.assertRaises((ValueError, FileExistsError)):
                FileOrganizerTool().execute({"plan": plan})
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep")

    def test_tampered_plan_token_is_rejected(self):
        import nova_ai.actions.file_manager as file_module

        plan = self._preview_for(self.root, ["safe.txt"])
        plan[0]["destination"] = str(self.root / "Documentos" / "different.txt")
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            with self.assertRaises(ValueError):
                FileOrganizerTool().execute({"plan": plan})

    def test_undo_rejects_adulterated_paths_and_token(self):
        import nova_ai.actions.file_manager as file_module

        plan = self._preview_for(self.root, ["safe.txt"])
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            organized = FileOrganizerTool().execute({"plan": plan})
            row = dict(organized.data["undo_mapping"][0])
            row["source"] = str(self.root / ".." / "outside.txt")
            with self.assertRaises(ValueError):
                UndoFileOrganizationTool().execute({"undo_mapping": [row]})
            row = dict(organized.data["undo_mapping"][0])
            row["destination"] = str(self.root / "Documentos" / "other.txt")
            with self.assertRaises(ValueError):
                UndoFileOrganizationTool().execute({"undo_mapping": [row]})

    def test_interruption_rolls_back_all_moves(self):
        import nova_ai.actions.file_manager as file_module

        plan = self._preview_for(self.root, ["one.txt", "two.txt"])

        class InterruptAfterFirstMove:
            calls = 0

            def checkpoint(self):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("interrupted")

        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            with self.assertRaises(RuntimeError):
                FileOrganizerTool().execute_with_context({"plan": plan}, InterruptAfterFirstMove())
        self.assertTrue((self.root / "one.txt").exists())
        self.assertTrue((self.root / "two.txt").exists())
        self.assertFalse((self.root / "Documentos" / "one.txt").exists())

    def test_normal_files_organize_and_restore_with_exclusive_rename(self):
        import nova_ai.actions.file_manager as file_module

        plan = self._preview_for(self.root, ["notes.txt", "photo.png"])
        with mock.patch.object(file_module, "_downloads_root", return_value=self.root):
            organized = FileOrganizerTool().execute({"plan": plan})
            self.assertTrue((self.root / "Documentos" / "notes.txt").exists())
            self.assertTrue((self.root / "Imagens" / "photo.png").exists())
            undone = UndoFileOrganizationTool().execute(
                {"undo_mapping": organized.data["undo_mapping"]}
            )
        self.assertTrue(undone.success)
        self.assertTrue((self.root / "notes.txt").exists())
        self.assertTrue((self.root / "photo.png").exists())

    def test_default_registry_contains_only_explicit_local_tools(self):
        registry = create_default_tool_registry(directory_policy=self.policy)
        self.assertIn("system.clock", registry.names())
        self.assertIn("files.list_directory", registry.names())
        self.assertIn("apps.launch", registry.names())
        self.assertNotIn("files.delete", registry.names())


if __name__ == "__main__":
    unittest.main()
