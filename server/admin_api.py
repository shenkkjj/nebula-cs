"""Admin: documents, probe, audit, constraint config, and eval launch."""
from __future__ import annotations

import csv
import io
import json
import threading
from pathlib import Path

from dify_client import (
    create_file_document,
    create_text_document,
    dataset_configured,
    delete_document,
    hit_test,
    list_documents,
)
from faq_meta import load_entries
from eval_runner import RESULTS_DIR, load_dataset, render_csv, render_markdown, run_group
from gateway import run_probe
from settings import ROOT, load_config, save_config
import store

_JOB_LOCK = threading.Lock()
_JOB = {
    "running": False,
    "progress": 0,
    "total": 0,
    "message": "",
    "error": "",
    "result": None,
}
_DATASETS = {
    "test": ROOT / "tests" / "eval" / "test-set.json",
    "dev": ROOT / "tests" / "eval" / "dev-set.json",
    "bad": ROOT / "tests" / "eval" / "bad-cases.json",
    "smoke": ROOT / "tests" / "eval" / "smoke-set.json",
}
_UPLOAD_TYPES = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_MAX_UPLOAD = 15 * 1024 * 1024
FAQ_HINT = "样例知识库是 sample-kb/客服样例FAQ.md 这一个文件（144 条都在里面）。导入这一篇，不要拆成 144 个文件。"


def feedback_rows(kind: str = "") -> dict:
    helpful = None
    if kind in ("1", "true", "有帮助"):
        helpful = 1
    elif kind in ("0", "false", "没解决"):
        helpful = 0
    rows = []
    for item in store.list_feedback(helpful):
        rows.append(
            {
                "id": item.get("id"),
                "helpful": bool(item.get("helpful")),
                "question": item.get("question") or "",
                "answer": item.get("answer") or "",
                "comment": item.get("comment") or "",
                "updated_at": item.get("updated_at") or "",
                "session": (item.get("portal_session") or "")[:24],
            }
        )
    return {"ok": True, "rows": rows}


