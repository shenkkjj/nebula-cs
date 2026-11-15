#!/usr/bin/env python3
"""Ticket queue, takeover, reply, close, writeback failure, and bad cases."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import agent_api
import store
from passwords import hash_password


def _user(username: str) -> dict:
    row = store.get_user_by_name(username)
    assert row is not None
    return {
        "user_id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
    }


class AgentApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.tmp.name
        store.reconnect()
        self.bad_path = agent_api.BAD_CASES_PATH
        agent_api.BAD_CASES_PATH = Path(self.tmp.name) / "bad-cases.json"
        conn = store.connection()
        conn.execute(
            "INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, 'agent', ?)",
            ("agent2", hash_password("agent123"), "李老师"),
        )
        conn.commit()
        self.ticket = store.create_ticket("visitor-a", "session-a", "refusal", "怎么请病假？")

    def tearDown(self) -> None:
        agent_api.BAD_CASES_PATH = self.bad_path
        if self.prev is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.prev
        store.reconnect()
        self.tmp.cleanup()

    def test_take_reply_and_required_close_note(self) -> None:
        agent = _user("agent1")
        other = _user("agent2")
        status, _payload = agent_api.reply(self.ticket["public_id"], agent, "先别发")
        self.assertEqual(status, 403)
        status, payload = agent_api.take(self.ticket["public_id"], agent)
        self.assertEqual(status, 200)
        self.assertEqual(payload["ticket"]["assignee_name"], "王老师")
        status, conflict = agent_api.take(self.ticket["public_id"], other)
        self.assertEqual(status, 409)
        self.assertIn("王老师", conflict["error"])
        status, empty = agent_api.reply(self.ticket["public_id"], agent, "  ")
        self.assertEqual(status, 400)
        status, replied = agent_api.reply(self.ticket["public_id"], agent, "先在一网通办提交请假。")
        self.assertEqual(status, 200)
        self.assertTrue(any(item["role"] == "agent" for item in replied["messages"]))
        status, denied = agent_api.close(self.ticket["public_id"], agent, "   ")
        self.assertEqual(status, 400)
        self.assertIn("处理说明", denied["error"])
        status, closed = agent_api.close(self.ticket["public_id"], agent, "已告知流程。")
        self.assertEqual(status, 200)
        self.assertEqual(closed["ticket"]["status"], "closed")
        waiting = agent_api.queue("waiting")
        self.assertEqual(waiting["counts"]["closed"], 1)

    def test_writeback_keeps_a_draft_without_dify(self) -> None:
        os.environ.pop("DIFY_DATASET_API_KEY", None)
        os.environ.pop("DIFY_DATASET_ID", None)
        agent = _user("agent1")
        status, empty = agent_api.writeback(self.ticket["public_id"], agent, "", "答")
        self.assertEqual(status, 400)
        status, saved = agent_api.writeback(self.ticket["public_id"], agent, "怎么请病假？", "先走一网通办。")
        self.assertEqual(status, 503)
        self.assertEqual(saved["writeback"]["status"], "failed")
        self.assertIn("草稿", saved["error"])
        self.assertEqual(saved["writeback"]["question"], "怎么请病假？")

    def test_bad_case_requires_a_type_and_dedupes(self) -> None:
        message_id = store.add_message("visitor-a", "bot", "知识库里没有。", "session-a", self.ticket["id"], author="校园助手")
        agent = _user("agent1")
        status, _missing = agent_api.mark_bad_case(agent, message_id, "", "")
        self.assertEqual(status, 400)
        status, first = agent_api.mark_bad_case(agent, message_id, "over-refuse", "应该说明没有病假条目")
        self.assertEqual(status, 200)
        status, second = agent_api.mark_bad_case(agent, message_id, "other", "改成其他")
        self.assertEqual(status, 200)
        self.assertEqual(first["bad_case"]["id"], second["bad_case"]["id"])
        rows = agent_api._read_bad_cases()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "other")


if __name__ == "__main__":
    unittest.main()
