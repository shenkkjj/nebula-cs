"""SQLite persistence for tickets, audit, sessions, and probe state.

The database file lives under DATA_DIR and is not committed.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from passwords import hash_password
from settings import data_dir

_LOCK = threading.RLock()
_CONN: sqlite3.Connection | None = None
_PATH: str | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL,
  display_name TEXT NOT NULL,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS visitors (
  token TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY,
  public_id TEXT UNIQUE NOT NULL,
  visitor_token TEXT NOT NULL,
  portal_session TEXT,
  status TEXT NOT NULL,
  source TEXT NOT NULL,
  first_question TEXT NOT NULL,
  assignee_id INTEGER,
  assignee_name TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  taken_at TEXT,
  closed_at TEXT,
  close_note TEXT
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY,
  ticket_id INTEGER,
  visitor_token TEXT NOT NULL,
  portal_session TEXT,
  role TEXT NOT NULL,
  author TEXT,
  body TEXT NOT NULL,
  meta_json TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS judgments (
  id INTEGER PRIMARY KEY,
  visitor_token TEXT,
  portal_session TEXT,
  ticket_id INTEGER,
  message_id INTEGER,
  question_masked TEXT,
  rewritten TEXT,
  decision TEXT,
  reason TEXT,
  trace_json TEXT,
  latency_ms INTEGER,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  kind TEXT NOT NULL,
  actor TEXT,
  session_ref TEXT,
  question TEXT,
  decision TEXT,
  source TEXT,
  latency_ms INTEGER,
  detail_json TEXT
);
CREATE TABLE IF NOT EXISTS probe_runs (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  ok INTEGER NOT NULL,
  checks_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS writebacks (
  id INTEGER PRIMARY KEY,
  ticket_id INTEGER,
  actor TEXT,
  question TEXT NOT NULL,
  answer TEXT NOT NULL,
  status TEXT NOT NULL,
  dify_document_id TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_file() -> Path:
    return data_dir() / "nebula.sqlite"


def reconnect() -> None:
    """Drop the cached connection so a new DATA_DIR takes effect."""
    global _CONN, _PATH
    with _LOCK:
        if _CONN is not None:
            _CONN.close()
        _CONN = None
        _PATH = None


def connection() -> sqlite3.Connection:
    global _CONN, _PATH
    path = str(db_file())
    with _LOCK:
        if _CONN is not None and _PATH == path:
            return _CONN
        if _CONN is not None:
            _CONN.close()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        _seed(conn)
        _CONN = conn
        _PATH = path
        return conn


def _seed(conn: sqlite3.Connection) -> None:
    demo = (
        ("admin", "admin123", "admin", "陈老师"),
        ("agent1", "agent123", "agent", "王老师"),
    )
    for username, password, role, display in demo:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row:
            continue
        conn.execute(
            "INSERT INTO users (username, password_hash, role, display_name) VALUES (?, ?, ?, ?)",
            (username, hash_password(password), role, display),
        )
    conn.commit()


def _one(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return dict(row)


def create_visitor(token: str) -> None:
    with _LOCK:
        conn = connection()
        conn.execute(
            "INSERT OR IGNORE INTO visitors (token, created_at) VALUES (?, ?)",
            (token, now()),
        )
        conn.commit()


def visitor_exists(token: str) -> bool:
    with _LOCK:
        row = connection().execute("SELECT token FROM visitors WHERE token = ?", (token,)).fetchone()
    return row is not None


def get_user_by_name(username: str) -> dict | None:
    with _LOCK:
        row = connection().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return _one(row)


def get_user(user_id: int) -> dict | None:
    with _LOCK:
        row = connection().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _one(row)


def mark_login_failure(user_id: int, attempts: int, locked_until: str | None) -> None:
    with _LOCK:
        conn = connection()
        conn.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, locked_until, user_id),
        )
        conn.commit()


def mark_login_success(user_id: int) -> None:
    with _LOCK:
        conn = connection()
        conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
            (user_id,),
        )
        conn.commit()


def create_session(token: str, user_id: int, hours: int = 12) -> None:
    created = datetime.now(timezone.utc).replace(microsecond=0)
    expires = (created + timedelta(hours=hours)).isoformat()
    with _LOCK:
        conn = connection()
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, created.isoformat(), expires),
        )
        conn.commit()


def get_session(token: str) -> dict | None:
    with _LOCK:
        row = connection().execute(
            """
            SELECT sessions.token, sessions.expires_at, users.id AS user_id, users.username,
                   users.role, users.display_name
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()
    if row is None:
        return None
    if row["expires_at"] <= now():
        delete_session(token)
        return None
    return dict(row)


def delete_session(token: str) -> None:
    with _LOCK:
        conn = connection()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def _next_public_id(conn: sqlite3.Connection) -> str:
    day = datetime.now().astimezone().strftime("%Y%m%d")
    prefix = f"TK{day}-"
    row = conn.execute(
        "SELECT public_id FROM tickets WHERE public_id LIKE ? ORDER BY public_id DESC LIMIT 1",
        (prefix + "%",),
    ).fetchone()
    number = 1
    if row:
        try:
            number = int(str(row["public_id"]).rsplit("-", 1)[-1]) + 1
        except ValueError:
            number = 1
    return f"{prefix}{number:04d}"


