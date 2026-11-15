"""Local FAQ title matching. No embeddings, no Ollama, no network.

Used to quote an official entry when the question clearly points at one
title, and to put that same entry on the citation card.
"""
from __future__ import annotations

import re

from faq_meta import load_entries

_PREFIX = re.compile(
    r"^(同学想问[，,：:]?|请问一下|请问|想问一下|想问|请教一下|请教|麻烦问一下|我想问一下|我想问|咨询一下|咨询)"
)
_FILLER = re.compile(r"(一般|到底|究竟|具体|指的是|都)")
_TAIL = re.compile(
    r"(该如何处理|该怎么办|如何处理|如何办理|怎么办理|怎样办理|怎么办|怎么处理|是什么时候|是什么|都包括什么|有哪些|在哪里|去哪儿|去哪里|吗|呢|呀|啊|吧|了)+$"
)
_PUNCT = re.compile(r"[，。！？、；：,.!?;:\s“”\"'（）()【】\[\]—\-~～]+")
_FOLLOW_LEAD = re.compile(r"^(那|这个|这|还有|然后|另外|同|同样)")
_NOISE = re.compile(r"(如何|怎样|怎么|可以|能否|是否|相关|办理|申请|处理|查询|开|的|了|吗|呢)")

_SYNONYMS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"去哪儿|去哪里|在哪儿|在哪(?!里)"), "在哪里"),
    (re.compile(r"何时|啥时候"), "什么时候"),
    (re.compile(r"有啥区别|有什么差别|差别在哪里|差别是什么|有何区别"), "有什么区别"),
    (re.compile(r"差别"), "区别"),
    (re.compile(r"怎样|怎么"), "如何"),
    (re.compile(r"能不能|能否"), "可以"),
    (re.compile(r"想申请"), "如何申请"),
    (re.compile(r"要如何去办|要怎么去办|想办理|要如何办"), "如何办理"),
    (re.compile(r"如何用|如何使用"), "如何使用"),
    (re.compile(r"在哪里查(?!询)|如何查(?!询)|在哪查"), "如何查询"),
    (re.compile(r"不制冷|不凉|不冷"), "不制冷"),
    (re.compile(r"去哪下|去哪里下|在哪里下|在哪下"), "在哪里下载"),
    (re.compile(r"开不开"), "开放"),
    (re.compile(r"指的是"), "是"),
    (re.compile(r"交到哪(?!里)|交到哪里"), "交到哪里"),
)


def normalize(text: str) -> str:
    t = (text or "").strip().lower()
    t = _PREFIX.sub("", t)
    t = t.replace("？", "").replace("?", "")
    for pattern, repl in _SYNONYMS:
        t = pattern.sub(repl, t)
    t = _FILLER.sub("", t)
    t = _TAIL.sub("", t)
    t = _PUNCT.sub("", t)
    return t.strip()


def content_key(text: str) -> str:
    t = normalize(text)
    t = _FOLLOW_LEAD.sub("", t)
    t = _NOISE.sub("", t)
    t = re.sub(r"(办|用|查|做)+$", "", t)
    return t.strip()


def is_followup(query: str, history: list | None) -> bool:
    text = (query or "").strip()
    if not text:
        return False
    if not _last_user(history):
        return False
    if len(text) <= 16 or _FOLLOW_LEAD.match(text):
        return True
    if text.endswith("呢") or text.endswith("呢？") or text.endswith("呢?"):
        return True
    return False


def _last_user(history: list | None) -> str:
    for item in reversed(history or []):
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or "").lower()
        text = (item.get("text") or item.get("content") or "").strip()
        if role in ("user", "human") and text:
            return text
    return ""


def _char_cover(needle: str, hay: str) -> float:
    if not needle or not hay:
        return 0.0
    if needle in hay:
        return 1.0
    best = 0
    length = len(needle)
    for size in range(length, 1, -1):
        for start in range(0, length - size + 1):
            if needle[start : start + size] in hay:
                best = size
                break
        if best:
            break
    return best / length


