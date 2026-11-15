#!/usr/bin/env python3
"""Login, lockout, and role checks."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import store
from auth import login
from proxy import PortalHandler


class LoginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.prev_data = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.tmp.name
        store.reconnect()

    def tearDown(self) -> None:
        if self.prev_data is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.prev_data
        store.reconnect()
        self.tmp.cleanup()

    def test_demo_admin_and_lockout(self) -> None:
        ok = login("admin", "admin123")
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["role"], "admin")
        self.assertNotIn("admin123", json.dumps(ok))
        for _ in range(4):
            bad = login("agent1", "nope")
            self.assertEqual(bad["status"], 401)
        locked = login("agent1", "nope")
        self.assertEqual(locked["status"], 429)
        self.assertIn("5 分钟", locked["error"])
        still = login("agent1", "agent123")
        self.assertEqual(still["status"], 429)


class HttpAuthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.prev_data = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.tmp.name
        store.reconnect()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), PortalHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self.prev_data is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.prev_data
        store.reconnect()
        self.tmp.cleanup()

    def _exchange(self, method: str, path: str, payload: dict | None = None, cookie: str = "") -> tuple[int, dict, str]:
        body = b"" if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(method, path, body, headers)
        resp = conn.getresponse()
        raw = resp.read()
        set_cookie = resp.getheader("Set-Cookie") or ""
        conn.close()
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {"raw": raw.decode("utf-8", "replace")}
        return resp.status, data, set_cookie

    def test_agent_cannot_open_admin_api(self) -> None:
        status, _data, cookie = self._exchange("POST", "/api/login", {"username": "agent1", "password": "agent123"})
        self.assertEqual(status, 200)
        token = cookie.split(";", 1)[0]
        status, data, _cookie = self._exchange("GET", "/api/admin/config", cookie=token)
        self.assertEqual(status, 403)
        self.assertIn("管理员", data["error"])
        status, data, _cookie = self._exchange("GET", "/api/agent/tickets?status=waiting", cookie=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["tickets"], [])
        bare, _data, _cookie = self._exchange("GET", "/api/admin/audit")
        self.assertEqual(bare, 401)


if __name__ == "__main__":
    unittest.main()
