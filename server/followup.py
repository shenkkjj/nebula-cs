"""Short follow-ups stay on the previous campus question. No model call."""
from __future__ import annotations

import re

HANDOFF_RE = re.compile(
    r"(转\s*人工|人工\s*客服|人工\s*坐席|转接\s*人工|找\s*人工|联系\s*人工|有没有真人|找真人)"
)
ANGRY_RE = re.compile(
    r"(我要投诉|投诉你们|我要反馈|太差了|服务太差|气死了|垃圾客服|找你们领导|找领导|受不了了|根本解决不了)"
)
_RESTART_RE = re.compile(r"^(重新开始|重新来过|换个话题|清空对话|开始新对话)[。.!！]?$")
_BACK_RE = re.compile(r"^(返回上一个问题|回到上一个问题|上一个问题|返回上一题|回到刚才)[。.!！]?$")
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
_TOPIC_SWITCH_RE = re.compile(
    r"^(?:那|那么|还有|另外|这个|那个)?\s*([\u4e00-\u9fffA-Za-z0-9]{1,12})\s*呢[？?]?$"
)
_LEADING_FOLLOW_RE = re.compile(r"^(?:那|那么|还有|另外|这个|那个)?\s*[\u4e00-\u9fffA-Za-z0-9]{1,12}\s*呢[？?]?$")
_OPENING_FOLLOW_RE = re.compile(r"^(那|那么|这个|那个|还有|另外)")


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
    if _LEADING_FOLLOW_RE.match(q):
        return True
    if _OPENING_FOLLOW_RE.match(q) and len(q) <= 18:
        return True
    if not _aspect_phrase(q):
        return False
    stripped = _FOLLOW_STRIP_RE.sub("", q)
    stripped = re.sub(r"[\s？?！!。.,，]", "", stripped)
    return len(stripped) < 2


def _switch_topic(query: str) -> str:
    match = _TOPIC_SWITCH_RE.match((query or "").strip())
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
