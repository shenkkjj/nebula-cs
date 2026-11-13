#!/usr/bin/env python3
"""Lite knowledge engine for Render Free (~512MB).

No embedding model and no extra packages. FAQ retrieval is BM25 over a
vocabulary taken from the campus FAQ itself (titles, quoted phrases, and a
small alias list). Common verbs such as 申请 / 办理 are not tokens, so they
cannot drag in a lookalike article.

Routing, in order: sensitive paste, greeting, narrow refusal, local skills,
high-confidence FAQ, clarifying question, then a helpful boundary.
DeepSeek is optional and never required.
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from lite_skills import (
    contains_sensitive,
    redact_sensitive,
    safety_payload,
    try_skill,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FAQ = ROOT / "sample-kb" / "客服样例FAQ.md"
ALT_FAQ = Path("/workspace/dify/sample-kb/客服样例FAQ.md")

DEEPSEEK_URL = os.environ.get(
    "DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"
)
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

SECTION_RE = re.compile(r"^##\s+(\d+)\.\s*(.+?)\s*$", re.MULTILINE)
_GREET_PREFIX = re.compile(
    r"^(?:(?:"
    r"你好|您好|嗨|哈喽|哈啰|在吗|在么|早上好|下午好|晚上好|早安|晚安|"
    r"hi|hello|hey"
    r")[呀啊哦哟吗嘛！!。.~～，,\s]*)+",
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
    r"(在读|成绩|证明|选课|缓考|补考|重修|转专业|休学|复学|毕业|辅修|"
    r"学籍|绩点|GPA|退学|入伍|免修|创新学分|四六级|培养方案|课表|考场|退课|"
    r"公选|体育课|复查|"
    r"图书馆|借书|续借|研讨|自习|图书|电子资源|分馆|荐购|还书|学位论文|馆际|"
    r"宿舍|报修|空调|热水|门禁|晚归|调宿|留校|失物|水电|访客|退宿|洗衣机|漏水|"
    r"校园网|认证|VPN|vpn|无线|有线|eduroam|流量|"
    r"校园卡|一卡通|充值|挂失|补办|学费|奖助|助学|贷款|勤工|绿色通道|困难|"
    r"奖学金|补助|"
    r"校医院|医务|心理|挂号|医保|转诊|快递|班车|体育馆|"
    r"办事|学号|一网通办|催办|补正|"
    r"假期|寒暑|节假日|食堂|教室|借用)"
)
_RESTART_RE = re.compile(r"^(重新开始|重新来过|换个话题|清空对话|开始新对话)[。.!！]?$")
_BACK_RE = re.compile(r"^(返回上一个问题|回到上一个问题|上一个问题|返回上一题|回到刚才)[。.!！]?$")

_KEY_PHRASES = (
    "在读证明", "成绩单", "缓考", "补考", "重修", "选课", "转专业", "休学", "复学",
    "毕业审核", "辅修", "图书馆", "开放时间", "借书", "续借", "超期", "研讨间",
    "自习", "电子资源", "宿舍", "报修", "空调", "热水", "晚归", "调宿", "留校",
    "校园网", "认证", "VPN", "校园卡", "充值", "挂失", "补办", "学费", "奖助学金",
    "校医院", "心理咨询", "快递", "班车", "体育馆", "办事进度", "办事单号",
    "一网通办", "学籍证明", "成绩查询", "成绩复查", "学分绩点", "GPA", "学历证明",
    "学位证明", "退学", "保留学籍", "实习证明", "免修", "创新学分", "学分认定",
    "毕业证明", "选课冲突", "退课", "人数已满", "公选课", "体育课", "课表", "考场",
    "补考安排", "四六级", "培养方案", "助学贷款", "生源地", "年度确认", "励志奖学金",
    "勤工助学", "困难补助", "困难认定", "绿色通道", "学费减免", "助学金", "分馆",
    "图书预约", "荐购", "馆际互借", "还书箱", "学位论文", "存包柜", "借阅权限",
    "水电费", "门禁时间", "访客", "钥匙", "漏水", "洗衣机", "退宿", "停电",
    "安全检查", "认证页面", "eduroam", "流量", "VPN 客户端", "断网", "上课平台",
    "消费明细", "圈存", "消磁", "临时校园卡", "校园卡退费", "付款码", "预约挂号",
    "医保", "转诊", "心理测评", "取消或改期", "心理危机", "待受理", "待补正",
    "待取件", "催办", "寒暑假", "法定节假日", "教室借用", "借教室", "空闲教室",
    "考试周",
)
# Surfaces that are not written as a title, but the FAQ uses them.
_EXTRA_TERMS = (
    "校园地贷款", "校园地", "国家助学贷款", "生源地回执", "回执", "假期作息",
    "寒暑假作息", "校园作息", "作息", "宿舍门禁", "水电", "开门", "无线网",
    "wifi", "wi-fi", "cet", "cet4", "cet-4", "cet6", "四六级", "贷款", "证明",
    "门禁", "成绩单",
)
# Query expansion. Every part must occur (any = at least one) before a hit counts.
_ALIAS_RAW = {
    "校园地贷款": {"all": ("国家助学贷款", "校园地"), "any": ()},
    "生源地回执": {"all": ("生源地", "回执"), "any": ()},
    "假期作息": {"all": ("作息",), "any": ("寒暑假", "假期")},
    "寒暑假作息": {"all": ("寒暑假", "作息"), "any": ()},
    "wifi": {"all": ("校园网",), "any": ()},
    "wi-fi": {"all": ("校园网",), "any": ()},
    "无线网": {"all": ("校园网",), "any": ()},
    "cet": {"all": ("四六级",), "any": ()},
    "cet4": {"all": ("四六级",), "any": ()},
    "cet-4": {"all": ("四六级",), "any": ()},
    "cet6": {"all": ("四六级",), "any": ()},
    "借教室": {"all": ("教室借用",), "any": ()},
    "开门": {"all": ("开放时间",), "any": ()},
    "gpa": {"all": ("绩点",), "any": ()},
}
_SUFFIXES = (
    "有什么区别", "有何区别", "分别是什么意思", "分别是什么",
    "如何办理", "怎么办理", "如何申请", "怎么申请", "如何查询", "怎么查询",
    "在哪里查询", "在哪里看", "在哪里", "哪里看", "哪里查",
    "怎么处理", "怎么办", "是什么", "哪些", "如何", "怎么", "吗", "呢",
)
_PREFIXES = ("请问", "如何办理", "怎么办理", "如何", "怎么")
_STOP_TERMS = {
    "什么", "哪些", "如何", "怎么", "怎么办", "是否", "可以", "能否", "一下",
    "请问", "帮我", "我们", "你们", "自己", "这个", "那个", "哪里", "多少",
    "为什么", "一样", "分别", "是什么", "在哪里", "有什么", "有何", "如何办理",
    "怎么办理", "同学", "一下", "什么时候",
}
_FUNC_PHRASES = (
    "怎么办理", "如何办理", "怎么办", "如何申请", "怎么申请", "如何查询", "怎么查询",
    "怎么处理", "有什么区别", "有何区别", "是什么", "在哪里", "请问", "帮我", "一下",
    "什么时候", "什么", "哪些", "如何", "怎么", "可以", "是否", "有没有", "能不能",
    "这个", "那个", "怎样", "咋办", "为什么", "为何", "多少", "哪里", "在哪", "多久",
    "几个", "需要什么材料", "什么材料", "哪些材料",
)
_FUNC_CHARS = set("的了吗呢吧啊呀我你他她它和与或及在对把被给让向从到是有就也都还很又这那个")
_ASPECT_FILLERS = (
    "需要什么材料", "哪些材料", "什么材料", "需要材料", "在哪里办理", "哪里办理",
    "在哪里", "需要多久", "多长时间", "费用是多少", "多少钱", "怎么办理", "如何办理",
    "怎么办", "材料", "多久", "费用", "哪里",
)
_PUNCT_RE = re.compile(r"[\s？?！!。.,，、；;：:（）()【】\[\]「」\"“”'‘’《》<>·…—\-_/\\]+")

INTRO_ANSWER = (
    "你好，我是校园助手。\n\n"
    "我按虚构样例「星云大学」的知识库回答办事问题，并给出依据。"
    "计算、单位换算、日期，以及词表里的校园用语短翻译也可以直接做；没有在线翻译引擎时，译不全我会直说。\n"
    "没有依据的校规我不会编。需要工作人员时，说「转人工」。\n"
    "追问会接着上一件事；说「重新开始」就换话题，说「返回上一个问题」可以回到上一件。"
)
RESTART_ANSWER = "好，之前的话题先放下。\n\n" + INTRO_ANSWER

_BARE_CLARIFY = {
    "申请": (
        "「申请」太宽，我不确定是哪一件，不想猜错。你想问的是下面哪一条？",
        (
            {"label": "在读证明", "query": "在读证明如何办理？"},
            {"label": "缓考", "query": "缓考如何申请？"},
            {"label": "助学贷款", "query": "国家助学贷款如何申请？"},
            {"label": "教室借用", "query": "教室借用怎么申请？"},
        ),
    ),
}

_CHIPS = (
    {"label": "在读证明", "query": "在读证明如何办理？"},
    {"label": "助学贷款", "query": "国家助学贷款如何申请？"},
    {"label": "宿舍报修", "query": "宿舍报修怎么提交？"},
    {"label": "校园网", "query": "校园网如何认证登录？"},
    {"label": "查办事进度", "query": "查询办事进度 SW20260001"},
    {"label": "转人工", "query": "转人工"},
)

K1 = 1.2
B = 0.75

FAQ_SYSTEM = (
    "你是「校园助手」，服务虚构样例「星云大学」的校园客服。\n"
    "校园政策、时限、金额、材料只根据下方知识库片段回答，不要编造校规，"
    "也不要承诺改分、代考、代写或重置他人密码。\n"
    "若片段不足以回答，明确说知识库未覆盖、未找到依据，并建议转人工。\n"
    "先给一句结论，再补充细节。回答简洁、中文。不要输出 <think>。"
)
GENERAL_SYSTEM = (
    "你是「校园助手」，服务虚构样例「星云大学」。\n"
    "校园政策只能来自用户消息里给出的知识库片段；没有片段就不要编造校规、金额或办件状态。\n"
    "通用问题（计算、翻译、日常说明）可以简洁回答。\n"
    "不能查看实时天气，不能诊断病情，不能代写正式申请文书，不能核实密码或私人记录。\n"
    "不要输出 <think>。"
)


@dataclass
class Chunk:
    id: str
    title: str
    question: str
    answer: str
    content: str
    document_name: str = "客服样例FAQ.md"
    dataset_name: str = "校园办事 FAQ"


@dataclass
class _Hit:
    chunk: Chunk
    score: float
    title_n: int
    body_n: int
    levels: tuple[str, ...]


_CHUNKS: list[Chunk] | None = None
_INDEX: FaqIndex | None = None


def norm_key(text: str) -> str:
    return _PUNCT_RE.sub("", (text or "").lower())


def _alias_table() -> dict[str, dict[str, tuple[str, ...]]]:
    table: dict[str, dict[str, tuple[str, ...]]] = {}
    for surface, spec in _ALIAS_RAW.items():
        table[norm_key(surface)] = {
            "all": tuple(norm_key(part) for part in spec["all"] if norm_key(part)),
            "any": tuple(norm_key(part) for part in spec["any"] if norm_key(part)),
        }
    return table


_ALIAS = _alias_table()


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
    global _CHUNKS, _INDEX
    if _CHUNKS is not None and not force:
        return _CHUNKS
    path = faq_path()
    if not path.is_file():
        _CHUNKS = []
        _INDEX = None
        return _CHUNKS
    text = path.read_text(encoding="utf-8")
    matches = list(SECTION_RE.finditer(text))
    chunks: list[Chunk] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        title = match.group(2).strip()
        question = title if title.endswith(("？", "?")) else title + "？"
        chunks.append(
            Chunk(
                id=f"faq-{match.group(1)}",
                title=title,
                question=question,
                answer=body,
                content=f"问：{question}\n答：{body}",
            )
        )
    _CHUNKS = chunks
    _INDEX = None
    return _CHUNKS


def _residues(title: str) -> list[str]:
    quoted = re.findall(r"「([^」]{2,16})」", title)
    cleaned = norm_key(title)
    for suffix in _SUFFIXES:
        piece = norm_key(suffix)
        if piece and cleaned.endswith(piece) and len(cleaned) - len(piece) >= 2:
            cleaned = cleaned[: -len(piece)]
            break
    for prefix in _PREFIXES:
        piece = norm_key(prefix)
        if piece and cleaned.startswith(piece) and len(cleaned) - len(piece) >= 2:
            cleaned = cleaned[len(piece) :]
            break
    parts = re.split(r"和|与|及", cleaned)
    out = [part.strip() for part in parts if len(part.strip()) >= 2]
    out.extend(norm_key(item) for item in quoted)
    return out


def _add_term(lex: set[str], term: str) -> None:
    key = norm_key(term)
    if len(key) < 2 or len(key) > 18:
        return
    if key in _STOP_TERMS or key.isdigit():
        return
    lex.add(key)


class FaqIndex:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.lexicon = self._build_lexicon(chunks)
        self.terms_by_len = sorted(self.lexicon, key=len, reverse=True)
        self.docs: list[dict] = []
        df: Counter[str] = Counter()
        for chunk in chunks:
            title_terms = self._present(chunk.title + chunk.question)
            body_terms = self._present(chunk.answer)
            df.update(title_terms | body_terms)
            self.docs.append(
                {
                    "title_tf": {term: 1 for term in title_terms},
                    "body_tf": {term: 1 for term in body_terms},
                    "title_len": max(1, len(norm_key(chunk.title))),
                    "body_len": max(1, len(norm_key(chunk.answer))),
                    "title_text": norm_key(chunk.title + chunk.question),
                    "body_text": norm_key(chunk.answer),
                }
            )
        self.df = df
        self.n = max(1, len(chunks))
        self.avg_title = (sum(doc["title_len"] for doc in self.docs) / self.n) if self.docs else 1.0
        self.avg_body = (sum(doc["body_len"] for doc in self.docs) / self.n) if self.docs else 1.0

    @staticmethod
    def _build_lexicon(chunks: list[Chunk]) -> set[str]:
        lex: set[str] = set()
        for chunk in chunks:
            for term in _residues(chunk.title):
                _add_term(lex, term)
            for quoted in re.findall(r"「([^」]{2,16})」", chunk.title + "\n" + chunk.answer):
                _add_term(lex, quoted)
        for phrase in _KEY_PHRASES:
            _add_term(lex, phrase)
        for phrase in _EXTRA_TERMS:
            _add_term(lex, phrase)
        for surface, spec in _ALIAS_RAW.items():
            _add_term(lex, surface)
            for part in spec["all"] + spec["any"]:
                _add_term(lex, part)
        return lex

    def _present(self, text: str) -> set[str]:
        hay = norm_key(text)
        return {term for term in self.lexicon if term in hay}

    def concepts(self, query: str) -> list[str]:
        text = norm_key(query)
        found: list[tuple[int, int, str]] = []
        for term in self.terms_by_len:
            start = 0
            while True:
                at = text.find(term, start)
                if at < 0:
                    break
                found.append((at, at + len(term), term))
                start = at + 1
        found.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
        used = [False] * len(text)
        chosen: list[str] = []
        for start, end, term in found:
            if any(used[start:end]):
                continue
            for index in range(start, end):
                used[index] = True
            chosen.append(term)
        return chosen

    def leftovers(self, query: str, concepts: list[str]) -> list[str]:
        text = norm_key(query)
        used = [False] * len(text)

        def mark(term: str) -> None:
            if len(term) < 1:
                return
            start = 0
            while True:
                at = text.find(term, start)
                if at < 0:
                    return
                for index in range(at, at + len(term)):
                    used[index] = True
                start = at + 1

        for concept in concepts:
            mark(concept)
        for phrase in sorted((norm_key(item) for item in _FUNC_PHRASES), key=len, reverse=True):
            mark(phrase)
        runs: list[str] = []
        index = 0
        while index < len(text):
            if used[index] or text[index] in _FUNC_CHARS:
                index += 1
                continue
            end = index
            while end < len(text) and not used[end] and text[end] not in _FUNC_CHARS:
                end += 1
            run = text[index:end]
            if len(run) >= 3:
                runs.append(run)
            index = end
        return runs

    def level(self, concept: str, doc: dict) -> str | None:
        title = doc["title_text"]
        body = doc["body_text"]
        if concept in title:
            return "title"
        direct = "body" if concept in body else None
        spec = _ALIAS.get(concept)
        if not spec:
            return direct
        parts = spec["all"]
        any_parts = spec["any"]

        def sat(text: str) -> bool:
            if parts and not all(part in text for part in parts):
                return False
            if any_parts and not any(part in text for part in any_parts):
                return False
            return bool(parts or any_parts)

        blob = title + body
        if sat(title):
            return "title"
        if sat(blob) and (
            any(part in title for part in parts) or any(part in title for part in any_parts)
        ):
            return "title"
        if sat(blob):
            return "body"
        return direct

    def _bm25(self, terms: list[str], tf: dict[str, int], length: int, avgdl: float) -> float:
        if avgdl <= 0:
            avgdl = 1.0
        score = 0.0
        seen: set[str] = set()
        for term in terms:
            if term in seen:
                continue
            seen.add(term)
            freq = tf.get(term, 0)
            if freq <= 0:
                continue
            df = self.df.get(term, 0)
            idf = math.log(1.0 + (self.n - df + 0.5) / (df + 0.5))
            denom = freq + K1 * (1.0 - B + B * length / avgdl)
            score += idf * (freq * (K1 + 1.0)) / denom
        return score

    def score(self, concepts: list[str], doc: dict, chunk: Chunk, query: str) -> float:
        terms: list[str] = []
        for concept in concepts:
            terms.append(concept)
            spec = _ALIAS.get(concept)
            if spec:
                terms.extend(spec["all"])
                terms.extend(spec["any"])
        score = 2.8 * self._bm25(terms, doc["title_tf"], doc["title_len"], self.avg_title)
        score += self._bm25(terms, doc["body_tf"], doc["body_len"], self.avg_body)
        aspect = _query_aspect(query)
        title = chunk.title
        if aspect == "process" and any(token in title for token in ("如何", "怎么", "办理")):
            score += 0.6
        elif aspect == "time" and any(token in title for token in ("时间", "何时", "开放")):
            score += 0.6
        elif aspect == "place" and any(token in title for token in ("哪里", "在哪")):
            score += 0.6
        elif aspect == "diff" and "区别" in title:
            score += 0.6
        elif aspect == "why" and "为什么" in title:
            score += 0.6
        return score


def get_index() -> FaqIndex:
    global _INDEX
    chunks = load_chunks()
    if _INDEX is None or _INDEX.chunks is not chunks:
        _INDEX = FaqIndex(chunks)
    return _INDEX


def _query_aspect(query: str) -> str | None:
    if re.search(r"为什么|为何", query):
        return "why"
    if re.search(r"区别|不同|不一样", query):
        return "diff"
    if re.search(r"在哪|哪里|哪儿|哪个窗口", query):
        return "place"
    if re.search(r"多久|几点|什么时候|何时|开门|几天", query):
        return "time"
    if re.search(r"怎么办|如何|怎么|办理|我要办|帮我办|咋办|申请|报名", query):
        return "process"
    return None


def _aspect_ok(title: str, aspect: str) -> bool:
    if aspect == "process":
        return any(token in title for token in ("如何", "怎么", "办理"))
    if aspect == "time":
        return any(token in title for token in ("时间", "多久", "何时", "开放", "几点"))
    if aspect == "place":
        return any(token in title for token in ("哪里", "在哪", "地点", "窗口"))
    if aspect == "diff":
        return "区别" in title or "不同" in title
    if aspect == "why":
        return "为什么" in title or "为何" in title
    return True


def _filter_peers(peers: list[_Hit], query: str) -> list[_Hit]:
    aspect = _query_aspect(query)
    if aspect and len(peers) >= 2:
        filtered = [hit for hit in peers if _aspect_ok(hit.chunk.title, aspect)]
        if filtered and len(filtered) < len(peers):
            peers = filtered
    if aspect == "process" and len(peers) >= 2:
        if "取消" in query or "改期" in query:
            alt = [hit for hit in peers if "取消" in hit.chunk.title or "改期" in hit.chunk.title]
        elif re.search(r"申请|办理|报名", query):
            alt = [
                hit
                for hit in peers
                if any(token in hit.chunk.title for token in ("申请", "办理", "报名"))
                and "取消" not in hit.chunk.title
            ]
        else:
            alt = []
        if alt and len(alt) < len(peers):
            peers = alt
    if len(peers) >= 2 and re.search(r"怎么|如何", query) and not re.search(r"打不开|故障|锁定|连不上", query):
        alt = [hit for hit in peers if not re.search(r"打不开|故障|锁定", hit.chunk.title)]
        if alt and len(alt) < len(peers):
            peers = alt
    return peers


def _extra_blocks(extra: str, title: str, terms: list[str]) -> bool:
    remaining = extra
    for filler in _ASPECT_FILLERS:
        remaining = remaining.replace(norm_key(filler), "")
    if not remaining:
        return False
    title_key = norm_key(title)
    for term in terms:
        if len(term) >= 2 and term in remaining and term not in title_key:
            return True
    return False


def _contained_chunk(query: str, index: FaqIndex) -> Chunk | None:
    folded = norm_key(query)
    if len(folded) < 4:
        return None
    found = [chunk for chunk in index.chunks if len(norm_key(chunk.title)) >= 4 and norm_key(chunk.title) in folded]
    if not found:
        return None
    found.sort(key=lambda chunk: len(norm_key(chunk.title)), reverse=True)
    top = found[0]
    extra = folded.replace(norm_key(top.title), "", 1)
    if _extra_blocks(extra, top.title, index.terms_by_len):
        return None
    return top


def _decide(query: str) -> tuple[str, list[Chunk], str, list[float]]:
    index = get_index()
    if not index.chunks:
        return "none", [], "empty", []
    contained = _contained_chunk(query, index)
    if contained is not None:
        return "answer", [contained], "contained-title", [99.0]
    concepts = index.concepts(query)
    if not concepts:
        return "none", [], "no-concept", []
    leftovers = index.leftovers(query, concepts)
    ranked: list[_Hit] = []
    for chunk, doc in zip(index.chunks, index.docs):
        levels = tuple(index.level(concept, doc) or "" for concept in concepts)
        title_n = sum(level == "title" for level in levels)
        body_n = sum(level in ("title", "body") for level in levels)
        if title_n == 0 and body_n == 0:
            continue
        ranked.append(
            _Hit(
                chunk=chunk,
                score=index.score(concepts, doc, chunk, query),
                title_n=title_n,
                body_n=body_n,
                levels=levels,
            )
        )
    if not ranked:
        return "none", [], "no-hit", []
    if leftovers:
        narrowed = [
            hit
            for hit in ranked
            if all(run in norm_key(hit.chunk.title) for run in leftovers)
        ]
        if not narrowed:
            return "none", [], "oov-leftover", []
        ranked = narrowed
    ranked.sort(key=lambda hit: (hit.title_n, hit.body_n, hit.score), reverse=True)
    best = ranked[0]
    if best.title_n <= 0:
        body_peers = [hit for hit in ranked if hit.body_n == best.body_n and hit.title_n == 0]
        if best.body_n >= len(concepts) and len(body_peers) == 1:
            return "answer", [best.chunk], "body", [best.score]
        return "none", [], "body-only", []
    peers = [hit for hit in ranked if hit.title_n == best.title_n and hit.levels == best.levels]
    peers = _filter_peers(peers, query)
    if len(peers) >= 2:
        chosen = peers[:3]
        return "clarify", [hit.chunk for hit in chosen], "tie", [hit.score for hit in chosen]
    if best.title_n * 2 >= len(concepts) or len(concepts) == 1:
        return "answer", [best.chunk], "title", [best.score]
    if len(ranked) == 1 or ranked[1].title_n < best.title_n:
        return "answer", [best.chunk], "partial", [best.score]
    return "clarify", [hit.chunk for hit in peers[:3]], "partial-tie", [hit.score for hit in peers[:3]]


def route_faq(query: str) -> dict:
    action, chunks, reason, scores = _decide(query)
    return {
        "action": action,
        "titles": [chunk.title for chunk in chunks],
        "reason": reason,
        "chunks": chunks,
        "scores": scores,
    }


def retrieve(query: str, top_k: int = 3, min_score: float = 0.45) -> list[tuple[Chunk, float]]:
    """High-confidence FAQ hits only.

    ``min_score`` is kept for older callers. Character-overlap cutoff is gone;
    a hit has to cover the query's content words, not just 申请 or 办理.
    """
    _ = min_score
    routed = route_faq(query)
    if routed["action"] != "answer":
        return []
    pairs = list(zip(routed["chunks"], routed["scores"]))
    return pairs[:top_k]


def _display_score(score: float) -> float:
    if score >= 50:
        return 0.96
    return round(min(0.94, 0.78 + min(max(score, 0.0), 6.0) / 6.0 * 0.14), 4)


def citations_from(hits: list[tuple[Chunk, float]]) -> list[dict]:
    out = []
    for chunk, score in hits:
        out.append(
            {
                "document_name": chunk.document_name,
                "dataset_name": chunk.dataset_name,
                "score": _display_score(score),
                "content": chunk.content[:480],
                "segment_id": chunk.id,
            }
        )
    return out


def _split_lead(text: str) -> tuple[str, str]:
    body = (text or "").strip()
    match = re.search(r"[。！？]", body)
    if not match:
        return body, ""
    lead = body[: match.end()].strip()
    rest = body[match.end() :].strip()
    return lead, rest


def format_policy_answer(chunk: Chunk) -> str:
    lead, rest = _split_lead(chunk.answer)
    parts = [lead]
    if rest:
        parts.append(rest)
    parts.append(f"依据：{chunk.document_name} · {chunk.title}")
    return "\n\n".join(part for part in parts if part)


def template_answer(query: str, hits: list[tuple[Chunk, float]]) -> str:
    if not hits:
        return (
            "知识库未覆盖这个问题，我没有依据，不能编一条校规。\n\n"
            "你可以把事情说得更具体，或转人工让工作人员处理。"
        )
    if len(hits) == 1:
        return format_policy_answer(hits[0][0])
    parts = ["这几条都相关，请对照出处：\n"]
    for index, (chunk, _) in enumerate(hits[:3], 1):
        parts.append(f"**{index}. {chunk.title}**\n{chunk.answer.strip()}\n")
    parts.append(f"依据：{hits[0][0].document_name}")
    return "\n".join(parts)


def _suggestions(chunks: list[Chunk]) -> list[dict]:
    return [{"label": chunk.title, "query": chunk.question} for chunk in chunks[:3]]


def _payload(
    answer: str,
    *,
    intent: str,
    action: str,
    refuse: bool = False,
    citations: list | None = None,
    suggestions: list | None = None,
    clarify: bool = False,
    title: str | None = None,
    generator: str | None = None,
    hits: list[tuple[Chunk, float]] | None = None,
    extra: dict | None = None,
) -> dict:
    if generator is None:
        if clarify:
            generator = "clarify"
        elif refuse:
            generator = "refuse"
        elif intent in ("intro", "restart"):
            generator = "intro"
        else:
            generator = "template"
    body = {
        "answer": answer,
        "citations": citations or [],
        "refuse": refuse,
        "clarify": clarify,
        "suggestions": suggestions or [],
        "matched_title": title,
        "agent_action": action,
        "intent": intent,
        "engine": "lite",
        "generator": generator,
        "streamed": False,
    }
    if hits is not None:
        body["_hits"] = hits
    if extra:
        body.update(extra)
    return body


def _clarify_text(chunks: list[Chunk]) -> str:
    lines = ["我找到几条都相关，不想猜错。你想问的是哪一件？", ""]
    for index, chunk in enumerate(chunks[:3], 1):
        lines.append(f"{index}. {chunk.title}")
    return "\n".join(lines)


def deepseek_api_key() -> str:
    return (os.environ.get("DEEPSEEK_API_KEY") or "").strip()


def _build_messages(query: str, hits: list[tuple[Chunk, float]], mode: str = "faq") -> list[dict]:
    if mode == "general":
        return [
            {"role": "system", "content": GENERAL_SYSTEM},
            {"role": "user", "content": query},
        ]
    parts = [f"[{index}] {chunk.content}" for index, (chunk, _score) in enumerate(hits, 1)]
    context = "\n\n".join(parts) if parts else "（无检索结果）"
    user = f"用户问题：{query}\n\n知识库片段：\n{context}"
    return [
        {"role": "system", "content": FAQ_SYSTEM},
        {"role": "user", "content": user},
    ]


def generate_with_deepseek(
    query: str,
    hits: list[tuple[Chunk, float]],
    mode: str = "faq",
) -> str | None:
    key = deepseek_api_key()
    if not key:
        return None
    if mode == "faq" and not hits:
        return None
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": _build_messages(query, hits, mode),
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


def iter_deepseek_stream(
    query: str,
    hits: list[tuple[Chunk, float]],
    mode: str = "faq",
) -> Iterator[str]:
    """Yield text deltas from DeepSeek SSE; empty iterator if unavailable."""
    key = deepseek_api_key()
    if not key or (mode == "faq" and not hits):
        return
        yield  # pragma: no cover — make this a generator
    body = {
        "model": DEEPSEEK_MODEL,
        "messages": _build_messages(query, hits, mode),
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
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
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
    """Pure greeting or self-intro, with no campus question left over."""
    rest = _strip_punct(_GREET_PREFIX.sub("", text))
    if not rest:
        return True
    if not _INTRO.search(rest) and not _INTRO.search(text):
        return False
    stripped = _strip_punct(_INTRO.sub(" ", rest))
    if _TOPIC.search(stripped):
        return False
    return True


def _body_query(text: str) -> str:
    rest = _strip_punct(_GREET_PREFIX.sub("", text))
    return rest or text


def _policy_shaped(query: str) -> bool:
    return bool(_TOPIC.search(query))


def _from_skill(spec: dict) -> dict:
    refuse = bool(spec.get("refuse"))
    intent = spec.get("intent") or "chitchat"
    if intent == "refuse":
        action = "refuse"
    elif refuse:
        action = "refuse"
    elif intent == "boundary":
        action = "general_skill"
    else:
        action = "general_skill"
    extra = {}
    if spec.get("sensitive"):
        extra["sensitive"] = True
        extra["redacted_query"] = spec.get("redacted_query") or ""
        action = "safety"
    return _payload(
        spec.get("answer") or "",
        intent=intent,
        action=action,
        refuse=refuse,
        suggestions=list(spec.get("suggestions") or []),
        generator=spec.get("generator"),
        extra=extra or None,
    )


def _maybe_llm(payload: dict, query: str, hits: list[tuple[Chunk, float]], mode: str, stream: bool) -> dict:
    if not deepseek_api_key():
        return payload
    if mode == "faq" and not hits:
        return payload
    if stream:
        pending = dict(payload)
        pending["generator"] = "deepseek_pending"
        pending["_hits"] = hits
        pending["_deepseek_mode"] = mode
        pending["_query"] = query
        return pending
    text = generate_with_deepseek(query, hits, mode=mode)
    if not text:
        return payload
    upgraded = dict(payload)
    upgraded["answer"] = text
    upgraded["generator"] = "deepseek"
    return upgraded


def lite_prelude(query: str) -> dict | None:
    """Greeting only. Other intents go through answer_lite so they stay consistent."""
    text = (query or "").strip()
    if text and _is_social(text):
        return _payload(
            INTRO_ANSWER,
            intent="intro",
            action="assistant_intro",
            suggestions=list(_CHIPS),
            generator="intro",
        )
    return None


def answer_lite(query: str, stream: bool = False) -> dict:
    """One routing decision for blocking and streaming callers."""
    text = (query or "").strip()
    if not text:
        return _payload(
            "直接说想办的事就行，例如在读证明、宿舍报修，或转人工。",
            intent="boundary",
            action="general_skill",
            suggestions=list(_CHIPS[:3]),
            generator="skill",
        )
    if contains_sensitive(text):
        redacted = text if "已隐去" in text else redact_sensitive(text)
        spec = safety_payload(redacted)
        return _from_skill(spec)
    if _RESTART_RE.match(text):
        return _payload(
            RESTART_ANSWER,
            intent="restart",
            action="restart",
            suggestions=list(_CHIPS),
            generator="intro",
        )
    if _BACK_RE.match(text):
        return _payload(
            "这一轮还没有上一个问题可以返回。直接说具体事项就行。",
            intent="chitchat",
            action="general_skill",
            suggestions=list(_CHIPS[:3]),
            generator="skill",
        )
    if _is_social(text):
        return _payload(
            INTRO_ANSWER,
            intent="intro",
            action="assistant_intro",
            suggestions=list(_CHIPS),
            generator="intro",
        )

    target = _body_query(text)
    skill = try_skill(target)
    if skill is not None:
        payload = _from_skill(skill)
        if skill.get("intent") == "translate":
            return _maybe_llm(payload, target, [], "general", stream)
        return payload

    routed = route_faq(target)
    if routed["action"] == "answer" and routed["chunks"]:
        chunk = routed["chunks"][0]
        score = routed["scores"][0] if routed["scores"] else 1.0
        hits = [(chunk, score)]
        payload = _payload(
            format_policy_answer(chunk),
            intent="campus_faq",
            action="knowledge_qa",
            citations=citations_from(hits),
            title=chunk.title,
            hits=hits,
        )
        return _maybe_llm(payload, target, hits, "faq", stream)
    if routed["action"] == "clarify" and routed["chunks"]:
        chunks = routed["chunks"][:3]
        return _payload(
            _clarify_text(chunks),
            intent="clarify",
            action="clarify",
            clarify=True,
            suggestions=_suggestions(chunks),
            generator="clarify",
        )
    bare = _BARE_CLARIFY.get(norm_key(target))
    if bare is not None:
        prompt, chips = bare
        return _payload(
            prompt,
            intent="clarify",
            action="clarify",
            clarify=True,
            suggestions=list(chips),
            generator="clarify",
        )
    if _policy_shaped(target):
        return _payload(
            "知识库未覆盖这个问题，我没有依据，不能编一条校规。\n\n"
            "你可以把事情说得更具体，或转人工让工作人员处理。下面几件是可以直接查的：",
            intent="refuse",
            action="refuse",
            refuse=True,
            suggestions=list(_CHIPS[:3]) + [_CHIPS[-1]],
            generator="refuse",
        )
    payload = _payload(
        "这句我接住了，但没有通用大模型，也没有知识库依据，不能随便展开。\n\n"
        "我可以直接做计算、单位换算、北京时间，以及校园用语的短翻译。"
        "校园规定请直接问具体事项，或者说转人工。",
        intent="boundary",
        action="general_skill",
        suggestions=list(_CHIPS[:3]) + [_CHIPS[-1]],
        generator="skill",
    )
    return _maybe_llm(payload, target, [], "general", stream)


_CATALOG = (
    ("教务学籍", ("在读", "学籍", "成绩", "选课", "退课", "缓考", "补考", "重修", "转专业", "休学", "复学", "毕业", "辅修", "绩点", "gpa", "考试", "考场", "四六级", "培养", "课表", "学分", "退学", "免修", "实习", "学历", "学位", "创新")),
    ("奖助贷", ("奖", "助学", "贷款", "勤工", "困难", "绿色通道", "学费", "减免", "助学金")),
    ("图书馆", ("图书", "借书", "研讨", "自习", "论文", "荐购", "馆际", "借阅")),
    ("宿舍后勤", ("宿舍", "报修", "门禁", "水电", "空调", "退宿", "晚归", "调宿", "漏水", "洗衣", "钥匙")),
    ("校园网", ("校园网", "vpn", "eduroam", "无线", "流量")),
    ("校园卡", ("校园卡", "一卡通", "圈存", "挂失", "付款码", "消磁")),
    ("医务心理", ("校医院", "心理", "医保", "挂号", "转诊")),
    ("教室借用", ("教室",)),
    ("假期作息", ("假期", "寒暑", "节假日", "食堂", "作息")),
    ("办事进度", ("办事", "一网通办", "催办", "补正", "单号", "转人工", "校园事务")),
)


def faq_catalog() -> dict:
    """Group existing FAQ titles for the in-portal navigator. No new policy text."""
    chunks = load_chunks()
    buckets: dict[str, list[dict]] = {name: [] for name, _keys in _CATALOG}
    other: list[dict] = []
    for chunk in chunks:
        hay = chunk.title.lower()
        best_name = ""
        best_score = 0
        for name, keys in _CATALOG:
            score = sum(len(key) for key in keys if key.lower() in hay)
            if score > best_score:
                best_name = name
                best_score = score
        item = {"title": chunk.title, "query": chunk.question, "id": chunk.id}
        if best_name:
            buckets[best_name].append(item)
        else:
            other.append(item)
    categories = [
        {"name": name, "items": buckets[name]}
        for name, _keys in _CATALOG
        if buckets[name]
    ]
    if other:
        categories.append({"name": "其他", "items": other})
    return {"categories": categories, "count": len(chunks)}


def lite_ready() -> dict:
    chunks = load_chunks()
    index = get_index()
    return {
        "faq_path": str(faq_path()),
        "chunks": len(chunks),
        "deepseek": bool(deepseek_api_key()),
        "router": "bm25-faq-vocab",
        "terms": len(index.lexicon),
    }
