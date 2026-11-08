#!/usr/bin/env python3
"""星云客服门户 — 本地代理：托管静态页 + 转发 Dify Chat API（支持 SSE 流式）。

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
        iter_deepseek_stream,
        lite_prelude,
        lite_ready,
        retrieve,
        template_answer,
        citations_from,
        deepseek_api_key,
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
    r"(转\s*人工|人工\s*客服|人工\s*坐席|转接\s*人工|找\s*人工|联系\s*人工)"
)
ORDER_RE = re.compile(
    r"(?:订单(?:号|编号)?|order(?:\s*id)?|查一下订单|查询订单)\s*[:：#]?\s*"
    r"(ORD[-_]?\d{5,}|\d{10,}|CC\d{8,})",
    re.IGNORECASE,
)
ORDER_BARE_RE = re.compile(r"\b(ORD[-_]?\d{5,}|CC\d{8,})\b", re.IGNORECASE)
ANAPHORA_TOPIC_RE = re.compile(
    r"^(?:那|那么|另外|还有)?\s*(.+?)\s*(?:呢|嘛|呢？|呢\?|吗|怎么样|如何)[？?！!。.]*$"
)
DEIXIS_RE = re.compile(r"(那|这个|那个|还有|另外|它|其|上述|刚才|上面)")

# 演示用订单存根（无真实后台）
MOCK_ORDERS = {
    "ORD123456": {
        "status": "运输中",
        "carrier": "演示快递",
        "eta": "预计明日送达",
        "items": "CloudCup Pro ×1",
    },
    "ORD654321": {
        "status": "已签收",
        "carrier": "演示快递",
        "eta": "已于昨日签收",
        "items": "CloudCup Pro ×1（黑色）",
    },
    "CC20260001": {
        "status": "备货中",
        "carrier": "—",
        "eta": "预计 2 日内发出",
        "items": "CloudCup Pro ×2",
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


def needs_query_rewrite(query: str, history: list | None) -> bool:
    q = (query or "").strip()
    if not q or not history:
        return False
    if len(q) > 48:
        return False
    if DEIXIS_RE.search(q):
        return True
    if len(q) <= 12 and q.endswith(("？", "?", "呢", "嘛", "吗")):
        return True
    # 极短追问且上一轮用户问较长
    prev = last_user_turns(history, 1)
    if prev and len(q) <= 10 and len(prev[-1]) >= 6:
        return True
    return False


def _is_anaphoric_short(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if len(t) <= 12 and DEIXIS_RE.search(t):
        return True
    if re.match(r"^那.+呢[？?]?$", t):
        return True
    return False


def rewrite_query_for_retrieval(query: str, history: list | None) -> tuple[str, dict | None]:
    """多轮短指代 → 可检索的完整问句。规则改写，不额外调 LLM。"""
    q = (query or "").strip()
    if not needs_query_rewrite(q, history):
        return q, None

    prev_users = [t for t in last_user_turns(history, 8) if t != q]
    if not prev_users:
        return q, None
    # 优先锚定最近一条「实质性」用户问题，跳过连续短指代
    prev = ""
    for t in reversed(prev_users):
        if not _is_anaphoric_short(t):
            prev = t
            break
    if not prev:
        prev = prev_users[-1]

    topic = ""
    m = ANAPHORA_TOPIC_RE.match(q)
    if m:
        topic = re.sub(r"^(那|那么|这个|那个|还有|另外)\s*", "", m.group(1)).strip()
        topic = topic.strip("的了吗呢嘛？?！!。.")
    # 「那电池呢」类：抓出实体
    if not topic:
        m2 = re.match(r"^那\s*(.+?)(?:呢|嘛)?[？?！!。.]*$", q)
        if m2:
            topic = m2.group(1).strip()

    # 根据上一问主题拼检索友好问句
    focus = ""
    if any(k in prev for k in ("保修", "质保", "保固")):
        focus = "保修"
    elif any(k in prev for k in ("退换", "退货", "换货")):
        focus = "退换货"
    elif any(k in prev for k in ("清洗", "保养", "清洁")):
        focus = "清洗保养"
    elif any(k in prev for k in ("绑定", "配对", "连接", "蓝牙", "App")):
        focus = "连接与绑定"
    elif any(k in prev for k in ("充电", "电量")):
        focus = "充电"
    elif any(k in prev for k in ("物流", "发货", "快递")):
        focus = "物流"

    if topic and focus:
        rewritten = f"{topic}的{focus}政策是怎样的？{topic}{focus}多久？"
    elif topic:
        rewritten = f"关于「{prev}」中的{topic}，请说明相关政策与细节"
    else:
        rewritten = f"承接上一问「{prev}」，请回答：{q}"

    meta = {
        "original": q,
        "rewritten": rewritten,
        "based_on": prev[:80],
        "method": "proxy-rule",
    }
    return rewritten, meta


def is_handoff_intent(query: str) -> bool:
    return bool(HANDOFF_RE.search(query or ""))


def make_ticket_id(*parts: str) -> str:
    seed = "|".join(parts) or "handoff"
    return "TK" + str(abs(hash(seed)) % 10_000_000).zfill(7)


def handoff_payload(query: str, user: str, detail: str = "") -> dict:
    ticket_id = make_ticket_id(query, user, detail, "handoff")
    answer = (
        "好的，已为您转接人工坐席（演示）。\n\n"
        f"- 演示工单号：**{ticket_id}**\n"
        "- 状态：**已受理（本地存根）**\n"
        "- 说明：当前环境未对接真实坐席队列；工单仅保存在本机回执中，便于课程演示。\n\n"
        "如需补充订单号、寄修地址或发票信息，请点击「转人工」填写工单，或直接在对话中说明。"
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


def lookup_mock_order(query: str) -> dict | None:
    oid = None
    m = ORDER_RE.search(query or "")
    if m:
        oid = m.group(1)
    else:
        m2 = ORDER_BARE_RE.search(query or "")
        if m2 and any(k in (query or "") for k in ("订单", "物流", "快递", "发货", "查", "order")):
            oid = m2.group(1)
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
        # also try ORD123456 style
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
                f"未在演示订单库中找到 **{oid}**。\n\n"
                "可试：`ORD123456` / `ORD654321` / `CC20260001`。\n"
                f"若需真人核实，可转人工（演示工单可登记为 {ticket_id}）。"
            ),
            "citations": [],
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
            f"已查询演示订单 **{key}**（本地存根，非真实物流）：\n\n"
            f"- 商品：{info['items']}\n"
            f"- 状态：**{info['status']}**\n"
            f"- 承运：{info['carrier']}\n"
            f"- 时效：{info['eta']}\n\n"
            "如需改地址、取消或发票，请转人工坐席处理。"
        ),
        "citations": [],
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
        # 仅保留最近若干轮，防滥用
        history = history[-12:]

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
        """转人工 / 订单存根等本地 Agent 动作：阻塞 JSON 或伪 SSE。"""
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

        # 1) 转人工意图 — 不调引擎
        if is_handoff_intent(original_query):
            shaped = handoff_payload(original_query, upstream.get("user") or "nebula-portal")
            shaped["conversation_id"] = upstream.get("conversation_id") or ""
            return self._emit_local_agent_reply(shaped, stream)

        # 2) 演示订单查询存根
        order = lookup_mock_order(original_query)
        if order is not None:
            order["conversation_id"] = upstream.get("conversation_id") or ""
            return self._emit_local_agent_reply(order, stream)

        # 3) Lite FAQ / DeepSeek，或 Dify
        rewrite_meta = upstream.pop("_rewrite", None)
        upstream.pop("_original_query", None)
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

        # Greetings and hard off-topic are decided before retrieval. The UI
        # defaults to SSE, so this must run on the streaming path too.
        early = lite_prelude(query)
        if early is not None:
            early["conversation_id"] = conversation_id
            early["message_id"] = ""
            early["rewrite"] = rewrite_meta
            return self._emit_local_agent_reply(early, stream)

        if not stream:
            shaped = answer_lite(query, stream=False)
            shaped["conversation_id"] = conversation_id
            shaped["message_id"] = ""
            shaped["rewrite"] = rewrite_meta
            self._json_response(200, shaped)
            return

        # Streaming path: DeepSeek SSE if key+hits, else chunked template.
        hits = retrieve(query)
        citations = citations_from(hits)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            start_ev = {
                "type": "start",
                "conversation_id": conversation_id,
                "message_id": "",
                "task_id": "",
                "agent_action": "knowledge_qa",
                "engine": "lite",
            }
            if rewrite_meta:
                start_ev["rewrite"] = rewrite_meta
            self._sse_write(start_ev)

            answer_parts: list[str] = []
            generator = "template"
            if hits and deepseek_api_key():
                got = False
                for delta in iter_deepseek_stream(query, hits):
                    got = True
                    answer_parts.append(delta)
                    self._sse_write({"type": "delta", "text": delta})
                if got:
                    generator = "deepseek"
                else:
                    # Fallback if stream failed mid-flight / empty
                    shaped = answer_lite(query, stream=False)
                    answer = shaped.get("answer") or ""
                    generator = shaped.get("generator") or "template"
                    citations = shaped.get("citations") or citations
                    step = 48
                    for i in range(0, len(answer), step):
                        piece = answer[i : i + step]
                        answer_parts.append(piece)
                        self._sse_write({"type": "delta", "text": piece})
            else:
                answer = template_answer(query, hits)
                step = 48
                for i in range(0, len(answer), step):
                    piece = answer[i : i + step]
                    answer_parts.append(piece)
                    self._sse_write({"type": "delta", "text": piece})

            answer = clean_answer("".join(answer_parts).strip())
            refuse = looks_like_refuse(answer, citations)
            if not hits:
                refuse = True
            done = {
                "type": "done",
                "answer": answer,
                "citations": citations,
                "conversation_id": conversation_id,
                "message_id": "",
                "task_id": "",
                "refuse": refuse,
                "streamed": True,
                "rewrite": rewrite_meta,
                "agent_action": "knowledge_qa",
                "engine": "lite",
                "generator": generator if hits else "refuse",
            }
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
    print(f"星云客服门户已启动 → http://{HOST}:{PORT}/", flush=True)
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
    print("Agent：query_rewrite + human_handoff + order_stub", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止门户", flush=True)


if __name__ == "__main__":
    main()
