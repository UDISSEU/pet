"""Focused safety tests for disk, log and assisted cleanup services."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from computer_maintenance import (
    _QueryCancelled, _run_cancellable_command, analyze_cleanup, collect_logs,
    delete_cleanup_items, inspect_disks,
)


class DiskHealthTests(unittest.TestCase):
    def test_missing_smartctl_reports_unavailable_without_escalation(self):
        lsblk_data = json.dumps({"blockdevices": [{"name": "sda", "path": "/dev/sda", "type": "disk", "size": 1000}]})
        run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=lsblk_data, stderr=""))
        result = inspect_disks(run=run, which=lambda name: "/usr/bin/lsblk" if name == "lsblk" else None)
        self.assertEqual(result["devices"][0]["smart_state"], "indisponível")
        self.assertIn("não está instalado", result["devices"][0]["detail"])
        self.assertEqual(run.call_count, 1)

    def test_smart_data_and_permission_error_are_not_fabricated(self):
        inventory = json.dumps({"blockdevices": [{"name": "nvme0n1", "path": "/dev/nvme0n1", "type": "disk", "size": 2048}]})
        responses = [SimpleNamespace(returncode=0, stdout=inventory, stderr=""),
                     SimpleNamespace(returncode=2, stdout="{}", stderr="Permission denied")]
        with mock.patch("computer_maintenance._valid_block_path", return_value=True):
            result = inspect_disks(run=mock.Mock(side_effect=responses), which=lambda name: "/sbin/" + name)
        self.assertEqual(result["devices"][0]["smart_state"], "indisponível")
        self.assertIn("Permissão adicional necessária", result["devices"][0]["detail"])
        self.assertIsNone(result["devices"][0]["temperature_c"])

    def test_smartctl_exit_bits_distinguish_failure_from_query_errors(self):
        inventory = json.dumps({"blockdevices": [{
            "name": "sda", "path": "/dev/sda", "type": "disk", "size": 1000,
        }]})
        expected = {
            0: "saudável", 0x01: "indisponível", 0x02: "indisponível",
            0x04: "indisponível", 0x08: "crítico", 0x10: "crítico",
            0x20: "atenção", 0x40: "atenção", 0x80: "atenção",
        }
        for code, state in expected.items():
            with self.subTest(exit_status=code):
                responses = [
                    SimpleNamespace(returncode=0, stdout=inventory, stderr=""),
                    SimpleNamespace(returncode=code,
                                    stdout=json.dumps({"smart_status": {"passed": True}}),
                                    stderr=""),
                ]
                with mock.patch("computer_maintenance._valid_block_path", return_value=True):
                    result = inspect_disks(
                        run=mock.Mock(side_effect=responses),
                        which=lambda name: "/usr/bin/" + name,
                    )
                self.assertEqual(result["devices"][0]["smart_state"], state)

    def test_cancellable_smart_command_terminates_its_child(self):
        cancellation = threading.Event()
        spawned = []
        started = threading.Event()
        actual_popen = subprocess.Popen

        def capture(*args, **kwargs):
            process = actual_popen(*args, **kwargs)
            spawned.append(process)
            started.set()
            return process

        outcome = []
        def run_query():
            try:
                _run_cancellable_command(
                    [sys.executable, "-c", "import time; time.sleep(10)"],
                    timeout=15, cancel_event=cancellation, popen=capture,
                )
            except Exception as exc:
                outcome.append(exc)

        worker = threading.Thread(target=run_query)
        worker.start()
        self.assertTrue(started.wait(2))
        cancellation.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertIsInstance(outcome[0], _QueryCancelled)
        self.assertIsNotNone(spawned[0].poll())


class LogCenterTests(unittest.TestCase):
    def test_empty_logs_and_secret_redaction_and_bounded_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "absent.log"
            self.assertEqual(collect_logs(app_log=missing, which=lambda _name: None), [])
            path = Path(temporary) / "aurova.log"
            path.write_text("2026-01-01 INFO app: started\n2026-01-02 ERROR app: token=abc123 password:hello\n", encoding="utf-8")
            rows = collect_logs(app_log=path, which=lambda _name: None, max_records=1)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("abc123", rows[0]["message"])
        self.assertNotIn("hello", rows[0]["message"])


class CleanupSafetyTests(unittest.TestCase):
    def test_analyzer_finds_stale_owned_cache_and_cancels(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            cache = home / ".cache" / "old-app"
            cache.mkdir(parents=True)
            data = cache / "cache.bin"
            data.write_bytes(b"12345")
            old = time.time() - 10 * 86400
            os.utime(cache, (old, old)); os.utime(data, (old, old))
            with mock.patch("computer_maintenance.Path.home", return_value=home):
                result = analyze_cleanup(max_entries=20, max_seconds=2)
                cancel = threading.Event(); cancel.set()
                cancelled = analyze_cleanup(cancel_event=cancel)
        self.assertIn(str(cache), [item["path"] for item in result["items"]])
        self.assertTrue(cancelled["cancelled"])

    def test_delete_rejects_outside_paths_and_symlink_trees_without_partial_removal(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            root = Path(temporary) / "cache-dir"
            root.mkdir()
            safe = root / "safe.txt"; safe.write_text("keep", encoding="utf-8")
            target = Path("/etc/hostname")
            original = target.read_text(encoding="utf-8")
            (root / "linked").symlink_to(target)
            result = delete_cleanup_items([str(root), str(target)])
            self.assertEqual(len(result["errors"]), 2)
            self.assertTrue(safe.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_delete_cancellation_and_valid_item(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            item = Path(temporary) / "old.tmp"
            item.write_text("cache", encoding="utf-8")
            result = delete_cleanup_items([str(item)])
        self.assertEqual(result["removed"], [str(item)])
        self.assertFalse(item.exists())
        cancel = threading.Event(); cancel.set()
        self.assertTrue(delete_cleanup_items(["/tmp/missing"], cancel_event=cancel)["cancelled"])

    def test_delete_refuses_items_not_owned_by_current_user(self):
        with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
            item = Path(temporary) / "owned.tmp"
            item.write_text("data", encoding="utf-8")
            with mock.patch("computer_maintenance.os.getuid", return_value=os.getuid() + 1):
                result = delete_cleanup_items([str(item)])
            self.assertTrue(item.exists())
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("Proprietário", result["errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
