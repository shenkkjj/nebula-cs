#!/usr/bin/env python3
"""Scoring math, dataset shape, and a real group A sample. No invented B/C numbers."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import eval_runner
from eval_runner import agreement, load_dataset, score_item, summarize


class ScoreTest(unittest.TestCase):
    def test_metrics_from_labeled_outcomes(self) -> None:
        items = [
            {"id": "T-1", "type": "in_scope", "question": "在读证明", "expected_title": "在读证明如何办理？", "expected_facts": ["3 个工作日"]},
            {"id": "T-2", "type": "in_scope", "question": "借书", "expected_title": "如何借书和续借？", "expected_facts": ["30 天"]},
            {"id": "T-3", "type": "out_of_scope", "question": "写诗", "expected_title": "", "expected_facts": []},
        ]
        outcomes = [
            {
                "answer": "电子版约 3 个工作日。",
                "citations": [{"document_name": "客服样例FAQ.md", "document_id": "faq", "content": "问：在读证明如何办理？"}],
                "retrieval": [{"title": "在读证明如何办理？", "content": "3 个工作日"}],
                "latency_ms": 10,
                "first_token_ms": 10,
            },
            {"answer": "知识库里没有这条办事说明，我不能编。", "citations": [], "retrieval": [], "refuse": True, "first_token_ms": 4},
            {"answer": "知识库里没有写诗的规定，我不能编。", "citations": [], "refuse": True, "first_token_ms": 3},
        ]
        rows = [score_item(item, outcome) for item, outcome in zip(items, outcomes)]
        self.assertTrue(rows[0]["pass"])
        self.assertFalse(rows[1]["pass"])
        self.assertEqual(rows[1]["label"], "误拒")
        self.assertTrue(rows[2]["pass"])
        metrics = summarize(rows)
        self.assertEqual(metrics["in_scope_accuracy"], 0.5)
        self.assertEqual(metrics["false_refusal"], 0.5)
        self.assertEqual(metrics["out_of_scope_refusal"], 1.0)
        self.assertEqual(metrics["duplicate_citations"], 0)

    def test_duplicate_documents_count(self) -> None:
        row = score_item(
            {"id": "T-9", "type": "in_scope", "question": "门禁", "expected_title": "宿舍门禁时间是什么？", "expected_facts": []},
            {
                "answer": "23:30",
                "matched_title": "宿舍门禁时间是什么？",
                "citations": [
                    {"document_name": "客服样例FAQ.md", "document_id": "faq", "content": "宿舍门禁时间是什么？"},
                    {"document_name": "客服样例FAQ.md", "document_id": "faq", "content": "宿舍门禁时间是什么？ 另一段"},
                ],
                "retrieval": [{"title": "宿舍门禁时间是什么？"}],
            },
        )
        self.assertTrue(row["duplicate"])

    def test_human_agreement(self) -> None:
        rows = [{"id": "T-1", "pass": True}, {"id": "T-2", "pass": False}]
        labels = [{"question_id": "T-1", "human_label": True}, {"question_id": "T-2", "human_label": True}]
        result = agreement(rows, labels)
        self.assertTrue(result["ran"])
        self.assertEqual(result["compared"], 2)
        self.assertEqual(result["agreement"], 0.5)
        self.assertFalse(agreement(rows, [])["ran"])


class DatasetAndGroupATest(unittest.TestCase):
    def test_sets_match_the_plan_shape(self) -> None:
        test_name, test_items = load_dataset(ROOT / "tests" / "eval" / "test-set.json")
        dev_name, dev_items = load_dataset(ROOT / "tests" / "eval" / "dev-set.json")
        _smoke_name, smoke_items = load_dataset(ROOT / "tests" / "eval" / "smoke-set.json")
        self.assertEqual(test_name, "test")
        self.assertEqual(dev_name, "dev")
        self.assertEqual(len(test_items), 107)
        self.assertEqual(len(dev_items), 105)
        self.assertGreaterEqual(len(test_items) + len(dev_items), 200)
        self.assertEqual(len(smoke_items), 12)
        smoke_questions = {item["question"] for item in smoke_items}
        self.assertFalse(smoke_questions & {item["question"] for item in test_items})
        self.assertGreaterEqual(sum(1 for item in test_items + dev_items if item["type"] == "in_scope"), 144)
        self.assertGreaterEqual(sum(1 for item in test_items + dev_items if item["type"] == "out_of_scope"), 40)
        self.assertGreaterEqual(sum(1 for item in test_items + dev_items if item["type"] == "multi_turn"), 15)
        self.assertGreaterEqual(sum(1 for item in test_items + dev_items if item["type"] == "clarify"), 10)

    def test_group_a_sample_runs_and_writes_a_file(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        prev = eval_runner.RESULTS_DIR
        eval_runner.RESULTS_DIR = Path(tmp.name)
        self.addCleanup(setattr, eval_runner, "RESULTS_DIR", prev)
        payload = eval_runner.run_group(ROOT / "tests" / "eval" / "test-set.json", "A", limit=3)
        self.assertTrue(payload["ran"])
        self.assertEqual(payload["group"], "A")
        self.assertEqual(payload["count"], 3)
        self.assertIn("in_scope_accuracy", payload["metrics"])
        saved = json.loads(Path(payload["path"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["count"], 3)
        self.assertNotIn("DEEPSEEK_API_KEY", json.dumps(saved))


if __name__ == "__main__":
    unittest.main()
