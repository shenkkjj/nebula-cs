"""Session cookies for staff and admin. Portal visitors stay anonymous."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from passwords import verify_password
import store

SESSION_COOKIE = "nebula_session"
VISITOR_COOKIE = "nebula_visitor"
LOCK_MINUTES = 5
LOCK_AFTER = 5


def parse_cookies(header: str | None) -> dict[str, str]:
    found: dict[str, str] = {}
    for part in (header or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        found[key.strip()] = value.strip()
    return found


def cookie_header(name: str, value: str, max_age: int) -> str:
    return f"{name}={value}; HttpOnly; Path=/; SameSite=Lax; Max-Age={max_age}"


def clear_cookie(name: str) -> str:
    return f"{name}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0"


def ensure_visitor(handler) -> str:
    cookies = parse_cookies(handler.headers.get("Cookie"))
    token = cookies.get(VISITOR_COOKIE)
    if token and store.visitor_exists(token):
        return token
    token = secrets.token_urlsafe(24)
    store.create_visitor(token)
    pending = getattr(handler, "_set_cookies", None)
    if pending is None:
        handler._set_cookies = []
        pending = handler._set_cookies
    pending.append(cookie_header(VISITOR_COOKIE, token, 60 * 60 * 24 * 30))
    return token


def current_user(handler) -> dict | None:
    cookies = parse_cookies(handler.headers.get("Cookie"))
    token = cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return store.get_session(token)


def require_user(handler, roles: tuple[str, ...]) -> dict | None:
    user = current_user(handler)
    if not user:
        handler._json_response(401, {"ok": False, "error": "请先登录"})
        return None
    if user["role"] not in roles:
        handler._json_response(403, {"ok": False, "error": "需要管理员权限" if "admin" in roles and "agent" not in roles else "没有权限"})
        return None
    return user


def login(username: str, password: str) -> dict:
    name = (username or "").strip()
    user = store.get_user_by_name(name) if name else None
    if user and user.get("locked_until") and str(user["locked_until"]) > store.now():
        store.add_audit("login", actor=name, decision="锁定", detail={"ok": False})
        return {"ok": False, "status": 429, "error": "已连续输错 5 次，请 5 分钟后再试。"}
    if user is None or not verify_password(password or "", user["password_hash"]):
        if user is not None:
            attempts = int(user.get("failed_attempts") or 0) + 1
            locked = None
            if attempts >= LOCK_AFTER:
                locked = (datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)).replace(microsecond=0).isoformat()
            store.mark_login_failure(user["id"], attempts, locked)
            if attempts >= LOCK_AFTER:
                store.add_audit("login", actor=name or "未知", decision="锁定", detail={"ok": False})
                return {"ok": False, "status": 429, "error": "已连续输错 5 次，请 5 分钟后再试。"}
        store.add_audit("login", actor=name or "未知", decision="失败", detail={"ok": False})
        return {"ok": False, "status": 401, "error": "账号或密码不对"}
    store.mark_login_success(user["id"])
    token = secrets.token_urlsafe(32)
    store.create_session(token, user["id"])
    store.add_audit("login", actor=user["username"], decision="成功", detail={"role": user["role"]})
    return {
        "ok": True,
        "status": 200,
        "token": token,
        "role": user["role"],
        "display_name": user["display_name"],
        "username": user["username"],
    }


def logout(handler) -> None:
    cookies = parse_cookies(handler.headers.get("Cookie"))
    token = cookies.get(SESSION_COOKIE)
    user = store.get_session(token) if token else None
    if token:
        store.delete_session(token)
    if user:
        store.add_audit("logout", actor=user["username"], decision="退出")
    pending = getattr(handler, "_set_cookies", None)
    if pending is None:
        handler._set_cookies = []
        pending = handler._set_cookies
    pending.append(clear_cookie(SESSION_COOKIE))


def safe_next(next_path: str, role: str) -> str:
    path = (next_path or "").strip()
    if not path.startswith("/") or path.startswith("//"):
        path = "/admin" if role == "admin" else "/agent"
    if role == "agent" and path.startswith("/admin"):
        return "/agent"
    if path.startswith("/agent") or path.startswith("/admin"):
        return path
    return "/admin" if role == "admin" else "/agent"
