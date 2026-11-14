"""HTTP routes for login, the portal thread, the staff desk, and admin."""
from __future__ import annotations

import re
from urllib.parse import unquote
from urllib.request import Request, urlopen

import admin_api
import agent_api
import auth
from auth import SESSION_COOKIE, cookie_header, current_user, ensure_visitor, require_user, safe_next
from dify_client import dataset_configured
from gateway import _handoff_source
from masking import mask_text
from settings import dify_app_key, ollama_host
import store


def try_get(handler, raw: str) -> bool:
    if raw in ("/api/me", "/api/me/"):
        user = current_user(handler)
        if not user:
            handler._json_response(401, {"ok": False, "error": "请先登录"})
            return True
        handler._json_response(200, {"ok": True, "user": _public_user(user)})
        return True
    if raw in ("/api/portal/state", "/api/portal/state/"):
        _portal_state(handler)
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
    if path == "/api/login":
        _login(handler)
        return True
    if path == "/api/logout":
        auth.logout(handler)
        handler._json_response(200, {"ok": True})
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
    if not match:
        return False
    user = require_user(handler, ("admin",))
    if not user:
        return True
    status, payload = admin_api.remove_document(match.group(1), user)
    handler._json_response(status, payload)
    return True


def health_payload() -> dict:
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


def create_portal_ticket(handler, subject: str, detail: str, contact: str, portal_session: str) -> None:
    visitor = ensure_visitor(handler)
    masked_subject, _a = mask_text(subject)
    masked_detail, _b = mask_text(detail)
    masked_contact, _c = mask_text(contact)
    question = masked_subject or masked_detail or "转人工"
    source = _handoff_source(visitor, portal_session)
    ticket = store.create_ticket(visitor, portal_session, source, question)
    if masked_detail:
        store.add_message(visitor, "user", masked_detail, portal_session, ticket["id"], meta={"contact": masked_contact})
    store.add_audit("ticket", actor="访客", session_ref=ticket["public_id"], decision="登记", question=question)
    handler._json_response(
        200,
        {
            "ok": True,
            "ticket_id": ticket["public_id"],
            "queue": True,
            "message": f"已登记工单 {ticket['public_id']}。坐席上线后会在这个窗口回复，不承诺具体时间。",
        },
    )


def _login(handler) -> None:
    try:
        data = handler._read_json()
    except ValueError as exc:
        handler._json_error(400, str(exc))
        return
    result = auth.login(str(data.get("username") or ""), str(data.get("password") or ""))
    status = result.pop("status")
    if result.get("ok"):
        target = safe_next(str(data.get("next") or ""), result["role"])
        result["redirect"] = target
        handler._set_cookies = getattr(handler, "_set_cookies", [])
        handler._set_cookies.append(cookie_header(SESSION_COOKIE, result.pop("token"), 60 * 60 * 12))
    handler._json_response(status, result)


def _portal_state(handler) -> None:
    visitor = ensure_visitor(handler)
    session = ""
    if "?" in handler.path:
        query = handler.path.split("?", 1)[1]
        for part in query.split("&"):
            if part.startswith("session="):
                session = part.split("=", 1)[1][:80]
    probe = store.latest_probe()
    maintenance = bool(probe and not probe.get("ok"))
    ticket = store.open_ticket(visitor, session) if session else None
    rows = store.list_messages(visitor=visitor, portal_session=session) if session else []
    visible = [row for row in rows if row["role"] in ("agent", "system")]
    handler._json_response(
        200,
        {
            "ok": True,
            "maintenance": maintenance,
            "probe_ok": None if probe is None else bool(probe.get("ok")),
            "ticket": None
            if not ticket
            else {
                "public_id": ticket["public_id"],
                "status": ticket["status"],
                "assignee_name": ticket.get("assignee_name") or "",
            },
            "messages": [
                {
                    "id": row["id"],
                    "role": row["role"],
                    "author": row.get("author") or "",
                    "body": row.get("body") or "",
                    "created_at": row.get("created_at") or "",
                }
                for row in visible[-40:]
            ],
        },
    )


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
        status, payload = agent_api.detail(match.group(1))
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
    if raw in ("/api/admin/documents", "/api/admin/documents/"):
        handler._json_response(200, admin_api.document_list())
        return True
    if raw in ("/api/admin/probe", "/api/admin/probe/"):
        probe = store.latest_probe()
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
    if path == "/api/admin/documents":
        _upload(handler, user)
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
    status, payload = admin_api.add_document(upload["filename"], upload["data"], user)
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
    return found


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
