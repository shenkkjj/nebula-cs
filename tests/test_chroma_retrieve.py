#!/usr/bin/env python3
"""Embedded Chroma: load, lexical fallback, hybrid rank, grounded citations."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import campus_engine
import chroma_store
import kb_retrieve
import kb_store
import store


EAST_BODY = "东侧柜台领取砚台证明，编号东砚-17。"
WEST_BODY = "西侧柜台领取砚台证明，编号西砚-18。"
QUERY = "砚台证明怎么办"


class ChromaRetrieveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.prev = {
            "DATA_DIR": os.environ.get("DATA_DIR"),
            "ENGINE": os.environ.get("ENGINE"),
            "CAMPUS_PROFILE": os.environ.get("CAMPUS_PROFILE"),
            "DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY"),
            "EMBEDDING_API_KEY": os.environ.get("EMBEDDING_API_KEY"),
            "EMBEDDING_BASE_URL": os.environ.get("EMBEDDING_BASE_URL"),
            "EMBEDDING_MODEL": os.environ.get("EMBEDDING_MODEL"),
        }
        os.environ["DATA_DIR"] = self.tmp.name
        os.environ["ENGINE"] = "campus"
        os.environ["CAMPUS_PROFILE"] = "demo"
        os.environ["DEEPSEEK_API_KEY"] = ""
        os.environ["EMBEDDING_API_KEY"] = ""
        os.environ["EMBEDDING_BASE_URL"] = ""
        os.environ["EMBEDDING_MODEL"] = "text-embedding-3-small"
        chroma_store.reset_for_tests()
        store.reconnect()
        kb_retrieve.set_embedder_for_tests(None)

    def tearDown(self) -> None:
        kb_retrieve.set_embedder_for_tests(None)
        chroma_store.reset_for_tests()
        for key, value in self.prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        store.reconnect()
        self.tmp.cleanup()

    def test_a_lexical_answer_stays_grounded_without_importing_chroma(self) -> None:
        result = campus_engine.answer(
            {
                "query": "在读证明如何办理？",
                "visitor": "eval-chroma",
                "user": "eval-chroma",
                "portal_session": "lex-1",
            }
        )
        self.assertNotIn("chromadb", sys.modules)
        self.assertEqual(result["intent"], "campus_faq")
        self.assertEqual(len(result["citations"]), 1)
        cite = result["citations"][0]
        chunks = {chunk.id: chunk for chunk in kb_store.chunks()}
        chunk = chunks[cite["segment_id"]]
        self.assertTrue(chunk.content.startswith(cite["content"]))
        self.assertIn("一网通办", cite["content"])
        self.assertIn("一网通办", result["answer"])
        self.assertIn(cite["content"], chunk.content)
        self.assertNotIn("chromadb", sys.modules)

    def test_fallback_when_chroma_is_disabled(self) -> None:
        calls = {"n": 0}

        def embed(texts: list[str]) -> list[list[float]]:
            calls["n"] += 1
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

        kb_retrieve.set_embedder_for_tests(embed)
        chroma_store.force_unavailable(True)
        with self.assertLogs("nebula.chroma", level="WARNING") as captured:
            status, payload = kb_retrieve.rebuild_embeddings()
        self.assertEqual(status, 503, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["fallback"], "lexical")
        self.assertEqual(calls["n"], 0)
        self.assertTrue(any("lexical-only" in line for line in captured.output))
        kb_retrieve.set_embedder_for_tests(lambda texts: [[1.0, 0.0, 0.0, 0.0] for _ in texts])
        self._add_pair()
        hit = kb_retrieve.search(QUERY)
        self.assertEqual(hit["action"], "clarify")
        self.assertEqual(hit["method"], "lexical")
        answered = campus_engine.answer(
            {
                "query": "在读证明如何办理？",
                "visitor": "eval-chroma",
                "user": "eval-chroma",
                "portal_session": "fall-1",
            }
        )
        self.assertIn("一网通办", answered["answer"])
        self.assertTrue(answered["citations"])

    def test_open_failure_stays_lexical(self) -> None:
        def boom(_path: str):
            raise RuntimeError("disk full")

        original = chroma_store._open_client
        chroma_store._open_client = boom
        try:
            with self.assertLogs("nebula.chroma", level="WARNING") as captured:
                self.assertFalse(chroma_store.ensure())
            self.assertTrue(any("lexical-only" in line for line in captured.output))
        finally:
            chroma_store._open_client = original
        result = kb_retrieve.search("在读证明如何办理？")
        self.assertEqual(result["action"], "answer")
        self.assertEqual(result["method"], "lexical")
        self.assertIn("在读证明", result["chunks"][0].title)

    def test_hybrid_breaks_a_lexical_tie_and_cites_that_segment(self) -> None:
        east_id, west_id = self._add_pair()
        before = kb_retrieve.search(QUERY)
        self.assertEqual(before["action"], "clarify")
        self.assertEqual(before["method"], "lexical")
        self.assertEqual({chunk.title for chunk in before["chunks"]}, {"砚台证明如何办理", "砚台证明怎么办理"})
        kb_retrieve.set_embedder_for_tests(lambda texts: [[1.0, 0.0, 0.0, 0.0] for _ in texts])
        still = kb_retrieve.search(QUERY)
        self.assertEqual(still["action"], "clarify")
        self.assertEqual(still["method"], "lexical")
        if not chroma_store.ensure():
            self.assertIn("lexical-only", chroma_store.describe()["reason"])
            return
        model = kb_retrieve.embedding_config()["model"]
        saved = kb_store.save_vectors(
            model,
            [(int(east_id), [1.0, 0.0, 0.0, 0.0]), (int(west_id), [0.0, 1.0, 0.0, 0.0])],
        )
        self.assertEqual(saved, 2)
        nearest = kb_store.knn(model, [1.0, 0.0, 0.0, 0.0], 2)
        self.assertEqual(nearest[0][0], east_id)
        self.assertAlmostEqual(nearest[0][1], 0.0, places=5)
        hit = kb_retrieve.search(QUERY)
        self.assertEqual(hit["action"], "answer")
        self.assertEqual(hit["method"], "hybrid")
        self.assertEqual(hit["chunks"][0].id, east_id)
        self.assertIn("东砚-17", hit["chunks"][0].answer)
        answered = campus_engine.answer(
            {
                "query": QUERY,
                "visitor": "eval-chroma",
                "user": "eval-chroma",
                "portal_session": "hyb-1",
            }
        )
        self.assertFalse(answered["refuse"])
        self.assertEqual(len(answered["citations"]), 1)
        cite = answered["citations"][0]
        self.assertEqual(cite["segment_id"], east_id)
        self.assertIn("东砚-17", cite["content"])
        self.assertIn("东砚-17", answered["answer"])
        self.assertNotIn("西砚-18", answered["answer"])
        chunks = {chunk.id: chunk for chunk in kb_store.chunks()}
        self.assertTrue(chunks[east_id].content.startswith(cite["content"]))
        self.assertNotIn("西砚-18", cite["content"])
        self.assertTrue(kb_store.delete_segment(east_id))
        after = kb_store.knn(model, [1.0, 0.0, 0.0, 0.0], 2)
        self.assertNotIn(east_id, [segment_id for segment_id, _distance in after])
        gone = campus_engine.answer(
            {
                "query": QUERY,
                "visitor": "eval-chroma",
                "user": "eval-chroma",
                "portal_session": "hyb-2",
            }
        )
        self.assertNotIn("东砚-17", gone["answer"])

    def test_legacy_json_vectors_move_into_chroma(self) -> None:
        if not chroma_store.ensure():
            self.assertTrue(chroma_store.describe()["fallback"])
            return
        east_id, west_id = self._add_pair()
        model = kb_retrieve.embedding_config()["model"]
        with store.exclusive() as conn:
            for segment_id, vector in (
                (int(east_id), [1.0, 0.0, 0.0, 0.0]),
                (int(west_id), [0.0, 1.0, 0.0, 0.0]),
            ):
                conn.execute(
                    """
                    INSERT INTO kb_vectors (segment_id, model, vector_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (segment_id, model, json.dumps(vector), store.now()),
                )
        kb_retrieve.set_embedder_for_tests(lambda texts: [[1.0, 0.0, 0.0, 0.0] for _ in texts])
        hit = kb_retrieve.search(QUERY)
        self.assertEqual(hit["method"], "hybrid")
        self.assertIn("东砚-17", hit["chunks"][0].answer)
        self.assertGreaterEqual(chroma_store.count(model), 2)

    def _add_pair(self) -> tuple[str, str]:
        east = kb_store.add_text_document(
            "东砚.md",
            f"## 砚台证明如何办理\n{EAST_BODY}\n",
        )
        west = kb_store.add_text_document(
            "西砚.md",
            f"## 砚台证明怎么办理\n{WEST_BODY}\n",
        )
        return east["segments"][0]["id"], west["segments"][0]["id"]


if __name__ == "__main__":
    unittest.main()
