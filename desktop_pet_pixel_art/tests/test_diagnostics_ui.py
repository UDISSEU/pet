import sys
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from diagnostics_ui import diagnostic_recommendations, open_diagnostics_window
from environment_check import EnvironmentReport


def report(**changes):
    values = {
        "python_version": "3.12.3",
        "python_supported": True,
        "dependencies": {
            "Pillow": True,
            "OpenCV": True,
            "NumPy": True,
            "psutil": True,
        },
        "ollama_status": "ready",
        "selected_model": "llama3.2:1b",
        "database_status": "ready",
        "personality_status": "available",
        "graphics_status": "ready",
        "graphics_available": 16,
        "graphics_total": 16,
        "free_disk_bytes": 4 * 1024 ** 3,
        "memory_total_bytes": 4 * 1024 ** 3,
        "cpu_count": 4,
    }
    values.update(changes)
    return EnvironmentReport(**values)


class DiagnosticsGuidanceTests(unittest.TestCase):
    def test_healthy_system_needs_no_repair(self):
        guidance = diagnostic_recommendations(report())
        self.assertEqual(len(guidance), 1)
        self.assertIn("nenhuma ação", guidance[0])

    def test_missing_dependencies_recommend_install_after_closing_application(self):
        guidance = diagnostic_recommendations(report(
            dependencies={"Pillow": True, "OpenCV": False, "NumPy": True, "psutil": True},
        ))
        self.assertTrue(any("Feche a Nova" in item and "./install.sh" in item for item in guidance))
        self.assertTrue(any("OpenCV" in item for item in guidance))

    def test_model_repair_requires_preferences_confirmation(self):
        guidance = diagnostic_recommendations(report(ollama_status="model_missing"))
        self.assertTrue(any("download exige confirmação" in item for item in guidance))

    def test_database_failure_never_recommends_reset_or_deletion(self):
        guidance = diagnostic_recommendations(report(database_status="corrupt"))
        self.assertTrue(any("não tentará recriar nem apagar" in item for item in guidance))
        self.assertFalse(any("apague" in item.lower() or "redefina" in item.lower() for item in guidance))

    def test_degraded_memory_health_recommends_preserving_backups(self):
        guidance = diagnostic_recommendations(
            report(), memory_health={"status": "degraded", "integrity_check": "failed"}
        )
        self.assertTrue(any("Preserve os backups" in item for item in guidance))


class DiagnosticsWindowTests(unittest.TestCase):
    def test_back_button_is_visible_and_calls_navigation_callback(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display unavailable: {exc}")

        calls = []
        checker_finished = threading.Event()

        def check_environment_for_test():
            result = report()
            checker_finished.set()
            return result

        try:
            window = open_diagnostics_window(
                root,
                checker=check_environment_for_test,
                on_open=lambda opened: calls.append(("open", opened)),
                on_back=lambda opened: calls.append(("back", opened)),
            )
            root.update_idletasks()
            root.update()
            recheck_button = next(
                widget for widget in window.winfo_children()[1].winfo_children()
                if isinstance(widget, ttk.Frame)
                for child in widget.winfo_children()
                if isinstance(child, ttk.Button)
                and child.cget("text") == "Verificar novamente"
            )
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                root.update()
                if checker_finished.is_set() and recheck_button.instate(["!disabled"]):
                    break
                time.sleep(0.01)
            self.assertTrue(checker_finished.is_set())
            self.assertTrue(recheck_button.instate(["!disabled"]))

            back_button = next(
                widget for widget in window.winfo_children()[0].winfo_children()
                if isinstance(widget, tk.Frame)
                for widget in widget.winfo_children()
                if isinstance(widget, tk.Button) and widget.cget("text") == "← Voltar"
            )
            self.assertTrue(back_button.winfo_ismapped())
            self.assertGreaterEqual(back_button.winfo_rootx(), window.winfo_rootx())
            self.assertGreaterEqual(back_button.winfo_rooty(), window.winfo_rooty())
            self.assertLessEqual(
                back_button.winfo_rootx() + back_button.winfo_width(),
                window.winfo_rootx() + window.winfo_width(),
            )
            self.assertLessEqual(
                back_button.winfo_rooty() + back_button.winfo_height(),
                window.winfo_rooty() + window.winfo_height(),
            )
            self.assertEqual(calls, [("open", window)])

            back_button.invoke()
            self.assertEqual(calls[-1], ("back", window))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
