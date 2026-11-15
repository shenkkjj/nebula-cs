"""Visitor ratings for their own assistant replies. Not the staff bad-case queue."""
from __future__ import annotations

import store


def submit_feedback(
    visitor: str,
    message_id: int,
    helpful: bool,
    comment: str = "",
    portal_session: str = "",
) -> tuple[int, dict]:
    if not visitor:
        return 401, {"ok": False, "error": "请先打开门户再评价"}
    message = store.get_message(message_id)
    if message is None or message.get("visitor_token") != visitor:
        return 403, {"ok": False, "error": "只能评价自己的回答"}
    if message.get("role") != "bot":
        return 400, {"ok": False, "error": "只能评价校园助手的回答"}
    session = message.get("portal_session") or ""
    if portal_session and session and portal_session != session:
        return 403, {"ok": False, "error": "只能评价自己的回答"}
    saved = store.upsert_feedback(visitor, session or portal_session, message["id"], bool(helpful), comment or "")
    question = store.previous_user_text(visitor, session, message["id"])
    store.add_audit(
        "feedback",
        actor="访客",
        session_ref=(session or visitor)[:24],
        question=question[:120],
        decision="有帮助" if helpful else "没解决",
        detail={"message_id": message["id"], "helpful": bool(helpful)},
    )
    return 200, {
        "ok": True,
        "helpful": bool(saved.get("helpful")),
        "message_id": message["id"],
    }
