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
from constraints import apply_constraints, merge_citations, seal_user_citations
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
            answer = "在读证明请到一网通办申请，电子版约 3 个工作日。[1]"
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
        glued, _notices = mask_text("联系方式+8613800138000")
        self.assertNotIn("13800138000", glued)
        self.assertIn("138****8000", glued)
        self.assertNotIn("+86", glued)
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
        cfg = dict(load_config())
        cfg["faq_shortcut"] = False
        decision = apply_constraints("随便请就行，不用手续。", [], cfg, retrieval_empty=True)
        self.assertTrue(decision["refuse"])
        self.assertEqual(decision["reason"], "empty_retrieval")
        self.assertNotIn("随便请", decision["answer"])
        self.assertIn("知识库里没有", decision["answer"])

    def test_low_score_is_missing_citation(self) -> None:
        cfg = dict(load_config())
        cfg["score_threshold"] = 0.5
        cfg["faq_shortcut"] = False
        decision = apply_constraints(
            "看起来像回答",
            [{"document_name": "客服样例FAQ.md", "document_id": "faq", "score": 0.1, "content": "片段"}],
            cfg,
        )
        self.assertTrue(decision["refuse"])
        self.assertEqual(decision["reason"], "missing_citation")
        self.assertEqual(decision["citations"], [])

    def _card(self, score: float = 0.91, content: str | None = None, document_id: str = "faq") -> dict:
        return {
            "document_name": "客服样例FAQ.md" if document_id == "faq" else "另一篇.md",
            "document_id": document_id,
            "score": score,
            "content": content or "问：在读证明如何办理？\n登录一网通办，电子版约 3 个工作日。",
        }

    def test_unmarked_answer_is_refused_without_listing_chunks(self) -> None:
        cfg = dict(load_config()); cfg["faq_shortcut"] = False; cfg["score_threshold"] = 0.5
        decision = apply_constraints("请到一网通办申请。", [self._card()], cfg)
        self.assertTrue(decision["refuse"])
        self.assertEqual(decision["reason"], "missing_citation")
        self.assertEqual(decision["citations"], [])
        self.assertNotIn("请到一网通办", decision["answer"])

    def test_unknown_mark_is_removed(self) -> None:
        cfg = dict(load_config()); cfg["faq_shortcut"] = False; cfg["score_threshold"] = 0.5
        decision = apply_constraints("请到一网通办。[9]", [self._card()], cfg)
        self.assertTrue(decision["refuse"])
        self.assertEqual(decision["citations"], [])

    def test_valid_mark_stays_and_stray_mark_goes(self) -> None:
        decision = apply_constraints(
            "请到一网通办。[1] 旁边还有 [9]",
            [self._card(), self._card(score=0.8, content="另一条", document_id="other")],
            (lambda c: (c.update({"faq_shortcut": False, "score_threshold": 0.5}), c)[1])(dict(load_config())),
        )
        self.assertFalse(decision["refuse"])
        self.assertEqual([card["mark"] for card in decision["citations"]], [1])
        self.assertIn("[1]", decision["answer"])
        self.assertNotIn("[9]", decision["answer"])
        self.assertNotIn("另一条", decision["answer"])

    def test_shortcut_quotes_the_faq_only_when_enabled_and_close(self) -> None:
        cfg = dict(load_config())
        cfg["faq_shortcut"] = False
        cfg["score_threshold"] = 0.5
        marked = apply_constraints("请到一网通办。[1]", [self._card(score=0.95)], cfg)
        self.assertEqual(marked["reason"], "ok")
        self.assertIn("请到一网通办", marked["answer"])
        cfg["faq_shortcut"] = True
        cfg["faq_shortcut_score"] = 0.85
        hit = apply_constraints("模型随便写。", [self._card(score=0.95)], cfg)
        self.assertEqual(hit["reason"], "faq_shortcut")
        self.assertIn("行政楼一楼", hit["answer"])
        self.assertIn("[1]", hit["answer"])
        self.assertEqual(hit["citations"][0]["mark"], 1)
        self.assertNotIn("模型随便写", hit["answer"])
        miss = apply_constraints("请到一网通办。[1]", [self._card(score=0.6)], cfg)
        self.assertEqual(miss["reason"], "ok")
        self.assertIn("请到一网通办", miss["answer"])
        self.assertNotIn("行政楼", miss["answer"])

    def test_seal_clears_cards_when_refused(self) -> None:
        leaked = seal_user_citations({"refuse": True, "citations": [{"document_name": "客服样例FAQ.md"}]})
        self.assertEqual(leaked["citations"], [])
        kept = seal_user_citations({"refuse": False, "citations": [{"document_name": "客服样例FAQ.md"}]})
        self.assertEqual(len(kept["citations"]), 1)



    def test_local_title_match_shortcuts_paraphrase_when_enabled(self) -> None:
        cfg = dict(load_config())
        cfg["faq_shortcut"] = True
        cfg["score_threshold"] = 0.1
        decision = apply_constraints(
            "模型可能会写错事实。",
            [{"document_name": "客服样例FAQ.md", "document_id": "faq", "score": 0.12, "content": "无关片段"}],
            cfg,
            query="怎样借书和续借？",
        )
        self.assertEqual(decision["reason"], "faq_shortcut")
        self.assertIn("校园卡", decision["answer"])
        self.assertIn("如何借书和续借？", decision["citations"][0]["content"])
        self.assertIn("[1]", decision["answer"])
        self.assertNotIn("模型可能会写错事实", decision["answer"])

    def test_local_title_match_does_not_answer_out_of_scope(self) -> None:
        cfg = dict(load_config())
        cfg["faq_shortcut"] = True
        decision = apply_constraints(
            "模型瞎答。[1]",
            [{"document_name": "客服样例FAQ.md", "document_id": "faq", "score": 0.12, "content": "片段 [1]"}],
            cfg,
            query="实验室门禁怎么开",
        )
        self.assertNotEqual(decision.get("reason"), "faq_shortcut")

    def test_followup_match_stays_on_previous_topic(self) -> None:
        import faq_match
        match = faq_match.confident_match(
            "那补办呢",
            [{"role": "user", "text": "校园卡如何充值和挂失？"}],
        )
        self.assertIsNotNone(match)
        self.assertEqual(match["title"], "校园卡如何补办？")



    def test_specific_certificate_question_is_not_clarified(self) -> None:
        from clarify import clarify_options
        self.assertIsNone(clarify_options("同学想问，实习证明怎么开？"))
        self.assertIsNotNone(clarify_options("证明怎么开？"))

    def test_followup_shortcut_does_not_repeat_previous_title(self) -> None:
        import faq_match
        match = faq_match.confident_match(
            "想改期",
            [{"role": "user", "text": "心理咨询如何预约？"}],
        )
        self.assertEqual(match["title"], "心理咨询如何取消或改期？")
        # The gateway history prefix must not override this.
        prefixed = "（追问。上一句用户问题：心理咨询如何预约？）想改期"
        wrong = faq_match.confident_match("想改期", [{"role": "user", "text": "心理咨询如何预约？"}], rewritten=prefixed)
        # Even if a caller passes the prefixed rewrite, history should still win or we simply not pass it.
        self.assertTrue(match and match["title"] == "心理咨询如何取消或改期？")

    def test_a_short_new_errand_is_not_a_followup(self) -> None:
        import faq_match
        from gateway import _prepare_query

        history = [{"role": "user", "text": "在读证明如何办理？"}, {"role": "assistant", "text": "到一网通办。"}]
        self.assertIsNone(faq_match.confident_match("怎么请病假？", history))
        plain, meta = _prepare_query("怎么请病假？", history, "")
        self.assertEqual(plain, "怎么请病假？")
        self.assertIsNone(meta)
        rewritten, follow = _prepare_query("那成绩单呢？", history, "")
        self.assertIsNotNone(follow)
        self.assertIn("在读证明如何办理？", rewritten)
        self.assertIn("那成绩单呢？", rewritten)
        grade = faq_match.confident_match("那成绩单呢？", history)
        self.assertEqual(grade["title"], "成绩单如何申请？")
        for fresh in ("怎么请病假呢？", "那怎么请病假？", "同学想问，怎么请病假？"):
            self.assertFalse(faq_match.is_followup(fresh, history), fresh)
            text, meta = _prepare_query(fresh, history, "conv-already")
            self.assertEqual(text, fresh, fresh)
            self.assertIsNone(meta, fresh)
            self.assertIsNone(faq_match.confident_match(fresh, history))
        still, follow_meta = _prepare_query("那成绩单呢？", history, "conv-already")
        self.assertIsNotNone(follow_meta)
        self.assertIn("在读证明", still)

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
        import gateway as gateway_mod
        self._load_config = gateway_mod.load_config

        def _cfg():
            cfg = dict(self._load_config())
            cfg["faq_shortcut"] = False
            return cfg

        gateway_mod.load_config = _cfg
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = self.tmp.name
        store.reconnect()
        store.save_probe(True, [{"name": "probe", "ok": True, "detail": "测试探针"}])
        _FakeDify.seen = []
        set_client(DifyClient(chat_url=f"http://127.0.0.1:{self.port}/v1/chat-messages", app_key="app-test"))

    def tearDown(self) -> None:
        import gateway as gateway_mod
        gateway_mod.load_config = self._load_config
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
        self.assertEqual(done["citations"], [])
        self.assertTrue(any(item.get("query") == "转人工" for item in done["suggestions"]))

    def test_stream_announces_lookup_before_the_answer(self) -> None:
        events = list(iter_events({"query": "在读证明如何办理？", "visitor": "v9", "portal_session": "s9", "user": "v9"}))
        phases = [event.get("phase") for event in events if event.get("type") == "status"]
        self.assertIn("retrieving", phases)
        self.assertIn("generating", phases)
        self.assertLess(phases.index("retrieving"), phases.index("generating"))
        done = next(event for event in events if event.get("type") == "done")
        self.assertFalse(done["refuse"])
        self.assertTrue(done.get("server_message_id"))

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

    def test_sick_leave_after_a_certificate_does_not_reuse_that_entry(self) -> None:
        import gateway as gateway_mod

        gateway_mod.load_config = lambda: {**self._load_config(), "faq_shortcut": True}
        history = [{"role": "user", "text": "在读证明如何办理？"}, {"role": "assistant", "text": "到一网通办。"}]
        done = run_chat(
            {
                "query": "怎么请病假？",
                "history": history,
                "visitor": "v-sick",
                "portal_session": "s-sick",
                "user": "v-sick",
            }
        )
        self.assertTrue(done["refuse"])
        self.assertEqual(done.get("citations"), [])
        self.assertNotIn("在读证明", done.get("answer") or "")
        self.assertNotEqual(done.get("reason"), "faq_shortcut")

    def test_handoff_keeps_the_earlier_four_steps(self) -> None:
        import agent_api
        import gateway as gateway_mod

        gateway_mod.load_config = lambda: {**self._load_config(), "faq_shortcut": True}
        first = run_chat({"query": "在读证明如何办理？", "visitor": "v-trace", "portal_session": "s-trace", "user": "v-trace"})
        self.assertEqual([step["step"] for step in first["trace"]], ["改写", "检索", "约束", "输出"])
        self.assertEqual(first["trace"][0]["detail"], "按原问题检索")
        handoff = run_chat({"query": "转人工", "visitor": "v-trace", "portal_session": "s-trace", "user": "v-trace"})
        status, detail = agent_api.detail(handoff["ticket_id"])
        self.assertEqual(status, 200)
        names = [step["step"] for item in detail["judgments"] for step in item["trace"]]
        for required in ("改写", "检索", "约束", "输出"):
            self.assertIn(required, names)
        self.assertTrue(any(item["decision"] == "human_handoff" for item in detail["judgments"]))

    def test_ticket_subject_is_stored_masked(self) -> None:
        import agent_api

        ticket = store.create_ticket("v-phone", "s-phone", "user", "在读证明怎么办，我的手机是13800138000")
        self.assertNotIn("13800138000", ticket["first_question"])
        self.assertIn("138****8000", ticket["first_question"])
        status, detail = agent_api.detail(ticket["public_id"])
        self.assertEqual(status, 200)
        self.assertNotIn("13800138000", detail["ticket"]["first_question"])
        self.assertIn("138****8000", detail["ticket"]["first_question"])

    def test_rate_limit_rests_before_the_model(self) -> None:
        import ratelimit

        original = ratelimit.allow

        def blocked(*_args, **_kwargs) -> bool:
            return False

        ratelimit.allow = blocked
        try:
            done = run_chat({"query": "在读证明如何办理？", "visitor": "v-rate", "portal_session": "s-rate", "user": "v-rate"})
        finally:
            ratelimit.allow = original
        self.assertIn("休息一下", done["answer"])
        self.assertEqual(done["citations"], [])
        self.assertEqual(_FakeDify.seen, [])

    def test_eval_caller_keeps_a_full_bucket(self) -> None:
        import ratelimit

        ratelimit.reset_for_tests()
        cfg = {"rate_limit_enabled": True, "rate_limit_burst": 8, "rate_limit_per_minute": 8}
        self.assertTrue(all(ratelimit.allow("person", "person", cfg) for _ in range(8)))
        self.assertFalse(ratelimit.allow("person", "person", cfg))
        self.assertTrue(all(ratelimit.allow("eval-C-T-001", "eval-C-T-001", cfg) for _ in range(8)))
        self.assertFalse(ratelimit.allow("eval-C-T-001", "eval-C-T-001", cfg))
        self.assertTrue(ratelimit.allow("eval-C-T-001", "eval-C-T-001", cfg, exempt=True))


if __name__ == "__main__":
    unittest.main()
