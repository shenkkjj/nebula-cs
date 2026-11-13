#!/usr/bin/env python3
"""校园客服门户 — 本地代理：托管静态页 + 转发 Dify Chat API（支持 SSE 流式）。

也支持 LITE_MODE：无 Dify 容器，本地 FAQ 检索 + 可选 DeepSeek / 模板作答（适合 Render Free）。

密钥只从环境变量 DIFY_APP_API_KEY 或文件 /tmp/dify-app-api-key.txt 读取，
绝不回显给浏览器。DeepSeek 密钥仅服务端使用。
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

from lite_skills import (
    contains_sensitive,
    redact_sensitive,
    safety_payload,
    ticket_sensitive_message,
)

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
DESIGN_DIR = ROOT / "docs" / "design"
DEFAULT_KEY_FILE = Path("/tmp/dify-app-api-key.txt")
DIFY_CHAT_URL = (
    os.environ.get("DIFY_CHAT_URL")
    or os.environ.get("DIFY_API_URL")
    or "http://127.0.0.1/v1/chat-messages"
).strip()


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def use_lite_mode() -> bool:
    """LITE_MODE=1, or no Dify URL configured (empty / unset marker)."""
    if _env_truthy("LITE_MODE"):
        return True
    # Explicit empty DIFY_CHAT_URL / DIFY_API_URL → lite
    raw_chat = os.environ.get("DIFY_CHAT_URL")
    raw_api = os.environ.get("DIFY_API_URL")
    if raw_chat is not None and not raw_chat.strip():
        return True
    if raw_api is not None and not str(raw_api).strip() and raw_chat is None:
        return True
    if _env_truthy("RENDER") and not (os.environ.get("DIFY_APP_API_KEY") or "").strip():
        # On Render without Dify credentials, prefer lite
        if not Path(os.environ.get("DIFY_APP_API_KEY_FILE", str(DEFAULT_KEY_FILE))).is_file():
            return True
    return False


LITE_MODE = use_lite_mode()

# Render Free: bind 0.0.0.0 and honor $PORT. Local demo keeps 127.0.0.1:8787.
if os.environ.get("PORT"):
    HOST = os.environ.get("PORTAL_HOST", "0.0.0.0")
    PORT = int(os.environ["PORT"])
else:
    HOST = os.environ.get("PORTAL_HOST", "127.0.0.1" if not LITE_MODE else "0.0.0.0")
    PORT = int(os.environ.get("PORTAL_PORT", "8787"))

if LITE_MODE:
    from lite_engine import (  # noqa: E402
        answer_lite,
        deepseek_api_key,
        faq_catalog,
        iter_deepseek_stream,
        lite_ready,
    )

THINK_RE = re.compile(
    r"<think>.*?</think>|<!--dify-deepseek-reasoning-->",
    re.DOTALL | re.IGNORECASE,
)


def load_api_key() -> str:
    if LITE_MODE:
        return ""
    key = (os.environ.get("DIFY_APP_API_KEY") or "").strip()
    if key:
        return key
    key_file = Path(os.environ.get("DIFY_APP_API_KEY_FILE", str(DEFAULT_KEY_FILE)))
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip()
    raise SystemExit(
        f"缺少应用 API Key：请设置 DIFY_APP_API_KEY 或写入 {key_file}；"
        f"或设置 LITE_MODE=1 使用本地 FAQ 轻量模式"
    )


def clean_answer(text: str) -> str:
    if not text:
        return ""
    return THINK_RE.sub("", text).strip()


def looks_like_refuse(answer: str, citations: list | None = None) -> bool:
    """仅在明确拒答/空依据时标 refuse；正常回答顺带提「可转人工」不算。"""
    a = (answer or "").strip()
    if not a:
        return True
    hard = (
        "知识库未覆盖",
        "未找到依据",
        "未找到相关信息",
        "无法从知识库",
        "检索到的知识库内容为空",
        "检索结果为空",
        "超出知识库",
        "没有找到相关",
        "已拒答",
        "建议转人工",
        "建议转接人工",
        "请转接人工",
        "请转人工",
    )
    if any(m in a for m in hard):
        soft_only = ("建议转人工", "请转人工", "请转接人工", "建议转接人工")
        hard_core = [m for m in hard if m not in soft_only]
        if citations and len(citations) > 0 and not any(m in a for m in hard_core):
            return False
        return True
    if not citations and a.startswith(("抱歉", "无法", "未能")):
        return True
    return False



HANDOFF_RE = re.compile(
    r"(转\s*人工|人工\s*客服|人工\s*坐席|转接\s*人工|找\s*人工|联系\s*人工|有没有真人|找真人)"
)
ANGRY_RE = re.compile(
    r"(我要投诉|投诉你们|我要反馈|太差了|服务太差|气死了|垃圾客服|找你们领导|找领导|受不了了|根本解决不了)"
)
_RESTART_RE = re.compile(r"^(重新开始|重新来过|换个话题|清空对话|开始新对话)[。.!！]?$")
_BACK_RE = re.compile(r"^(返回上一个问题|回到上一个问题|上一个问题|返回上一题|回到刚才)[。.!！]?$")
ORDER_RE = re.compile(
    r"(?:办事(?:单号|编号|进度)?|报修(?:单号|编号|进度)?|申请(?:单号|编号)?|"
    r"查一下(?:办事|报修|进度)|查询(?:办事(?:进度|单号|编号)?|报修(?:进度|单号)?|进度))"
    r"\s*[:：#]?\s*"
    r"(SW\d{6,}|BX\d{6,}|JY\d{6,})",
    re.IGNORECASE,
)
ORDER_BARE_RE = re.compile(r"\b(SW\d{6,}|BX\d{6,}|JY\d{6,})\b", re.IGNORECASE)
_ASPECT_RULES = (
    ("需要什么材料", re.compile(r"材料|要准备|要带")),
    ("在哪里办理", re.compile(r"在哪|哪里|去哪|哪个窗口")),
    ("需要多久", re.compile(r"多久|多长时间|几天|能下来|什么时候能|何时能")),
    ("费用是多少", re.compile(r"多少钱|费用|收费")),
)
_ASPECT_TOPIC_RE = re.compile(r"^(材料|多久|费用|哪里|时限|手续|流程|多久能下来|什么材料|怎么办)$")
_FOLLOW_STRIP_RE = re.compile(
    r"(那|么|这个|那个|请问|一下|多久|多长时间|几天|能下来|什么材料|哪些材料|要什么材料|"
    r"需要什么材料|要准备|要带|在哪里办|在哪里|去哪|多少钱|费用|是多少|怎么|如何|办理|"
    r"需要|什么|哪些|吗|呢|嘛|呀|啊|吧|的|了|请|帮我|想问|材料)"
)

# 演示用办事进度存根（无真实办件后台）。字段沿用本地查询结构。
MOCK_ORDERS = {
    "SW20260001": {
        "status": "办理中",
        "office": "信息化办公室",
        "eta": "预计 1 个工作日内完成",
        "items": "校园网账号开通",
    },
    "BX20260118": {
        "status": "已派工",
        "office": "后勤报修",
        "eta": "预计今日上门",
        "items": "宿舍空调不制冷",
    },
    "JY20260302": {
        "status": "待取件",
        "office": "教务处",
        "eta": "证明已开好，请工作日到窗口领取",
        "items": "在读证明 ×1",
    },
}


def last_user_turns(history: list | None, limit: int = 4) -> list[str]:
    turns = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or "").lower()
        text = (item.get("text") or item.get("content") or item.get("query") or "").strip()
        if role in ("user", "human") and text:
            turns.append(text)
    return turns[-limit:]


def is_restart(query: str) -> bool:
    return bool(_RESTART_RE.match((query or "").strip()))


def is_back(query: str) -> bool:
    return bool(_BACK_RE.match((query or "").strip()))


def _aspect_phrase(query: str) -> str:
    for label, pattern in _ASPECT_RULES:
        if pattern.search(query or ""):
            return label
    return ""


def is_followup_query(query: str) -> bool:
    """Ellipsis such as 那多久能下来 / 要什么材料, not a fresh question."""
    q = (query or "").strip()
    if not q or len(q) > 22 or is_restart(q) or is_back(q):
        return False
    if re.match(r"^(?:那|那么|还有|另外|这个|那个)?\s*[\u4e00-\u9fffA-Za-z0-9]{1,12}\s*呢[？?]?$", q):
        return True
    if re.match(r"^(那|那么|这个|那个|还有|另外)", q) and len(q) <= 18:
        return True
    if not _aspect_phrase(q):
        return False
    stripped = _FOLLOW_STRIP_RE.sub("", q)
    stripped = re.sub(r"[\s？?！!。.,，]", "", stripped)
    return len(stripped) < 2


def _switch_topic(query: str) -> str:
    match = re.match(
        r"^(?:那|那么|还有|另外|这个|那个)?\s*([\u4e00-\u9fffA-Za-z0-9]{1,12})\s*呢[？?]?$",
        (query or "").strip(),
    )
    if not match:
        return ""
    topic = match.group(1).strip()
    if _ASPECT_TOPIC_RE.match(topic) or _aspect_phrase(topic):
        return ""
    return topic


def _substantive_users(history: list | None, current: str) -> list[str]:
    kept = []
    for text in last_user_turns(history, 8):
        if text == current or "已隐去" in text:
            continue
        if is_restart(text) or is_back(text) or is_followup_query(text):
            continue
        kept.append(text)
    return kept


def needs_query_rewrite(query: str, history: list | None) -> bool:
    q = (query or "").strip()
    if not q or not history:
        return False
    return is_followup_query(q) or is_back(q)


def rewrite_query_for_retrieval(query: str, history: list | None) -> tuple[str, dict | None]:
    """Keep follow-ups on the previous campus intent. No extra model call."""
    q = (query or "").strip()
    if is_restart(q):
        return q, {"original": q, "rewritten": q, "method": "restart"}
    if not is_followup_query(q) and not is_back(q):
        return q, None
    anchors = _substantive_users(history, q)
    if is_back(q):
        if not anchors:
            return q, {"original": q, "rewritten": q, "method": "back", "missing": True}
        target = anchors[-2] if len(anchors) >= 2 else anchors[-1]
        return target, {
            "original": q,
            "rewritten": target,
            "based_on": target[:80],
            "method": "back",
        }
    if not anchors:
        return q, None
    prev = anchors[-1]
    switched = _switch_topic(q)
    if switched and switched not in prev:
        return switched, {
            "original": q,
            "rewritten": switched,
            "based_on": prev[:80],
            "method": "topic-switch",
        }
    aspect = _aspect_phrase(q) or "请补充说明"
    rewritten = f"{prev} {aspect}"
    return rewritten, {
        "original": q,
        "rewritten": rewritten,
        "based_on": prev[:80],
        "method": "follow-up",
    }


def is_handoff_intent(query: str) -> bool:
    q = query or ""
    if re.search(r"(什么情况|什么时候|何时|如何|怎么|哪些|要不要|是否).{0,12}转\s*人工", q):
        return False
    if re.search(r"转\s*人工.{0,8}(什么|哪些|条件|情况)", q):
        return False
    if HANDOFF_RE.search(q) or ANGRY_RE.search(q):
        return True
    return False


def classify_portal_intent(query: str) -> str:
    """Intent gate before any FAQ lookup: safety, restart, handoff, ticket, then lite."""
    if contains_sensitive(query):
        return "safety"
    if is_restart(query):
        return "restart"
    if is_handoff_intent(query):
        return "handoff"
    if lookup_mock_order(query) is not None:
        return "ticket"
    if is_back(query):
        return "back"
    return "lite"


def _public_shaped(shaped: dict) -> dict:
    return {key: value for key, value in shaped.items() if not str(key).startswith("_")}


def safety_shaped(query: str) -> dict:
    spec = safety_payload(redact_sensitive(query))
    return {
        "answer": spec["answer"],
        "citations": [],
        "refuse": False,
        "clarify": False,
        "suggestions": list(spec["suggestions"]),
        "sensitive": True,
        "redacted_query": spec["redacted_query"],
        "agent_action": "safety",
        "intent": "safety",
        "engine": "lite" if LITE_MODE else "proxy",
        "generator": "safety",
        "handoff": False,
        "streamed": False,
    }


def make_ticket_id(*parts: str) -> str:
    seed = "|".join(parts) or "handoff"
    return "TK" + str(abs(hash(seed)) % 10_000_000).zfill(7)


def handoff_payload(query: str, user: str, detail: str = "") -> dict:
    ticket_id = make_ticket_id(query, user, detail, "handoff")
    answer = (
        "好的，已为你转接人工（演示）。说一下事项即可，不必填写身份证号、银行卡或病历。\n\n"
        f"- 演示工单号：**{ticket_id}**\n"
        "- 状态：**已受理（本地存根）**\n"
        "- 说明：当前环境未对接真实坐席队列；工单只留在这次演示回执里。\n\n"
        "可以点「转人工」补一句联系方式，或继续在对话里说明。"
    )
    return {
        "answer": answer,
        "citations": [],
        "conversation_id": "",
        "message_id": "",
        "refuse": False,
        "handoff": True,
        "ticket_id": ticket_id,
        "agent_action": "human_handoff",
        "streamed": False,
    }


_ORDER_SUGGESTIONS = (
    {"label": "和一网通办的区别", "query": "一网通办「我的申请」和对话里查进度有何区别？"},
    {"label": "转人工", "query": "转人工"},
)
_DEMO_NOTE = "这是演示查单，不是一网通办里的真实进度。真实办件请以一网通办「我的申请」为准。"


def lookup_mock_order(query: str) -> dict | None:
    text = query or ""
    oid = None
    matched = ORDER_RE.search(text)
    if matched:
        oid = matched.group(1)
    else:
        bare = ORDER_BARE_RE.search(text)
        if bare:
            compact = re.sub(r"[\s？?！!。.,，]", "", text)
            keywords = ("办事", "报修", "进度", "申请", "查询", "教务", "宿舍", "校园网", "查单", "查一下")
            if compact.upper() == bare.group(1).upper() or any(word in text for word in keywords) or len(text) <= 24:
                oid = bare.group(1)
    if not oid:
        return None
    key = oid.upper().replace("_", "-")
    # normalize ORD-123 → try both
    variants = {key, key.replace("-", ""), oid.upper()}
    info = None
    for v in variants:
        if v in MOCK_ORDERS:
            info = MOCK_ORDERS[v]
            key = v
            break
        # also try compact IDs such as SW20260001
        compact = v.replace("-", "")
        for mk, mv in MOCK_ORDERS.items():
            if mk.replace("-", "") == compact:
                info = mv
                key = mk
                break
        if info:
            break
    if not info:
        # unknown id — still demo-grade stub
        ticket_id = make_ticket_id(oid, "order-miss")
        return {
            "answer": (
                f"未在演示办事库中找到 **{oid}**。{_DEMO_NOTE}\n\n"
                "可试：`SW20260001` / `BX20260118` / `JY20260302`。\n"
                f"若要工作人员核实，可以说转人工（演示工单可登记为 {ticket_id}）。"
            ),
            "citations": [],
            "suggestions": list(_ORDER_SUGGESTIONS),
            "conversation_id": "",
            "message_id": "",
            "refuse": False,
            "handoff": False,
            "agent_action": "order_lookup",
            "order_id": oid,
            "order_found": False,
            "streamed": False,
        }
    return {
        "answer": (
            f"已查到演示单 **{key}**。{_DEMO_NOTE}\n\n"
            f"- 事项：{info['items']}\n"
            f"- 状态：**{info['status']}**\n"
            f"- 经办：{info['office']}\n"
            f"- 时效：{info['eta']}\n\n"
            "催办、补材料或撤销需要工作人员，可以说转人工。"
        ),
        "citations": [],
        "suggestions": list(_ORDER_SUGGESTIONS),
        "conversation_id": "",
        "message_id": "",
        "refuse": False,
        "handoff": False,
        "agent_action": "order_lookup",
        "order_id": key,
        "order_found": True,
        "streamed": False,
    }


def shape_citations(resources) -> list:
    citations = []
    for item in resources or []:
        if not isinstance(item, dict):
            continue
        citations.append(
            {
                "document_name": item.get("document_name")
                or item.get("document_id")
                or "未命名文档",
                "dataset_name": item.get("dataset_name") or "",
                "score": item.get("score"),
                "content": (item.get("content") or "")[:480],
                "segment_id": item.get("segment_id") or "",
            }
        )
    return citations


class ThinkStripper:
    """流式剔除 <think>…</think> 与 reasoning 注释，只放出可见回答。"""

    OPEN = "<think>"
    CLOSE = "</think>"
    COMMENT = "<!--dify-deepseek-reasoning-->"

    def __init__(self) -> None:
        self.buf = ""
        self.in_think = False

    def _partial_suffix(self, s: str, token: str) -> int:
        """若 s 末尾是 token 的真前缀，返回应保留长度。"""
        max_keep = min(len(s), len(token) - 1)
        for n in range(max_keep, 0, -1):
            if token.lower().startswith(s[-n:].lower()):
                return n
        return 0

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self.buf += chunk
        out: list[str] = []
        while True:
            if self.in_think:
                lower = self.buf.lower()
                end = lower.find(self.CLOSE)
                if end < 0:
                    keep = self._partial_suffix(self.buf, self.CLOSE)
                    if keep:
                        self.buf = self.buf[-keep:]
                    else:
                        self.buf = ""
                    break
                self.buf = self.buf[end + len(self.CLOSE) :]
                self.in_think = False
                continue

            lower = self.buf.lower()
            start = lower.find(self.OPEN)
            if start < 0:
                keep = self._partial_suffix(self.buf, self.OPEN)
                if keep:
                    emit, self.buf = self.buf[:-keep], self.buf[-keep:]
                else:
                    emit, self.buf = self.buf, ""
                if emit:
                    out.append(emit.replace(self.COMMENT, ""))
                break

            emit = self.buf[:start].replace(self.COMMENT, "")
            if emit:
                out.append(emit)
            self.buf = self.buf[start + len(self.OPEN) :]
            self.in_think = True
        return "".join(out)

    def flush(self) -> str:
        if self.in_think:
            self.buf = ""
            return ""
        emit = self.buf.replace(self.COMMENT, "")
        self.buf = ""
        return emit


def dify_base() -> str:
    """从 chat URL 推导 /v1 基址。"""
    u = urlparse(DIFY_CHAT_URL)
    # http://127.0.0.1/v1/chat-messages → http://127.0.0.1/v1
    path = u.path.rstrip("/")
    if path.endswith("/chat-messages"):
        path = path[: -len("/chat-messages")]
    return f"{u.scheme}://{u.netloc}{path}"


class PortalHandler(SimpleHTTPRequestHandler):
    api_key: str = ""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def end_headers(self) -> None:
        if self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store")
        else:
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        raw = self.path.split("?", 1)[0]
        if raw in ("/api/health", "/api/health/"):
            features = ["query_rewrite", "human_handoff", "order_stub"]
            payload = {
                "ok": True,
                "service": "nebula-cs",
                "engine": "lite" if LITE_MODE else "dify",
                "streaming": True,
                "agent": True,
                "features": features + (["lite_faq", "deepseek_optional", "assistant_intro"] if LITE_MODE else []),
                "lite_mode": LITE_MODE,
            }
            if LITE_MODE:
                try:
                    payload["lite"] = lite_ready()
                except Exception as exc:  # noqa: BLE001
                    payload["lite"] = {"error": type(exc).__name__}
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if raw in ("/api/faq-nav", "/api/faq-nav/"):
            if not LITE_MODE:
                self._json_error(404, "办事导航只在轻量模式提供")
                return
            self._json_response(200, faq_catalog())
            return
        if raw.startswith("/api/"):
            self._json_error(404, "unknown endpoint")
            return
        if raw == "/design" or raw.startswith("/design/"):
            return self._serve_design(raw)
        if raw == "/" or raw == "":
            self.path = "/index.html"
        return super().do_GET()

    def _serve_design(self, raw: str) -> None:
        rel = raw[len("/design") :]
        if rel in ("", "/"):
            rel = "/index.html"
        candidate = (DESIGN_DIR / rel.lstrip("/")).resolve()
        try:
            candidate.relative_to(DESIGN_DIR.resolve())
        except ValueError:
            self._json_error(403, "forbidden")
            return
        if candidate.is_dir():
            candidate = candidate / "index.html"
        if not candidate.is_file():
            self.send_error(404, "design file not found")
            return
        import mimetypes

        ctype, _ = mimetypes.guess_type(str(candidate))
        if not ctype:
            ctype = "application/octet-stream"
        if candidate.suffix.lower() in (".html", ".htm"):
            ctype = "text/html; charset=utf-8"
        elif candidate.suffix.lower() == ".css":
            ctype = "text/css; charset=utf-8"
        elif candidate.suffix.lower() == ".js":
            ctype = "application/javascript; charset=utf-8"
        data = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        path = self.path.rstrip("/")
        if path == "/api/chat":
            return self._handle_chat()
        if path == "/api/chat/stop":
            return self._handle_stop()
        if path == "/api/ticket":
            return self._handle_ticket()
        self._json_error(404, "unknown endpoint")

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid json: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    def _json_response(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: int, message: str, **extra) -> None:
        payload = {"error": message, **extra}
        self._json_response(status, payload)

    def _handle_ticket(self) -> None:
        try:
            data = self._read_json()
        except ValueError as exc:
            self._json_error(400, str(exc))
            return
        subject = (data.get("subject") or "").strip() or "未填写主题"
        detail = (data.get("detail") or "").strip()
        contact = (data.get("contact") or "").strip()
        blocked = ticket_sensitive_message(subject, detail, contact)
        if blocked:
            self._json_response(400, {"ok": False, "message": blocked})
            return
        ticket_id = "TK" + str(abs(hash(subject + detail + contact)) % 10_000_000).zfill(7)
        self._json_response(
            200,
            {
                "ok": True,
                "ticket_id": ticket_id,
                "message": f"已登记演示工单 {ticket_id}。状态：已受理（本地存根，未对接真实坐席队列）。",
            },
        )

    def _handle_stop(self) -> None:
        try:
            data = self._read_json()
        except ValueError as exc:
            self._json_error(400, str(exc))
            return
        task_id = (data.get("task_id") or "").strip()
        user = (data.get("user") or "nebula-portal").strip()[:64] or "nebula-portal"
        if LITE_MODE:
            # Lite has no upstream task; client aborts locally.
            self._json_response(
                200, {"ok": True, "stopped": True, "lite": True, "task_id": task_id}
            )
            return
        if not task_id:
            self._json_error(400, "task_id 不能为空")
            return
        stop_url = f"{dify_base()}/chat-messages/{task_id}/stop"
        req = urllib.request.Request(
            stop_url,
            data=json.dumps({"user": user}).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                status = resp.status
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            # 停止失败不阻断前端：仍返回 ok，让客户端本地 abort
            self._json_response(
                200,
                {
                    "ok": False,
                    "stopped": False,
                    "detail": err_body[:200] or str(exc),
                    "upstream_status": exc.code,
                },
            )
            return
        except Exception as exc:  # noqa: BLE001
            self._json_response(
                200, {"ok": False, "stopped": False, "detail": type(exc).__name__}
            )
            return
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw[:200]}
        self._json_response(
            200, {"ok": True, "stopped": True, "upstream_status": status, "result": payload}
        )

    def _parse_chat_request(self) -> tuple[dict, bool, list, str] | None:
        try:
            data = self._read_json()
        except ValueError as exc:
            self._json_error(400, str(exc))
            return None

        query = (data.get("query") or "").strip()
        if not query:
            self._json_error(400, "query 不能为空")
            return None
        if len(query) > 2000:
            self._json_error(400, "query 过长")
            return None

        user = (data.get("user") or "nebula-portal").strip()[:64] or "nebula-portal"
        conversation_id = (data.get("conversation_id") or "").strip()
        # 默认流式；显式 stream:false 走阻塞（便于 curl 验收）
        stream = data.get("stream")
        if stream is None:
            stream = True
        else:
            stream = bool(stream)

        history = data.get("history") or data.get("recent_turns") or []
        if not isinstance(history, list):
            history = []
        # 仅保留最近若干轮，防滥用。历史里的证件号先抹掉，避免追问把它们拼回去。
        history = history[-12:]
        safe_history = []
        for item in history:
            if isinstance(item, dict):
                copied = dict(item)
                for field in ("text", "content", "query"):
                    if copied.get(field):
                        copied[field] = redact_sensitive(str(copied.get(field) or ""))
                safe_history.append(copied)
            else:
                safe_history.append(item)
        history = safe_history

        if contains_sensitive(query):
            redacted = redact_sensitive(query)
            upstream = {
                "inputs": {},
                "query": redacted,
                "response_mode": "streaming" if stream else "blocking",
                "user": user,
                "_original_query": redacted,
                "_rewrite": None,
                "_sensitive": True,
            }
            if conversation_id:
                upstream["conversation_id"] = conversation_id
            return upstream, stream, history, redacted

        # Agent 层：查询改写（短指代 → 可检索问句）；上游仍走 Dify KR
        rewritten, rewrite_meta = rewrite_query_for_retrieval(query, history)
        upstream_query = rewritten

        upstream = {
            "inputs": {},
            "query": upstream_query,
            "response_mode": "streaming" if stream else "blocking",
            "user": user,
        }
        if conversation_id:
            upstream["conversation_id"] = conversation_id
        # stash meta on upstream for handlers (popped before wire)
        upstream["_original_query"] = query
        upstream["_rewrite"] = rewrite_meta
        return upstream, stream, history, query

    def _emit_local_agent_reply(self, shaped: dict, stream: bool) -> None:
        """转人工 / 办事进度存根等本地 Agent 动作：阻塞 JSON 或伪 SSE。"""
        if not stream:
            self._json_response(200, shaped)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self._sse_write(
                {
                    "type": "start",
                    "conversation_id": shaped.get("conversation_id") or "",
                    "message_id": "",
                    "task_id": "",
                    "agent_action": shaped.get("agent_action") or "",
                }
            )
            answer = shaped.get("answer") or ""
            # 分片推送，前端流式体感一致
            step = 48
            for i in range(0, len(answer), step):
                self._sse_write({"type": "delta", "text": answer[i : i + step]})
            done = dict(shaped)
            done["type"] = "done"
            done["streamed"] = True
            self._sse_write(done)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _handle_chat(self) -> None:
        parsed = self._parse_chat_request()
        if parsed is None:
            return
        upstream, stream, _history, original_query = parsed
        conversation_id = upstream.get("conversation_id") or ""
        kind = classify_portal_intent(original_query)

        # 证件号 / 病历：不进检索，也不进工单。
        if kind == "safety":
            shaped = safety_shaped(original_query)
            shaped["conversation_id"] = conversation_id
            return self._emit_local_agent_reply(shaped, stream)

        if kind == "restart":
            if LITE_MODE:
                shaped = answer_lite(original_query)
            else:
                shaped = {
                    "answer": "好，我们重新开始。请直接说出新的问题。",
                    "citations": [],
                    "refuse": False,
                    "agent_action": "restart",
                    "intent": "restart",
                    "engine": "proxy",
                    "generator": "intro",
                    "streamed": False,
                }
            shaped["conversation_id"] = ""
            return self._emit_local_agent_reply(shaped, stream)

        # 转人工是独立出口，不拿去检索。
        if kind == "handoff":
            shaped = handoff_payload(original_query, upstream.get("user") or "nebula-portal")
            shaped["conversation_id"] = conversation_id
            return self._emit_local_agent_reply(shaped, stream)

        # 演示查单，和知识库问答分开。
        if kind == "ticket":
            order = lookup_mock_order(original_query) or {}
            order["conversation_id"] = conversation_id
            return self._emit_local_agent_reply(order, stream)

        # Lite FAQ / DeepSeek，或 Dify
        rewrite_meta = upstream.pop("_rewrite", None)
        upstream.pop("_original_query", None)
        upstream.pop("_sensitive", None)
        # 短指代改写后去掉 conversation_id：部分 Chatflow 多轮下 KR 上下文会空，
        # 导致「有改写仍拒答」。改写句已自含上文主题，单轮检索更稳。
        if rewrite_meta and upstream.get("conversation_id"):
            upstream.pop("conversation_id", None)
            rewrite_meta = dict(rewrite_meta)
            rewrite_meta["dropped_conversation_id"] = True
        if LITE_MODE:
            return self._handle_chat_lite(upstream, stream, rewrite_meta=rewrite_meta)
        if stream:
            return self._handle_chat_stream(upstream, rewrite_meta=rewrite_meta)
        return self._handle_chat_blocking(upstream, rewrite_meta=rewrite_meta)

    def _handle_chat_lite(
        self, upstream: dict, stream: bool, rewrite_meta: dict | None = None
    ) -> None:
        query = (upstream.get("query") or "").strip()
        conversation_id = upstream.get("conversation_id") or ""
        # Keep a stable demo conversation id for the portal history UI.
        if not conversation_id:
            conversation_id = "lite-" + str(abs(hash(upstream.get("user") or "u")) % 10_000_000)

        shaped = answer_lite(query, stream=stream)
        shaped["conversation_id"] = conversation_id
        shaped["message_id"] = ""
        shaped["rewrite"] = rewrite_meta
        hits = shaped.get("_hits") or []
        mode = shaped.get("_deepseek_mode") or "faq"
        if stream and shaped.get("generator") == "deepseek_pending" and deepseek_api_key():
            return self._stream_lite_deepseek(shaped, hits, mode, query)
        public = _public_shaped(shaped)
        if not stream:
            self._json_response(200, public)
            return
        self._emit_local_agent_reply(public, True)

    def _stream_lite_deepseek(self, shaped: dict, hits: list, mode: str, query: str) -> None:
        """Optional DeepSeek SSE. Local answer stays the fallback if the stream is empty."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            start_ev = {
                "type": "start",
                "conversation_id": shaped.get("conversation_id") or "",
                "message_id": "",
                "task_id": "",
                "agent_action": shaped.get("agent_action") or "knowledge_qa",
                "engine": "lite",
            }
            if shaped.get("rewrite"):
                start_ev["rewrite"] = shaped["rewrite"]
            self._sse_write(start_ev)
            parts: list[str] = []
            got = False
            for delta in iter_deepseek_stream(query, hits, mode=mode):
                got = True
                parts.append(delta)
                self._sse_write({"type": "delta", "text": delta})
            citations = shaped.get("citations") or []
            if got:
                answer = clean_answer("".join(parts).strip())
                if looks_like_refuse(answer, citations):
                    answer = shaped.get("answer") or answer
                    generator = shaped.get("generator") if shaped.get("generator") != "deepseek_pending" else "template"
                else:
                    generator = "deepseek"
            else:
                answer = shaped.get("answer") or ""
                generator = "template" if mode == "faq" else (shaped.get("generator") or "skill")
                step = 48
                for i in range(0, len(answer), step):
                    self._sse_write({"type": "delta", "text": answer[i : i + step]})
            done = _public_shaped(shaped)
            done.update(
                {
                    "type": "done",
                    "answer": answer,
                    "citations": citations,
                    "refuse": bool(shaped.get("refuse")),
                    "streamed": True,
                    "generator": generator,
                }
            )
            self._sse_write(done)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _handle_chat_blocking(self, upstream: dict, rewrite_meta: dict | None = None) -> None:
        req = urllib.request.Request(
            DIFY_CHAT_URL,
            data=json.dumps(upstream).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read().decode("utf-8")
                upstream_status = resp.status
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("message") or err_json.get("error") or err_body[:200]
            except json.JSONDecodeError:
                msg = err_body[:200] or str(exc)
            self._json_error(502, f"引擎调用失败（HTTP {exc.code}）", detail=str(msg)[:300])
            return
        except urllib.error.URLError as exc:
            self._json_error(502, f"无法连接知识引擎：{exc.reason}")
            return
        except Exception as exc:  # noqa: BLE001
            self._json_error(502, f"引擎异常：{type(exc).__name__}")
            return

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._json_error(502, "引擎返回非 JSON")
            return

        answer = clean_answer(payload.get("answer") or "")
        resources = (payload.get("metadata") or {}).get("retriever_resources") or []
        citations = shape_citations(resources)
        refuse = looks_like_refuse(answer, citations)
        shaped = {
            "answer": answer,
            "citations": citations,
            "conversation_id": payload.get("conversation_id") or "",
            "message_id": payload.get("message_id") or payload.get("id") or "",
            "refuse": refuse,
            "engine_status": upstream_status,
            "streamed": False,
            "rewrite": rewrite_meta,
            "agent_action": "knowledge_qa",
        }
        self._json_response(200, shaped)

    def _sse_write(self, obj: dict) -> None:
        line = "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"
        self.wfile.write(line.encode("utf-8"))
        self.wfile.flush()

    def _iter_upstream_sse(self, resp) -> Iterator[dict]:
        buf = ""
        while True:
            chunk = resp.read(256)
            if not chunk:
                break
            buf += chunk.decode("utf-8", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.rstrip("\r")
                if not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue

    def _handle_chat_stream(self, upstream: dict, rewrite_meta: dict | None = None) -> None:
        req = urllib.request.Request(
            DIFY_CHAT_URL,
            data=json.dumps(upstream).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )

        try:
            resp = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("message") or err_json.get("error") or err_body[:200]
            except json.JSONDecodeError:
                msg = err_body[:200] or str(exc)
            self._json_error(502, f"引擎调用失败（HTTP {exc.code}）", detail=str(msg)[:300])
            return
        except urllib.error.URLError as exc:
            self._json_error(502, f"无法连接知识引擎：{exc.reason}")
            return
        except Exception as exc:  # noqa: BLE001
            self._json_error(502, f"引擎异常：{type(exc).__name__}")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        stripper = ThinkStripper()
        answer_parts: list[str] = []
        conversation_id = ""
        message_id = ""
        task_id = ""
        citations: list = []
        started = False
        client_gone = False

        try:
            for ev in self._iter_upstream_sse(resp):
                if not isinstance(ev, dict):
                    continue
                et = ev.get("event") or ""
                if ev.get("conversation_id"):
                    conversation_id = ev["conversation_id"]
                if ev.get("message_id"):
                    message_id = ev["message_id"]
                if ev.get("task_id"):
                    task_id = ev["task_id"]

                if not started and (conversation_id or task_id or message_id):
                    started = True
                    try:
                        start_ev = {
                            "type": "start",
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "task_id": task_id,
                            "agent_action": "knowledge_qa",
                        }
                        if rewrite_meta:
                            start_ev["rewrite"] = rewrite_meta
                        self._sse_write(start_ev)
                    except (BrokenPipeError, ConnectionResetError):
                        client_gone = True
                        break

                if et in ("message", "agent_message"):
                    delta = stripper.feed(ev.get("answer") or "")
                    if delta:
                        answer_parts.append(delta)
                        try:
                            self._sse_write({"type": "delta", "text": delta})
                        except (BrokenPipeError, ConnectionResetError):
                            client_gone = True
                            break
                elif et == "message_end":
                    tail = stripper.flush()
                    if tail:
                        answer_parts.append(tail)
                        try:
                            self._sse_write({"type": "delta", "text": tail})
                        except (BrokenPipeError, ConnectionResetError):
                            client_gone = True
                            break
                    meta = ev.get("metadata") or {}
                    citations = shape_citations(meta.get("retriever_resources") or [])
                elif et == "error":
                    try:
                        self._sse_write(
                            {
                                "type": "error",
                                "error": (ev.get("message") or ev.get("code") or "引擎错误")[
                                    :300
                                ],
                            }
                        )
                    except (BrokenPipeError, ConnectionResetError):
                        client_gone = True
                    break

            if client_gone:
                return

            # flush residual
            tail = stripper.flush()
            if tail:
                answer_parts.append(tail)
                try:
                    self._sse_write({"type": "delta", "text": tail})
                except (BrokenPipeError, ConnectionResetError):
                    return

            answer = "".join(answer_parts).strip()
            # 二次保险：完整标签清理
            answer = clean_answer(answer)
            refuse = looks_like_refuse(answer, citations)
            try:
                done_ev = {
                        "type": "done",
                        "answer": answer,
                        "citations": citations,
                        "conversation_id": conversation_id,
                        "message_id": message_id,
                        "task_id": task_id,
                        "refuse": refuse,
                        "streamed": True,
                        "rewrite": rewrite_meta,
                        "agent_action": "knowledge_qa",
                    }
                self._sse_write(done_ev)
            except (BrokenPipeError, ConnectionResetError):
                return
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass


def main() -> None:
    if not WEB_DIR.is_dir():
        raise SystemExit(f"缺少前端目录：{WEB_DIR}")
    key = load_api_key()
    PortalHandler.api_key = key
    server = ThreadingHTTPServer((HOST, PORT), PortalHandler)
    print(f"校园客服门户已启动 → http://{HOST}:{PORT}/", flush=True)
    print(f"静态资源：{WEB_DIR}", flush=True)
    if LITE_MODE:
        info = lite_ready()
        print(
            f"引擎：LITE FAQ（chunks={info.get('chunks')} deepseek={info.get('deepseek')}）",
            flush=True,
        )
        print(f"FAQ：{info.get('faq_path')}", flush=True)
    else:
        print(f"引擎：{DIFY_CHAT_URL}（SSE 流式默认开启）", flush=True)
    print("Agent：query_rewrite + human_handoff + case_stub", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止门户", flush=True)


if __name__ == "__main__":
    main()
