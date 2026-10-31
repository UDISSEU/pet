import concurrent.futures
import http.cookiejar
import json
import socket
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from frontend_bridge import FrontendBridge, validate_rpc_message


class TestFrontendBridge(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.frontend = root / "frontend"
        self.frontend.mkdir()
        (self.frontend / "index.html").write_text("<main>Nova UI</main>", encoding="utf-8")
        (self.frontend / "app.css").write_text("body{color:#123}", encoding="utf-8")
        (self.frontend / "app.js").write_text("'use strict';", encoding="utf-8")
        self.icon = root / "nova.png"
        self.icon.write_bytes(b"png-test")
        self.bridge = FrontendBridge(self.frontend, self.icon, rpc_timeout=2)
        self.bridge.start()
        self.origin = self.bridge.origin
        self.cookie = self._open_session()

    def tearDown(self):
        self.bridge.close()
        self.tempdir.cleanup()

    def _open_session(self):
        token = self.bridge.launch_url.rsplit("#", 1)[1]
        request = urllib.request.Request(
            f"{self.origin}/api/v1/session",
            data=b"",
            headers={"Origin": self.origin, "Authorization": f"Bearer {token}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("HttpOnly", response.headers["Set-Cookie"])
            self.assertIn("SameSite=Strict", response.headers["Set-Cookie"])
            return response.headers["Set-Cookie"].split(";", 1)[0]

    def _rpc_request(self, payload, *, cookie=None, origin=None):
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Origin": origin or self.origin,
            "Content-Type": "application/json",
        }
        if cookie is not None:
            headers["Cookie"] = cookie
        return urllib.request.Request(
            f"{self.origin}/api/v1/rpc", data=data, headers=headers, method="POST",
        )

    def test_rpc_schema_allows_only_known_versioned_operations(self):
        request_id = str(uuid.uuid4())
        call = validate_rpc_message({
            "version": 1,
            "id": request_id,
            "op": "state.get",
            "payload": {},
        })
        self.assertEqual((call.request_id, call.operation), (request_id, "state.get"))
        invalid = (
            {"version": 1, "id": request_id, "op": "shell.exec", "payload": {}},
            {"version": 1, "id": request_id, "op": "state.get", "payload": [], "extra": 1},
            {"version": 2, "id": request_id, "op": "state.get", "payload": {}},
            {"version": 1, "id": "not-an-id", "op": "state.get", "payload": {}},
        )
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                validate_rpc_message(item)

    def test_static_files_are_allowlisted_and_use_security_headers(self):
        request = urllib.request.Request(f"{self.origin}/")
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertIn("Nova UI", response.read().decode("utf-8"))
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{self.origin}/private-file", timeout=2)
        self.assertEqual(caught.exception.code, 404)

    def test_session_bootstrap_is_one_time_and_rpc_requires_its_cookie(self):
        token = self.bridge.launch_url.rsplit("#", 1)[1]
        request = urllib.request.Request(
            f"{self.origin}/api/v1/session", data=b"",
            headers={"Origin": self.origin, "Authorization": f"Bearer {token}"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 403)

        request_id = str(uuid.uuid4())
        payload = {"version": 1, "id": request_id, "op": "state.get", "payload": {}}
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self._rpc_request(payload), timeout=2)
        self.assertEqual(caught.exception.code, 403)

    def test_rpc_rejects_wrong_origin_and_invalid_operations(self):
        payload = {"version": 1, "id": str(uuid.uuid4()), "op": "state.get", "payload": {}}
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self._rpc_request(payload, cookie=self.cookie, origin="http://evil.invalid"), timeout=2)
        self.assertEqual(caught.exception.code, 403)

        payload["op"] = "shell.exec"
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self._rpc_request(payload, cookie=self.cookie), timeout=2)
        self.assertEqual(caught.exception.code, 400)
        self.assertTrue(self.bridge.requests.empty())

    def test_rpc_correlates_concurrent_responses_out_of_order(self):
        request_ids = [str(uuid.uuid4()), str(uuid.uuid4())]

        def send(request_id):
            payload = {"version": 1, "id": request_id, "op": "state.get", "payload": {}}
            with urllib.request.urlopen(self._rpc_request(payload, cookie=self.cookie), timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(send, request_id) for request_id in request_ids]
            calls = []
            deadline = time.monotonic() + 1
            while len(calls) < 2 and time.monotonic() < deadline:
                calls.extend(self.bridge.drain_requests(limit=2 - len(calls)))
                if len(calls) < 2:
                    time.sleep(0.005)
            self.assertEqual({call.request_id for call in calls}, set(request_ids))
            for call in reversed(calls):
                call.complete(result={"request_id": call.request_id})
            results = [future.result(timeout=2) for future in futures]
        self.assertEqual({result["id"] for result in results}, set(request_ids))
        self.assertTrue(all(result["result"]["request_id"] == result["id"] for result in results))

    def test_duplicate_request_ids_cannot_repeat_a_local_operation(self):
        request_id = str(uuid.uuid4())
        payload = {"version": 1, "id": request_id, "op": "state.get", "payload": {}}
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            request = self._rpc_request(payload, cookie=self.cookie)
            future = executor.submit(lambda: urllib.request.urlopen(request, timeout=2))
            call = None
            deadline = time.monotonic() + 1
            while call is None and time.monotonic() < deadline:
                calls = self.bridge.drain_requests()
                call = calls[0] if calls else None
                if call is None:
                    time.sleep(0.005)
            self.assertIsNotNone(call)
            call.complete(result={"ok": True})
            with future.result(timeout=2) as response:
                self.assertEqual(json.loads(response.read())["id"], request_id)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self._rpc_request(payload, cookie=self.cookie), timeout=2)
        self.assertEqual(caught.exception.code, 409)

    def test_timed_out_calls_are_not_dispatched_after_the_client_gives_up(self):
        self.bridge.close()
        self.bridge = FrontendBridge(self.frontend, self.icon, rpc_timeout=0.05)
        self.bridge.start()
        self.origin = self.bridge.origin
        self.cookie = self._open_session()
        payload = {"version": 1, "id": str(uuid.uuid4()), "op": "state.get", "payload": {}}
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self._rpc_request(payload, cookie=self.cookie), timeout=1)
        self.assertEqual(caught.exception.code, 504)
        self.assertEqual(self.bridge.drain_requests(), [])

    def test_incomplete_http_request_is_closed_after_client_timeout(self):
        self.bridge.close()
        self.bridge = FrontendBridge(
            self.frontend, self.icon, rpc_timeout=2, client_timeout=0.1,
        )
        self.bridge.start()
        self.origin = self.bridge.origin
        connection = socket.create_connection(("127.0.0.1", self.bridge.server.server_port), timeout=1)
        try:
            connection.settimeout(1)
            connection.sendall(b"GET / HTTP/1.1")
            try:
                response = connection.recv(1)
            except ConnectionResetError:
                response = b""
            self.assertEqual(response, b"")
        finally:
            connection.close()

    def test_server_rejects_connections_above_its_thread_limit(self):
        limited = FrontendBridge(self.frontend, self.icon, max_clients=1)
        slots = limited.server._client_slots
        self.assertTrue(slots.acquire(blocking=False))
        request = Mock()
        try:
            with patch.object(limited.server, "shutdown_request") as shutdown:
                limited.server.process_request(request, ("127.0.0.1", 12345))
            shutdown.assert_called_once_with(request)
        finally:
            slots.release()
            limited.server.server_close()


if __name__ == "__main__":
    unittest.main()
