#!/usr/bin/env python3
"""Visitor session titles and handoff subjects share web/mask.js."""
from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PortalMaskTest(unittest.TestCase):
    def test_session_title_and_handoff_subject_hide_the_phone(self) -> None:
        script = r"""
const mask = require("./web/mask.js");
const raw = "在读证明怎么办，我的手机是 13800138000";
const title = mask.sessionTitle(raw);
const subject = mask.handoffSubject(raw);
const stored = mask.maskStoredSession({
  title: raw,
  messages: [{ role: "user", text: raw }, { role: "bot", text: "到一网通办。" }],
});
const again = mask.maskPhone(subject);
if (title.includes("13800138000") || subject.includes("13800138000")) process.exit(2);
if (!title.includes("138****8000") || !subject.includes("138****8000")) process.exit(3);
if (!subject.startsWith("跟进：")) process.exit(4);
if (stored.title !== title) process.exit(5);
if (stored.messages[0].text.includes("13800138000")) process.exit(6);
if (again !== subject) process.exit(7);
if (mask.maskPhone("坐席已是 138****8000").includes("13800138000")) process.exit(8);
const glued = mask.maskPhone("联系方式+8613800138000");
if (glued.includes("13800138000") || glued.includes("+86")) process.exit(9);
if (!glued.includes("138****8000")) process.exit(10);
process.stdout.write(JSON.stringify({ title, subject }));
"""
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["title"], "在读证明怎么办，我的手机是 138****8000")
        self.assertEqual(payload["subject"], "跟进：在读证明怎么办，我的手机是 138****8000")
