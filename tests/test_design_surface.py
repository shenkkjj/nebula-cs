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

    def test_qut_portal_has_scoped_guides_and_citations_without_ticket_ui(self) -> None:
        portal = _text("web/app.js", "web/index.html")
        for label in ("青岛理工大学", "校园办事助手", "办事指南", "查看出处", "打开学校原文", "非校方官方平台"):
            self.assertIn(label, portal)
        self.assertIn('data-audience="student" aria-pressed="true"', portal)
        self.assertIn('data-audience="staff" aria-pressed="false"', portal)
        self.assertIn('id="sourcePanel"', portal)
        for retired in ("/api/agent/", "/api/portal/tickets", "/api/ticket", "ticketProgress", "转人工"):
            self.assertNotIn(retired, portal)
        shared = _text("web/campus.css")
        self.assertIn(":focus-visible", shared)
        self.assertIn("prefers-reduced-motion", shared)

    def test_admin_nav_and_eval_stay_honest(self) -> None:
        admin = _text("web/admin.html", "web/admin.js")
        panels = ("overview", "feedback", "docs", "segments", "probe", "audit", "config", "eval")
        positions = [admin.index(f'data-nav="{panel}"') for panel in panels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('/api/admin/overview', admin)
        self.assertIn("历史评测", admin)
        self.assertNotIn('data-nav="handoffs"', admin)
        self.assertNotIn("/api/admin/eval/run", admin)
        self.assertNotIn("auto_ticket_on_refusal", admin)
        login = _text("web/login.html", "web/login.js")
        self.assertIn("管理登录", login)
        self.assertNotIn("坐席", login)
        self.assertNotIn('name="role"', login)
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
