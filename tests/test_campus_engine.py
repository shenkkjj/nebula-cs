#!/usr/bin/env python3
"""Self-built campus engine: grounded FAQ answers, refusal, handoff, and edits."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import agent_api
import campus_engine
import kb_retrieve
import kb_store
import store


def self_user() -> dict:
    return {"user_id": 1, "username": "admin", "display_name": "陈老师", "role": "admin"}


class CampusEngineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = {
            "DATA_DIR": os.environ.get("DATA_DIR"),
            "ENGINE": os.environ.get("ENGINE"),
            "DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY"),
            "EMBEDDING_API_KEY": os.environ.get("EMBEDDING_API_KEY"),
            "EMBEDDING_BASE_URL": os.environ.get("EMBEDDING_BASE_URL"),
        }
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["ENGINE"] = "campus"
        os.environ["DEEPSEEK_API_KEY"] = ""
        os.environ["EMBEDDING_API_KEY"] = ""
        os.environ["EMBEDDING_BASE_URL"] = ""
        store.reconnect()
        kb_retrieve.set_embedder_for_tests(None)

    def tearDown(self) -> None:
        kb_retrieve.set_embedder_for_tests(None)
        for key, value in self.prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        store.reconnect()
        self.tmp.cleanup()

    def test_sample_faq_is_seeded_and_cited(self) -> None:
        info = kb_store.stats()
        self.assertGreaterEqual(info["segments"], 140)
        self.assertGreaterEqual(info["documents"], 1)
        result = campus_engine.answer("在读证明如何办理？")
        self.assertEqual(result["intent"], "campus_faq")
        self.assertFalse(result["refuse"])
        self.assertIn("一网通办", result["answer"])
        self.assertIn("工作日", result["answer"])
        self.assertIn("[1]", result["answer"])
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["document_name"], "客服样例FAQ.md")
        self.assertEqual(result["matched_title"], "在读证明如何办理？")
        self.assertGreaterEqual(result["citations"][0]["score"], 0.8)

    def test_missing_rule_refuses_without_inventing(self) -> None:
        result = campus_engine.answer("怎么请病假？")
        self.assertTrue(result["refuse"])
        self.assertEqual(result["citations"], [])
        self.assertIn("原因", result["answer"])
        self.assertIn("转人工", result["answer"] + json.dumps(result["suggestions"], ensure_ascii=False))
        self.assertNotIn("一网通办", result["answer"])
        self.assertNotIn("工作日", result["answer"])

    def test_broad_question_asks_once(self) -> None:
        result = campus_engine.answer("申请")
        self.assertEqual(result["agent_action"], "clarify")
        self.assertTrue(result["clarify"])
        self.assertEqual(result["citations"], [])
        self.assertGreaterEqual(len(result["suggestions"]), 2)
        self.assertLessEqual(len(result["suggestions"]), 4)

    def test_follow_up_switches_topic(self) -> None:
        result = campus_engine.answer(
            {
                "query": "那成绩单呢？",
                "history": [
                    {"role": "user", "text": "在读证明如何办理？"},
                    {"role": "assistant", "text": "电子版约 3 个工作日。"},
                    {"role": "user", "text": "那成绩单呢？"},
                ],
                "visitor": "eval-campus",
                "user": "eval-campus",
                "portal_session": "follow-1",
            }
        )
        self.assertEqual(result["rewrite"]["method"], "topic-switch")
        self.assertIn("成绩单", result["rewrite"]["rewritten"])
        self.assertEqual(result["agent_action"], "clarify")
        self.assertEqual(result["citations"], [])
        labels = " ".join(item["label"] for item in result["suggestions"])
        self.assertIn("成绩单如何申请", labels)
        self.assertIn("少了一门课", labels)
        aspect = campus_engine.answer(
            {
                "query": "那多久能下来",
                "history": [{"role": "user", "text": "在读证明如何办理？"}],
                "visitor": "eval-campus",
                "user": "eval-campus",
                "portal_session": "follow-2",
            }
        )
        self.assertEqual(aspect["rewrite"]["method"], "follow-up")
        self.assertEqual(aspect["matched_title"], "在读证明如何办理？")
        self.assertIn("工作日", aspect["answer"])

    def test_everyday_chat_does_not_cite_policy(self) -> None:
        result = campus_engine.answer("帮我写一首关于傍晚的短诗")
        self.assertEqual(result["citations"], [])
        self.assertFalse(result["refuse"])
        self.assertIn("DEEPSEEK_API_KEY", result["answer"])
        self.assertNotIn("一网通办", result["answer"])
        self.assertNotIn("沈凯杰", result["answer"])

    def test_phone_is_masked_before_the_audit(self) -> None:
        result = campus_engine.answer(
            {
                "query": "在读证明如何办理？ 13812345678",
                "visitor": "eval-campus",
                "user": "eval-campus",
                "portal_session": "phone-1",
            }
        )
        self.assertNotIn("13812345678", result["answer"])
        self.assertIn("已隐去", result["answer"])
        self.assertIn("一网通办", result["answer"])
        blob = json.dumps(store.list_audit(kind="qa"), ensure_ascii=False)
        self.assertNotIn("13812345678", blob)
        self.assertIn("138****5678", blob)

    def test_uploaded_segment_can_be_edited_and_deleted(self) -> None:
        created = kb_store.add_text_document(
            "病假.md",
            "## 怎么请病假？\n先在学院辅导员处登记，不要自己编天数。\n",
            source="upload",
        )
        hit = campus_engine.answer("怎么请病假？")
        self.assertFalse(hit["refuse"])
        self.assertIn("辅导员", hit["answer"])
        self.assertEqual(hit["citations"][0]["document_name"], "病假.md")
        segment_id = created["segments"][0]["id"]
        kb_store.update_segment(segment_id, "怎么请病假？", "改为先联系书院值班室。")
        edited = campus_engine.answer("怎么请病假？")
        self.assertIn("书院值班室", edited["answer"])
        self.assertNotIn("辅导员", edited["answer"])
        self.assertTrue(kb_store.delete_segment(segment_id))
        gone = campus_engine.answer("怎么请病假？")
        self.assertTrue(gone["refuse"])
        self.assertEqual(gone["citations"], [])

    def test_writeback_is_retrievable(self) -> None:
        ticket = store.create_ticket("visitor-a", "session-a", "user", "夜班")
        user = {
            "user_id": 1,
            "username": "agent1",
            "display_name": "王老师",
            "role": "agent",
        }
        status, payload = agent_api.writeback(
            ticket["public_id"],
            user,
            "校医院夜班怎么挂号？",
            "夜班先到一楼导诊台取号。",
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["writeback"]["status"], "completed")
        result = campus_engine.answer("校医院夜班怎么挂号？")
        self.assertIn("导诊台", result["answer"])
        self.assertFalse(result["refuse"])

    def test_handoff_is_visible_to_admin(self) -> None:
        import admin_api

        result = campus_engine.answer(
            {
                "query": "转人工",
                "visitor": "eval-campus",
                "user": "eval-campus",
                "portal_session": "hand-1",
            }
        )
        self.assertTrue(result["handoff"])
        self.assertTrue(str(result["ticket_id"]).startswith("TK"))
        board = admin_api.handoff_board()
        self.assertTrue(any(row["public_id"] == result["ticket_id"] for row in board["tickets"]))
        self.assertTrue(board["sessions"])

    def test_probe_passes_on_the_sample(self) -> None:
        probe = campus_engine.run_probe()
        self.assertTrue(probe["ok"])
        self.assertEqual(len(probe["checks"]), 3)

    def test_model_cannot_invent_a_place(self) -> None:
        source = "电子版约 3 个工作日，在一网通办申请"
        invented = "请到教务处西门地下室窗口领取，记得带导师签字。[1]"
        self.assertFalse(campus_engine._accept_policy(invented, source))
        self.assertTrue(
            campus_engine._accept_policy("电子版约 3 个工作日，在一网通办申请。[1]", source)
        )
        os.environ["DEEPSEEK_API_KEY"] = "test-key-not-sent"
        original = campus_engine._complete
        campus_engine._complete = lambda *_args, **_kwargs: invented
        try:
            result = campus_engine.answer("在读证明如何办理？")
        finally:
            campus_engine._complete = original
        self.assertNotIn("西门", result["answer"])
        self.assertNotIn("导师", result["answer"])
        self.assertIn("一网通办", result["answer"])
        self.assertEqual(result["generator"], "template")

    def test_writing_a_campus_document_uses_the_knowledge_base(self) -> None:
        certificate = campus_engine.answer("帮我写一份在读证明")
        self.assertEqual(certificate["agent_action"], "clarify")
        self.assertEqual(certificate["citations"], [])
        labels = " ".join(item["label"] for item in certificate["suggestions"])
        self.assertIn("在读证明如何办理", labels)
        self.assertNotIn("DEEPSEEK_API_KEY", certificate["answer"])
        picked = campus_engine.answer("在读证明如何办理？")
        self.assertIn("一网通办", picked["answer"])
        self.assertTrue(picked["citations"])
        party = campus_engine.answer("帮我写一份入党申请书")
        self.assertEqual(party["citations"], [])
        self.assertNotEqual(party["intent"], "campus_faq")
        poem = campus_engine.answer("帮我写一首短诗")
        self.assertEqual(poem["citations"], [])
        self.assertEqual(poem["intent"], "needs_model")

    def test_short_query_with_an_extra_character_asks_first(self) -> None:
        result = campus_engine.answer("自习室")
        self.assertEqual(result["agent_action"], "clarify")
        self.assertEqual(result["citations"], [])
        labels = " ".join(item["label"] for item in result["suggestions"])
        self.assertIn("自习座位", labels)
        self.assertNotIn("4 小时", result["answer"])

    def test_deleted_sample_can_be_imported_again(self) -> None:
        import admin_api

        docs = kb_store.list_documents()
        seed = next(item for item in docs if item["source_key"] == "seed")
        self.assertTrue(kb_store.delete_document(seed["id"]))
        self.assertFalse(any(item["source_key"] == "seed" for item in kb_store.list_documents()))
        status, payload = admin_api.reimport_sample(self_user())
        self.assertEqual(status, 200)
        self.assertFalse(payload["already"])
        again = campus_engine.answer("在读证明如何办理？")
        self.assertEqual(again["matched_title"], "在读证明如何办理？")
        status, second = admin_api.reimport_sample(self_user())
        self.assertEqual(status, 200)
        self.assertTrue(second["already"])

    def test_model_cannot_invent_a_number(self) -> None:
        os.environ["DEEPSEEK_API_KEY"] = "test-key-not-sent"

        def fake_complete(*_args, **_kwargs):
            return "电子版大约 99 个工作日就能好。[1]"

        original = campus_engine._complete
        campus_engine._complete = fake_complete
        try:
            result = campus_engine.answer("在读证明如何办理？")
        finally:
            campus_engine._complete = original
        self.assertNotIn("99", result["answer"])
        self.assertIn("3", result["answer"])
        self.assertEqual(result["generator"], "template")

    def test_everyday_model_cannot_state_a_rule(self) -> None:
        os.environ["DEEPSEEK_API_KEY"] = "test-key-not-sent"

        def fake_complete(*_args, **_kwargs):
            return "去一网通办就行，大约 3 个工作日。"

        original = campus_engine._complete
        campus_engine._complete = fake_complete
        try:
            result = campus_engine.answer("写一首短诗")
        finally:
            campus_engine._complete = original
        self.assertEqual(result["citations"], [])
        self.assertNotIn("一网通办", result["answer"])

    def test_docx_and_simple_pdf_upload(self) -> None:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>## 夜间自习室在哪？</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>主馆二楼东侧。</w:t></w:r></w:p></w:body></w:document>"
        )
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            package.writestr("word/document.xml", xml)
        created = kb_store.add_upload("room.docx", buffer.getvalue())
        self.assertIn("夜间自习室", created["segments"][0]["title"] + created["segments"][0]["body"])
        pdf = b"%PDF-1.1\n1 0 obj\n<< /Length 48 >>\nstream\nBT (library night desk) Tj ET\nendstream\nendobj\n%%EOF\n"
        pdf_doc = kb_store.add_upload("note.pdf", pdf)
        self.assertIn("library night desk", pdf_doc["segments"][0]["body"])
        with self.assertRaises(ValueError):
            kb_store.add_upload("scan.pdf", b"%PDF-1.4\nno text literals here\n%%EOF")

    def test_retrieval_does_not_call_the_network(self) -> None:
        import urllib.request

        def boom(*_args, **_kwargs):
            raise AssertionError("network")

        original = urllib.request.urlopen
        urllib.request.urlopen = boom
        try:
            result = campus_engine.answer("在读证明如何办理？")
        finally:
            urllib.request.urlopen = original
        self.assertIn("一网通办", result["answer"])

    def test_portal_page_has_no_teammate_names(self) -> None:
        text = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("沈凯杰", text)
        self.assertNotIn("王瑞康", text)
        self.assertIn("校园客服", text)
        self.assertIn("星云大学", text)


class CampusHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.prev_data = os.environ.get("DATA_DIR")
        cls.prev_engine = os.environ.get("ENGINE")
        cls.prev_key = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DATA_DIR"] = cls.tmp.name
        os.environ["ENGINE"] = "campus"
        os.environ["DEEPSEEK_API_KEY"] = ""
        store.reconnect()
        from proxy import PortalHandler

        PortalHandler.api_key = ""
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), PortalHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        if cls.prev_data is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = cls.prev_data
        if cls.prev_engine is None:
            os.environ.pop("ENGINE", None)
        else:
            os.environ["ENGINE"] = cls.prev_engine
        if cls.prev_key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = cls.prev_key
        store.reconnect()
        cls.tmp.cleanup()

    def test_health_and_blocking_answer(self) -> None:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        health = json.loads(resp.read().decode("utf-8"))
        conn.close()
        self.assertEqual(health["engine"], "campus")
        self.assertGreaterEqual(health["components"]["segments"], 140)
        self.assertEqual(health["components"]["embeddings"], "off")
        body = json.dumps({"query": "在读证明如何办理？", "stream": False, "user": "eval-http"}).encode()
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/chat", body, {"Content-Type": "application/json"})
        resp = conn.getresponse()
        payload = json.loads(resp.read().decode("utf-8"))
        conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn("一网通办", payload["answer"])
        self.assertEqual(payload["engine"], "campus")
        self.assertTrue(payload["citations"])


if __name__ == "__main__":
    unittest.main()
