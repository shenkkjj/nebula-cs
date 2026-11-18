#!/usr/bin/env python3
"""Portal and staff UI contracts, with previous design prototypes retained."""
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
        portal = _text("web/app.js", "web/index.html")
        for state in ("澄清选项", "人工客服", "等待坐席接入", "人工已接入", "知识库维护中"):
            self.assertIn(state, portal)
        self.assertIn('id="sourcePanel"', portal)
        self.assertIn('id="ticketProgress"', portal)
        self.assertIn('aria-labelledby="ticketTitle"', portal)
        staff = _text("web/agent.html", "web/agent.js")
        for label in ("待接入", "处理中", "已结束", "处理详情", "写入知识库", "标记坏例", "索引中", "索引完成", "请写一句处理说明"):
            self.assertIn(label, staff)
        self.assertIn('setAttribute("aria-current", "true")', staff)
        self.assertIn('role="tablist"', staff)
        shared = _text("web/campus.css")
        self.assertIn(":focus-visible", shared)
        self.assertIn("prefers-reduced-motion", shared)

    def test_admin_nav_and_eval_stay_honest(self) -> None:
        admin = _text("web/admin.html", "web/admin.js")
        panels = ("overview", "handoffs", "feedback", "docs", "segments", "probe", "audit", "config", "eval")
        positions = [admin.index(f'data-nav="{panel}"') for panel in panels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('/api/admin/overview', admin)
        self.assertIn("未运行", admin)
        self.assertIn("知识库直出", admin)
        login = _text("web/login.html", "web/login.js")
        self.assertIn("坐席", login)
        self.assertIn("管理员", login)
        self.assertIn('name="role"', login)
        self.assertNotIn("admin123", login)
        self.assertNotIn("agent123", login)
        self.assertNotIn("演示账号", login)
        home = _text("web/index.html")
        self.assertIn("/fonts/fonts.css?v=", home)
        self.assertIn("/campus.css?v=", home)
        self.assertIn("/portal.css?v=", home)
        self.assertNotIn("campus.webp", home + login + _text("web/portal.css", "web/staff.css"))
        self.assertIn("app.js?v=", home)
        admin = _text("web/admin.js")
        self.assertIn("历史记录", admin)
        self.assertIn("item.historical", admin)
        self.assertNotIn('historical) return `${text} <span class="badge ok">', admin)

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

    def test_pages_serve_local_fonts_and_the_preview_is_confirmed(self) -> None:
        files = list((ROOT / "web").rglob("*.html"))
        files += list((ROOT / "web").rglob("*.css"))
        files += list((ROOT / "web").rglob("*.js"))
        files += list((ROOT / "docs" / "design").rglob("*.html"))
        files += list((ROOT / "docs" / "design").rglob("*.css"))
        blob = "\n".join(path.read_text(encoding="utf-8") for path in files)
        self.assertNotIn("fonts.googleapis.com", blob)
        self.assertNotIn("fonts.gstatic.com", blob)
        css = (ROOT / "web" / "fonts" / "fonts.css").read_text(encoding="utf-8")
        self.assertIn("Cormorant Garamond", css)
        self.assertIn("Manrope", css)
        self.assertIn("font-weight: 500 700", css)
        self.assertIn("font-weight: 400 700", css)
        for name in (
            "cormorant-garamond.woff2",
            "cormorant-garamond-500-italic.woff2",
            "manrope.woff2",
            "CormorantGaramond-OFL.txt",
            "Manrope-OFL.txt",
        ):
            self.assertTrue((ROOT / "web" / "fonts" / name).is_file(), name)
        page = (ROOT / "docs" / "design" / "index.html").read_text(encoding="utf-8")
        for banned in ("尚未确认", "选定前不会替换", "无一款已确认", "沉默不算确认", "沈凯杰", "王瑞康", "美团", "腾讯", "阿里巴巴"):
            self.assertNotIn(banned, page)
        self.assertIn("现代校园", page)
        self.assertIn("归档", page)
        self.assertIn("这不是正式终验", page)
        self.assertNotIn("新设计还没实施", page)
        self.assertNotIn("旧版门户", page)
        self.assertIn("E5", page)
        self.assertIn("S1", page)


if __name__ == "__main__":
    unittest.main()
