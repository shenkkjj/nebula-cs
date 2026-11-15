#!/usr/bin/env python3
"""Maintenance banner on a throwaway local server. Does not touch Render or port 8080."""
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

import gateway
import store
from proxy import PortalHandler


class MaintenanceHttpTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = {
            "DATA_DIR": os.environ.get("DATA_DIR"),
            "LITE_MODE": os.environ.get("LITE_MODE"),
            "DIFY_CHAT_URL": os.environ.get("DIFY_CHAT_URL"),
        }
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["LITE_MODE"] = "0"
        os.environ["DIFY_CHAT_URL"] = "http://127.0.0.1:9/v1/chat-messages"
        store.reconnect()
        store.save_probe(False, [{"name": "probe", "ok": False, "detail": "隔离实例"}])
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), PortalHandler)
        self.port = self.httpd.server_address[1]
        self.assertNotEqual(self.port, 8080)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        for key, value in self.prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        store.reconnect()
        self.tmp.cleanup()

    def test_failed_probe_registers_a_ticket_without_calling_upstream(self) -> None:
        body = json.dumps(
            {
                "query": "在读证明如何办理？",
                "stream": False,
                "user": "eval-should-not-matter",
                "eval_run": True,
                "portal_session": "maint-local",
            },
            ensure_ascii=False,
        ).encode("utf-8")

        class _CountingClient:
            def __init__(self) -> None:
                self.calls = 0

            def iter_remote(self, *_args, **_kwargs):
                self.calls += 1
                raise AssertionError("维护态不应调用上游")
                yield None

        counter = _CountingClient()
        previous = gateway._CLIENT
        gateway._CLIENT = counter
        try:
            conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("POST", "/api/chat", body, {"Content-Type": "application/json"})
            resp = conn.getresponse()
            payload = json.loads(resp.read().decode("utf-8"))
            conn.close()
        finally:
            gateway._CLIENT = previous
        self.assertEqual(counter.calls, 0)
        self.assertEqual(resp.status, 200)
        self.assertTrue(payload.get("maintenance"))
        self.assertIn("知识库维护中", payload.get("answer") or "")
        self.assertTrue(str(payload.get("ticket_id") or "").startswith("TK"))
        self.assertEqual(payload.get("citations") or [], [])
        health = HTTPConnection("127.0.0.1", self.port, timeout=10)
        health.request("GET", "/api/health")
        health_body = json.loads(health.getresponse().read().decode("utf-8"))
        health.close()
        self.assertTrue(health_body.get("maintenance"))
        self.assertNotIn("demo_hint", health_body)
        self.assertNotIn("admin123", json.dumps(health_body))
