"""SQLite knowledge base: documents, FAQ segments, and optional vectors.

The active preset is imported once into the database. Later edits, uploads,
and deletions stay. Vector rows, when remote embeddings are configured, live
in an embedded Chroma index under the same DATA_DIR. There is no second
database server. The lexical index does not read Chroma.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import chroma_store
from campus_profile import ARTICLES, ARTICLE_BY_TITLE, AUDIENCES, profile, scope
from lite_engine import Chunk, load_chunks
import store

_REV = 0
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_NUMBER_RE = re.compile(r"^\d+\.\s*")
_PDF_STRING_RE = re.compile(r"\(((?:\\.|[^\\)]){1,400})\)")
_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MAX_SEGMENTS = 400
_MAX_BODY = 8000
_MAX_TITLE = 180
SAMPLE_NAME = "客服样例FAQ.md"


def revision() -> tuple[str, int]:
    return str(store.db_file()), _REV


def _bump() -> None:
    global _REV
    _REV += 1


def _now() -> str:
    return store.now()


def ensure_seeded() -> None:
    """Seed only the selected profile, preserving existing documents and edits."""
    demo = profile() == "demo"
    key = "seeded" if demo else "seeded_qut_v1"
    with store.exclusive() as conn:
        if conn.execute("SELECT 1 FROM kb_meta WHERE key = ?", (key,)).fetchone():
            return
        if demo:
            _insert_sample(conn)
        else:
            _insert_presets(conn)
        conn.execute("INSERT INTO kb_meta (key, value) VALUES (?, '1')", (key,))
    _bump()


def _insert_presets(conn) -> int:
    stamp = _now()
    added = 0
    for item in ARTICLES:
        doc = conn.execute(
            "SELECT id FROM kb_documents WHERE source = 'preset' AND name = ? AND audience = ? AND source_url = ?",
            (item.source, item.audience, item.url),
        ).fetchone()
        if doc is None:
            cur = conn.execute(
                """
                INSERT INTO kb_documents (name, source, audience, source_url, status, created_at, updated_at)
                VALUES (?, 'preset', ?, ?, '已索引', ?, ?)
                """,
                (item.source, item.audience, item.url, stamp, stamp),
            )
            document_id = int(cur.lastrowid)
        else:
            document_id = int(doc["id"])
        if conn.execute(
            "SELECT id FROM kb_segments WHERE document_id = ? AND title = ? AND enabled = 1",
            (document_id, item.title),
        ).fetchone():
            continue
        position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM kb_segments WHERE document_id = ?", (document_id,),
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO kb_segments (document_id, title, body, position, enabled, updated_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (document_id, item.title, item.answer, position, stamp),
        )
        added += 1
    return added


def _insert_sample(conn) -> int:
    stamp = _now()
    cur = conn.execute(
        """
        INSERT INTO kb_documents (name, source, status, created_at, updated_at)
        VALUES (?, 'seed', '已索引', ?, ?)
        """,
        (SAMPLE_NAME, stamp, stamp),
    )
    document_id = int(cur.lastrowid)
    for position, chunk in enumerate(load_chunks()):
        conn.execute(
            """
            INSERT INTO kb_segments (document_id, title, body, position, enabled, updated_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (document_id, chunk.title[:_MAX_TITLE], chunk.answer[:_MAX_BODY], position, stamp),
        )
    return document_id


def reimport_sample() -> dict:
    """Restore missing entries from the current preset."""
    ensure_seeded()
    if profile() != "demo":
        with store.exclusive() as conn:
            count = _insert_presets(conn)
        if count:
            _bump()
        return {"ok": True, "already": count == 0, "count": count}
    with store.exclusive() as conn:
        row = conn.execute(
            "SELECT id FROM kb_documents WHERE name = ? AND source = 'seed' ORDER BY id ASC LIMIT 1",
            (SAMPLE_NAME,),
        ).fetchone()
        if row is not None:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM kb_segments WHERE document_id = ? AND enabled = 1",
                (row["id"],),
            ).fetchone()["n"]
            if count:
                return {"ok": True, "already": True, "id": str(row["id"])}
            ids = [
                int(item["id"])
                for item in conn.execute(
                    "SELECT id FROM kb_segments WHERE document_id = ?",
                    (row["id"],),
                )
            ]
            _drop_vectors(conn, ids)
            conn.execute("DELETE FROM kb_segments WHERE document_id = ?", (row["id"],))
            conn.execute("DELETE FROM kb_documents WHERE id = ?", (row["id"],))
        document_id = _insert_sample(conn)
    _bump()
    return {"ok": True, "already": False, "id": str(document_id)}


