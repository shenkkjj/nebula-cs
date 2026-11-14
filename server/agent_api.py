"""Staff queue: take, reply, close, write back, and mark a bad case."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from dify_client import create_text_document, dataset_configured
from settings import ROOT
import store

BAD_CASES_PATH = ROOT / "tests" / "eval" / "bad-cases.json"
_FILE_LOCK = threading.Lock()
SOURCE_LABEL = {"user": "用户主动", "refusal": "拒答后", "maintenance": "知识库维护"}
KIND_LABEL = {
    "wrong": "答错",
    "cite": "引用不对",
    "miss-refuse": "该拒没拒",
    "over-refuse": "不该拒却拒",
    "other": "其他",
}


def queue(status: str) -> dict:
    allowed = {"waiting", "active", "closed"}
    chosen = status if status in allowed else "waiting"
    items = []
    for ticket in store.list_tickets(chosen):
        items.append(_card(ticket))
    return {"ok": True, "status": chosen, "counts": store.ticket_counts(), "tickets": items}


def detail(public_id: str) -> tuple[int, dict]:
    ticket = store.get_ticket(public_id)
    if not ticket:
        return 404, {"ok": False, "error": "没有这张工单"}
    messages = store.list_messages(ticket_id=ticket["id"])
    judgments = store.list_judgments(ticket_id=ticket["id"])
    return 200, {
        "ok": True,
        "ticket": _card(ticket),
        "messages": [_public_message(item) for item in messages],
        "judgments": judgments,
    }


def take(public_id: str, user: dict) -> tuple[int, dict]:
    ticket = store.get_ticket(public_id)
    if not ticket:
        return 404, {"ok": False, "error": "没有这张工单"}
    if ticket["status"] == "closed":
        return 400, {"ok": False, "error": "这张工单已经结束"}
    if ticket["status"] == "active" and ticket.get("assignee_id") not in (None, user["user_id"]):
        name = ticket.get("assignee_name") or "其他坐席"
        return 409, {"ok": False, "error": f"已被 {name} 接入"}
    was_waiting = ticket["status"] == "waiting"
    if was_waiting or ticket.get("assignee_id") in (None, user["user_id"]):
        store.update_ticket(
            public_id,
            status="active",
            assignee_id=user["user_id"],
            assignee_name=user["display_name"],
            taken_at=ticket.get("taken_at") or store.now(),
        )
        if was_waiting:
            store.add_message(
                ticket["visitor_token"],
                "system",
                f"{user['display_name']}接入，机器人暂停回复",
                ticket.get("portal_session") or "",
                ticket["id"],
                author="系统",
            )
            store.add_audit("ticket_take", actor=user["username"], session_ref=public_id, decision="接入")
    return detail(public_id)


def reply(public_id: str, user: dict, text: str) -> tuple[int, dict]:
    body = (text or "").strip()
    if not body:
        return 400, {"ok": False, "error": "回复内容不能为空"}
    if len(body) > 800:
        return 400, {"ok": False, "error": "回复请控制在 800 字以内"}
    ticket = store.get_ticket(public_id)
    if not ticket:
        return 404, {"ok": False, "error": "没有这张工单"}
    if ticket["status"] != "active" or ticket.get("assignee_id") != user["user_id"]:
        return 403, {"ok": False, "error": "只有接入这张工单的坐席可以回复"}
    store.add_message(
        ticket["visitor_token"],
        "agent",
        body,
        ticket.get("portal_session") or "",
        ticket["id"],
        author=user["display_name"],
    )
    store.add_audit("ticket_reply", actor=user["username"], session_ref=public_id, decision="回复", question=body[:120])
    return detail(public_id)


def close(public_id: str, user: dict, note: str) -> tuple[int, dict]:
    text = (note or "").strip()
    if not text:
        return 400, {"ok": False, "error": "请写一句处理说明"}
    if len(text) > 300:
        return 400, {"ok": False, "error": "处理说明请控制在 300 字以内"}
    ticket = store.get_ticket(public_id)
    if not ticket:
        return 404, {"ok": False, "error": "没有这张工单"}
    if ticket["status"] == "closed":
        return 400, {"ok": False, "error": "这张工单已经结束"}
    if ticket.get("assignee_id") != user["user_id"]:
        return 403, {"ok": False, "error": "只有接入这张工单的坐席可以结束"}
    store.update_ticket(public_id, status="closed", closed_at=store.now(), close_note=text)
    store.add_message(
        ticket["visitor_token"],
        "system",
        "工单已结束，可以继续问校园助手。",
        ticket.get("portal_session") or "",
        ticket["id"],
        author="系统",
    )
    store.add_audit("ticket_close", actor=user["username"], session_ref=public_id, decision="结束", detail={"note": text})
    return detail(public_id)


def writeback(public_id: str, user: dict, question: str, answer: str) -> tuple[int, dict]:
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        return 400, {"ok": False, "error": "请填写问题和标准答法"}
    if len(q) > 120 or len(a) > 800:
        return 400, {"ok": False, "error": "问题不超过 120 字，答法不超过 800 字"}
    ticket = store.get_ticket(public_id)
    if not ticket:
        return 404, {"ok": False, "error": "没有这张工单"}
    row = store.add_writeback(ticket["id"], user["username"], q, a, "indexing")
    name = f"坐席回写｜{q}"
    text = f"问：{q}\n答：{a}\n"
    if not dataset_configured():
        saved = store.update_writeback(row["id"], "failed", error="没有配置知识库 API，草稿已保留，可稍后重试。")
        store.add_audit("writeback", actor=user["username"], session_ref=public_id, decision="失败", question=q)
        return 503, {"ok": False, "writeback": saved, "error": saved.get("error") if saved else "知识库不可用"}
    try:
        created = create_text_document(name, text)
    except Exception as exc:  # noqa: BLE001
        saved = store.update_writeback(row["id"], "failed", error=str(exc)[:300])
        store.add_audit("writeback", actor=user["username"], session_ref=public_id, decision="失败", question=q, detail={"error": str(exc)[:180]})
        return 502, {"ok": False, "writeback": saved, "error": "写入知识库失败，草稿已保留，可重试。"}
    status = "completed" if str(created.get("indexing_status")) in ("completed", "available", "indexed") else "indexing"
    saved = store.update_writeback(row["id"], status, dify_document_id=str(created.get("id") or ""))
    store.add_audit(
        "writeback",
        actor=user["username"],
        session_ref=public_id,
        decision="回写",
        question=q,
        source="坐席回写",
        detail={"document_id": created.get("id") or "", "status": status},
    )
    return 200, {"ok": True, "writeback": saved}


def writeback_status(row_id: int) -> tuple[int, dict]:
    row = store.get_writeback(row_id)
    if not row:
        return 404, {"ok": False, "error": "没有这条回写"}
    return 200, {"ok": True, "writeback": row}


def mark_bad_case(user: dict, message_id: int, kind: str, expect: str) -> tuple[int, dict]:
    if kind not in KIND_LABEL:
        return 400, {"ok": False, "error": "请选择问题类型"}
    message = store.get_message(message_id)
    if not message:
        return 404, {"ok": False, "error": "没有这条回答"}
    record = _upsert_bad_case(message, kind, (expect or "").strip(), user["username"])
    store.add_audit(
        "bad_case",
        actor=user["username"],
        session_ref=str(message_id),
        decision=KIND_LABEL[kind],
        question=(message.get("body") or "")[:120],
        detail={"bad_id": record["id"]},
    )
    return 200, {"ok": True, "bad_case": record}


def _upsert_bad_case(message: dict, kind: str, expect: str, actor: str) -> dict:
    with _FILE_LOCK:
        rows = _read_bad_cases()
        existing = next((row for row in rows if row.get("source_message_id") == message["id"]), None)
        if existing:
            existing["kind"] = kind
            existing["kind_label"] = KIND_LABEL[kind]
            existing["expect"] = expect
            existing["updated_at"] = store.now()
            existing["actor"] = actor
            _write_bad_cases(rows)
            return existing
        number = 1 + max((int(str(row.get("id", "BAD-0")).split("-")[-1] or 0) for row in rows), default=0)
        record = {
            "id": f"BAD-{number:03d}",
            "type": "bad_case",
            "kind": kind,
            "kind_label": KIND_LABEL[kind],
            "question": "",
            "answer": message.get("body") or "",
            "expect": expect,
            "source_message_id": message["id"],
            "created_at": store.now(),
            "actor": actor,
        }
        prior = store.list_messages(ticket_id=message.get("ticket_id")) if message.get("ticket_id") else []
        for item in reversed(prior):
            if item["id"] < message["id"] and item["role"] == "user":
                record["question"] = item["body"]
                break
        rows.append(record)
        _write_bad_cases(rows)
        return record


def _read_bad_cases() -> list:
    if not BAD_CASES_PATH.is_file():
        return []
    try:
        data = json.loads(BAD_CASES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _write_bad_cases(rows: list) -> None:
    BAD_CASES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BAD_CASES_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _card(ticket: dict) -> dict:
    return {
        "id": ticket["id"],
        "public_id": ticket["public_id"],
        "status": ticket["status"],
        "source": ticket["source"],
        "source_label": SOURCE_LABEL.get(ticket["source"], ticket["source"]),
        "first_question": ticket["first_question"],
        "assignee_name": ticket.get("assignee_name") or "",
        "assignee_id": ticket.get("assignee_id"),
        "created_at": ticket["created_at"],
        "wait_seconds": ticket.get("wait_seconds") or 0,
        "active_seconds": ticket.get("active_seconds") or 0,
        "close_note": ticket.get("close_note") or "",
        "visitor": (ticket.get("visitor_token") or "")[:4],
        "portal_session": ticket.get("portal_session") or "",
    }


def _public_message(item: dict) -> dict:
    return {
        "id": item["id"],
        "role": item["role"],
        "author": item.get("author") or "",
        "body": item.get("body") or "",
        "created_at": item.get("created_at") or "",
        "meta": item.get("meta") or {},
    }