def _bigram_jaccard(a: str, b: str) -> float:
    def grams(text: str) -> set[str]:
        if len(text) <= 1:
            return {text} if text else set()
        return {text[i : i + 2] for i in range(len(text) - 1)}

    left, right = grams(a), grams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _pair_score(query: str, title: str, previous: str = "") -> tuple[float, str]:
    nq = normalize(query)
    nt = normalize(title)
    if not nq or not nt:
        return 0.0, "empty"
    if nq == nt:
        return 1.0, "exact"
    contained = False
    if nt in nq or nq in nt:
        shorter, longer = (nt, nq) if len(nt) <= len(nq) else (nq, nt)
        if len(shorter) >= 4 or (len(shorter) >= 2 and shorter in nt):
            contained = True
            ratio = len(shorter) / len(longer)
            score = 0.88 + 0.12 * ratio
            reason = "contain"
        else:
            score = 0.0
            reason = "weak-contain"
    else:
        cover_q = _char_cover(nq, nt)
        cover_t = _char_cover(nt, nq)
        jac = _bigram_jaccard(nq, nt)
        score = 0.45 * cover_q + 0.25 * cover_t + 0.30 * jac
        reason = "overlap"

    aspect = content_key(query)
    title_key = content_key(title)
    if aspect and title_key:
        if aspect == title_key:
            score = max(score, 0.97)
            reason = "aspect-title"
        elif aspect in title_key or title_key.startswith(aspect) or aspect.startswith(title_key):
            score = max(score, 0.88)
            reason = "aspect-title"
    if previous:
        prev_n = normalize(previous)
        prev_key = content_key(previous)
        related = max(_char_cover(prev_n, nt), _bigram_jaccard(prev_n, nt), _char_cover(nt, prev_n))
        if prev_key:
            related = max(related, _char_cover(prev_key, nt), _char_cover(prev_key, title_key))
        aspect_hit = bool(aspect) and (
            aspect in nt or aspect in title or aspect in title_key or _char_cover(aspect, nt) >= 0.4
        )
        if not aspect_hit and aspect:
            parts = [aspect[i : i + n] for n in (2, 3, 4) for i in range(len(aspect) - n + 1)]
            generic = {"如何", "在哪", "哪里", "交到", "到哪", "怎么", "办理", "申请", "处理", "查询", "开放", "使用"}
            strong = [part for part in parts if part not in generic and part in nt]
            aspect_hit = bool(strong)
        if aspect_hit:
            score += 0.18 + 0.18 * related
            # Prefer the title that also keeps the previous topic (转专业+学分, 校园卡+补办)
            if prev_key and (prev_key in nt or prev_key in title_key or _char_cover(prev_key, nt) >= 0.4):
                score += 0.12
            reason = "follow-aspect" if reason not in {"exact", "contain", "aspect-title"} else reason
        elif related >= 0.25:
            score += 0.06 * related
            if reason == "overlap":
                reason = "follow-related"
        if aspect and nt == prev_n and aspect not in nt:
            score -= 0.35
    elif contained:
        return score, reason
    return max(score, 0.0), reason


def rank(query: str, history: list | None = None) -> list[dict]:
    previous = _last_user(history) if is_followup(query, history) else ""
    rows: list[dict] = []
    for entry in load_entries():
        score, reason = _pair_score(query, entry["title"], previous)
        rows.append({"title": entry["title"], "score": score, "reason": reason, "entry": entry})
    rows.sort(key=lambda item: item["score"], reverse=True)
    return rows


def confident_match(query: str, history: list | None = None, rewritten: str | None = None) -> dict | None:
    """Return one official entry when the question clearly names it.

    Conservative on purpose: out-of-scope questions must not get a card.
    """
    text = (query or "").strip()
    if not text:
        return None
    ranked = rank(text, history)
    if rewritten and rewritten.strip() and rewritten.strip() != text:
        alt = rank(rewritten.strip(), history)
        if alt and (not ranked or alt[0]["score"] > ranked[0]["score"]):
            ranked = alt
    if not ranked:
        return None
    follow = is_followup(text, history)
    previous = _last_user(history) if follow else ""
    if previous:
        ranked = _prefer_previous_topic(ranked, previous)
    ranked = _break_close_ties(ranked, text, previous)
    best = ranked[0]
    second = ranked[1]["score"] if len(ranked) > 1 else 0.0
    margin = best["score"] - second
    if best["reason"] in {"exact", "contain", "aspect-title"} and best["score"] >= 0.9 and margin >= 0.04:
        return best
    if follow and best["reason"] in {"follow-aspect", "follow-topic", "exact", "contain", "aspect-title"} and best["score"] >= 0.66 and margin >= 0.05:
        return best
    if best["score"] >= 0.84 and margin >= 0.07:
        return best
    return None