def create_ticket(visitor: str, portal_session: str, source: str, question: str) -> dict:
    with _LOCK:
        conn = connection()
        public_id = _next_public_id(conn)
        stamp = now()
        cur = conn.execute(
            """
            INSERT INTO tickets (
              public_id, visitor_token, portal_session, status, source, first_question,
              created_at, updated_at
            ) VALUES (?, ?, ?, 'waiting', ?, ?, ?, ?)
            """,
            (public_id, visitor, portal_session or "", source, question[:500], stamp, stamp),
        )
        ticket_id = cur.lastrowid
        conn.execute(
            """
            UPDATE messages SET ticket_id = ?
            WHERE visitor_token = ? AND portal_session = ? AND ticket_id IS NULL
            """,
            (ticket_id, visitor, portal_session or ""),
        )
        conn.commit()
    ticket = get_ticket(public_id)
    return ticket or {"public_id": public_id, "id": ticket_id}


def get_ticket(public_id: str) -> dict | None:
    with _LOCK:
        row = connection().execute("SELECT * FROM tickets WHERE public_id = ?", (public_id,)).fetchone()
    return _one(row)


def get_ticket_by_id(ticket_id: int) -> dict | None:
    with _LOCK:
        row = connection().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _one(row)


def open_ticket(visitor: str, portal_session: str) -> dict | None:
    with _LOCK:
        row = connection().execute(
            """
            SELECT * FROM tickets
            WHERE visitor_token = ? AND portal_session = ? AND status IN ('waiting', 'active')
            ORDER BY id DESC LIMIT 1
            """,
            (visitor, portal_session or ""),
        ).fetchone()
    return _one(row)


def list_tickets(status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM tickets"
    args: tuple = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY updated_at DESC, id DESC"
    with _LOCK:
        rows = connection().execute(sql, args).fetchall()
    items = []
    current = datetime.now(timezone.utc)
    for row in rows:
        item = dict(row)
        try:
            created = datetime.fromisoformat(item["created_at"])
            item["wait_seconds"] = max(0, int((current - created).total_seconds()))
        except ValueError:
            item["wait_seconds"] = 0
        if item.get("taken_at"):
            try:
                taken = datetime.fromisoformat(item["taken_at"])
                item["active_seconds"] = max(0, int((current - taken).total_seconds()))
            except ValueError:
                item["active_seconds"] = 0
        else:
            item["active_seconds"] = 0
        items.append(item)
    return items


def ticket_counts() -> dict:
    with _LOCK:
        rows = connection().execute(
            "SELECT status, COUNT(*) AS n FROM tickets GROUP BY status"
        ).fetchall()
    counts = {"waiting": 0, "active": 0, "closed": 0}
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] = row["n"]
    return counts


def update_ticket(public_id: str, **fields) -> dict | None:
    allowed = {
        "status",
        "assignee_id",
        "assignee_name",
        "taken_at",
        "closed_at",
        "close_note",
        "updated_at",
    }
    sets = []
    values = []
    for key, value in fields.items():
        if key in allowed:
            sets.append(f"{key} = ?")
            values.append(value)
    if not sets:
        return get_ticket(public_id)
    if "updated_at" not in fields:
        sets.append("updated_at = ?")
        values.append(now())
    values.append(public_id)
    with _LOCK:
        conn = connection()
        conn.execute(f"UPDATE tickets SET {', '.join(sets)} WHERE public_id = ?", values)
        conn.commit()
    return get_ticket(public_id)


