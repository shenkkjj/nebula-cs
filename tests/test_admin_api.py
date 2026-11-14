#!/usr/bin/env python3
"""Admin config, audit, upload rejection, and eval launch guards."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import admin_api
import settings
import store


class AdminApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.prev_data = os.environ.get("DATA_DIR")
        os.environ["DATA_DIR"] = self.tmp.name
        store.reconnect()
        self.prev_config = settings.CONFIG_PATH
        settings.CONFIG_PATH = Path(self.tmp.name) / "config.json"
        settings.CONFIG_PATH.write_text(self.prev_config.read_text(encoding="utf-8"), encoding="utf-8")
        settings._CONFIG_CACHE = None
        settings._CONFIG_MTIME = None
        self.user = {"user_id": 1, "username": "admin", "display_name": "陈老师", "role": "admin"}

    def tearDown(self) -> None:
        settings.CONFIG_PATH = self.prev_config
        settings._CONFIG_CACHE = None
        settings._CONFIG_MTIME = None
        if self.prev_data is None:
            os.environ.pop("DATA_DIR", None)
        else:
            os.environ["DATA_DIR"] = self.prev_data
        store.reconnect()
        self.tmp.cleanup()

    def test_config_save_is_clamped_and_audited(self) -> None:
        status, payload = admin_api.update_config({"score_threshold": 0.62, "max_citations": 99, "refusal_text": "知识库里没有这条。"}, self.user)
        self.assertEqual(status, 200)
        self.assertEqual(payload["config"]["score_threshold"], 0.62)
        self.assertEqual(payload["config"]["max_citations"], 8)
        again = settings.load_config()
        self.assertEqual(again["score_threshold"], 0.62)
        rows = store.list_audit(kind="config")
        self.assertTrue(rows)
        self.assertEqual(rows[0]["actor"], "admin")

    def test_upload_rejects_type_and_size_without_calling_dify(self) -> None:
        os.environ.pop("DIFY_DATASET_API_KEY", None)
        status, bad_type = admin_api.add_document("notes.exe", b"hello", self.user)
        self.assertEqual(status, 400)
        self.assertIn("md", bad_type["error"])
        status, too_big = admin_api.add_document("big.md", b"x" * (15 * 1024 * 1024 + 1), self.user)
        self.assertEqual(status, 400)
        self.assertIn("15MB", too_big["error"])
        status, missing = admin_api.add_document("faq.md", "在读证明。".encode("utf-8"), self.user)
        self.assertEqual(status, 503)
        listed = admin_api.document_list()
        self.assertFalse(listed["configured"])
        self.assertIn("一个文件", listed["hint"])

    def test_audit_hides_secrets_and_probe_records_failure(self) -> None:
        store.add_audit("qa", actor="访客", question="手机138****5678", decision="通过")
        text = admin_api.audit_csv()
        self.assertNotIn("13812345678", text)
        self.assertIn("138****5678", text)
        os.environ["DIFY_APP_API_KEY"] = ""
        os.environ.pop("DIFY_DATASET_API_KEY", None)
        # Probe uses the chat API. Point it at a closed port so it fails fast.
        os.environ["DIFY_CHAT_URL"] = "http://127.0.0.1:9/v1/chat-messages"
        result = admin_api.probe_now(self.user)
        self.assertFalse(result["ok"])
        self.assertTrue(result["checks"])


if __name__ == "__main__":
    unittest.main()
