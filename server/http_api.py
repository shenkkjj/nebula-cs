"""HTTP routes for login, the portal thread, the staff desk, and admin."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote
from urllib.request import Request, urlopen

import admin_api
import agent_api
import auth
import campus_engine
from feedback import submit_feedback
from auth import SESSION_COOKIE, cookie_header, current_user, ensure_visitor, require_user, safe_next
from dify_client import dataset_configured
from engine_mode import engine_mode, uses_qut
from gateway import _handoff_source
from masking import mask_text
from settings import dify_app_key, ollama_host
import store


def _retired_route(path: str) -> bool:
    return uses_qut() and (
        path.rstrip("/") in ("/api/ticket", "/api/portal/state", "/api/portal/tickets", "/api/admin/handoffs")
        or path.startswith(("/api/agent/", "/api/portal/tickets/"))
    )


def try_get(handler, raw: str) -> bool:
    if _retired_route(raw):
        handler._json_error(404, "unknown endpoint")
        return True
    if raw in ("/api/me", "/api/me/"):
        user = current_user(handler)
        if not user or (uses_qut() and user["role"] != "admin"):
            handler._json_response(401, {"ok": False, "error": "请先登录"})
            return True
        handler._json_response(200, {"ok": True, "user": _public_user(user)})
        return True
    if raw in ("/api/portal/state", "/api/portal/state/"):
        _portal_state(handler)
        return True
    if raw in ("/api/portal/tickets", "/api/portal/tickets/"):
        _portal_tickets(handler)
        return True
    match = re.fullmatch(r"/api/portal/tickets/([^/]{1,80})", raw)
    if match:
        _portal_ticket(handler, match.group(1))
        return True
    if raw in ("/api/health", "/api/health/"):
        return False
    if raw.startswith("/api/agent/"):
        user = require_user(handler, ("agent", "admin"))
        if not user:
            return True
        return _agent_get(handler, raw, user)
    if raw.startswith("/api/admin/"):
        user = require_user(handler, ("admin",))
        if not user:
            return True
        return _admin_get(handler, raw, user)
    return False


def try_post(handler, path: str) -> bool:
    if _retired_route(path):
        handler._json_error(404, "unknown endpoint")
        return True
    if path == "/api/login":
        _login(handler)
        return True
    if path == "/api/logout":
        auth.logout(handler)
        handler._json_response(200, {"ok": True})
        return True
    if path == "/api/feedback":
        _feedback(handler)
        return True
    if path == "/api/ticket":
        return False
    if path.startswith("/api/agent/"):
        user = require_user(handler, ("agent", "admin"))
        if not user:
            return True
        return _agent_post(handler, path, user)
    if path.startswith("/api/admin/"):
        user = require_user(handler, ("admin",))
        if not user:
            return True
        return _admin_post(handler, path, user)
    return False


def try_delete(handler, path: str) -> bool:
    match = re.fullmatch(r"/api/admin/documents/([^/]+)", path)
    segment = re.fullmatch(r"/api/admin/segments/([^/]+)", path)
    if not match and not segment:
        return False
    user = require_user(handler, ("admin",))
    if not user:
        return True
    if segment:
        status, payload = admin_api.remove_segment(segment.group(1), user)
    else:
        status, payload = admin_api.remove_document(match.group(1), user)
    handler._json_response(status, payload)
    return True


def health_payload() -> dict:
    if engine_mode() == "campus":
        return campus_engine.health_payload()
    return _dify_health()


def _dify_health() -> dict:
    probe = store.latest_probe()
    maintenance = bool(probe and not probe.get("ok"))
    return {
        "ok": True,
        "service": "nebula-cs",
        "engine": "dify+gateway",
        "streaming": True,
        "maintenance": maintenance,
        "probe": probe,
        "components": {
            "gateway": "up",
            "database": "up",
            "dify": "configured" if dify_app_key() else "missing_key",
            "dataset": "configured" if dataset_configured() else "missing_key",
            "ollama": _ollama_status(),
        },
    }


def _feedback(handler) -> None:
    visitor = ensure_visitor(handler)
    try:
        data = handler._read_json()
    except ValueError as exc:
        handler._json_error(400, str(exc))
        return
    try:
        message_id = int(data.get("message_id"))
    except (TypeError, ValueError):
        handler._json_error(400, "缺少要评价的回答")
        return
    status, payload = submit_feedback(
        visitor,
        message_id,
        bool(data.get("helpful")),
        str(data.get("comment") or ""),
        str(data.get("portal_session") or "")[:80],
    )
    handler._json_response(status, payload)


def create_portal_ticket(handler, subject: str, detail: str, contact: str, portal_session: str) -> None:
    visitor = ensure_visitor(handler)
    masked_subject, _a = mask_text(subject)
    masked_detail, _b = mask_text(detail)
    masked_contact, _c = mask_text(contact)
    question = masked_subject or masked_detail or "转人工"
    source = _handoff_source(visitor, portal_session)
    with store.exclusive():
        if portal_session:
            ticket, created = store.open_or_create_ticket(visitor, portal_session, source, question)
        else:
            ticket, created = store.create_ticket(visitor, portal_session, source, question), True
        body = masked_detail if created else " · ".join(filter(None, (masked_subject, masked_detail)))
        if body:
            store.add_message(visitor, "user", body, portal_session, ticket["id"], meta={"contact": masked_contact})
        action = "登记" if created else "补充"
        store.add_audit("ticket", actor="访客", session_ref=ticket["public_id"], decision=action, question=question)
    public_id = ticket["public_id"]
    next_step = "坐席上线后会在这个窗口回复。" if ticket["status"] == "waiting" else "坐席会在这个窗口回复。"
    handler._json_response(
        200,
        {
            "ok": True,
            "ticket_id": public_id,
            "ticket": {"public_id": public_id, "status": ticket["status"], "assignee_name": ticket["assignee_name"] or ""},
            "queue": True,
            "message": f"已{action}工单 {public_id}。{next_step}",
        },
    )


def _login(handler) -> None:
    try:
        data = handler._read_json()
    except ValueError as exc:
        handler._json_error(400, str(exc))
        return
    qut = uses_qut()
    result = auth.login(
        str(data.get("username") or ""),
        str(data.get("password") or ""),
        "admin" if qut else str(data.get("role") or ""),
    )
    status = result.pop("status")
    if result.get("ok"):
        target = "/admin" if qut else safe_next(str(data.get("next") or ""), result["role"])
        result["redirect"] = target
        handler._set_cookies = getattr(handler, "_set_cookies", [])
        handler._set_cookies.append(cookie_header(SESSION_COOKIE, result.pop("token"), 60 * 60 * 12))
    handler._json_response(status, result)


def _portal_state(handler) -> None:
    visitor = ensure_visitor(handler)
    session = _query_value(handler, "session")[:80]
    after = _query_cursor(handler) or 0
    probe = store.latest_probe_status()
    ticket = store.latest_portal_ticket(visitor, session) if session else None
    if ticket:
        ticket["assignee_name"] = ticket["assignee_name"] or ""
    handler._json_response(
        200,
        {
            "ok": True,
            "maintenance": bool(probe and not probe["ok"]),
            "probe_ok": probe["ok"] if probe else None,
            "ticket": ticket,
            "messages": store.portal_updates(visitor, session, after) if session else [],
        },
    )


def _portal_tickets(handler) -> None:
    visitor = auth.current_visitor(handler)
    tickets, next_before = store.list_portal_tickets(visitor, _query_cursor(handler, "before")) if visitor else ([], None)
    handler._json_response(200, {"ok": True, "tickets": tickets, "next_before": next_before})


def _portal_ticket(handler, public_id: str) -> None:
    visitor = auth.current_visitor(handler)
    detail = store.portal_ticket_detail(visitor, public_id, _query_cursor(handler, "before")) if visitor else None
    if detail is None:
        handler._json_response(404, {"ok": False, "error": "没有找到这张工单"})
        return
    handler._json_response(200, {"ok": True, **detail})


def _agent_get(handler, raw: str, user: dict) -> bool:
    if raw in ("/api/agent/tickets", "/api/agent/tickets/"):
        status = "waiting"
        if "?" in handler.path:
            for part in handler.path.split("?", 1)[1].split("&"):
                if part.startswith("status="):
                    status = part.split("=", 1)[1]
        handler._json_response(200, agent_api.queue(status))
        return True
    match = re.fullmatch(r"/api/agent/tickets/([^/]+)", raw)
    if match:
        status, payload = agent_api.detail(
            match.group(1), after=_query_cursor(handler), trace_after=_query_cursor(handler, "trace_after")
        )
        handler._json_response(status, payload)
        return True
    match = re.fullmatch(r"/api/agent/writebacks/(\d+)", raw)
    if match:
        status, payload = agent_api.writeback_status(int(match.group(1)))
        handler._json_response(status, payload)
        return True
    handler._json_error(404, "unknown endpoint")
    return True


def _agent_post(handler, path: str, user: dict) -> bool:
    try:
        data = handler._read_json()
    except ValueError as exc:
        handler._json_error(400, str(exc))
        return True
    match = re.fullmatch(r"/api/agent/tickets/([^/]+)/(take|reply|close|writeback)", path)
    if match:
        public_id, action = match.group(1), match.group(2)
        if action == "take":
            status, payload = agent_api.take(public_id, user)
        elif action == "reply":
            status, payload = agent_api.reply(public_id, user, str(data.get("text") or ""))
        elif action == "close":
            status, payload = agent_api.close(public_id, user, str(data.get("note") or ""))
        else:
            status, payload = agent_api.writeback(public_id, user, str(data.get("question") or ""), str(data.get("answer") or ""))
        handler._json_response(status, payload)
        return True
    if path == "/api/agent/bad-cases":
        try:
            message_id = int(data.get("message_id"))
        except (TypeError, ValueError):
            handler._json_error(400, "缺少要标记的回答")
            return True
        status, payload = agent_api.mark_bad_case(user, message_id, str(data.get("kind") or ""), str(data.get("expect") or ""))
        handler._json_response(status, payload)
        return True
    handler._json_error(404, "unknown endpoint")
    return True


def _admin_get(handler, raw: str, user: dict) -> bool:
    del user
    if raw in ("/api/admin/overview", "/api/admin/overview/"):
        handler._json_response(200, admin_api.overview())
        return True
    if raw in ("/api/admin/documents", "/api/admin/documents/"):
        handler._json_response(200, admin_api.document_list())
        return True
    match = re.fullmatch(r"/api/admin/documents/([^/]+)", raw)
    if match:
        status, payload = admin_api.document_detail(match.group(1))
        handler._json_response(status, payload)
        return True
    if raw in ("/api/admin/handoffs", "/api/admin/handoffs/"):
        handler._json_response(200, admin_api.handoff_board())
        return True
    if raw in ("/api/admin/faq-check", "/api/admin/faq-check/"):
        handler._json_response(200, admin_api.faq_check())
        return True
    if raw in ("/api/admin/feedback", "/api/admin/feedback/"):
        kind = _query_value(handler, "helpful")
        handler._json_response(200, {**admin_api.feedback_rows(kind), "summary": admin_api.feedback_summary()})
        return True
    if raw in ("/api/admin/feedback.csv",):
        kind = _query_value(handler, "helpful")
        body = admin_api.feedback_csv(kind).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/csv; charset=utf-8")
        handler.send_header("Content-Disposition", "attachment; filename=feedback.csv")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    if raw in ("/api/admin/probe", "/api/admin/probe/"):
        probe = campus_engine.current_probe() if uses_qut() else store.latest_probe()
        handler._json_response(200, {"ok": True, "probe": probe})
        return True
    if raw in ("/api/admin/audit", "/api/admin/audit/"):
        kind, decision, query = _filters(handler)
        handler._json_response(200, admin_api.audit_rows(kind, decision, query))
        return True
    if raw in ("/api/admin/audit.csv",):
        kind, decision, query = _filters(handler)
        body = admin_api.audit_csv(kind, decision, query).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/csv; charset=utf-8")
        handler.send_header("Content-Disposition", "attachment; filename=audit.csv")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    if raw in ("/api/admin/config", "/api/admin/config/"):
        handler._json_response(200, admin_api.current_config())
        return True
    if raw in ("/api/admin/datasets", "/api/admin/datasets/"):
        handler._json_response(200, admin_api.dataset_cards())
        return True
    if raw in ("/api/admin/eval", "/api/admin/eval/"):
        handler._json_response(200, admin_api.eval_status())
        return True
    match = re.fullmatch(r"/api/admin/eval/export\.(md|csv)", raw)
    if match:
        group, dataset = "C", "test"
        if "?" in handler.path:
            for part in handler.path.split("?", 1)[1].split("&"):
                if part.startswith("group="):
                    group = part.split("=", 1)[1][:1].upper() or "C"
                if part.startswith("dataset="):
                    dataset = part.split("=", 1)[1][:40]
        status, ctype, body = admin_api.export_result(group, dataset, match.group(1))
        raw_body = body.encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", ctype)
        if status == 200:
            filename = f"eval-{group}-{dataset}.{match.group(1)}"
            handler.send_header("Content-Disposition", f"attachment; filename={filename}")
        handler.send_header("Content-Length", str(len(raw_body)))
        handler.end_headers()
        handler.wfile.write(raw_body)
        return True
    handler._json_error(404, "unknown endpoint")
    return True


def _admin_post(handler, path: str, user: dict) -> bool:
    if path == "/api/admin/feedback/bad-case":
        try:
            data = handler._read_json()
        except ValueError as exc:
            handler._json_error(400, str(exc))
            return True
        try:
            message_id = int(data.get("message_id"))
        except (TypeError, ValueError):
            handler._json_error(400, "缺少要加入的回答")
            return True
        status, payload = admin_api.promote_feedback(user, message_id, str(data.get("kind") or ""))
        handler._json_response(status, payload)
        return True
    if path == "/api/admin/documents":
        _upload(handler, user)
        return True
    if path == "/api/admin/documents/reseed":
        status, payload = admin_api.reimport_sample(user)
        handler._json_response(status, payload)
        return True
    if path == "/api/admin/segments":
        _save_segment(handler, user, "")
        return True
    match = re.fullmatch(r"/api/admin/segments/([^/]+)", path)
    if match:
        _save_segment(handler, user, match.group(1))
        return True
    if path == "/api/admin/embeddings":
        status, payload = admin_api.rebuild_embeddings(user)
        handler._json_response(status, payload)
        return True
    if path == "/api/admin/probe":
        handler._json_response(200, {"ok": True, "probe": admin_api.probe_now(user)})
        return True
    if path == "/api/admin/config":
        try:
            data = handler._read_json()
        except ValueError as exc:
            handler._json_error(400, str(exc))
            return True
        status, payload = admin_api.update_config(data.get("config") if isinstance(data.get("config"), dict) else data, user)
        handler._json_response(status, payload)
        return True
    if path == "/api/admin/eval/run":
        try:
            data = handler._read_json()
        except ValueError as exc:
            handler._json_error(400, str(exc))
            return True
        try:
            limit = int(data.get("limit") or 0)
        except (TypeError, ValueError):
            limit = 0
        status, payload = admin_api.start_eval(str(data.get("dataset") or "test"), str(data.get("group") or "A"), limit=limit)
        handler._json_response(status, payload)
        return True
    handler._json_error(404, "unknown endpoint")
    return True


def _save_segment(handler, user: dict, segment_id: str) -> None:
    try:
        data = handler._read_json()
    except ValueError as exc:
        handler._json_error(400, str(exc))
        return
    status, payload = admin_api.save_segment(
        user,
        segment_id,
        str(data.get("title") or ""),
        str(data.get("body") or ""),
        str(data.get("document_id") or ""),
    )
    handler._json_response(status, payload)


def _upload(handler, user: dict) -> None:
    length = int(handler.headers.get("Content-Length") or 0)
    if length > 16 * 1024 * 1024:
        handler._json_error(400, "单个文件不能超过 15MB")
        return
    raw = handler.rfile.read(length) if length else b""
    ctype = handler.headers.get("Content-Type") or ""
    if "multipart/form-data" not in ctype:
        handler._json_error(400, "请用表单上传文件")
        return
    parsed = _multipart(ctype, raw)
    upload = parsed.get("file")
    if not upload:
        handler._json_error(400, "没有收到文件")
        return
    status, payload = admin_api.add_document(upload["filename"], upload["data"], user, parsed.get("audience", "student"))
    handler._json_response(status, payload)


def _multipart(content_type: str, body: bytes) -> dict:
    match = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', content_type)
    if not match:
        return {}
    boundary = (match.group(1) or match.group(2)).strip().encode("utf-8")
    found = {}
    for part in body.split(b"--" + boundary):
        if b"Content-Disposition" not in part:
            continue
        header, _, data = part.partition(b"\r\n\r\n")
        data = data.rstrip(b"\r\n")
        if data.endswith(b"--"):
            data = data[:-2].rstrip(b"\r\n")
        text = header.decode("utf-8", "replace")
        name_match = re.search(r'name="([^"]+)"', text)
        file_match = re.search(r'filename="([^"]*)"', text)
        if not name_match:
            continue
        if file_match and file_match.group(1):
            found[name_match.group(1)] = {"filename": file_match.group(1), "data": data}
        elif name_match.group(1) == "audience":
            found["audience"] = data.decode("utf-8", "replace").strip()[:20]
    return found


def _query_value(handler, name: str) -> str:
    if "?" not in handler.path:
        return ""
    for part in handler.path.split("?", 1)[1].split("&"):
        if part.startswith(name + "="):
            return unquote(part.split("=", 1)[1])
    return ""


def _query_cursor(handler, name: str = "after") -> int | None:
    try:
        return max(0, min(int(_query_value(handler, name)), 2**63 - 1))
    except ValueError:
        return None


def _filters(handler) -> tuple[str, str, str]:
    kind = decision = query = ""
    if "?" in handler.path:
        for part in handler.path.split("?", 1)[1].split("&"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            value = unquote(value)
            if key == "kind":
                kind = value
            elif key == "decision":
                decision = value
            elif key == "q":
                query = value
    return kind, decision, query


def _public_user(user: dict) -> dict:
    return {
        "username": user["username"],
        "role": user["role"],
        "display_name": user["display_name"],
        "user_id": user["user_id"],
    }


def _ollama_status() -> str:
    try:
        req = Request(ollama_host().rstrip("/") + "/api/tags")
        with urlopen(req, timeout=0.4) as resp:
            return "up" if resp.status == 200 else "down"
    except Exception:  # noqa: BLE001
        return "down"


def retired_page(handler, raw: str) -> bool:
    return uses_qut() and Path(handler.translate_path(raw)).name.lower() in ("agent", "agent.html", "agent.js")


def page_guard(handler, raw: str) -> bool:
    """Return True when the request was already answered."""
    if raw in ("/login", "/login/", "/login.html"):
        handler.path = "/login.html"
        return False
    needs_admin = raw in ("/admin", "/admin/", "/admin.html")
    needs_agent = raw in ("/agent", "/agent/", "/agent.html")
    if not needs_admin and not needs_agent:
        return False
    user = current_user(handler)
    if not user:
        target = "/admin" if needs_admin else "/agent"
        _redirect(handler, "/login?next=" + target)
        return True
    if needs_admin and user["role"] != "admin":
        body = "这个页面需要管理员账号。".encode("utf-8")
        handler.send_response(403)
        handler.send_header("Content-Type", "text/plain; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
        return True
    handler.path = "/admin.html" if needs_admin else "/agent.html"
    return False


def _redirect(handler, location: str) -> None:
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Content-Length", "0")
    handler.end_headers()