def faq_check() -> dict:
    """Compare the local FAQ file with knowledge-base segments. Never raises."""
    entries = load_entries()
    titles = [item["title"] for item in entries]
    if len(titles) > 3:
        sample = [titles[0], titles[len(titles) // 2], titles[-1]]
    else:
        sample = titles
    payload = {
        "ok": True,
        "local_count": len(entries),
        "document": "客服样例FAQ.md",
        "title_sample": sample,
        "segment_count": None,
        "document_count": None,
        "title_hits": [],
        "warning": "",
    }
    if not dataset_configured():
        payload["warning"] = "当前没有连上知识库，只显示本地 FAQ 条数。"
        return payload
    try:
        documents = list_documents()
        overview = _segment_overview(documents)
    except Exception:  # noqa: BLE001
        payload["warning"] = "知识库分段暂时读不到，本地条数仍然有效。"
        return payload
    payload["document_count"] = overview["documents"]
    payload["segment_count"] = overview["segments"]
    local_count = payload["local_count"]
    segments = overview["segments"]
    if segments == 1 and local_count > 20:
        payload["warning"] = "知识库看起来整篇只有一段。请在知识库设置里改用自定义分隔，例如按 ## 。"
    elif segments is not None and local_count and segments >= local_count * 4:
        payload["warning"] = "分段数比本地 FAQ 条数多出很多，可能切得太碎。请在知识库设置里改用自定义分隔，例如按 ## 。"
    hits = []
    for title in sample:
        matched = None
        try:
            found = hit_test(title)
            blob = " ".join((item.get("content") or "") for item in found)
            matched = title.rstrip("？?") in blob or title in blob
        except Exception:  # noqa: BLE001
            matched = None
        hits.append({"title": title, "seen": matched})
    payload["title_hits"] = hits
    if payload["warning"] == "" and any(item["seen"] is None for item in hits):
        payload["warning"] = "标题抽查没有连上检索，本地条数和分段数仍然有效。"
    return payload


def _segment_overview(documents: list[dict]) -> dict:
    """Count segments only when the upstream sent a segment count."""
    total = 0
    known = False
    for doc in documents:
        raw = doc.get("segment_count")
        if raw is None:
            continue
        try:
            total += int(raw)
        except (TypeError, ValueError):
            continue
        known = True
    return {"documents": len(documents), "segments": total if known else None}


def document_list() -> dict:
    if not dataset_configured():
        return {
            "ok": True,
            "configured": False,
            "documents": [],
            "hint": FAQ_HINT + " 当前没有配置知识库 API，列表为空，不是零篇知识。",
        }
    try:
        documents = list_documents()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "configured": True, "documents": [], "error": str(exc)[:300], "hint": FAQ_HINT}
    return {"ok": True, "configured": True, "documents": documents, "hint": FAQ_HINT}


def remove_document(document_id: str, user: dict) -> tuple[int, dict]:
    if not document_id:
        return 400, {"ok": False, "error": "缺少文档编号"}
    if not dataset_configured():
        return 503, {"ok": False, "error": "没有配置知识库 API，不能删除。"}
    try:
        delete_document(document_id)
    except Exception as exc:  # noqa: BLE001
        return 502, {"ok": False, "error": "删除失败：" + str(exc)[:200]}
    store.add_audit("delete", actor=user["username"], session_ref=document_id, decision="删除文档")
    return 200, {"ok": True}


def add_document(filename: str, data: bytes, user: dict) -> tuple[int, dict]:
    name = Path(filename or "").name
    suffix = Path(name).suffix.lower()
    if suffix not in _UPLOAD_TYPES:
        return 400, {"ok": False, "error": "只接受 md、txt、pdf、docx"}
    if not data:
        return 400, {"ok": False, "error": "文件是空的"}
    if len(data) > _MAX_UPLOAD:
        return 400, {"ok": False, "error": "单个文件不能超过 15MB"}
    if not dataset_configured():
        return 503, {"ok": False, "error": "没有配置知识库 API。文件没有上传，请先在本机 .env 里填写知识库密钥。"}
    try:
        if suffix in (".md", ".txt"):
            text = data.decode("utf-8")
            created = create_text_document(name, text)
        else:
            created = create_file_document(name, data, _UPLOAD_TYPES[suffix])
    except UnicodeDecodeError:
        return 400, {"ok": False, "error": "文本文件需要是 UTF-8"}
    except Exception as exc:  # noqa: BLE001
        return 502, {"ok": False, "error": "上传失败：" + str(exc)[:240]}
    store.add_audit("upload", actor=user["username"], decision="上传", source=name, detail={"document_id": created.get("id") or ""})
    return 200, {"ok": True, "document": created}


def probe_now(user: dict | None) -> dict:
    result = run_probe()
    store.add_audit(
        "probe",
        actor=(user or {}).get("username") or "system",
        decision="通过" if result.get("ok") else "失败",
        detail={"checks": result.get("checks")},
    )
    return result


def audit_rows(kind: str = "", decision: str = "", query: str = "") -> dict:
    kind_map = {"问答": "qa", "后台操作": ""}
    stored_kind = kind_map.get(kind, "")
    rows = store.list_audit(kind="" if kind in ("", "全部") else stored_kind, decision="" if decision in ("", "全部") else decision, query=query, limit=200)
    if kind == "后台操作":
        rows = [row for row in rows if row.get("kind") != "qa"]
    elif kind == "问答":
        rows = [row for row in rows if row.get("kind") == "qa"]
    return {"ok": True, "rows": rows}


def audit_csv(kind: str = "", decision: str = "", query: str = "") -> str:
    payload = audit_rows(kind, decision, query)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["时间", "类型", "操作者", "会话", "问题", "判定", "来源", "耗时毫秒"])
    for row in payload["rows"]:
        writer.writerow([
            _cell(row.get("created_at")),
            _cell(row.get("kind")),
            _cell(row.get("actor")),
            _cell(row.get("session_ref")),
            _cell(row.get("question")),
            _cell(row.get("decision")),
            _cell(row.get("source")),
            _cell(row.get("latency_ms")),
        ])
    return buffer.getvalue()


