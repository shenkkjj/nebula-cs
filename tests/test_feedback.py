#!/usr/bin/env python3
"""Portal ratings: create, change, and refuse someone else's message."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import admin_api
import agent_api
import store
from feedback import submit_feedback


class FeedbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.tmp.name
        store.reconnect()
        store.create_visitor("visitor-a")
        store.create_visitor("visitor-b")
        store.add_message("visitor-a", "user", "在读证明怎么开？", "session-a")
        self.message_id = store.add_message("visitor-a", "bot", "到一网通办办理。", "session-a", author="校园助手")

    def tearDown(self) -> None:
        if self.prev is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.prev
        store.reconnect()
        self.tmp.cleanup()

    def test_create_then_change_rating(self) -> None:
        status, first = submit_feedback("visitor-a", self.message_id, True, portal_session="session-a")
        self.assertEqual(status, 200)
        self.assertTrue(first["helpful"])
        status, second = submit_feedback("visitor-a", self.message_id, False, comment="没写窗口", portal_session="session-a")
        self.assertEqual(status, 200)
        self.assertFalse(second["helpful"])
        rows = store.list_feedback()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["helpful"])
        self.assertEqual(rows[0]["question"], "在读证明怎么开？")
        self.assertIn("一网通办", rows[0]["answer"])
        audits = store.list_audit(kind="feedback")
        self.assertGreaterEqual(len(audits), 2)

    def test_cannot_rate_another_visitors_message(self) -> None:
        status, payload = submit_feedback("visitor-b", self.message_id, False, portal_session="session-a")
        self.assertEqual(status, 403)
        self.assertFalse(payload["ok"])
        self.assertEqual(store.list_feedback(), [])

    def test_wrong_session_is_rejected(self) -> None:
        status, _payload = submit_feedback("visitor-a", self.message_id, True, portal_session="other-session")
        self.assertEqual(status, 403)
        self.assertEqual(store.list_feedback(), [])

    def test_overview_counts_the_whole_seven_day_window(self) -> None:
        for i in range(503):
            message_id = store.add_message("visitor-a", "bot", "办理答复", "session-a")
            store.upsert_feedback("visitor-a", "session-a", message_id, i % 2 == 0, "")
        old = store.upsert_feedback("visitor-a", "session-a", self.message_id, True, "")
        with store.exclusive():
            conn = store.connection()
            conn.execute("UPDATE feedback SET updated_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", old["id"]))
            conn.commit()
        summary = admin_api.overview()["feedback"]
        self.assertEqual(summary["total"], 503)
        self.assertEqual(summary["helpful"], 252)
        self.assertEqual(summary["unhappy"], 251)

    def test_seven_day_summary_and_bad_case(self) -> None:
        submit_feedback("visitor-a", self.message_id, False, comment="窗口没写", portal_session="session-a")
        summary = admin_api.feedback_summary()
        self.assertEqual(summary["days"], 7)
        self.assertEqual(summary["unhappy"], 1)
        self.assertEqual(summary["helpful"], 0)
        self.assertEqual(summary["unhappy_rate"], 1.0)
        csv_text = admin_api.feedback_csv("0")
        self.assertIn("没解决", csv_text)
        self.assertIn("窗口没写", csv_text)
        previous = agent_api.BAD_CASES_PATH
        agent_api.BAD_CASES_PATH = Path(self.tmp.name) / "bad-cases.json"
        try:
            status, payload = admin_api.promote_feedback({"username": "admin"}, self.message_id, "cite")
        finally:
            agent_api.BAD_CASES_PATH = previous
        self.assertEqual(status, 200)
        self.assertEqual(payload["bad_case"]["kind"], "cite")
        self.assertEqual(payload["bad_case"]["kind_label"], "引用不对")
        self.assertIn("在读证明", payload["bad_case"]["question"])
        refused, _error = admin_api.promote_feedback({"username": "admin"}, self.message_id, "new-kind")
        self.assertEqual(refused, 400)
