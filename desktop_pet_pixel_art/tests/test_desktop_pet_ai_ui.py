import queue
import sys
import threading
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from tkinter import ttk

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_pet_ai import DesktopPetAIMixin
from providers.tool_contract import ToolCall


class _UiPet(DesktopPetAIMixin):
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self._closing = False
        self.callbacks = queue.Queue()
        definition = SimpleNamespace(
            tool=SimpleNamespace(description="Move arquivos após aprovação."),
            read_only=False,
        )
        self.aurova_integration = SimpleNamespace(
            cognition=SimpleNamespace(dispatcher=SimpleNamespace(
                registry=SimpleNamespace(get=lambda _name: definition)
            ))
        )

    def _set_aurova_window_icon(self, window):
        return window

    def post_ui_callback(self, callback, *args, **kwargs):
        self.callbacks.put((callback, args, kwargs))
        return True

    def close(self):
        self._closing = True
        self.root.destroy()


def _walk(widget):
    try:
        children = tuple(widget.winfo_children())
    except tk.TclError:
        return
    for child in children:
        try:
            if not child.winfo_exists():
                continue
        except tk.TclError:
            continue
        yield child
        yield from _walk(child)


def _cancel_pending_after(root):
    try:
        after_ids = root.tk.call("after", "info")
    except tk.TclError:
        return
    for after_id in after_ids:
        try:
            root.after_cancel(after_id)
        except tk.TclError:
            pass


class DesktopPetConfirmationUiTests(unittest.TestCase):
    def make_pet(self):
        try:
            return _UiPet()
        except tk.TclError as exc:
            self.skipTest(f"Tk display indisponível: {exc}")

    def test_confirmation_buttons_return_distinct_decisions_without_blocking_tk(self):
        for selected, expected in (("Aprovar", "approve"), ("Negar", "deny"),
                                   ("Cancelar", "cancel")):
            with self.subTest(button=selected):
                pet = self.make_pet()
                event = threading.Event()
                decision = {"value": "cancel"}
                call = ToolCall("ui-call-1", "files.organize_downloads", {"plan": []})
                worker_result = {}
                worker = threading.Thread(target=lambda: worker_result.setdefault(
                    "value", pet._operational_confirmation(call, event, timeout_seconds=2)
                ), daemon=True)
                worker.start()
                heartbeat = {"count": 0, "clicked": False, "scheduled": False}

                def keep_ui_responsive():
                    heartbeat["count"] += 1
                    if worker.is_alive():
                        pet.root.after(10, keep_ui_responsive)

                def click_button():
                    for widget in _walk(pet.root):
                        if isinstance(widget, ttk.Button) and widget.cget("text") == selected:
                            heartbeat["clicked"] = True
                            widget.invoke()
                            return

                def pump_ui():
                    while True:
                        try:
                            callback, args, kwargs = pet.callbacks.get_nowait()
                        except queue.Empty:
                            break
                        callback(*args, **kwargs)
                    if not heartbeat["clicked"] and not heartbeat["scheduled"]:
                        heartbeat["scheduled"] = True
                        pet.root.after(100, click_button)
                    if worker.is_alive():
                        pet.root.after(10, pump_ui)
                    else:
                        pet.root.quit()

                pet.root.after(0, keep_ui_responsive)
                pet.root.after(0, pump_ui)
                pet.root.after(2500, pet.root.quit)
                pet.root.mainloop()
                _cancel_pending_after(pet.root)
                worker.join(timeout=1)
                self.assertFalse(worker.is_alive())
                self.assertEqual(worker_result.get("value"), expected)
                self.assertGreater(heartbeat["count"], 1)
                pet.close()

    def test_progress_cancel_button_signals_without_waiting_for_worker(self):
        pet = self.make_pet()
        cancellation = threading.Event()
        pet._start_ai_progress(cancellation)
        self.assertTrue(pet._ai_progress_dialog.winfo_exists())
        pet._ai_progress_cancel_button.invoke()
        self.assertTrue(cancellation.is_set())
        self.assertEqual(str(pet._ai_progress_cancel_button.cget("state")), "disabled")
        pet._close_ai_progress()
        self.assertIsNone(pet._ai_progress_dialog)
        pet.close()

    def test_request_cancel_closes_pending_confirmation_and_releases_worker(self):
        pet = self.make_pet()
        cancellation = threading.Event()
        call = ToolCall("ui-cancel-1", "files.organize_downloads", {"plan": []})
        result = {}
        worker = threading.Thread(target=lambda: result.setdefault(
            "decision", pet._operational_confirmation(call, cancellation, timeout_seconds=2)
        ), daemon=True)
        worker.start()
        ticks = {"count": 0}

        def tick():
            while True:
                try:
                    callback, args, kwargs = pet.callbacks.get_nowait()
                except queue.Empty:
                    break
                callback(*args, **kwargs)
            ticks["count"] += 1
            if worker.is_alive():
                pet.root.after(10, tick)
            else:
                pet.root.quit()

        pet.root.after(75, cancellation.set)
        pet.root.after(0, tick)
        pet.root.after(2500, pet.root.quit)
        pet.root.mainloop()
        _cancel_pending_after(pet.root)
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result.get("decision"), "cancel")
        self.assertGreater(ticks["count"], 1)
        pet.close()

    def test_application_close_cancels_active_confirmation(self):
        pet = self.make_pet()
        cancellation = threading.Event()
        call = ToolCall("ui-close-1", "files.organize_downloads", {"plan": []})
        result = {}
        worker = threading.Thread(target=lambda: result.setdefault(
            "decision", pet._operational_confirmation(call, cancellation, timeout_seconds=2)
        ), daemon=True)
        worker.start()

        def pump_and_close():
            while True:
                try:
                    callback, args, kwargs = pet.callbacks.get_nowait()
                except queue.Empty:
                    break
                callback(*args, **kwargs)
            pet._cancel_operational_confirmation()
            pet.root.quit()

        pet.root.after(0, pump_and_close)
        pet.root.mainloop()
        _cancel_pending_after(pet.root)
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result.get("decision"), "cancel")
        pet.close()


if __name__ == "__main__":
    unittest.main()
