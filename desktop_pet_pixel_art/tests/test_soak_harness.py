import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SoakHarnessTests(unittest.TestCase):
    def test_short_run_records_real_service_and_process_metrics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "soak.jsonl"
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "nova_soak.py"),
                 "--scenario", "30m", "--duration-seconds", "0.15",
                 "--sample-interval", "0.03", "--target-pid", str(os.getpid()),
                 "--output", str(report)],
                cwd=ROOT, capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(line) for line in report.read_text().splitlines()]
            samples = [row for row in rows if row["kind"] == "sample"]
            summary = rows[-1]
            self.assertTrue(samples)
            self.assertIn("process_memory", samples[0])
            self.assertIn("cpu_percent", samples[0])
            self.assertIn("threads", samples[0])
            self.assertIn("event_queue", samples[0])
            self.assertIn("nova_cpu_percent", samples[0])
            self.assertIn("nova_memory", samples[0])
            self.assertIn("nova_worker_threads_estimate", samples[0])
            self.assertLessEqual(summary["notification_history_final"], 200)
            self.assertLessEqual(summary["monitor_history_final"], 120)
            self.assertTrue(summary["worker_stopped"])
            self.assertEqual(summary["children_after_worker_exit"], 0)


if __name__ == "__main__":
    unittest.main()