def _profile_audiences() -> tuple[str, ...]:
    return ("demo",) * 3 if profile() == "demo" else AUDIENCES


def stats() -> dict:
    ensure_seeded()
    audiences = _profile_audiences()
    with store.exclusive() as conn:
        documents = conn.execute(
            "SELECT COUNT(*) AS n FROM kb_documents WHERE audience IN (?, ?, ?)", audiences,
        ).fetchone()["n"]
        segments = conn.execute(
            """
            SELECT COUNT(*) AS n FROM kb_segments s JOIN kb_documents d ON d.id = s.document_id
            WHERE s.enabled = 1 AND d.audience IN (?, ?, ?)
            """,
            audiences,
        ).fetchone()["n"]
        vectors = conn.execute("SELECT COUNT(*) AS n FROM kb_vectors").fetchone()["n"]
    return {
        "documents": int(documents),
        "segments": int(segments),
        "vectors": _vector_total(int(vectors)),
    }


def list_documents() -> list[dict]:
    ensure_seeded()
    with store.exclusive() as conn:
        rows = conn.execute(
            """
            SELECT d.id, d.name, d.source, d.audience, d.source_url, d.status, d.created_at, d.updated_at,
                   COUNT(s.id) AS segment_count
            FROM kb_documents d
            LEFT JOIN kb_segments s ON s.document_id = d.id AND s.enabled = 1
            GROUP BY d.id
            ORDER BY d.id ASC
            """
        ).fetchall()
    return [_public_document(row) for row in rows]


def get_document(document_id: str | int) -> dict | None:
    ensure_seeded()
    try:
        number = int(document_id)
    except (TypeError, ValueError):
        return None
    with store.exclusive() as conn:
        row = conn.execute("SELECT * FROM kb_documents WHERE id = ?", (number,)).fetchone()
        if row is None:
            return None
        segments = conn.execute(
            """
            SELECT id, title, body, position, enabled, updated_at
            FROM kb_segments WHERE document_id = ? ORDER BY position ASC, id ASC
            """,
            (number,),
        ).fetchall()
    payload = _public_document(row)
    payload["segments"] = [_public_segment(item) for item in segments]
    payload["segment_count"] = sum(1 for item in segments if item["enabled"])
    return payload


