"""Dify Chat and dataset adapter.

Assumption (Dify 1.x, recorded in docs/evidence/dify-adapter.md):
chat-messages streaming emits message / message_end / node_finished.
Dataset routes use a separate dataset API key. Scores are higher-is-better
on a 0–1 scale. Retrieval hits may be either retriever_resources or
knowledge-retrieval node outputs.result[].metadata.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from constraints import normalize_resource
from settings import dify_api_base, dify_app_key, dify_chat_url, dify_dataset_id, dify_dataset_key

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class ChatRaw:
    answer: str = ""
    resources: list = field(default_factory=list)
    conversation_id: str = ""
    message_id: str = ""
    task_id: str = ""
    error: str = ""
    http_status: int = 0
    latency_ms: int = 0
    first_token_ms: int | None = None
    retrieval_seen: bool = False
    retrieval_empty: bool = False


def clean_answer(text: str) -> str:
    if not text:
        return ""
    return _THINK_RE.sub("", text).strip()


class DifyClient:
    def __init__(self, chat_url: str | None = None, app_key: str | None = None, timeout: int = 90):
        self.chat_url = chat_url
        self.app_key = app_key
        self.timeout = timeout

    def _chat_url(self) -> str:
        return self.chat_url or dify_chat_url()

    def _app_key(self) -> str:
        return self.app_key if self.app_key is not None else dify_app_key()

    def configured(self) -> bool:
        return bool(self._app_key())

    def chat(self, query: str, user: str, conversation_id: str = "", inputs: dict | None = None) -> ChatRaw:
        started = time.perf_counter()
        body = {
            "inputs": inputs or {},
            "query": query,
            "response_mode": "streaming",
            "user": user or "nebula-portal",
        }
        if conversation_id:
            body["conversation_id"] = conversation_id
        raw = ChatRaw()
        key = self._app_key()
        if not key:
            raw.error = "missing_app_key"
            raw.latency_ms = int((time.perf_counter() - started) * 1000)
            return raw
        req = urllib.request.Request(
            self._chat_url(),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            raw.error = f"http_{exc.code}"
            raw.http_status = exc.code
            raw.answer = detail
            raw.latency_ms = int((time.perf_counter() - started) * 1000)
            return raw
        except urllib.error.URLError as exc:
            raw.error = "unreachable"
            raw.answer = str(getattr(exc, "reason", exc))[:300]
            raw.latency_ms = int((time.perf_counter() - started) * 1000)
            return raw
        except Exception as exc:  # noqa: BLE001
            raw.error = type(exc).__name__
            raw.latency_ms = int((time.perf_counter() - started) * 1000)
            return raw
        parts: list[str] = []
        node_resources: list = []
        try:
            for event in _iter_sse(resp):
                if event.get("conversation_id"):
                    raw.conversation_id = event["conversation_id"]
                if event.get("message_id"):
                    raw.message_id = event["message_id"]
                if event.get("task_id"):
                    raw.task_id = event["task_id"]
                kind = event.get("event") or ""
                if kind in ("message", "agent_message"):
                    if raw.first_token_ms is None:
                        raw.first_token_ms = int((time.perf_counter() - started) * 1000)
                    parts.append(event.get("answer") or "")
                elif kind == "message_end":
                    meta = event.get("metadata") or {}
                    found = _resources_from(meta.get("retriever_resources") or [])
                    if found:
                        raw.resources = found
                elif kind == "node_finished":
                    found, seen = _resources_from_node(event)
                    if seen:
                        raw.retrieval_seen = True
                        node_resources = found
                        raw.retrieval_empty = not found
                elif kind == "workflow_finished":
                    outputs = (event.get("data") or {}).get("outputs") or {}
                    clarify = outputs.get("clarify")
                    if isinstance(clarify, list) and clarify:
                        raw.answer = json.dumps({"clarify": clarify}, ensure_ascii=False)
                elif kind == "error":
                    raw.error = str(event.get("message") or event.get("code") or "dify_error")[:300]
        finally:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
        if not raw.resources and node_resources:
            raw.resources = node_resources
        if raw.retrieval_seen and not raw.resources:
            raw.retrieval_empty = True
        text = clean_answer("".join(parts))
        if text:
            raw.answer = text
        raw.latency_ms = int((time.perf_counter() - started) * 1000)
        return raw

    def stop(self, task_id: str, user: str) -> bool:
        if not task_id or not self._app_key():
            return False
        base = self._chat_url()
        if base.endswith("/chat-messages"):
            url = base[: -len("/chat-messages")] + f"/chat-messages/{task_id}/stop"
        else:
            url = base.rstrip("/") + f"/{task_id}/stop"
        req = urllib.request.Request(
            url,
            data=json.dumps({"user": user or "nebula-portal"}).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self._app_key()}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15):
                return True
        except Exception:  # noqa: BLE001
            return False


def dataset_configured() -> bool:
    return bool(dify_dataset_key() and dify_dataset_id())


def _dataset_request(method: str, path: str, payload: dict | None = None, timeout: int = 30):
    key = dify_dataset_key()
    if not key:
        raise RuntimeError("missing_dataset_key")
    url = dify_api_base().rstrip("/") + path
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"unreachable: {exc.reason}") from exc
    try:
        parsed = json.loads(body) if body else {}
    except json.JSONDecodeError:
        parsed = {"raw": body[:400]}
    return status, parsed


def list_documents() -> list[dict]:
    dataset_id = dify_dataset_id()
    _status, payload = _dataset_request("GET", f"/datasets/{dataset_id}/documents?page=1&limit=100")
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    documents = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        documents.append(
            {
                "id": row.get("id") or "",
                "name": row.get("name") or "未命名文档",
                "source": _doc_source(row.get("name") or ""),
                "indexing_status": row.get("indexing_status") or row.get("display_status") or "",
                "segment_count": row.get("segment_count") or row.get("tokens") or row.get("word_count") or 0,
                "error": row.get("error") or "",
            }
        )
    return documents


def delete_document(document_id: str) -> None:
    dataset_id = dify_dataset_id()
    _dataset_request("DELETE", f"/datasets/{dataset_id}/documents/{document_id}")


def create_text_document(name: str, text: str) -> dict:
    dataset_id = dify_dataset_id()
    _status, payload = _dataset_request(
        "POST",
        f"/datasets/{dataset_id}/document/create-by-text",
        {
            "name": name[:120],
            "text": text,
            "indexing_technique": "high_quality",
            "process_rule": {"mode": "automatic"},
        },
        timeout=60,
    )
    document = payload.get("document") if isinstance(payload, dict) else None
    if not isinstance(document, dict):
        document = payload if isinstance(payload, dict) else {}
    return {
        "id": document.get("id") or "",
        "indexing_status": document.get("indexing_status") or "indexing",
        "raw": payload,
    }


def create_file_document(filename: str, data: bytes, mime: str) -> dict:
    """Upload pdf/docx/md/txt. Multipart field names follow Dify create-by-file."""
    dataset_id = dify_dataset_id()
    key = dify_dataset_key()
    if not key:
        raise RuntimeError("missing_dataset_key")
    boundary = "----nebula-cs-boundary"
    meta = json.dumps(
        {"indexing_technique": "high_quality", "process_rule": {"mode": "automatic"}},
        ensure_ascii=False,
    ).encode("utf-8")
    safe_name = filename.replace('"', "")
    chunks = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="data"\r\n',
        b"Content-Type: application/json\r\n\r\n",
        meta,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        data,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    body = b"".join(chunks)
    url = dify_api_base().rstrip("/") + f"/datasets/{dataset_id}/document/create-by-file"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"http_{exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"unreachable: {exc.reason}") from exc
    document = payload.get("document") if isinstance(payload, dict) else {}
    if not isinstance(document, dict):
        document = {}
    return {
        "id": document.get("id") or "",
        "indexing_status": document.get("indexing_status") or "indexing",
    }


def hit_test(query: str) -> list[dict]:
    dataset_id = dify_dataset_id()
    _status, payload = _dataset_request(
        "POST",
        f"/datasets/{dataset_id}/hit-testing",
        {"query": query, "retrieval_model": {"search_method": "semantic_search", "top_k": 3}},
        timeout=40,
    )
    records = []
    if isinstance(payload, dict):
        records = payload.get("records") or payload.get("data") or []
    resources = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        segment = record.get("segment") if isinstance(record.get("segment"), dict) else record
        item = normalize_resource(
            {
                "content": segment.get("content") or record.get("content") or "",
                "score": record.get("score"),
                "document_name": (segment.get("document") or {}).get("name")
                if isinstance(segment.get("document"), dict)
                else segment.get("document_name"),
                "document_id": segment.get("document_id") or "",
                "segment_id": segment.get("id") or "",
            }
        )
        if item:
            resources.append(item)
    return resources


def _doc_source(name: str) -> str:
    if name.startswith("坐席回写"):
        return "坐席回写"
    return "上传"


def _resources_from(rows: list) -> list[dict]:
    found = []
    for row in rows or []:
        item = normalize_resource(row)
        if item:
            found.append(item)
    return found


def _resources_from_node(event: dict) -> tuple[list[dict], bool]:
    data = event.get("data") or {}
    node_type = str(data.get("node_type") or "")
    title = str(data.get("title") or "")
    if node_type != "knowledge-retrieval" and "检索" not in title and "知识" not in title:
        return [], False
    outputs = data.get("outputs") or {}
    result = outputs.get("result")
    if result is None:
        result = []
    if isinstance(result, dict):
        result = result.get("records") or result.get("result") or []
    if not isinstance(result, list):
        return [], True
    return _resources_from(result), True


def _iter_sse(resp):
    buf = ""
    while True:
        chunk = resp.read(512)
        if not chunk:
            break
        buf += chunk.decode("utf-8", errors="replace")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line = line.rstrip("\r")
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                yield event
