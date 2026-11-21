"""Default QUT profile and optional, evidence-based model assistance."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import admin_api
import campus_engine
import kb_retrieve
import kb_store
import settings
import store
from campus_profile import ARTICLE_BY_TITLE


class QutCampusTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.addCleanup(store.reconnect)
        self.enterContext(patch.dict(os.environ, {
            "DATA_DIR": tmp.name,
            "ENGINE": "campus",
            "CAMPUS_PROFILE": "",
            "DEEPSEEK_API_KEY": "",
            "DEEPSEEK_API_URL": "https://models.example.test/chat/completions",
            "EMBEDDING_API_KEY": "",
            "EMBEDDING_BASE_URL": "",
        }))
        self.enterContext(patch.object(settings, "CONFIG_PATH", Path(tmp.name) / "config.json"))
        store.reconnect()
        self.assertTrue(campus_engine.run_probe()["ok"])

    def ask(self, query: str, *, audience="student", visitor="test-qut", session="qut-session", history=()) -> dict:
        return campus_engine.answer({
            "query": query, "audience": audience, "visitor": visitor, "portal_session": session, "history": list(history),
        })

    def model(self, select):
        os.environ["DEEPSEEK_API_KEY"] = "test-placeholder"

        def respond(request, *, timeout):
            self.assertEqual(timeout, 6)
            self.assertEqual(request.full_url, os.environ["DEEPSEEK_API_URL"])
            payload = json.loads(request.data)
            self.assertFalse(payload["stream"])
            self.assertEqual([message["role"] for message in payload["messages"]], ["system", "user"])
            selected = select(json.loads(payload["messages"][-1]["content"]))
            content = selected if isinstance(selected, str) else json.dumps(selected, ensure_ascii=False)
            reply = {"choices": [{"message": {"content": content}}]}
            return io.BytesIO(json.dumps(reply, ensure_ascii=False).encode("utf-8"))

        return patch.object(campus_engine.urllib.request, "urlopen", side_effect=respond)

    def test_new_install_uses_official_sources_without_a_key(self) -> None:
        with patch.object(campus_engine.urllib.request, "urlopen") as remote:
            card = self.ask("学生证怎么补？")
            self.assertEqual(card["generator"], "template")
            self.assertIn("理工学子", card["answer"])
            self.assertEqual(card["citations"][0]["source_url"], ARTICLE_BY_TITLE["学生证补办"].url)
            self.assertIn("后勤公共服务平台", self.ask("宿舍灯不亮了")["answer"])
            self.assertTrue(self.ask("教工病假怎么请")["refuse"])
            self.assertIn("销假表", self.ask("教工病假怎么请", audience="staff")["answer"])
            self.assertTrue(self.ask("本科生成绩单怎么办理？")["refuse"])
        remote.assert_not_called()

    def test_legacy_documents_are_retained_but_excluded(self) -> None:
        with patch.dict(os.environ, {"CAMPUS_PROFILE": "demo"}):
            kb_store.add_text_document("旧版实验.md", "## 测试条目\n这是旧演示的资料。")
            self.assertGreater(len(kb_retrieve.get_index().chunks), 140)
        self.assertTrue(any(doc["audience"] == "demo" for doc in kb_store.list_documents()))
        self.assertTrue(all(chunk.audience in ("student", "shared") for chunk in kb_retrieve.get_index().chunks))
        self.assertTrue(self.ask("在读证明如何办理？")["refuse"])
        self.assertEqual(admin_api.dataset_cards()["datasets"], [])
        self.assertEqual(admin_api.start_eval("main", "C")[0], 409)

    def test_model_understands_colloquial_multi_topic_query(self) -> None:
        question = "已经连上无线了，能说说怎么验证账号以及充网费吗？"
        self.assertTrue(self.ask(question)["refuse"])
        kb_store.add_text_document("仅供检索.md", "## 本地测试材料\n这是不可发送给对话模型的正文。")

        def select(data):
            self.assertEqual(data["question"], question)
            self.assertIsNone(data["fixed_topic"])
            guides = {item["title"]: item["topic"] for item in data["guides"]}
            self.assertNotIn("教工校园网登录", guides)
            self.assertNotIn("本地测试材料", guides)
            return {
                "answers": [{"topic": guides[title], "facts": [1]} for title in ("学生校园网登录", "学生校园网缴费")],
                "choices": [], "partial": False,
            }

        with self.model(select) as remote:
            answer = self.ask(question, history=[{"role": "assistant", "text": "不要把这条旧答复发给模型"}])
            remote.assert_called_once()
        self.assertEqual(answer["generator"], "deepseek")
        self.assertIn("QUT-POL", answer["answer"])
        self.assertIn("套餐缴费", answer["answer"])
        self.assertNotIn("具体套餐", answer["answer"])
        self.assertEqual(answer["answer"].count("[1]"), 2)
        self.assertEqual(len(answer["citations"]), 1)
        self.assertIsNone(answer["citations"][0]["score"])

    def test_model_followup_only_uses_own_confirmed_session_topic(self) -> None:
        self.ask("学生证怎么补？")
        seen = []

        def select(data):
            seen.append(data["recent_topics"])
            if data["recent_topics"] != ["学生证补办"]:
                return {"answers": [], "choices": [], "partial": False}
            topic = next(item["topic"] for item in data["guides"] if item["title"] == "学生证补办")
            return {"answers": [{"topic": topic, "facts": [1]}], "choices": [], "partial": True}

        with self.model(select):
            self.assertTrue(self.ask("那要准备什么？", visitor="other-visitor")["refuse"])
            self.assertTrue(self.ask("那要准备什么？", session="other-session")["refuse"])
            self.assertTrue(self.ask("那要准备什么？", audience="staff", session="other-staff-session")["refuse"])
            result = self.ask("那要准备什么？")
        self.assertEqual(seen, [[], [], [], ["学生证补办"]])
        self.assertEqual(result["generator"], "deepseek")
        self.assertIn("上传电子照片", result["answer"])
        self.assertIn("现有资料没有说明", result["answer"])

    def test_model_can_request_clarification_without_claiming_an_answer(self) -> None:
        def select(data):
            titles = ("研究生在读证明", "研究生带公章成绩单")
            options = [item["topic"] for item in data["guides"] if item["title"] in titles]
            return {"answers": [], "choices": options, "partial": False}

        with self.model(select):
            result = self.ask("研究生要学校盖章的材料要去哪弄？")
        self.assertEqual(result["generator"], "deepseek")
        self.assertTrue(result["clarify"])
        self.assertFalse(result["citations"])
        self.assertEqual({item["label"] for item in result["suggestions"]}, {"研究生在读证明", "研究生带公章成绩单"})

    def test_invalid_output_timeout_and_sensitive_input_fall_back(self) -> None:
        invalid = {"answers": [{"topic": 1, "facts": [999]}], "choices": [], "partial": False}
        with self.model(lambda _: invalid):
            self.assertEqual(self.ask("学生证怎么补")["generator"], "template")
        with self.model(lambda _: "不是 JSON"):
            self.assertTrue(self.ask("校园巴士几点到？")["refuse"])
        with patch.object(campus_engine.urllib.request, "urlopen", side_effect=TimeoutError) as remote:
            self.assertEqual(self.ask("学生证怎么补")["generator"], "template")
            remote.assert_called_once()
            remote.reset_mock()
            self.ask("我的学号是 2024 1234，怎么补证？")
            self.ask("我的密码：private-token，校园网怎么连？")
            remote.assert_not_called()

    def test_retired_endpoints_and_audience_catalog_on_loopback(self) -> None:
        from proxy import PortalHandler

        class QuietPortal(PortalHandler):
            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), QuietPortal)
        self.addCleanup(server.server_close)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)

        def request(method, url, data=None):
            conn = HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                body = json.dumps(data).encode() if data else None
                conn.request(method, url, body=body, headers={"Content-Type": "application/json"})
                result = conn.getresponse()
                return result.status, result.read()
            finally:
                conn.close()

        for method, url in (("GET", "/agent"), ("HEAD", "/agent.js"), ("GET", "/api/agent/tickets"),
                            ("GET", "/api/portal/tickets"), ("GET", "/api/admin/handoffs"), ("POST", "/api/ticket")):
            with self.subTest(method=method, url=url):
                self.assertEqual(request(method, url)[0], 404)
        status, body = request("GET", "/api/faq-nav?audience=staff")
        self.assertEqual(status, 200)
        titles = {row["title"] for group in json.loads(body)["categories"] for row in group["items"]}
        self.assertIn("教工校园网登录", titles)
        self.assertNotIn("学生证补办", titles)
        status, body = request("POST", "/api/chat", {"query": "我要转人工", "stream": False})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["refuse"])
        self.assertFalse(json.loads(body)["queue"])
        self.assertEqual(store.list_tickets(), [])