def current_config() -> dict:
    cfg = load_config()
    return {"ok": True, "config": cfg, "note": "检索 top_k 和混合检索权重在 Dify 编排里改。这里只改约束层。保存后下一次问答即生效。"}


def update_config(updates: dict, user: dict) -> tuple[int, dict]:
    before = load_config()
    if not isinstance(updates, dict):
        return 400, {"ok": False, "error": "配置需要是一个对象"}
    saved = save_config(updates)
    store.add_audit(
        "config",
        actor=user["username"],
        decision="改参数",
        detail={"before": before, "after": saved},
    )
    return 200, {"ok": True, "config": saved}


def dataset_cards() -> dict:
    cards = []
    for key, path in _DATASETS.items():
        count = 0
        ready = path.is_file()
        if ready:
            try:
                _name, items = load_dataset(path)
                count = len(items)
            except (OSError, ValueError, json.JSONDecodeError):
                ready = False
        cards.append({"id": key, "file": path.name, "ready": ready, "count": count})
    return {"ok": True, "datasets": cards}


def start_eval(dataset_id: str, group: str, limit: int = 0) -> tuple[int, dict]:
    path = _DATASETS.get(dataset_id)
    if path is None or not path.is_file():
        return 404, {"ok": False, "error": "数据集还没有准备好"}
    chosen = (group or "").upper()
    if chosen not in ("A", "B", "C"):
        return 400, {"ok": False, "error": "组别只能是 A、B 或 C"}
    with _JOB_LOCK:
        if _JOB["running"]:
            return 409, {"ok": False, "error": "已有评测在跑"}
        _JOB.update(running=True, progress=0, total=0, message="准备", error="", result=None)

    def work() -> None:
        try:
            payload = run_group(path, chosen, limit=limit, progress=_JOB)
            _JOB["result"] = {
                "ran": True,
                "group": payload["group"],
                "dataset": payload["dataset"],
                "count": payload["count"],
                "metrics": payload["metrics"],
                "targets": payload["targets"],
                "note": payload["note"],
                "path": payload["path"],
            }
        except Exception as exc:  # noqa: BLE001
            _JOB["error"] = str(exc)
        finally:
            _JOB["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return 202, {"ok": True, "message": "评测已开始"}


def eval_status() -> dict:
    with _JOB_LOCK:
        current = dict(_JOB)
    latest = _latest_results()
    return {"ok": True, "job": current, "latest": latest}


def export_result(group: str, dataset: str, kind: str) -> tuple[int, str, str]:
    path = RESULTS_DIR / f"eval-{group}-{dataset}.json"
    if not path.is_file():
        return 404, "text/plain; charset=utf-8", "这一组还没有实测结果。"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 500, "text/plain; charset=utf-8", "结果文件读不出来。"
    if kind == "md":
        return 200, "text/markdown; charset=utf-8", render_markdown(payload)
    return 200, "text/csv; charset=utf-8", render_csv(payload)


def _latest_results() -> list[dict]:
    if not RESULTS_DIR.is_dir():
        return []
    found = []
    for path in sorted(RESULTS_DIR.glob("eval-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:6]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not payload.get("ran"):
            continue
        found.append({
            "group": payload.get("group"),
            "dataset": payload.get("dataset"),
            "count": payload.get("count"),
            "metrics": payload.get("metrics"),
            "targets": payload.get("targets"),
            "note": payload.get("note"),
            "file": path.name,
        })
    return found


def _cell(value) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text