def add_upload(filename: str, data: bytes, source: str = "upload", audience: str = "student") -> dict:
    name = Path(filename or "").name
    suffix = Path(name).suffix.lower()
    if suffix in (".md", ".txt"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("文本文件需要是 UTF-8") from exc
    elif suffix == ".docx":
        text = _docx_text(data)
    elif suffix == ".pdf":
        text = _pdf_text(data)
    else:
        raise ValueError("只接受 md、txt、pdf、docx")
    return add_text_document(name, text, source=source, audience=audience)


def add_text_document(name: str, text: str, source: str = "upload", audience: str = "student") -> dict:
    if profile() == "demo":
        audience = "demo"
    elif audience not in AUDIENCES:
        raise ValueError("请选择适用对象：学生、教职工或通用")
    ensure_seeded()
    segments = split_segments(name, text)
    if not segments:
        raise ValueError("文件里没有可以索引的文字")
    stamp = _now()
    clean_name = Path(name or "未命名.md").name[:180] or "未命名.md"
    with store.exclusive() as conn:
        cur = conn.execute(
            """
            INSERT INTO kb_documents (name, source, audience, status, created_at, updated_at)
            VALUES (?, ?, ?, '已索引', ?, ?)
            """,
            (clean_name, source, audience, stamp, stamp),
        )
        document_id = int(cur.lastrowid)
        for position, (title, body) in enumerate(segments):
            conn.execute(
                """
                INSERT INTO kb_segments (document_id, title, body, position, enabled, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (document_id, title, body, position, stamp),
            )
    _bump()
    found = get_document(document_id)
    return found or {"id": str(document_id), "name": clean_name}


def add_segment(document_id: str | int, title: str, body: str) -> dict:
    ensure_seeded()
    number = _require_id(document_id)
    clean_title, clean_body = _clean_pair(title, body)
    stamp = _now()
    with store.exclusive() as conn:
        parent = conn.execute("SELECT id FROM kb_documents WHERE id = ?", (number,)).fetchone()
        if parent is None:
            raise ValueError("没有这篇文档")
        position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) AS n FROM kb_segments WHERE document_id = ?",
            (number,),
        ).fetchone()["n"]
        cur = conn.execute(
            """
            INSERT INTO kb_segments (document_id, title, body, position, enabled, updated_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (number, clean_title, clean_body, int(position) + 1, stamp),
        )
        segment_id = int(cur.lastrowid)
        conn.execute(
            "UPDATE kb_documents SET updated_at = ?, status = '已索引' WHERE id = ?",
            (stamp, number),
        )
    _bump()
    return _require_segment(segment_id)


def update_segment(segment_id: str | int, title: str, body: str) -> dict:
    number = _require_id(segment_id)
    clean_title, clean_body = _clean_pair(title, body)
    stamp = _now()
    with store.exclusive() as conn:
        row = conn.execute("SELECT id, document_id FROM kb_segments WHERE id = ?", (number,)).fetchone()
        if row is None:
            raise ValueError("没有这个分段")
        conn.execute(
            "UPDATE kb_segments SET title = ?, body = ?, enabled = 1, updated_at = ? WHERE id = ?",
            (clean_title, clean_body, stamp, number),
        )
        _drop_vectors(conn, [number])
        conn.execute(
            "UPDATE kb_documents SET updated_at = ? WHERE id = ?",
            (stamp, row["document_id"]),
        )
    _bump()
    return _require_segment(number)


def delete_document(document_id: str | int) -> bool:
    try:
        number = int(document_id)
    except (TypeError, ValueError):
        return False
    with store.exclusive() as conn:
        row = conn.execute("SELECT id FROM kb_documents WHERE id = ?", (number,)).fetchone()
        if row is None:
            return False
        ids = [
            int(item["id"])
            for item in conn.execute("SELECT id FROM kb_segments WHERE document_id = ?", (number,))
        ]
        _drop_vectors(conn, ids)
        conn.execute("DELETE FROM kb_segments WHERE document_id = ?", (number,))
        conn.execute("DELETE FROM kb_documents WHERE id = ?", (number,))
    _bump()
    return True


def delete_segment(segment_id: str | int) -> bool:
    try:
        number = int(segment_id)
    except (TypeError, ValueError):
        return False
    with store.exclusive() as conn:
        row = conn.execute(
            "SELECT id, document_id FROM kb_segments WHERE id = ?",
            (number,),
        ).fetchone()
        if row is None:
            return False
        _drop_vectors(conn, [number])
        conn.execute("DELETE FROM kb_segments WHERE id = ?", (number,))
        conn.execute(
            "UPDATE kb_documents SET updated_at = ? WHERE id = ?",
            (_now(), row["document_id"]),
        )
    _bump()
    return True


def chunks(audience: str = "") -> list[Chunk]:
    ensure_seeded()
    selected = scope(audience)
    shared = "demo" if selected == "demo" else "shared"
    with store.exclusive() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.body, d.name, d.source, d.source_url, d.audience
            FROM kb_segments s
            JOIN kb_documents d ON d.id = s.document_id
            WHERE s.enabled = 1 AND d.audience IN (?, ?)
            ORDER BY d.id ASC, s.position ASC, s.id ASC
            """,
            (selected, shared),
        ).fetchall()
    built: list[Chunk] = []
    for row in rows:
        title = row["title"]
        question = title if str(title).endswith(("？", "?")) else f"{title}？"
        body = row["body"] or ""
        preset = ARTICLE_BY_TITLE.get(title) if row["source"] == "preset" else None
        if preset and (preset.url != row["source_url"] or preset.audience != row["audience"]):
            preset = None
        built.append(
            Chunk(
                id=str(row["id"]),
                title=title,
                question=question,
                answer=body,
                content=f"问：{question}\n答：{body}",
                document_name=row["name"] or SAMPLE_NAME,
                dataset_name="校园知识库" if selected == "demo" else "青岛理工大学公开资料",
                source_url=row["source_url"],
                audience=row["audience"],
                category=preset.group if preset else "",
                aliases=preset.aliases if preset else (),
                curated=row["source"] == "preset",
            )
        )
    return built


def save_vectors(model: str, pairs: list[tuple[int, list[float]]]) -> int:
    """Write segment vectors into the embedded Chroma index."""
    saved = chroma_store.upsert(model, pairs)
    if saved:
        _bump()
    return saved


def knn(model: str, vector: list[float], limit: int = 8) -> list[tuple[str, float]]:
    """Nearest segments from Chroma. Each row is (segment id, cosine distance)."""
    return chroma_store.query(model, vector, limit)


def migrate_legacy_vectors() -> int:
    """Copy JSON vectors from older databases into Chroma once.

    New builds write only to Chroma. If Chroma cannot open, the JSON rows
    stay where they are and retrieval remains lexical.
    """
    if chroma_store.describe()["fallback"]:
        return 0
    if chroma_store.count() > 0:
        return 0
    grouped: dict[str, list[tuple[int, list[float]]]] = {}
    with store.exclusive() as conn:
        rows = conn.execute(
            "SELECT segment_id, model, vector_json FROM kb_vectors"
        ).fetchall()
    for row in rows:
        try:
            vector = json.loads(row["vector_json"])
        except json.JSONDecodeError:
            continue
        if not isinstance(vector, list) or not vector:
            continue
        grouped.setdefault(str(row["model"]), []).append(
            (int(row["segment_id"]), [float(item) for item in vector])
        )
    if not grouped:
        return 0
    model = max(grouped, key=lambda key: len(grouped[key]))
    return save_vectors(model, grouped[model])


def vectors_for(model: str) -> dict[str, list[float]]:
    """Legacy JSON vectors. Search does not read these; Chroma does."""
    if not model:
        return {}
    with store.exclusive() as conn:
        rows = conn.execute(
            "SELECT segment_id, vector_json FROM kb_vectors WHERE model = ?",
            (model,),
        ).fetchall()
    found: dict[str, list[float]] = {}
    for row in rows:
        try:
            vector = json.loads(row["vector_json"])
        except json.JSONDecodeError:
            continue
        if isinstance(vector, list) and vector:
            found[str(row["segment_id"])] = [float(item) for item in vector]
    return found


def vector_count(model: str = "") -> int:
    sql_count = _sql_vector_count(model)
    return _vector_total(sql_count) if not model else _vector_total_for_model(model, sql_count)


def segment_rows() -> list[dict]:
    ensure_seeded()
    with store.exclusive() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.title, s.body
            FROM kb_segments s JOIN kb_documents d ON d.id = s.document_id
            WHERE s.enabled = 1 AND d.audience IN (?, ?, ?)
            ORDER BY s.id ASC
            """,
            _profile_audiences(),
        ).fetchall()
    return [{"id": int(row["id"]), "title": row["title"], "body": row["body"]} for row in rows]


def split_segments(name: str, text: str) -> list[tuple[str, str]]:
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not raw:
        return []
    matches = list(_HEADING_RE.finditer(raw))
    if not matches:
        title = Path(name).stem or "未命名"
        return [(title[:_MAX_TITLE], raw[:_MAX_BODY])]
    segments: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        body = raw[start:end].strip()
        title = _NUMBER_RE.sub("", match.group(1).strip())
        if not title:
            continue
        if not body:
            body = title
        segments.append((title[:_MAX_TITLE], body[:_MAX_BODY]))
        if len(segments) >= _MAX_SEGMENTS:
            break
    return segments


def _docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            xml = package.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ValueError("这份 docx 打不开") from exc
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError("这份 docx 的正文读不出来") from exc
    lines: list[str] = []
    for para in root.iter(_WORD_NS + "p"):
        parts = [(node.text or "") for node in para.iter(_WORD_NS + "t")]
        line = "".join(parts).strip()
        if line:
            lines.append(line)
    text = "\n".join(lines).strip()
    if len(text) < 2:
        raise ValueError("这份 docx 里没有文字")
    return text


def _pdf_text(data: bytes) -> str:
    raw = data.decode("latin-1", errors="ignore")
    pieces: list[str] = []
    for match in _PDF_STRING_RE.finditer(raw):
        chunk = match.group(1)
        chunk = (
            chunk.replace(r"\n", "\n")
            .replace(r"\r", "")
            .replace(r"\t", " ")
            .replace(r"\(", "(")
            .replace(r"\)", ")")
            .replace(r"\\", "\\")
        )
        if not re.search(r"[\u4e00-\u9fffA-Za-z]", chunk):
            continue
        printable = sum(ch.isprintable() or ch == "\n" for ch in chunk)
        if printable < max(1, int(len(chunk) * 0.8)):
            continue
        pieces.append(chunk.strip())
    text = "\n".join(piece for piece in pieces if piece).strip()
    if len(text) < 8:
        raise ValueError("这份 PDF 抽不出文字。请另存为 md、txt 或 docx 再上传。")
    return text


def _public_document(row) -> dict:
    source = row["source"]
    labels = {"seed": "样例库", "preset": "学校公开资料", "upload": "上传", "writeback": "坐席回写"}
    return {
        "id": str(row["id"]),
        "name": row["name"],
        "source": labels.get(source, source),
        "source_key": source,
        "audience": row["audience"],
        "source_url": row["source_url"],
        "indexing_status": row["status"] or "已索引",
        "segment_count": int(row["segment_count"]) if "segment_count" in row.keys() else None,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _public_segment(row) -> dict:
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "body": row["body"],
        "position": row["position"],
        "enabled": bool(row["enabled"]),
        "updated_at": row["updated_at"],
    }


def _require_id(value: str | int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("编号不对") from exc


def _clean_pair(title: str, body: str) -> tuple[str, str]:
    clean_title = (title or "").strip()
    clean_body = (body or "").strip()
    if not clean_title or not clean_body:
        raise ValueError("标题和正文都要填")
    if len(clean_title) > _MAX_TITLE or len(clean_body) > _MAX_BODY:
        raise ValueError("标题不超过 180 字，正文不超过 8000 字")
    return clean_title, clean_body


def _drop_vectors(conn, segment_ids: list[int]) -> None:
    if not segment_ids:
        return
    marks = ",".join("?" for _ in segment_ids)
    conn.execute(
        f"DELETE FROM kb_vectors WHERE segment_id IN ({marks})",
        segment_ids,
    )
    chroma_store.delete_ids(segment_ids)


def _sql_vector_count(model: str = "") -> int:
    with store.exclusive() as conn:
        if model:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM kb_vectors WHERE model = ?",
                (model,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS n FROM kb_vectors").fetchone()
    return int(row["n"])


def _vector_total(sql_count: int) -> int:
    if chroma_store.describe()["fallback"]:
        return sql_count
    if not chroma_store.store_present() and not chroma_store.describe()["loaded"]:
        return sql_count
    counted = chroma_store.count()
    if chroma_store.describe()["fallback"]:
        return sql_count
    return counted


def _vector_total_for_model(model: str, sql_count: int) -> int:
    if chroma_store.describe()["fallback"]:
        return sql_count
    if not chroma_store.store_present() and not chroma_store.describe()["loaded"]:
        return sql_count
    counted = chroma_store.count(model)
    if chroma_store.describe()["fallback"]:
        return sql_count
    return counted


def _require_segment(segment_id: int) -> dict:
    with store.exclusive() as conn:
        row = conn.execute("SELECT * FROM kb_segments WHERE id = ?", (segment_id,)).fetchone()
    if row is None:
        raise ValueError("没有这个分段")
    return _public_segment(row)
