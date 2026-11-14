#!/usr/bin/env python3
"""Constraint layer: mask, merge, empty-retrieval block, and a fake Dify."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import store
from constraints import apply_constraints, merge_citations
from dify_client import DifyClient
from gateway import iter_events, run_chat, set_client
from masking import mask_text
from settings import load_config


class _FakeDify(BaseHTTPRequestHandler):
    seen: list[str] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        query = body.get("query") or ""
        _FakeDify.seen.append(query)
        if "病假" in query:
            resources = []
            answer = "随便请就行，不用手续。"
        else:
            resources = [
                {
                    "document_name": "客服样例FAQ.md",
                    "document_id": "faq-1",
                    "dataset_name": "星云大学办事",
                    "segment_id": "a",
                    "score": 0.91,
                    "content": "问：在读证明如何办理？\n登录一网通办，电子版约 3 个工作日。",
                },
                {
                    "document_name": "客服样例FAQ.md",
                    "document_id": "faq-1",
                    "dataset_name": "星云大学办事",
                    "segment_id": "b",
                    "score": 0.72,
                    "content": "纸质版请到行政楼一楼教务处窗口领取。",
                },
            ]
            answer = "在读证明请到一网通办申请，电子版约 3 个工作日。"
        events = [
            {"event": "message", "answer": answer, "conversation_id": "c1", "message_id": "m1", "task_id": "t1"},
            {"event": "message_end", "conversation_id": "c1", "metadata": {"retriever_resources": resources}},
        ]
        raw = "".join("data: " + json.dumps(event, ensure_ascii=False) + "\n\n" for event in events).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args) -> None:
        return


class ConstraintTest(unittest.TestCase):
    def test_mask_phone_and_id(self) -> None:
        masked, notices = mask_text("手机13812345678，证件110101199001011234")
        self.assertIn("手机号", notices)
        self.assertIn("证件号", notices)
        self.assertNotIn("13812345678", masked)
        self.assertNotIn("110101199001011234", masked)
        self.assertIn("138****5678", masked)
        self.assertIn("已隐去", masked)

    def test_merge_keeps_one_card_per_document(self) -> None:
        cards = merge_citations(
            [
                {"document_name": "客服样例FAQ.md", "document_id": "faq", "score": 0.4, "content": "低", "segment_id": "1"},
                {"document_name": "客服样例FAQ.md", "document_id": "faq", "score": 0.9, "content": "高", "segment_id": "2"},
                {"document_name": "另一篇.md", "document_id": "other", "score": 0.8, "content": "另一", "segment_id": "3"},
            ],
            max_cards=3,
        )
        self.assertEqual(len(cards), 2)
        faq = next(card for card in cards if card["document_id"] == "faq")
        self.assertEqual(faq["content"], "高")
        self.assertEqual(faq["score"], 0.9)
        self.assertEqual(len(faq["segments"]), 2)

    def test_empty_retrieval_blocks_model_text(self) -> None:
        cfg = load_config()
        decision = apply_constraints("随便请就行，不用手续。", [], cfg, retrieval_empty=True)
        self.assertTrue(decision["refuse"])
        self.assertEqual(decision["reason"], "empty_retrieval")
        self.assertNotIn("随便请", decision["answer"])
        self.assertIn("知识库里没有", decision["answer"])

    def test_low_score_is_missing_citation(self) -> None:
        cfg = load_config()
        decision = apply_constraints(
            "看起来像回答",
            [{"document_name": "客服样例FAQ.md", "document_id": "faq", "score": 0.1, "content": "片段"}],
            cfg,
        )
        self.assertTrue(decision["refuse"])
        self.assertEqual(decision["reason"], "missing_citation")


class GatewayFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDify)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        store.reconnect()
        store.save_probe(True, [{"name": "probe", "ok": True, "detail": "测试探针"}])
        _FakeDify.seen = []
        set_client(DifyClient(chat_url=f"http://127.0.0.1:{self.port}/v1/chat-messages", app_key="app-test"))

    def tearDown(self) -> None:
        set_client(DifyClient())
        self.tmp.cleanup()

    def test_cited_answer_merges_segments(self) -> None:
        done = run_chat({"query": "在读证明如何办理？", "visitor": "v1", "portal_session": "s1", "user": "v1"})
        self.assertFalse(done["refuse"])
        self.assertEqual(len(done["citations"]), 1)
        self.assertEqual(done["citations"][0]["document_name"], "客服样例FAQ.md")
        self.assertEqual(len(done["citations"][0]["segments"]), 2)
        self.assertIn("3 个工作日", done["answer"])
        self.assertIn("一网通办", done["citations"][0]["content"])

    def test_empty_retrieval_does_not_pass_the_model_answer(self) -> None:
        done = run_chat({"query": "怎么请病假？", "visitor": "v2", "portal_session": "s2", "user": "v2"})
        self.assertTrue(done["refuse"])
        self.assertEqual(done["reason"], "empty_retrieval")
        self.assertNotIn("随便请", done["answer"])
        self.assertTrue(any(item.get("query") == "转人工" for item in done["suggestions"]))

    def test_phone_is_masked_before_dify_and_audit(self) -> None:
        done = run_chat(
            {
                "query": "我的手机是13812345678，在读证明如何办理？",
                "visitor": "v3",
                "portal_session": "s3",
                "user": "v3",
            }
        )
        self.assertTrue(_FakeDify.seen)
        self.assertNotIn("13812345678", _FakeDify.seen[-1])
        self.assertIn("138****5678", _FakeDify.seen[-1])
        self.assertIn("已隐去", done["answer"])
        blob = json.dumps(store.list_audit(), ensure_ascii=False)
        self.assertNotIn("13812345678", blob)

    def test_clarify_greeting_and_off_topic_do_not_call_dify(self) -> None:
        clarify = run_chat({"query": "证明怎么开？", "visitor": "v4", "portal_session": "s4"})
        self.assertEqual(clarify["agent_action"], "clarify")
        self.assertGreaterEqual(len(clarify["suggestions"]), 2)
        self.assertEqual(clarify["citations"], [])
        hello = run_chat({"query": "你好", "visitor": "v4", "portal_session": "s5"})
        self.assertEqual(hello["agent_action"], "assistant_intro")
        self.assertNotIn("引用", hello["answer"])
        poem = run_chat({"query": "帮我写首诗", "visitor": "v4", "portal_session": "s6"})
        self.assertEqual(poem["agent_action"], "scope")
        self.assertEqual(poem["citations"], [])
        self.assertEqual(_FakeDify.seen, [])

    def test_handoff_creates_a_queue_ticket(self) -> None:
        done = run_chat({"query": "转人工", "visitor": "v5", "portal_session": "s7"})
        self.assertTrue(done["handoff"])
        self.assertTrue(str(done["ticket_id"]).startswith("TK"))
        self.assertIn("坐席上线后回复", done["answer"])
        ticket = store.get_ticket(done["ticket_id"])
        self.assertEqual(ticket["status"], "waiting")

    def test_maintenance_registers_a_ticket_and_skips_the_model(self) -> None:
        store.save_probe(False, [{"name": "probe", "ok": False, "detail": "未绑定"}])
        events = list(iter_events({"query": "在读证明如何办理？", "visitor": "v6", "portal_session": "s8"}))
        done = next(event for event in events if event["type"] == "done")
        self.assertTrue(done["maintenance"])
        self.assertTrue(done["ticket_id"])
        self.assertEqual(_FakeDify.seen, [])
        self.assertTrue(any(event["type"] == "delta" for event in events))


if __name__ == "__main__":
    unittest.main()
