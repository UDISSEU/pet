import tempfile
import unittest
from pathlib import Path
import json
import shutil
import sys
import queue
import threading
import os
import time
import subprocess
from unittest import mock

from event_bus import Event, EventBus, EventType
from notifications import NotificationCategory, NotificationManager
from permissions import PermissionManager
from plugin_manager import Plugin, PluginManifest, PluginManager
from state_manager import StateManager
from system_monitor import SystemMonitor


class ArchitectureTests(unittest.TestCase):
    def make_external_process(self, directory, script, **limits):
        from plugin_manager import IsolatedPluginProcess
        root = Path(directory)
        plugin_file = root / "resource_probe.py"
        plugin_file.write_text(script, encoding="utf-8")
        return IsolatedPluginProcess(
            ["/usr/bin/python3", plugin_file.name], cwd=root,
            network_access=True, **limits,
        )

    def test_state_priority_and_temporary_restore(self):
        manager = StateManager()
        self.assertTrue(manager.transition("greeting", temporary=True))
        self.assertFalse(manager.transition("walk", priority=20))
        self.assertTrue(manager.restore())
        self.assertEqual(manager.current, "idle")

    def test_state_generation_prevents_stale_restore(self):
        manager = StateManager()
        manager.transition("greeting", temporary=True)
        manager.transition("thinking", force=True)
        self.assertFalse(manager.restore())
        self.assertEqual(manager.current, "thinking")

    def test_event_subscribe_cancel_and_isolated_exception(self):
        bus = EventBus()
        received = []
        bus.subscribe(EventType.PET_STATE_CHANGED, lambda _event: (_ for _ in ()).throw(RuntimeError()))
        token = bus.subscribe(EventType.PET_STATE_CHANGED, received.append)
        bus.publish(Event(EventType.PET_STATE_CHANGED, {"current": "walk"}))
        self.assertEqual(len(received), 1)
        self.assertTrue(bus.unsubscribe(token))
        self.assertEqual(bus.drain(), 0)
        bus.close()

    def test_post_queues_for_ui_thread(self):
        bus = EventBus()
        received = []
        bus.subscribe(EventType.TASK_FINISHED, received.append)
        bus.post(Event(EventType.TASK_FINISHED))
        self.assertEqual(received, [])
        self.assertEqual(bus.drain(), 1)
        self.assertEqual(len(received), 1)

    def test_worker_publish_is_delivered_only_when_owner_drains(self):
        import threading
        bus = EventBus()
        received = []
        bus.subscribe(EventType.TASK_FINISHED, received.append)
        worker = threading.Thread(target=lambda: bus.publish(Event(EventType.TASK_FINISHED)))
        worker.start()
        worker.join()
        self.assertEqual(received, [])
        self.assertEqual(bus.drain(), 1)
        self.assertEqual(len(received), 1)

    def test_event_payload_must_be_structured(self):
        with self.assertRaises(TypeError):
            Event(EventType.TASK_FINISHED, [])

    def test_plugin_lifecycle_explicit_registration(self):
        class Example(Plugin):
            manifest = PluginManifest("example", "Example")
            def __init__(self): self.calls = []
            def initialize(self, context): self.calls.append("initialize")
            def activate(self): self.calls.append("activate")
            def deactivate(self): self.calls.append("deactivate")
            def shutdown(self): self.calls.append("shutdown")
        plugin, manager = Example(), PluginManager()
        self.assertTrue(manager.register(plugin))
        self.assertFalse(manager.register(plugin))
        self.assertTrue(manager.activate("example"))
        self.assertEqual(manager.counts["active"], 1)
        manager.shutdown()
        self.assertEqual(plugin.calls, ["initialize", "activate", "deactivate", "shutdown"])

    def test_plugin_permission_checked_at_activation_and_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            permissions = PermissionManager(Path(directory) / "permissions.json")
            class Skill(Plugin):
                manifest = PluginManifest("safe_skill", "Safe", permissions=("file.read",))
            manager = PluginManager(permission_manager=permissions)
            manager.register(Skill())
            self.assertFalse(manager.activate("safe_skill"))
            permissions.authorize("safe_skill", "file.read")
            self.assertTrue(manager.activate("safe_skill"))
            self.assertEqual(manager.execute("safe_skill", "file.read", lambda: "ok"), "ok")
            permissions.revoke("safe_skill", "file.read")
            with self.assertRaises(PermissionError):
                manager.execute("safe_skill", "file.read", lambda: "bad")

    def test_permission_deny_default_sensitive_confirmation_and_revoke(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = PermissionManager(Path(directory) / "permissions.json")
            self.assertFalse(manager.allowed("skill", "file.delete"))
            self.assertFalse(manager.authorize("skill", "file.delete"))
            self.assertTrue(manager.authorize("skill", "file.delete", confirmed=True))
            manager.require("skill", "file.delete", confirmed=True)
            manager.revoke("skill", "file.delete")
            self.assertFalse(manager.allowed("skill", "file.delete"))

    def test_permission_loader_rejects_invalid_data_and_preserves_original(self):
        invalid_documents = (
            "{not valid json}",
            "[]",
            json.dumps({"grants": {"skill": ["file.read"]}, "history": []}),
            json.dumps({"grants": {"skill": {"file.read": "true"}}, "history": []}),
            json.dumps({"grants": {"skill": {"unknown.action": True}}, "history": []}),
            json.dumps({"grants": {}, "history": [{"plugin": "skill"}]}),
            json.dumps({
                "grants": {"skill": {"file.read": True}},
                "history": [{"plugin": "skill", "permission": "unknown.action", "granted": True}],
            }),
            json.dumps({"grants": {}, "history": [
                {"plugin": "skill", "permission": [], "granted": True}
            ]}),
            json.dumps({"grants": {}, "history": [], "unexpected": True}),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, contents in enumerate(invalid_documents):
                with self.subTest(contents=contents):
                    path = root / f"permissions-{index}.json"
                    path.write_text(contents, encoding="utf-8")
                    manager = PermissionManager(path)

                    self.assertFalse(manager.allowed("skill", "file.read"))
                    self.assertFalse(manager.allowed("skill", "unknown.action"))
                    backups = list(root.glob(f"{path.name}.corrupt-*"))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual(backups[0].read_text(encoding="utf-8"), contents)

            manager = PermissionManager(root / "new.json")
            with self.assertRaises(ValueError):
                manager.authorize("skill", "unknown.action")
            with self.assertRaises(ValueError):
                manager.revoke("skill", "unknown.action")

    def test_permission_and_notification_storage_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "real_store"
            target.mkdir()

            linked_dir = root / "linked_dir"
            linked_dir.symlink_to(target, target_is_directory=True)

            with self.assertRaises(OSError):
                PermissionManager(linked_dir / "permissions.json")
            with self.assertRaises(OSError):
                NotificationManager(linked_dir / "notifications.json")

            file_target = root / "target.json"
            file_target.write_text("{}", encoding="utf-8")
            linked_file = root / "linked.json"
            linked_file.symlink_to(file_target)
            with self.assertRaises(OSError):
                PermissionManager(linked_file)
            with self.assertRaises(OSError):
                NotificationManager(linked_file)

    def test_permission_read_failure_blocks_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "permissions.json"
            original = json.dumps({"grants": {}, "history": []})
            path.write_text(original, encoding="utf-8")
            with mock.patch.object(Path, "read_text", side_effect=OSError("sem acesso")):
                manager = PermissionManager(path)
                with self.assertRaises(OSError):
                    manager.authorize("skill", "file.read")

            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertFalse(manager.allowed("skill", "file.read"))

    def test_permission_grants_and_revocations_roll_back_after_save_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = PermissionManager(Path(directory) / "permissions.json")
            self.assertTrue(manager.authorize("skill", "file.read"))
            manager.revoke("skill", "file.read")
            history_before_failed_grant = list(manager._history)

            with mock.patch.object(manager, "_save", side_effect=OSError("falha")):
                with self.assertRaises(OSError):
                    manager.authorize("skill", "file.read")

            self.assertFalse(manager.allowed("skill", "file.read"))
            self.assertEqual(manager._history, history_before_failed_grant)
            self.assertFalse(PermissionManager(manager.path).allowed("skill", "file.read"))

            self.assertTrue(manager.authorize("skill", "file.read"))
            history_before_failed_revoke = list(manager._history)
            with mock.patch.object(manager, "_save", side_effect=OSError("falha")):
                with self.assertRaises(OSError):
                    manager.revoke("skill", "file.read")

            self.assertTrue(manager.allowed("skill", "file.read"))
            self.assertEqual(manager._history, history_before_failed_revoke)
            self.assertTrue(PermissionManager(manager.path).allowed("skill", "file.read"))

    def test_notification_persistence_dedupe_and_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notifications.json"
            manager = NotificationManager(path)
            item = manager.create("Pronto", "Tarefa concluída", NotificationCategory.SUCCESS)
            duplicate = manager.create("Pronto", "Tarefa concluída", NotificationCategory.SUCCESS)
            self.assertEqual(item.notification_id, duplicate.notification_id)
            self.assertEqual(manager.unread_count, 1)
            manager.mark_read(item.notification_id)
            restored = NotificationManager(path)
            self.assertEqual(restored.unread_count, 0)

    def test_notification_filters_and_configuration_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notifications.json"
            manager = NotificationManager(path, cooldown_seconds=0)
            manager.create("Info", "hello")
            warning = manager.create("Warn", "careful", NotificationCategory.WARNING)
            manager.configure_category(NotificationCategory.WARNING, False)
            manager.set_silent(True)
            self.assertIsNone(manager.create("Hidden", "disabled", NotificationCategory.WARNING))
            self.assertEqual(len(manager.filtered(NotificationCategory.INFO)), 1)
            restored = NotificationManager(path)
            self.assertTrue(restored.silent)
            self.assertFalse(restored.categories[NotificationCategory.WARNING.value])
            self.assertEqual(restored.filtered(NotificationCategory.WARNING)[0].notification_id,
                             warning.notification_id)
            self.assertFalse(restored.should_display(restored.filtered(NotificationCategory.INFO)[0]))

    def test_notification_cooldown_and_silent_critical_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = NotificationManager(Path(directory) / "notifications.json", cooldown_seconds=60)
            first = manager.create("Repeated", "message")
            repeated = manager.create("Repeated", "message")
            self.assertEqual(first.notification_id, repeated.notification_id)
            manager.configure_cooldown(0)
            self.assertNotEqual(manager.create("Repeated", "message").notification_id,
                                first.notification_id)
            manager.set_silent(True)
            critical = manager.create("Critical", "urgent", priority=100)
            self.assertTrue(manager.should_display(critical))

    def test_system_monitor_collects_bounded_real_metrics(self):
        monitor = SystemMonitor(history_limit=2)
        first = monitor.collect(extra={"pet_state": "walk"})
        monitor.collect()
        monitor.collect()
        self.assertIn("timestamp", first)
        self.assertEqual(first["pet_state"], "walk")
        self.assertLessEqual(len(monitor.history), 2)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is needed for isolated plugin process test")
    def test_external_plugin_runs_inside_sandbox_and_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            secret = root / "host-secret.txt"
            secret.write_text("host-only", encoding="utf-8")
            (plugin_dir / "plugin.py").write_text(
                "import json,sys,os\n"
                "request=json.loads(sys.stdin.readline())\n"
                f"try: open({str(secret)!r}).read(); host_file=True\n"
                "except OSError: host_file=False\n"
                "print(json.dumps({'protocol':1,'ok':True,'result':[request['action'], 'API_KEY' in os.environ, host_file]}))\n",
                encoding="utf-8",
            )
            manifest = plugin_dir / "plugin.json"
            manifest.write_text(json.dumps({
                "kind": "external", "plugin_id": "ext_skill", "name": "External",
                "command": ["/usr/bin/python3", "plugin.py"], "permissions": ["network.access"],
                "timeout": 3,
            }), encoding="utf-8")
            permissions = PermissionManager(root / "permissions.json")
            permissions.authorize("ext_skill", "network.access", confirmed=True)
            manager = PluginManager(permission_manager=permissions)
            spawned = []
            popen = __import__("plugin_manager").subprocess.Popen
            def capture(*args, **kwargs):
                process = popen(*args, **kwargs)
                spawned.append(process)
                return process
            with mock.patch("plugin_manager.subprocess.Popen", side_effect=capture):
                self.assertTrue(manager.register_external_manifest(manifest))
                self.assertTrue(manager.activate("ext_skill"))
                self.assertEqual(manager.execute_external("ext_skill", "network.access", "query",
                                                           confirmed=True), ["query", False, False])
                manager.shutdown()
            self.assertGreaterEqual(len(spawned), 5)
            self.assertTrue(all(process.poll() is not None for process in spawned))

    def test_ai_worker_delivers_result_on_event_bus(self):
        from desktop_pet import DesktopPet
        bus = EventBus()
        pet = DesktopPet.__new__(DesktopPet)
        pet.event_bus = bus
        pet.settings = {"ai_provider": "ollama"}
        observed = []
        for event_type in (EventType.AI_REQUEST_STARTED, EventType.AI_RESPONSE_RECEIVED):
            bus.subscribe(event_type, observed.append)
        with mock.patch("desktop_pet.answer_request", return_value="resposta local"):
            pet._ask_worker([], settings=pet.settings)
        self.assertEqual(observed, [])
        bus.drain()
        self.assertEqual([event.type for event in observed],
                         [EventType.AI_REQUEST_STARTED, EventType.AI_RESPONSE_RECEIVED])
        self.assertEqual(observed[-1].payload["answer"], "resposta local")

    def test_ai_and_automation_workers_complete_concurrently(self):
        from desktop_pet import DesktopPet
        with tempfile.TemporaryDirectory() as directory:
            pet = DesktopPet.__new__(DesktopPet)
            pet.event_bus = EventBus()
            pet.permission_manager = PermissionManager(Path(directory) / "permissions.json")
            pet.permission_manager.authorize("nova.core", "ai.use")
            pet.permission_manager.authorize("nova.core", "file.read")
            pet.settings = {"ai_provider": "ollama"}
            pet._authorize_core_action = lambda permission, confirmed=False: pet.permission_manager.require(
                "nova.core", permission, confirmed=confirmed)
            ready = threading.Barrier(2)
            received = []
            pet.event_bus.subscribe(EventType.AI_RESPONSE_RECEIVED, received.append)
            pet.event_bus.subscribe(EventType.TASK_FINISHED, received.append)
            automation = {"id": "large_files", "executor": lambda: (
                ready.wait(timeout=2), {"title": "relatório", "lines": [], "status": "ok"},
            )[1]}
            with mock.patch("desktop_pet.answer_request", side_effect=lambda *args, **kwargs: (
                    ready.wait(timeout=2), "resposta em paralelo")[1]):
                workers = [
                    threading.Thread(target=pet._ask_worker, args=([],), kwargs={"settings": pet.settings}),
                    threading.Thread(target=pet._automation_worker, args=(automation,)),
                ]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=3)
            self.assertTrue(all(not worker.is_alive() for worker in workers))
            pet.event_bus.drain()
            self.assertCountEqual(
                [event.type for event in received],
                [EventType.AI_RESPONSE_RECEIVED, EventType.TASK_FINISHED],
            )

    def test_notification_burst_keeps_history_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = NotificationManager(
                Path(directory) / "notifications.json", limit=25, cooldown_seconds=0,
            )
            for index in range(60):
                manager.create(f"Aviso {index}", "mensagem", persistent=True)
            self.assertEqual(len(manager.items), 25)
            self.assertEqual(manager.items[0].title, "Aviso 35")

    def test_worker_ui_callback_runs_only_when_main_thread_drains(self):
        from desktop_pet import DesktopPet
        pet = DesktopPet.__new__(DesktopPet)
        pet._closing = False
        pet._ui_callbacks = queue.Queue()
        called = []
        worker = threading.Thread(target=lambda: pet.post_ui_callback(
            lambda: called.append(threading.get_ident())))
        worker.start()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(called, [])
        main_thread = threading.get_ident()
        pet._drain_ui_callbacks()
        self.assertEqual(called, [main_thread])

    def test_external_plugin_rejects_invalid_manifest_and_bad_json_response(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "bad.json"
            manifest.write_text(json.dumps({
                "kind": "external", "plugin_id": "invalid", "name": "Bad",
                "command": ["/bin/true"], "permissions": ["unknown.permission"],
            }), encoding="utf-8")
            manager = PluginManager()
            with self.assertRaises(ValueError):
                manager.register_external_manifest(manifest)

            plugin = __import__("plugin_manager").IsolatedPluginProcess.__new__(
                __import__("plugin_manager").IsolatedPluginProcess)
            plugin.command = ["/bin/true"]
            plugin.cwd = str(root)
            plugin.timeout = 1
            plugin.cpu_seconds = 1
            plugin.memory_bytes = 64 * 1024 * 1024
            plugin.network_access = True
            plugin.bwrap = "/usr/bin/bwrap"
            plugin._lock = threading.Lock()
            fake_process = mock.Mock()
            fake_process.returncode = 0
            with mock.patch("plugin_manager.shutil.which", return_value="/usr/bin/prlimit"), \
                    mock.patch("plugin_manager.subprocess.Popen", return_value=fake_process) as popen, \
                    mock.patch("plugin_manager.tempfile.TemporaryFile") as temporary, \
                    mock.patch("plugin_manager.os.killpg"):
                output = mock.Mock()
                output.read.return_value = b"{malformed\n"
                temporary.return_value.__enter__.return_value = output
                with self.assertRaises(ValueError):
                    plugin.request("run")
                command = popen.call_args.args[0]
                self.assertEqual(command.count("/bin/true"), 1)
                self.assertIn("--nproc=32", command)

    def test_external_plugin_bounds_manifest_arguments_and_paths(self):
        from plugin_manager import IsolatedPluginProcess
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            outside = root / "outside.py"
            outside.write_text("pass\n", encoding="utf-8")
            (plugin_dir / "escape.py").symlink_to(outside)

            with self.assertRaises(ValueError):
                IsolatedPluginProcess([sys.executable, "../outside.py"], cwd=plugin_dir)
            with self.assertRaises(ValueError):
                IsolatedPluginProcess([sys.executable, "escape.py"], cwd=plugin_dir)
            with self.assertRaises(ValueError):
                IsolatedPluginProcess(["python3", "outside.py"], cwd=plugin_dir)
            with self.assertRaises(ValueError):
                IsolatedPluginProcess(
                    [sys.executable, *("x" for _ in range(IsolatedPluginProcess.MAX_COMMAND_ARGS))],
                    cwd=plugin_dir,
                )
            with self.assertRaises(ValueError):
                IsolatedPluginProcess(
                    [sys.executable, "x" * (IsolatedPluginProcess.MAX_COMMAND_ARG_LENGTH + 1)],
                    cwd=plugin_dir,
                )
            with self.assertRaises(ValueError):
                IsolatedPluginProcess(
                    [sys.executable, *("x" * 500 for _ in range(9))],
                    cwd=plugin_dir,
                )

            manifest = plugin_dir / "plugin.json"
            manifest.write_bytes(b" " * (IsolatedPluginProcess.MAX_MANIFEST + 1))
            with self.assertRaises(ValueError):
                PluginManager().register_external_manifest(manifest)

            manifest.write_text(json.dumps({
                "kind": "external", "plugin_id": "escape", "name": "Escape",
                "command": [sys.executable, "escape.py"], "permissions": ["file.read"],
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                PluginManager().register_external_manifest(manifest)

            manifest.write_text(json.dumps({
                "kind": "external", "plugin_id": "unknown", "name": "Unknown",
                "command": [sys.executable, "escape.py"], "permissions": ["file.read"],
                "unexpected": True,
            }), encoding="utf-8")
            with self.assertRaises(ValueError):
                PluginManager().register_external_manifest(manifest)

    def test_external_plugin_rechecks_revoked_permission_while_active(self):
        from plugin_manager import IsolatedPluginProcess
        with tempfile.TemporaryDirectory() as directory:
            permissions = PermissionManager(Path(directory) / "permissions.json")
            permissions.authorize("active_plugin", "file.read")
            manager = PluginManager(permission_manager=permissions)
            plugin = IsolatedPluginProcess.__new__(IsolatedPluginProcess)
            plugin.manifest = PluginManifest(
                "active_plugin", "Active", permissions=("file.read",),
            )
            plugin.request = mock.Mock(return_value="executed")
            manager._plugins["active_plugin"] = plugin
            manager._active.add("active_plugin")

            self.assertEqual(manager.execute_external("active_plugin", "file.read", "read"), "executed")
            permissions.revoke("active_plugin", "file.read")
            with self.assertRaises(PermissionError):
                manager.execute_external("active_plugin", "file.read", "read_again")
            plugin.request.assert_called_once_with("read", None)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is needed for isolated plugin process test")
    def test_external_plugin_without_grant_has_no_host_file_or_network_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin_dir = root / "plugin"
            plugin_dir.mkdir()
            secret = root / "host-secret.txt"
            secret.write_text("host-only", encoding="utf-8")
            script = plugin_dir / "plugin.py"
            script.write_text(
                "import json,os,socket,sys\n"
                "request=json.loads(sys.stdin.readline())\n"
                f"try: open({str(secret)!r}).read(); host_file=True\n"
                "except OSError: host_file=False\n"
                "try:\n"
                " s=socket.create_connection(('1.1.1.1',53),timeout=.25); s.close(); network=True\n"
                "except OSError: network=False\n"
                "print(json.dumps({'protocol':1,'ok':True,'result':{'file':host_file,'network':network,'credential':'API_KEY' in os.environ}}))\n",
                encoding="utf-8",
            )
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
            manifest = root / "plugin.json"
            manifest.write_text(json.dumps({
                "kind": "external", "plugin_id": "isolated_check", "name": "Isolation",
                "command": ["/usr/bin/python3", "plugin.py"], "permissions": ["file.read"],
                "timeout": 3,
            }), encoding="utf-8")
            permissions = PermissionManager(root / "permissions.json")
            permissions.authorize("isolated_check", "file.read")
            manager = PluginManager(permission_manager=permissions)
            self.assertTrue(manager.register_external_manifest(manifest))
            capability = subprocess.run(
                [shutil.which("bwrap"), "--unshare-user", "--unshare-pid", "--unshare-net",
                 "--ro-bind", "/usr", "/usr", "--proc", "/proc", "--dev", "/dev", "--", "true"],
                capture_output=True, text=True, timeout=3, check=False,
            )
            if capability.returncode:
                self.assertFalse(manager.activate("isolated_check"))
                self.assertNotIn("isolated_check", manager._active)
                self.skipTest("host blocks Bubblewrap network namespace; plugin remained inactive")
            if not manager.activate("isolated_check"):
                self.assertNotIn("isolated_check", manager._active)
                self.assertTrue(manager.errors)
                self.fail("Bubblewrap namespace probe succeeded but plugin activation failed")
            result = manager.execute_external("isolated_check", "file.read", "probe")
            self.assertEqual(result, {"file": False, "network": False, "credential": False})
            manager.shutdown()

    def test_external_plugin_fails_closed_without_bubblewrap(self):
        with mock.patch("plugin_manager.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError):
                __import__("plugin_manager").IsolatedPluginProcess(["/bin/true"])

    def test_real_automation_worker_checks_permission_and_posts_completion(self):
        from desktop_pet import DesktopPet
        with tempfile.TemporaryDirectory() as directory:
            pet = DesktopPet.__new__(DesktopPet)
            pet.event_bus = EventBus()
            pet.permission_manager = PermissionManager(Path(directory) / "permissions.json")
            observed = []
            pet.event_bus.subscribe(EventType.TASK_FINISHED, observed.append)
            automation = {"id": "large_files", "executor": lambda: {
                "title": "Arquivos grandes", "lines": [], "status": "ok"}}
            pet._automation_worker(automation)
            self.assertEqual(observed, [])
            pet.event_bus.drain()
            self.assertEqual(len(observed), 1)
            self.assertTrue(pet.permission_manager.allowed("nova.core", "file.read"))

    def test_revoked_app_permission_blocks_launch_worker(self):
        from desktop_pet import DesktopPet
        with tempfile.TemporaryDirectory() as directory:
            pet = DesktopPet.__new__(DesktopPet)
            pet.permission_manager = PermissionManager(Path(directory) / "permissions.json")
            pet.permission_manager.authorize("nova.core", "system.app.launch", confirmed=True)
            pet.permission_manager.revoke("nova.core", "system.app.launch")
            pet._app_launch_results = queue.Queue()
            launcher = mock.Mock()
            pet._launch_app = launcher
            pet._app_launch_worker("open app", {"name": "Example"})
            self.assertFalse(launcher.called)
            self.assertFalse(pet._app_launch_results.get_nowait()[1])

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is needed for isolated plugin process test")
    def test_external_plugin_timeout_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "slow.py").write_text(
                "import subprocess,sys,time\n"
                "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])\n"
                "time.sleep(10)\n",
                encoding="utf-8",
            )
            plugin = __import__("plugin_manager").IsolatedPluginProcess(
                ["/usr/bin/python3", "slow.py"], cwd=root, timeout=0.1, network_access=True)
            spawned = []
            popen = __import__("plugin_manager").subprocess.Popen
            def capture(*args, **kwargs):
                process = popen(*args, **kwargs)
                spawned.append(process)
                return process
            with mock.patch("plugin_manager.subprocess.Popen", side_effect=capture):
                with self.assertRaises(TimeoutError):
                    plugin.request("slow")
            self.assertEqual(len(spawned), 1)
            self.assertIsNotNone(spawned[0].poll())
            spawned[0].wait(timeout=1)
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                active_group_processes = []
                for proc_stat in Path("/proc").glob("[0-9]*/stat"):
                    try:
                        stat = proc_stat.read_text(encoding="ascii")
                        fields = stat[stat.rfind(")") + 2:].split()
                        if int(fields[2]) == spawned[0].pid and fields[0] != "Z":
                            active_group_processes.append(proc_stat.parent.name)
                    except (OSError, ValueError, IndexError):
                        continue
                if not active_group_processes:
                    break
                time.sleep(0.02)
            else:
                self.fail(f"plugin child processes remained after timeout: {active_group_processes}")

    def test_close_app_clears_callbacks_stops_monitor_and_ignores_late_posts(self):
        from desktop_pet import DesktopPet
        with tempfile.TemporaryDirectory() as directory:
            pet = DesktopPet.__new__(DesktopPet)
            pet._closing = False
            pet.event_bus = EventBus()
            pet.plugin_manager = mock.Mock()
            pet.permission_manager = PermissionManager(Path(directory) / "permissions.json")
            pet.permission_manager.authorize("nova.core", "file.read")
            pet._ui_callbacks = queue.Queue()
            pet._ui_callbacks.put((lambda: self.fail("callback ran after close"), (), {}))
            pet._device_monitor_stop = threading.Event()
            pet._device_monitor_thread = threading.Thread(
                target=lambda: pet._device_monitor_stop.wait(5), daemon=True,
            )
            pet._device_monitor_thread.start()
            pet._device_announcement_retry_job = "pending-retry"
            pet._animation_loader = mock.Mock()
            pet.root = mock.Mock()
            entered, release = threading.Event(), threading.Event()
            automation = {"id": "large_files", "executor": lambda: (
                entered.set(), release.wait(2),
                {"title": "done", "lines": [], "status": "ok"},
            )[2]}
            worker = threading.Thread(target=pet._automation_worker, args=(automation,), daemon=True)
            worker.start()
            self.assertTrue(entered.wait(1))
            pet.close_app()
            release.set()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())
            self.assertTrue(pet.event_bus._closed)
            self.assertEqual(pet.event_bus.drain(), 0)
            self.assertTrue(pet._closing)
            self.assertTrue(pet._device_monitor_stop.is_set())
            self.assertFalse(pet._device_monitor_thread.is_alive())
            self.assertTrue(pet._ui_callbacks.empty())
            self.assertFalse(pet.post_ui_callback(lambda: None))
            pet._drain_ui_callbacks()
            pet.plugin_manager.shutdown.assert_called_once_with()
            pet._animation_loader.close.assert_called_once_with()
            pet.root.after_cancel.assert_called_once_with("pending-retry")
            pet.root.destroy.assert_called_once_with()
            pet.close_app()
            pet.plugin_manager.shutdown.assert_called_once_with()

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("prlimit"),
                         "bubblewrap and prlimit are needed for resource limit tests")
    def test_external_plugin_cpu_limit_kills_process_and_cleans_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = self.make_external_process(directory, "while True: pass\n",
                                                cpu_seconds=1, timeout=5)
            spawned = []
            popen = __import__("plugin_manager").subprocess.Popen
            def capture(*args, **kwargs):
                process = popen(*args, **kwargs)
                spawned.append(process)
                return process
            started = time.monotonic()
            with mock.patch("plugin_manager.subprocess.Popen", side_effect=capture):
                with self.assertRaises(RuntimeError):
                    plugin.request("burn")
            self.assertLess(time.monotonic() - started, 5)
            self.assertEqual(len(spawned), 1)
            self.assertIsNotNone(spawned[0].poll())
            spawned[0].wait(timeout=1)
            with self.assertRaises(ProcessLookupError):
                os.killpg(spawned[0].pid, 0)

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("prlimit"),
                         "bubblewrap and prlimit are needed for resource limit tests")
    def test_external_plugin_memory_limit_is_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            script = (
                "import json\n"
                "try:\n"
                " memory=bytearray(256*1024*1024); result='allocated'\n"
                "except MemoryError:\n"
                " result='limited'\n"
                "print(json.dumps({'protocol':1,'ok':True,'result':result}))\n"
            )
            plugin = self.make_external_process(
                directory, script, memory_bytes=64 * 1024 * 1024, timeout=5,
            )
            self.assertEqual(plugin.request("allocate"), "limited")

    @unittest.skipUnless(shutil.which("bwrap") and shutil.which("prlimit"),
                         "bubblewrap and prlimit are needed for resource limit tests")
    def test_external_plugin_process_limit_is_enforced_and_children_are_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            script = (
                "import json,subprocess,sys\n"
                "children=[]\n"
                "try:\n"
                " for _ in range(40):\n"
                "  children.append(subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)']))\n"
                "except OSError:\n"
                " pass\n"
                "count=len(children)\n"
                "for child in children:\n"
                " child.terminate()\n"
                "for child in children:\n"
                " child.wait(timeout=1)\n"
                "print(json.dumps({'protocol':1,'ok':True,'result':count}))\n"
            )
            plugin = self.make_external_process(directory, script, timeout=5)
            count = plugin.request("fork")
            self.assertLessEqual(count, 31)


if __name__ == "__main__":
    unittest.main()
