#!/usr/bin/env python3
"""Lite knowledge engine for Render Free (~512MB).

No Dify containers. Local FAQ retrieval + optional DeepSeek generation,
or template answers from retrieved snippets so the demo still works offline.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FAQ = ROOT / "sample-kb" / "客服样例FAQ.md"
# Fallback when FAQ was only under the Dify tree (local box).
ALT_FAQ = Path("/workspace/dify/sample-kb/客服样例FAQ.md")

DEEPSEEK_URL = os.environ.get(
    "DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"
)
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

SECTION_RE = re.compile(r"^##\s+(\d+)\.\s*(.+?)\s*$", re.MULTILINE)
TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]+")
# Leading hello / hi only. A real question after the greeting still goes to retrieval.
_GREET_PREFIX = re.compile(
    r"^(?:(?:"
    r"你好|您好|嗨|哈喽|哈啰|在吗|在么|早上好|下午好|晚上好|早安|晚安|"
    r"hi|hello|hey"
    r")[呀啊哦哟！!。.~～，,\s]*)+",
    re.IGNORECASE,
)
_INTRO = re.compile(
    r"(?:"
    r"介绍一下你自己|介绍一下自己|介绍下你自己|介绍下自己|自我介绍|"
    r"你是谁|你叫什么|你能做什么|你能干什么|你会什么|你可以做什么|"
    r"你是做什么的|你是干什么的|你能帮(?:我)?什么|你能帮我做什么|"
    r"who are you|what can you do|introduce yourself"
    r")",
    re.IGNORECASE,
)
_TOPIC = re.compile(
    r"(保修|质保|退换|退货|换货|退款|物流|快递|发货|运费|发票|支付|付款|"
    r"账号|绑定|解绑|密码|电池|充电|清洗|保温|温度|指示灯|订单|售后|寄修|"
    r"漏水|容量|材质|蓝牙|密封|异味|开机|App|app|CloudCup|水杯|杯子)"
)
# Clearly outside the demo catalog. Checked before retrieval so a stray
# keyword (发票 / 订单) cannot turn them into a cited answer.
_OFFTOPIC = re.compile(
    r"(火星|月球|外太空|写一首诗|写首诗|今天天气|天气怎么样|股票怎么|彩票|"
    r"比特币|帮我写代码|黑客攻击|破解密码)"
)
_KEY_PHRASES = (
    "保修",
    "质保",
    "退换",
    "退货",
    "换货",
    "退款",
    "清洗",
    "充电",
    "指示灯",
    "绑定",
    "解绑",
    "保温",
    "温度",
    "饮水",
    "物流",
    "发货",
    "快递",
    "运费",
    "发票",
    "支付",
    "付款",
    "账号",
    "密码",
    "电池",
    "续航",
    "售后",
    "寄修",
    "漏水",
    "容量",
    "材质",
    "蓝牙",
    "密封",
    "异味",
    "开机",
    "颜色",
    "规格",
    "序列号",
)
INTRO_ANSWER = (
    "你好，我是星云助手。\n\n"
    "我是 CloudCup Pro 的私有知识库智能客服，可以回答保修、退换、物流、账号绑定、"
    "支付与发票、售后和常见故障。\n\n"
    "直接说出具体问题即可，我会附上知识库依据。"
)


@dataclass
class Chunk:
    id: str
    title: str
    question: str
    answer: str
    content: str
    document_name: str = "客服样例FAQ.md"
    dataset_name: str = "CloudCup Pro FAQ"


_CHUNKS: list[Chunk] | None = None


def faq_path() -> Path:
    override = (os.environ.get("LITE_FAQ_PATH") or "").strip()
    if override:
        return Path(override)
    if DEFAULT_FAQ.is_file():
        return DEFAULT_FAQ
    if ALT_FAQ.is_file():
        return ALT_FAQ
    return DEFAULT_FAQ


def load_chunks(force: bool = False) -> list[Chunk]:
    global _CHUNKS
    if _CHUNKS is not None and not force:
        return _CHUNKS
    path = faq_path()
    if not path.is_file():
        _CHUNKS = []
        return _CHUNKS
    text = path.read_text(encoding="utf-8")
    matches = list(SECTION_RE.finditer(text))
    chunks: list[Chunk] = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        title = m.group(2).strip()
        q = title if title.endswith(("？", "?")) else title + "？"
        chunks.append(
            Chunk(
                id=f"faq-{m.group(1)}",
                title=title,
                question=q,
                answer=body,
                content=f"问：{q}\n答：{body}",
            )
        )
    _CHUNKS = chunks
    return _CHUNKS


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")]


def bigrams(tokens: list[str]) -> set[str]:
    out: set[str] = set()
    for i in range(len(tokens) - 1):
        out.add(tokens[i] + tokens[i + 1])
    # also keep unigrams for Chinese chars / words
    out.update(tokens)
    return out


def score_chunk(query: str, chunk: Chunk) -> float:
    q_toks = tokenize(query)
    if not q_toks:
        return 0.0
    q_set = bigrams(q_toks)
    # Prefer title/question hits
    title_set = bigrams(tokenize(chunk.question + " " + chunk.title))
    body_set = bigrams(tokenize(chunk.answer))
    title_hits = len(q_set & title_set)
    body_hits = len(q_set & body_set)
    # Bonus for whole-substring overlap on key phrases
    bonus = 0.0
    hay = chunk.question + chunk.answer
    for phrase in _KEY_PHRASES:
        if phrase in query and phrase in hay:
            bonus += 2.0
    raw = title_hits * 3.0 + body_hits * 1.0 + bonus
    # Normalize loosely by query size
    return raw / max(3.0, float(len(q_set)))


def retrieve(query: str, top_k: int = 3, min_score: float = 0.45) -> list[tuple[Chunk, float]]:
    scored: list[tuple[Chunk, float]] = []
    for ch in load_chunks():
        s = score_chunk(query, ch)
        if s >= min_score:
            scored.append((ch, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    if not scored:
        return []
    best = scored[0][1]
    # Drop weak near-misses so citations stay on-topic for demos.
    scored = [x for x in scored if x[1] >= max(min_score, best * 0.55)]
    return scored[:top_k]


def citations_from(hits: list[tuple[Chunk, float]]) -> list[dict]:
    out = []
    for ch, score in hits:
        out.append(
            {
                "document_name": ch.document_name,
                "dataset_name": ch.dataset_name,
                "score": round(min(0.99, 0.55 + score * 0.12), 4),
                "content": ch.content[:480],
                "segment_id": ch.id,
            }
        )
    return out


def template_answer(query: str, hits: list[tuple[Chunk, float]]) -> str:
    if not hits:
        return (
            "抱歉，当前知识库未覆盖该问题，未找到依据。\n\n"
            "建议转人工坐席处理（演示环境可点「转人工」提交工单）。"
        )
    # Single strong hit → paraphrase lightly from FAQ
    if len(hits) == 1 or hits[0][1] >= hits[1][1] * 1.4:
        ch, _ = hits[0]
        return (
            f"根据知识库「{ch.title}」：\n\n"
            f"{ch.answer.strip()}\n\n"
            f"— 依据：{ch.document_name}"
        )
    parts = ["根据知识库检索到的相关条目：\n"]
    for i, (ch, _) in enumerate(hits[:3], 1):
        parts.append(f"**{i}. {ch.title}**\n{ch.answer.strip()}\n")
    parts.append(f"— 依据：{hits[0][0].document_name}")
    return "\n".join(parts)


def deepseek_api_key() -> str:
    return (os.environ.get("DEEPSEEK_API_KEY") or "").strip()


def _build_messages(query: str, hits: list[tuple[Chunk, float]]) -> list[dict]:
    ctx_parts = []
    for i, (ch, score) in enumerate(hits, 1):
        ctx_parts.append(f"[{i}] {ch.content}")
    context = "\n\n".join(ctx_parts) if ctx_parts else "（无检索结果）"
    system = (
        "你是「星云客服」智能客服助手，产品为虚构样例 CloudCup Pro。\n"
        "只根据下方知识库片段作答；不要编造库外政策。\n"
        "若片段不足以回答，明确说「知识库未覆盖 / 未找到依据」，并建议转人工。\n"
        "回答简洁、中文、可分点；不要输出 <think> 或推理过程。"
    )
    user = f"用户问题：{query}\n\n知识库片段：\n{context}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_with_deepseek(query: str, hits: list[tuple[Chunk, float]]) -> str | None:
    key = deepseek_api_key()
    if not key or not hits:
        return None
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": _build_messages(query, hits),
        "temperature": 0.2,
        "max_tokens": 800,
        "stream": False,
    }
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        choices = payload.get("choices") or []
        if not choices:
            return None
        msg = (choices[0].get("message") or {}).get("content") or ""
        return msg.strip() or None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, KeyError):
        return None


def iter_deepseek_stream(query: str, hits: list[tuple[Chunk, float]]) -> Iterator[str]:
    """Yield text deltas from DeepSeek SSE; empty iterator if unavailable."""
    key = deepseek_api_key()
    if not key or not hits:
        return
        yield  # pragma: no cover — make this a generator
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": _build_messages(query, hits),
        "temperature": 0.2,
        "max_tokens": 800,
        "stream": True,
    }
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=90)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return
        yield  # pragma: no cover
    buf = ""
    try:
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
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                choices = ev.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0].get("delta") or {}).get("content") or ""
                if delta:
                    yield delta
    finally:
        try:
            resp.close()
        except Exception:  # noqa: BLE001
            pass


def _strip_punct(text: str) -> str:
    return text.strip("，,。.!！?？~～、 \t")


def _is_social(text: str) -> bool:
    """Pure greeting or self-intro, with no product question left over."""
    rest = _strip_punct(_GREET_PREFIX.sub("", text))
    if not rest:
        return True
    if not _INTRO.search(rest) and not _INTRO.search(text):
        return False
    stripped = _strip_punct(_INTRO.sub(" ", rest))
    if _TOPIC.search(stripped):
        return False
    return True


def lite_prelude(query: str) -> dict | None:
    """Greeting / self-intro, or a hard out-of-scope refuse. None → retrieve.

    Greetings must not look like an empty-KB miss. Off-topic requests are
    refused before retrieval so a shared word like 发票 cannot cite an FAQ.
    """
    text = (query or "").strip()
    if not text:
        return None
    if _OFFTOPIC.search(text):
        return {
            "answer": template_answer(text, []),
            "citations": [],
            "refuse": True,
            "agent_action": "knowledge_qa",
            "engine": "lite",
            "generator": "refuse",
            "streamed": False,
        }
    if not _is_social(text):
        return None
    return {
        "answer": INTRO_ANSWER,
        "citations": [],
        "refuse": False,
        "agent_action": "assistant_intro",
        "engine": "lite",
        "generator": "intro",
        "streamed": False,
    }


def answer_lite(query: str, stream: bool = False) -> dict:
    """Blocking-shaped result used by proxy (stream handled separately)."""
    early = lite_prelude(query)
    if early is not None:
        return early
    hits = retrieve(query)
    citations = citations_from(hits)
    if not hits:
        answer = template_answer(query, hits)
        return {
            "answer": answer,
            "citations": [],
            "refuse": True,
            "agent_action": "knowledge_qa",
            "engine": "lite",
            "generator": "refuse",
            "streamed": False,
        }
    generated = generate_with_deepseek(query, hits)
    if generated:
        answer = generated
        generator = "deepseek"
    else:
        answer = template_answer(query, hits)
        generator = "template"
    refuse = False
    hard = ("知识库未覆盖", "未找到依据", "检索结果为空")
    if any(m in answer for m in hard) and not citations:
        refuse = True
    return {
        "answer": answer,
        "citations": citations,
        "refuse": refuse,
        "agent_action": "knowledge_qa",
        "engine": "lite",
        "generator": generator,
        "streamed": False,
    }


def lite_ready() -> dict:
    chunks = load_chunks()
    return {
        "faq_path": str(faq_path()),
        "chunks": len(chunks),
        "deepseek": bool(deepseek_api_key()),
    }
