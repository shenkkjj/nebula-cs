#!/usr/bin/env python3
"""DESIGN v1.0 strings that the production pages have to keep."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))


def _text(*parts: str) -> str:
    return "\n".join((ROOT / part).read_text(encoding="utf-8") for part in parts)


class DesignSurfaceTest(unittest.TestCase):
    def test_production_pages_do_not_name_teammates_or_vendors(self) -> None:
        blob = _text(
            "web/index.html",
            "web/app.js",
            "web/agent.html",
            "web/agent.js",
            "web/admin.html",
            "web/admin.js",
            "web/login.html",
            "web/login.js",
        )
        for banned in ("沈凯杰", "王瑞康", "美团", "腾讯", "阿里巴巴", "淘宝"):
            self.assertNotIn(banned, blob)

    def test_portal_states_and_staff_desk_are_in_the_pages(self) -> None:
        portal = _text("web/app.js", "web/styles.css", "web/index.html")
        self.assertIn("澄清选项", portal)
        self.assertIn("人工客服", portal)
        self.assertIn("人工接入中", portal)
        self.assertIn("知识库维护中", portal)
        self.assertIn("人工客服的回答不附引用", portal)
        self.assertIn("outline: 2px solid var(--gold)", portal)
        staff = _text("web/agent.html", "web/agent.js", "web/staff.css")
        self.assertIn("待接入", staff)
        self.assertIn("处理中", staff)
        self.assertIn("已结束", staff)
        self.assertIn('aria-current="true"', staff)
        self.assertIn("判定详情", staff)
        self.assertIn("回写知识库", staff)
        self.assertIn("标记坏例", staff)
        self.assertIn("索引中", staff)
        self.assertIn("索引完成", staff)
        self.assertIn("请写一句处理说明", staff)
        self.assertIn("max-width: 1279px", staff)
        self.assertIn("max-width: 760px", staff)
        self.assertIn("prefers-reduced-motion", staff)

    def test_admin_nav_follows_s1_and_eval_stays_honest(self) -> None:
        admin = _text("web/admin.html", "web/admin.js")
        docs = admin.index("知识库文档")
        probe = admin.index("绑定自检")
        audit = admin.index("审计日志")
        config = admin.index("约束参数")
        evaluation = admin.index(">评测<")
        self.assertLess(docs, probe)
        self.assertLess(probe, audit)
        self.assertLess(audit, config)
        self.assertLess(config, evaluation)
        self.assertIn("未运行", admin)
        self.assertIn("知识库直出", admin)
        login = _text("web/login.html", "web/login.js")
        self.assertIn("坐席", login)
        self.assertIn("管理员", login)
        self.assertIn('name="role"', login)

    def test_campus_extra_stays_out_of_the_lite_requirements(self) -> None:
        base_lines = [
            line.split("#", 1)[0].strip().lower()
            for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        ]
        base = "\n".join(line for line in base_lines if line)
        campus = (ROOT / "requirements-campus.txt").read_text(encoding="utf-8").lower()
        for banned in ("chromadb", "ollama", "langchain", "dify", "fastgpt", "ragflow", "maxkb"):
            self.assertNotIn(banned, base)
        self.assertIn("chromadb", campus)


if __name__ == "__main__":
    unittest.main()