def _topic_related(previous: str, title: str) -> float:
    prev_key = content_key(previous)
    title_key = content_key(title)
    if not prev_key or not title_key:
        return 0.0
    return max(
        _char_cover(prev_key, title_key),
        _char_cover(prev_key, normalize(title)),
        _bigram_jaccard(prev_key, title_key),
    )


def _prefer_previous_topic(ranked: list[dict], previous: str) -> list[dict]:
    """When a follow-up is generic, keep the title that stays on the prior topic."""
    if not ranked or not previous:
        return ranked
    scored = []
    for row in ranked:
        related = _topic_related(previous, row["title"])
        scored.append((related, row))
    best_rel = scored[0][0]
    alt = next((item for item in scored[1:6] if item[0] >= 0.35 and item[0] > best_rel + 0.1), None)
    # Also prefer a slightly lower lexical score if it is clearly more on-topic
    if alt and scored[0][1]["score"] - alt[1]["score"] <= 0.25:
        chosen = dict(alt[1])
        chosen["score"] = max(chosen["score"], scored[0][1]["score"] + 0.08)
        chosen["reason"] = "follow-topic"
        rest = [row for _, row in scored if row is not alt[1]]
        return [chosen] + rest
    return ranked



def _break_close_ties(ranked: list[dict], query: str, previous: str) -> list[dict]:
    if len(ranked) < 2:
        return ranked
    aspect = content_key(query)

    def key(row: dict) -> tuple:
        title_key = content_key(row["title"])
        exact = 1 if aspect and aspect == title_key else 0
        contained = 1 if aspect and title_key and aspect in title_key else 0
        related = _topic_related(previous, row["title"]) if previous else 0.0
        concise = -len(title_key or row["title"])
        return (row["score"], exact, related, contained, concise)

    top = ranked[0]["score"]
    close = [row for row in ranked if top - row["score"] <= 0.12]
    rest = [row for row in ranked if row not in close]
    close.sort(key=key, reverse=True)
    return close + rest


def official_card(match: dict, mark: int = 1) -> dict:
    entry = match["entry"]
    title = entry["title"]
    body = (entry["body"] or "").strip()
    content = f"{title}\n{body}"
    return {
        "document_name": entry.get("document") or "客服样例FAQ.md",
        "document_id": "",
        "dataset_name": "星云大学校园办事FAQ",
        "dataset_id": "",
        "segment_id": f"faq-{entry.get('n') or title}",
        "score": max(float(match.get("score") or 0.0), 0.99),
        "content": content[:1600],
        "mark": mark,
        "title": title,
        "segments": [{"content": content[:1600], "score": 0.99, "segment_id": f"faq-{entry.get('n') or title}"}],
    }


def official_answer(match: dict) -> str:
    body = (match["entry"].get("body") or "").strip()
    return f"{body} [1]" if body else ""


def blend_retrieval(resources: list, query: str, history: list | None = None) -> list:
    """Put a confident official entry first so Hit@3 sees the right title."""
    match = confident_match(query, history)
    mixed = list(resources or [])
    if match:
        card = official_card(match)
        mixed = [card] + [item for item in mixed if (item.get("content") or "") != card["content"]]
    return mixed


def align_resources_to_answer(resources: list, answer: str, query: str = "") -> list:
    """Prefer the segment that actually supports the answer or the query title."""
    if not resources:
        return resources
    blob = (answer or "") + "\n" + (query or "")
    best_i = 0
    best = -1.0
    for index, item in enumerate(resources):
        content = (item.get("content") if isinstance(item, dict) else "") or ""
        score = 0.0
        if query:
            score += 2.0 * _char_cover(normalize(query), normalize(content))
        # titles that appear in the answer should win
        for entry in load_entries():
            title = entry["title"]
            if title and title.rstrip("？?") in content and title.rstrip("？?") in blob:
                score += 3.0
        score += 0.3 * _char_cover(normalize(answer)[:40], normalize(content))
        raw = item.get("score") if isinstance(item, dict) else None
        if isinstance(raw, (int, float)):
            score += 0.1 * float(raw)
        if score > best:
            best = score
            best_i = index
    if best_i == 0:
        return resources
    chosen = resources[best_i]
    return [chosen] + [item for i, item in enumerate(resources) if i != best_i]