def add_message(
    visitor: str,
    role: str,
    body: str,
    portal_session: str = "",
    ticket_id: int | None = None,
    author: str = "",
    meta: dict | None = None,
) -> int:
    with _LOCK:
        conn = connection()
        cur = conn.execute(
            """
            INSERT INTO messages (
              ticket_id, visitor_token, portal_session, role, author, body, meta_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket_id,
                visitor,
                portal_session or "",
                role,
                author,
                body,
                json.dumps(meta or {}, ensure_ascii=False),
                now(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_message(message_id: int) -> dict | None:
    with _LOCK:
        row = connection().execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    if row is None:
        return None
    item = dict(row)
    try:
        item["meta"] = json.loads(item.pop("meta_json") or "{}")
    except json.JSONDecodeError:
        item["meta"] = {}
    return item


def list_messages(
    ticket_id: int | None = None,
    visitor: str | None = None,
    portal_session: str | None = None,
    since_id: int = 0,
) -> list[dict]:
    clauses = ["id > ?"]
    args: list = [since_id]
    if ticket_id is not None:
        clauses.append("ticket_id = ?")
        args.append(ticket_id)
    if visitor is not None:
        clauses.append("visitor_token = ?")
        args.append(visitor)
    if portal_session is not None:
        clauses.append("portal_session = ?")
        args.append(portal_session)
    sql = f"SELECT * FROM messages WHERE {' AND '.join(clauses)} ORDER BY id ASC"
    with _LOCK:
        rows = connection().execute(sql, args).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["meta"] = json.loads(item.pop("meta_json") or "{}")
        except json.JSONDecodeError:
            item["meta"] = {}
        items.append(item)
    return items


def add_judgment(
    visitor: str,
    portal_session: str,
    question: str,
    rewritten: str,
    decision: str,
    reason: str,
    trace: list,
    latency_ms: int,
    ticket_id: int | None = None,
    message_id: int | None = None,
) -> int:
    with _LOCK:
        conn = connection()
        cur = conn.execute(
            """
            INSERT INTO judgments (
              visitor_token, portal_session, ticket_id, message_id, question_masked, rewritten,
              decision, reason, trace_json, latency_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                visitor,
                portal_session or "",
                ticket_id,
                message_id,
                question[:500],
                rewritten[:500],
                decision,
                reason,
                json.dumps(trace, ensure_ascii=False),
                int(latency_ms),
                now(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_judgments(ticket_id: int | None = None, visitor: str | None = None) -> list[dict]:
    clauses = []
    args: list = []
    if ticket_id is not None:
        clauses.append("ticket_id = ?")
        args.append(ticket_id)
    if visitor is not None:
        clauses.append("visitor_token = ?")
        args.append(visitor)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _LOCK:
        rows = connection().execute(
            f"SELECT * FROM judgments {where} ORDER BY id ASC",
            args,
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["trace"] = json.loads(item.pop("trace_json") or "[]")
        except json.JSONDecodeError:
            item["trace"] = []
        items.append(item)
    return items


def add_audit(
    kind: str,
    actor: str = "",
    session_ref: str = "",
    question: str = "",
    decision: str = "",
    source: str = "",
    latency_ms: int | None = None,
    detail: dict | None = None,
) -> int:
    with _LOCK:
        conn = connection()
        cur = conn.execute(
            """
            INSERT INTO audit_log (
              created_at, kind, actor, session_ref, question, decision, source, latency_ms, detail_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now(),
                kind,
                actor,
                session_ref,
                question[:500],
                decision,
                source,
                latency_ms,
                json.dumps(detail or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_audit(
    kind: str = "",
    decision: str = "",
    query: str = "",
    limit: int = 100,
) -> list[dict]:
    clauses = []
    args: list = []
    if kind and kind != "全部":
        clauses.append("kind = ?")
        args.append(kind)
    if decision and decision != "全部":
        clauses.append("decision LIKE ?")
        args.append(f"%{decision}%")
    if query:
        clauses.append("(question LIKE ? OR session_ref LIKE ? OR actor LIKE ?)")
        like = f"%{query}%"
        args.extend([like, like, like])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(max(1, min(limit, 500)))
    with _LOCK:
        rows = connection().execute(
            f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?",
            args,
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        try:
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
        except json.JSONDecodeError:
            item["detail"] = {}
        items.append(item)
    return items


def save_probe(ok: bool, checks: list) -> dict:
    stamp = now()
    with _LOCK:
        conn = connection()
        conn.execute(
            "INSERT INTO probe_runs (created_at, ok, checks_json) VALUES (?, ?, ?)",
            (stamp, 1 if ok else 0, json.dumps(checks, ensure_ascii=False)),
        )
        conn.commit()
    return {"ok": ok, "checked_at": stamp, "checks": checks}


def latest_probe() -> dict | None:
    with _LOCK:
        row = connection().execute(
            "SELECT * FROM probe_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    try:
        checks = json.loads(row["checks_json"] or "[]")
    except json.JSONDecodeError:
        checks = []
    return {"ok": bool(row["ok"]), "checked_at": row["created_at"], "checks": checks}


def add_writeback(ticket_id: int | None, actor: str, question: str, answer: str, status: str) -> dict:
    stamp = now()
    with _LOCK:
        conn = connection()
        cur = conn.execute(
            """
            INSERT INTO writebacks (
              ticket_id, actor, question, answer, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ticket_id, actor, question, answer, status, stamp, stamp),
        )
        conn.commit()
        row_id = int(cur.lastrowid)
    return get_writeback(row_id) or {"id": row_id, "status": status}


def update_writeback(row_id: int, status: str, dify_document_id: str = "", error: str = "") -> dict | None:
    with _LOCK:
        conn = connection()
        conn.execute(
            """
            UPDATE writebacks
            SET status = ?, dify_document_id = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, dify_document_id, error[:400], now(), row_id),
        )
        conn.commit()
    return get_writeback(row_id)


def get_writeback(row_id: int) -> dict | None:
    with _LOCK:
        row = connection().execute("SELECT * FROM writebacks WHERE id = ?", (row_id,)).fetchone()
    return _one(row)
