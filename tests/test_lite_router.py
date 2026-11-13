#!/usr/bin/env python3
"""Router checks for the lite campus assistant. Stdlib only."""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
os.environ["LITE_MODE"] = "1"
os.environ.pop("DEEPSEEK_API_KEY", None)

import lite_engine  # noqa: E402
from lite_engine import answer_lite, faq_catalog, get_index, load_chunks, route_faq  # noqa: E402
from proxy import (  # noqa: E402
    PortalHandler,
    classify_portal_intent,
    handoff_payload,
    is_handoff_intent,
    lookup_mock_order,
    rewrite_query_for_retrieval,
    ticket_sensitive_message,
)


def _blob(result: dict) -> str:
    suggestions = " ".join(
        f"{item.get('label', '')} {item.get('query', '')}" for item in result.get("suggestions") or []
    )
    return f"{result.get('answer', '')}\n{result.get('matched_title') or ''}\n{suggestions}"


class RouterTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("DEEPSEEK_API_KEY", None)
        lite_engine.deepseek_api_key = lambda: ""

    def test_every_faq_title_answers_itself(self) -> None:
        mismatches = []
        for chunk in load_chunks(force=True):
            routed = route_faq(chunk.question)
            if routed["action"] != "answer" or routed["titles"][:1] != [chunk.title]:
                mismatches.append((chunk.title, routed["action"], routed["titles"][:2], routed["reason"]))
        self.assertEqual(mismatches, [])

    def test_catalog_uses_existing_titles_once(self) -> None:
        catalog = faq_catalog()
        titles = [item["title"] for cat in catalog["categories"] for item in cat["items"]]
        expected = [chunk.title for chunk in load_chunks()]
        self.assertEqual(sorted(titles), sorted(expected))
        self.assertEqual(len(titles), len(set(titles)))
        placed = {
            item["title"]: cat["name"]
            for cat in catalog["categories"]
            for item in cat["items"]
        }
        self.assertEqual(placed["在读证明如何办理？"], "教务学籍")
        self.assertEqual(placed["国家助学贷款如何申请？"], "奖助贷")
        self.assertEqual(placed["宿舍门禁时间是什么？"], "宿舍后勤")
        self.assertEqual(placed["寒暑假校园作息怎么安排？"], "假期作息")
        self.assertEqual(catalog["count"], len(expected))

    def test_index_is_a_small_lexical_build(self) -> None:
        index = get_index()
        self.assertGreater(len(index.chunks), 100)
        self.assertLess(len(index.lexicon), 2000)
        self.assertGreater(len(index.lexicon), 50)

    def test_enrollment_certificate_is_cited(self) -> None:
        result = answer_lite("在读证明如何办理？")
        self.assertEqual(result["intent"], "campus_faq")
        self.assertFalse(result["refuse"])
        self.assertFalse(result["clarify"])
        self.assertEqual(result["matched_title"], "在读证明如何办理？")
        self.assertIn("一网通办", result["answer"])
        self.assertIn("3", result["answer"])
        self.assertIn("工作日", result["answer"])
        self.assertIn("依据：客服样例FAQ.md", result["answer"])
        self.assertNotIn("根据知识库", result["answer"])
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["document_name"], "客服样例FAQ.md")
        self.assertEqual(result["citations"][0]["dataset_name"], "校园办事 FAQ")
        self.assertGreaterEqual(result["citations"][0]["score"], 0.8)

    def test_loan_paraphrases_stay_on_the_loan_faqs(self) -> None:
        campus = answer_lite("校园地贷款")
        self.assertEqual(campus["matched_title"], "国家助学贷款如何申请？")
        self.assertIn("校园地", campus["answer"])
        self.assertFalse(campus["refuse"])
        receipt = answer_lite("生源地回执")
        self.assertIn("生源地", receipt["matched_title"])
        self.assertFalse(receipt["refuse"])
        broad = answer_lite("助学贷款")
        self.assertTrue(broad["clarify"])
        self.assertEqual(broad["citations"], [])
        self.assertGreaterEqual(len(broad["suggestions"]), 2)
        for item in broad["suggestions"]:
            self.assertIn("助学贷款", item["query"])

    def test_dorm_classroom_and_calendar_stay_in_scope(self) -> None:
        power = answer_lite("水电")
        self.assertIn("水电", power["matched_title"])
        calendar = answer_lite("寒暑假作息")
        self.assertIn("作息", calendar["matched_title"])
        holiday = answer_lite("假期作息")
        self.assertIn("作息", holiday["matched_title"])
        gate = answer_lite("宿舍门禁")
        self.assertFalse(gate["refuse"])
        self.assertIn("门禁", _blob(gate))
        room = answer_lite("教室借用")
        self.assertFalse(room["refuse"])
        self.assertIn("教室", _blob(room))
        if room["clarify"]:
            self.assertEqual(room["citations"], [])

    def test_close_matches_clarify_instead_of_guessing(self) -> None:
        vague = answer_lite("申请")
        self.assertTrue(vague["clarify"])
        self.assertEqual(vague["citations"], [])
        self.assertNotIn("我的申请", vague["answer"])
        hours = answer_lite("图书馆几点开门")
        self.assertTrue(hours["clarify"])
        labels = " ".join(item["label"] for item in hours["suggestions"])
        self.assertIn("图书馆开放时间", labels)
        self.assertIn("分馆", labels)

    def test_party_application_is_not_the_lookalike_faq(self) -> None:
        result = answer_lite("帮我写一份入党申请书")
        self.assertTrue(result["refuse"])
        self.assertEqual(result["citations"], [])
        self.assertNotIn("我的申请", result["answer"])
        self.assertNotIn("真实办件进度", result["answer"])
        self.assertIn("转人工", result["answer"])
        self.assertTrue(result["suggestions"])

    def test_math_translation_and_everyday_skills(self) -> None:
        math = answer_lite("15*24+8")
        self.assertEqual(math["intent"], "math")
        self.assertIn("368", math["answer"])
        self.assertEqual(math["citations"], [])
        self.assertFalse(math["refuse"])
        root = answer_lite("二十五的平方根")
        self.assertEqual(root["intent"], "math")
        self.assertIn("= 5", root["answer"])
        translated = answer_lite("把「在读证明如何办理」译成英文")
        self.assertEqual(translated["intent"], "translate")
        self.assertIn("certificate of enrollment", translated["answer"])
        self.assertNotIn("3 个工作日", translated["answer"])
        self.assertEqual(translated["citations"], [])
        units = answer_lite("3公里等于多少米")
        self.assertEqual(units["intent"], "unit")
        self.assertIn("3000", units["answer"])
        clock = answer_lite("今天星期几")
        self.assertEqual(clock["intent"], "datetime")
        self.assertIn("北京时间", clock["answer"])
        self.assertIn("星期", clock["answer"])

    def test_poem_weather_and_light_chat_do_not_cite_a_faq(self) -> None:
        poem = answer_lite("写一首诗")
        self.assertEqual(poem["intent"], "poem")
        self.assertFalse(poem["refuse"])
        self.assertEqual(poem["citations"], [])
        self.assertIn("路灯", poem["answer"])
        weather = answer_lite("今天天气怎么样")
        self.assertEqual(weather["intent"], "weather")
        self.assertIn("实时天气", weather["answer"])
        self.assertNotIn("晴", weather["answer"])
        self.assertEqual(weather["citations"], [])
        movie = answer_lite("推荐一部电影")
        self.assertEqual(movie["citations"], [])
        self.assertNotIn("水电", movie["answer"])
        food = answer_lite("今晚吃什么")
        self.assertNotIn("门禁", food["answer"])
        self.assertEqual(food["citations"], [])
        stocks = answer_lite("怎么投资股票")
        self.assertTrue(stocks["refuse"])
        self.assertEqual(stocks["citations"], [])
        self.assertIn("转人工", stocks["answer"])
        secret = answer_lite("试试这个密码对不对")
        self.assertTrue(secret["refuse"])
        self.assertEqual(secret["citations"], [])
        self.assertIn("没有核对", secret["answer"])
        homework = answer_lite("帮我写作业")
        self.assertTrue(homework["refuse"])
        self.assertNotIn("毕业审核", homework["answer"])

    def test_greeting_introduces_the_named_assistant(self) -> None:
        result = answer_lite("你好")
        self.assertEqual(result["agent_action"], "assistant_intro")
        self.assertFalse(result["refuse"])
        self.assertIn("校园助手", result["answer"])
        self.assertEqual(result["citations"], [])
        self.assertGreaterEqual(len(result["suggestions"]), 3)
        self.assertLessEqual(len(result["suggestions"]), 6)

    def test_followups_stay_on_the_previous_topic(self) -> None:
        history = [
            {"role": "user", "text": "在读证明如何办理？"},
            {"role": "assistant", "text": "电子版约 3 个工作日。"},
        ]
        rewritten, meta = rewrite_query_for_retrieval("那多久能下来", history)
        self.assertEqual(meta["method"], "follow-up")
        self.assertIn("在读证明如何办理", rewritten)
        self.assertIn("需要多久", rewritten)
        answered = answer_lite(rewritten)
        self.assertEqual(answered["matched_title"], "在读证明如何办理？")
        self.assertIn("3", answered["answer"])
        materials, _meta = rewrite_query_for_retrieval("要什么材料", history)
        material_answer = answer_lite(materials)
        self.assertEqual(material_answer["matched_title"], "在读证明如何办理？")
        self.assertIn("校园卡", material_answer["answer"])
        switched, switch_meta = rewrite_query_for_retrieval("那成绩单呢", history)
        self.assertEqual(switch_meta["method"], "topic-switch")
        self.assertIn("成绩单", switched)
        self.assertNotIn("在读证明如何办理", switched)
        longer = history + [
            {"role": "user", "text": "图书馆开放时间是什么？"},
            {"role": "assistant", "text": "主馆 8:00 开门。"},
        ]
        back, back_meta = rewrite_query_for_retrieval("返回上一个问题", longer)
        self.assertEqual(back_meta["method"], "back")
        self.assertIn("在读证明", back)
        self.assertNotIn("图书馆", back)
        restart, restart_meta = rewrite_query_for_retrieval("重新开始", history)
        self.assertEqual(restart_meta["method"], "restart")
        restarted = answer_lite("重新开始")
        self.assertEqual(restarted["agent_action"], "restart")
        self.assertIn("校园助手", restarted["answer"])

    def test_portal_intents_for_ticket_handoff_and_safety(self) -> None:
        self.assertEqual(classify_portal_intent("查询办事进度 SW20260001"), "ticket")
        self.assertEqual(classify_portal_intent("SW20260001"), "ticket")
        self.assertEqual(classify_portal_intent("转人工"), "handoff")
        self.assertEqual(classify_portal_intent("我要投诉"), "handoff")
        self.assertEqual(classify_portal_intent("什么情况下应转人工？"), "lite")
        self.assertFalse(is_handoff_intent("什么情况下应转人工？"))
        about = answer_lite("什么情况下应转人工？")
        self.assertEqual(about["matched_title"], "什么情况下应转人工？")
        found = lookup_mock_order("SW20260001")
        self.assertTrue(found["order_found"])
        self.assertIn("办理中", found["answer"])
        self.assertIn("一网通办", found["answer"])
        self.assertIn("演示", found["answer"])
        self.assertEqual(found["citations"], [])
        handoff = handoff_payload("转人工", "nebula-portal")
        self.assertTrue(handoff["handoff"])
        self.assertTrue(handoff["ticket_id"].startswith("TK"))
        self.assertIn("身份证", handoff["answer"])
        blocked = ticket_sensitive_message("跟进", "110101199001011234", "")
        self.assertIsNotNone(blocked)
        self.assertNotIn("110101199001011234", blocked or "")
        hidden = answer_lite("我的证件是110101199001011234")
        self.assertEqual(hidden["agent_action"], "safety")
        self.assertNotIn("110101199001011234", hidden["answer"])
        self.assertNotIn("110101199001011234", hidden.get("redacted_query") or "")
        self.assertEqual(hidden["citations"], [])


class HttpRouteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        PortalHandler.api_key = ""
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), PortalHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _post(self, payload: dict) -> tuple[int, str, bytes]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/chat", body, {"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read()
        ctype = resp.getheader("Content-Type") or ""
        status = resp.status
        conn.close()
        return status, ctype, raw

    def _done(self, raw: bytes) -> dict:
        done = {}
        for line in raw.decode("utf-8").splitlines():
            if not line.startswith("data:"):
                continue
            event = json.loads(line[5:].strip())
            if event.get("type") == "done":
                done = event
        return done

    def test_stream_clarify_math_ticket_and_handoff(self) -> None:
        status, ctype, raw = self._post({"query": "助学贷款", "stream": True, "user": "tester"})
        self.assertEqual(status, 200)
        self.assertIn("text/event-stream", ctype)
        done = self._done(raw)
        self.assertEqual(done.get("agent_action"), "clarify")
        self.assertFalse(done.get("refuse"))
        self.assertGreaterEqual(len(done.get("suggestions") or []), 2)
        self.assertEqual(done.get("citations") or [], [])

        status, ctype, raw = self._post({"query": "15*24+8", "stream": False, "user": "tester"})
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        body = json.loads(raw.decode("utf-8"))
        self.assertIn("368", body["answer"])
        self.assertEqual(body["citations"], [])

        status, _ctype, raw = self._post(
            {
                "query": "那多久能下来",
                "stream": False,
                "user": "tester",
                "history": [{"role": "user", "text": "在读证明如何办理？"}],
            }
        )
        body = json.loads(raw.decode("utf-8"))
        self.assertEqual(status, 200)
        self.assertEqual(body.get("matched_title"), "在读证明如何办理？")
        self.assertIn("工作日", body["answer"])
        self.assertEqual(body.get("rewrite", {}).get("method"), "follow-up")

        status, _ctype, raw = self._post({"query": "SW20260001", "stream": False, "user": "tester"})
        body = json.loads(raw.decode("utf-8"))
        self.assertEqual(body.get("agent_action"), "order_lookup")
        self.assertIn("办理中", body["answer"])
        self.assertTrue(body.get("order_found"))

        status, _ctype, raw = self._post({"query": "转人工", "stream": False, "user": "tester"})
        body = json.loads(raw.decode("utf-8"))
        self.assertTrue(body.get("handoff"))
        self.assertTrue(str(body.get("ticket_id") or "").startswith("TK"))

        status, _ctype, raw = self._post(
            {"query": "我的证件是110101199001011234", "stream": False, "user": "tester"}
        )
        body = json.loads(raw.decode("utf-8"))
        self.assertEqual(body.get("agent_action"), "safety")
        self.assertNotIn("110101199001011234", raw.decode("utf-8"))

        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request(
            "POST",
            "/api/ticket",
            json.dumps({"subject": "证件", "detail": "110101199001011234", "contact": ""}).encode(),
            {"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        ticket_raw = resp.read()
        self.assertEqual(resp.status, 400)
        self.assertNotIn("110101199001011234", ticket_raw.decode("utf-8"))
        conn.close()

        conn = HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/api/faq-nav")
        resp = conn.getresponse()
        nav = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(resp.status, 200)
        self.assertGreater(nav.get("count") or 0, 100)
        self.assertTrue(nav.get("categories"))
        conn.close()


if __name__ == "__main__":
    unittest.main()
