import sys
import concurrent.futures
import json
import tempfile
import time
import unittest
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from desktop_pet import DesktopPet
from frontend_bridge import FrontendBridge, RpcCall


class TestFrontendCore(unittest.TestCase):
    def make_pet(self):
        pet = DesktopPet.__new__(DesktopPet)
        pet.history = [{"role": "user", "content": "Oi", "timestamp": "now"}]
        pet.settings = {
            "user_name": "Ana", "ai_provider": "gemini", "gemini_model": "model",
            "online_ai_enabled": True, "mode": "companhia", "reminders": [],
            "GEMINI_API_KEY": "must-not-leak", "memories": [],
            "confirm_app_launch": True,
        }
        pet.ai_request_active = False
        pet.focus_mode = "idle"
        pet.focus_goal = ""
        pet.app_launch_active = False
        pet._pending_frontend_actions = {}
        pet._frontend_calls = {}
        pet._last_user_activity_at = 0
        pet.state = "walk"
        pet._show_idea_icon = True
        pet.show_bubble = Mock()
        pet._video_for_current_pose = Mock(return_value="idle")
        pet._start_app_launch = Mock()
        pet._record_local_interaction = Mock(return_value="Ação registrada")
        return pet

    def test_state_exposes_only_allowlisted_display_fields(self):
        pet = self.make_pet()
        state = pet._frontend_state()
        self.assertEqual(state["history"][0]["index"], 0)
        self.assertEqual(state["history"][0]["content"], pet.history[0]["content"])
        self.assertEqual(state["provider"], "gemini")
        self.assertNotIn("GEMINI_API_KEY", state)
        self.assertNotIn("memories", state)
        self.assertNotIn("settings", state)

    def test_app_confirmation_cancel_never_starts_application(self):
        pet = self.make_pet()
        confirmation_id = "temporary-confirmation"
        pet._pending_frontend_actions[confirmation_id] = {
            "question": "abra editor", "app": {"name": "Editor", "command": "editor"},
            "expires_at": time.monotonic() + 30,
        }
        result = pet._confirm_frontend_action({
            "confirmation_id": confirmation_id, "confirmed": False,
        })
        self.assertEqual(result, {"message": "Abertura cancelada."})
        pet._start_app_launch.assert_not_called()

    def test_app_confirmation_requires_explicit_boolean_and_current_token(self):
        pet = self.make_pet()
        with self.assertRaises(ValueError):
            pet._confirm_frontend_action({"confirmation_id": "x", "confirmed": 1})
        with self.assertRaises(ValueError):
            pet._confirm_frontend_action({"confirmation_id": "expired", "confirmed": True})
        pet._start_app_launch.assert_not_called()

    def test_approved_action_uses_existing_python_launcher(self):
        pet = self.make_pet()
        confirmation_id = "temporary-confirmation"
        app = {"name": "Editor", "command": "editor"}
        pet._pending_frontend_actions[confirmation_id] = {
            "question": "abra editor", "app": app,
            "expires_at": time.monotonic() + 30,
        }
        result = pet._confirm_frontend_action({
            "confirmation_id": confirmation_id, "confirmed": True,
        })
        self.assertEqual(result, {"message": "A Nova está abrindo Editor."})
        pet._start_app_launch.assert_called_once_with("abra editor", app)

    def test_generic_chat_uses_existing_ai_worker_asynchronously(self):
        pet = self.make_pet()
        call = RpcCall("request-id", "chat.send", {"message": "Como você está?"})
        with patch("desktop_pet.save_history", return_value=True), patch("desktop_pet.threading.Thread") as thread:
            self.assertIsNone(pet._handle_frontend_chat(call, "Como você está?"))
        self.assertTrue(pet.ai_request_active)
        self.assertEqual(pet._frontend_calls[call.request_id], call)
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["target"], pet._ask_worker)

    def test_focus_inputs_are_validated_before_reaching_core(self):
        pet = self.make_pet()
        pet.start_focus = Mock(return_value=True)
        call = RpcCall("request-id", "focus.start", {
            "goal": "Escrever", "focus_minutes": True, "break_minutes": 5,
        })
        with self.assertRaises(ValueError):
            pet._handle_frontend_call(call)
        pet.start_focus.assert_not_called()
        call.payload["focus_minutes"] = 25
        result = pet._handle_frontend_call(call)
        pet.start_focus.assert_called_once_with("Escrever", 25, 5)
        self.assertEqual(result["message"], "Sessão de foco iniciada.")

    def test_frontend_history_and_reminder_mutations_persist(self):
        pet = self.make_pet()
        pet.settings["reminders"] = [{"at": "2030-01-01T10:00", "text": "Água", "done": False}]
        with patch("desktop_pet.save_history", return_value=True) as save_history, patch("desktop_pet.save_settings", return_value=True) as save_settings:
            result = pet._handle_frontend_call(RpcCall("id", "history.delete", {"index": 0}))
            self.assertEqual(result["message"], "Histórico atualizado.")
            save_history.assert_called_once_with([])
            pet._handle_frontend_call(RpcCall("id2", "reminder.add", {"at": "2030-01-02T11:30", "text": "Consulta"}))
            pet._handle_frontend_call(RpcCall("id3", "reminder.complete", {"index": 0}))
            pet._handle_frontend_call(RpcCall("id4", "reminder.delete", {"index": 1}))
        self.assertEqual(pet.settings["reminders"], [{"at": "2030-01-01T10:00", "text": "Água", "done": True}])
        self.assertEqual(save_settings.call_count, 3)

    def test_frontend_mutations_reject_bad_inputs_and_roll_back_failed_save(self):
        pet = self.make_pet()
        with self.assertRaises(ValueError):
            pet._handle_frontend_call(RpcCall("id", "reminder.add", {"at": "invalid", "text": "X"}))
        with self.assertRaises(ValueError):
            pet._handle_frontend_call(RpcCall("id", "reminder.delete", {"index": True}))
        with patch("desktop_pet.save_settings", return_value=False):
            with self.assertRaises(ValueError):
                pet._handle_frontend_call(RpcCall("id", "reminder.add", {"at": "2030-01-02T11:30", "text": "Consulta"}))
        self.assertEqual(pet.settings["reminders"], [])
        with patch("desktop_pet.save_history", return_value=False):
            with self.assertRaises(ValueError):
                pet._handle_frontend_call(RpcCall("id", "history.clear", {}))
        self.assertEqual(len(pet.history), 1)

    def test_http_rpc_round_trips_through_the_real_python_core(self):
        pet = self.make_pet()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frontend = root / "frontend"
            frontend.mkdir()
            for name in ("index.html", "app.css", "app.js"):
                (frontend / name).write_text("local", encoding="utf-8")
            icon = root / "icon.png"
            icon.write_bytes(b"local-test-icon")
            bridge = FrontendBridge(frontend, icon, rpc_timeout=2)
            bridge.start()
            try:
                origin = bridge.origin
                token = bridge.launch_url.rsplit("#", 1)[1]
                session_request = urllib.request.Request(
                    f"{origin}/api/v1/session", data=b"",
                    headers={"Origin": origin, "Authorization": f"Bearer {token}"},
                    method="POST",
                )
                with urllib.request.urlopen(session_request, timeout=2) as response:
                    cookie = response.headers["Set-Cookie"].split(";", 1)[0]
                request_id = str(uuid.uuid4())
                body = json.dumps({
                    "version": 1, "id": request_id, "op": "state.get", "payload": {},
                }).encode("utf-8")
                request = urllib.request.Request(
                    f"{origin}/api/v1/rpc", data=body,
                    headers={"Origin": origin, "Cookie": cookie, "Content-Type": "application/json"},
                    method="POST",
                )

                def receive():
                    with urllib.request.urlopen(request, timeout=2) as response:
                        return json.loads(response.read().decode("utf-8"))

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(receive)
                    call = None
                    deadline = time.monotonic() + 1
                    while call is None and time.monotonic() < deadline:
                        calls = bridge.drain_requests()
                        call = calls[0] if calls else None
                        if call is None:
                            time.sleep(0.005)
                    self.assertIsNotNone(call)
                    call.complete(result=pet._handle_frontend_call(call))
                    envelope = future.result(timeout=2)
                self.assertEqual(envelope["id"], request_id)
                self.assertEqual(envelope["result"]["history"][0]["content"], pet.history[0]["content"])
                self.assertNotIn("GEMINI_API_KEY", envelope["result"])
            finally:
                bridge.close()


if __name__ == "__main__":
    unittest.main()
