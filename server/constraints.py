"""Citation gate, empty-retrieval block, and per-document merge.

R-201: a knowledge answer needs a citation at or above the threshold.
R-202: empty retrieval never reaches the user as a model answer.
R-203: segments from the same document become one card.
Numbered marks must point at those cards. Unmatched marks are removed.
"""
from __future__ import annotations

import re

from faq_meta import load_entries

_MARK_RE = re.compile(r"\[(\d+)\]")


def norm_score(score) -> float | None:
    if score is None or score == "":
        return None
    try:
        number = float(score)
    except (TypeError, ValueError):
        return None
    if number > 1:
        return number / 100.0
    return number


def normalize_resource(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    content = (item.get("content") or item.get("text") or meta.get("content") or "").strip()
    document_name = (
        item.get("document_name")
        or meta.get("document_name")
        or item.get("title")
        or meta.get("title")
        or ""
    )
    document_id = str(item.get("document_id") or meta.get("document_id") or "")
    dataset_name = item.get("dataset_name") or meta.get("dataset_name") or ""
    dataset_id = str(item.get("dataset_id") or meta.get("dataset_id") or "")
    segment_id = str(item.get("segment_id") or meta.get("segment_id") or "")
    if not content and not document_name:
        return None
    return {
        "document_name": document_name or "未命名文档",
        "document_id": document_id,
        "dataset_name": dataset_name,
        "dataset_id": dataset_id,
        "segment_id": segment_id,
        "score": norm_score(item.get("score") if item.get("score") is not None else meta.get("score")),
        "content": content[:1600],
    }


def merge_citations(resources: list, max_cards: int = 3) -> list[dict]:
    """One card per document. The highest-scoring segment is the visible one."""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for raw in resources or []:
        item = raw if isinstance(raw, dict) and "document_name" in raw and "content" in raw else None
        if item is None or "segments" in (raw or {}):
            item = normalize_resource(raw) if not (isinstance(raw, dict) and raw.get("segments")) else raw
        if not item:
            continue
        if item.get("segments") and "score" in item and item.get("content"):
            # Already a card. Keep it as its own group.
            key = item.get("document_id") or item.get("document_name") or str(id(item))
        else:
            key = item.get("document_id") or item.get("document_name") or item.get("segment_id") or str(len(order))
        if key not in groups:
            groups[key] = {
                "document_name": item.get("document_name") or "未命名文档",
                "document_id": item.get("document_id") or "",
                "dataset_name": item.get("dataset_name") or "",
                "dataset_id": item.get("dataset_id") or "",
                "score": item.get("score"),
                "content": item.get("content") or "",
                "segment_id": item.get("segment_id") or "",
                "segments": [],
            }
            order.append(key)
        card = groups[key]
        segment = {
            "content": item.get("content") or "",
            "score": item.get("score"),
            "segment_id": item.get("segment_id") or "",
        }
        if item.get("segments"):
            for extra in item["segments"]:
                if isinstance(extra, dict):
                    card["segments"].append(extra)
        else:
            card["segments"].append(segment)
        best = card["score"]
        new = item.get("score")
        if new is not None and (best is None or new > best):
            card["score"] = new
            card["content"] = item.get("content") or card["content"]
            card["segment_id"] = item.get("segment_id") or card["segment_id"]
            if item.get("document_name"):
                card["document_name"] = item["document_name"]
    cards = [groups[key] for key in order]
    for card in cards:
        card["segments"] = sorted(
            card["segments"],
            key=lambda seg: seg.get("score") if isinstance(seg.get("score"), (int, float)) else -1,
            reverse=True,
        )
    cards.sort(key=lambda card: card["score"] if isinstance(card["score"], (int, float)) else -1, reverse=True)
    if max_cards > 0:
        cards = cards[:max_cards]
    return cards


def seal_user_citations(payload: dict) -> dict:
    """A refusal never keeps citation cards. The structured refuse flag decides this."""
    if payload.get("refuse"):
        payload["citations"] = []
    return payload


def apply_constraints(answer: str, resources: list, cfg: dict, retrieval_empty: bool = False) -> dict:
    """Decide whether the model text may be shown."""
    normalized = []
    for raw in resources or []:
        item = normalize_resource(raw)
        if item:
            normalized.append(item)
    empty = retrieval_empty or not normalized
    threshold = float(cfg.get("score_threshold") or 0.5)
    max_cards = int(cfg.get("max_citations") or 3)
    refusal = str(cfg.get("refusal_text") or "")
    if empty:
        return {
            "action": "refuse",
            "answer": refusal,
            "citations": [],
            "refuse": True,
            "reason": "empty_retrieval",
            "raw_segments": 0,
            "merged_cards": 0,
        }
    strong = [item for item in normalized if item.get("score") is not None and item["score"] >= threshold]
    merged = merge_citations(strong, max_cards=max_cards)
    if not merged:
        return {
            "action": "refuse",
            "answer": refusal,
            "citations": [],
            "refuse": True,
            "reason": "missing_citation",
            "raw_segments": len(normalized),
            "merged_cards": 0,
        }
    shortcut = _shortcut_text(merged, cfg)
    if shortcut:
        top = dict(merged[0])
        top["mark"] = 1
        return {
            "action": "answer",
            "answer": shortcut,
            "citations": [top],
            "refuse": False,
            "reason": "faq_shortcut",
            "raw_segments": len(normalized),
            "merged_cards": 1,
        }
    marked, kept = _keep_marked_cards(answer, merged)
    if not kept:
        return {
            "action": "refuse",
            "answer": refusal,
            "citations": [],
            "refuse": True,
            "reason": "missing_citation",
            "raw_segments": len(normalized),
            "merged_cards": 0,
        }
    return {
        "action": "answer",
        "answer": marked,
        "citations": kept,
        "refuse": False,
        "reason": "ok",
        "raw_segments": len(normalized),
        "merged_cards": len(kept),
    }


def _keep_marked_cards(answer: str, cards: list[dict]) -> tuple[str, list[dict]]:
    """Drop [n] that does not point at a retrieved card. Keep only cited cards."""
    cited: set[int] = set()

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if 1 <= number <= len(cards):
            cited.add(number)
            return f"[{number}]"
        return ""

    text = _MARK_RE.sub(replace, answer or "")
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    kept = []
    for number in range(1, len(cards) + 1):
        if number not in cited:
            continue
        card = dict(cards[number - 1])
        card["mark"] = number
        kept.append(card)
    return text, kept


def _shortcut_text(cards: list[dict], cfg: dict) -> str | None:
    """Optional: quote the FAQ body when the top hit is already very close.

    Off unless faq_shortcut is true. This does not retrieve on its own.
    """
    if not cfg.get("faq_shortcut") or not cards:
        return None
    top = cards[0]
    score = top.get("score")
    bar = max(float(cfg.get("score_threshold") or 0.5), float(cfg.get("faq_shortcut_score") or 0.85))
    if not isinstance(score, (int, float)) or score < bar:
        return None
    parts = [top.get("content") or ""]
    for segment in top.get("segments") or []:
        parts.append(segment.get("content") or "")
    blob = "\n".join(parts)
    for entry in load_entries():
        title = entry["title"]
        if title and title in blob:
            body = (entry["body"] or "").strip()
            if not body:
                return None
            return f"{body} [1]"
    return None
