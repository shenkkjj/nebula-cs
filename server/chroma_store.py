"""Embedded Chroma index for campus segment vectors.

PersistentClient stores the index under DATA_DIR/chroma. There is no Chroma
server and no second database process. If the package or the client cannot
be opened, retrieval stays on the BM25 index.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from settings import data_dir

logger = logging.getLogger("nebula.chroma")

COLLECTION = "kb_segments"

_LOCK = threading.RLock()
_CLIENT = None
_PATH: str | None = None
_RUNTIME = None
_FORCED = False
_FAILED = False
_REASON = ""
_ANNOUNCED = False


def force_unavailable(disabled: bool) -> None:
    """Tests use this to exercise the lexical fallback without uninstalling Chroma."""
    global _FORCED
    with _LOCK:
        _FORCED = disabled


def reset_for_tests() -> None:
    global _RUNTIME, _FAILED, _REASON, _ANNOUNCED, _FORCED
    with _LOCK:
        _FORCED = False
        _FAILED = False
        _REASON = ""
        _ANNOUNCED = False
        _RUNTIME = None
        _close_locked()


def describe() -> dict:
    with _LOCK:
        return {
            "loaded": _CLIENT is not None and not _FORCED and not _FAILED,
            "fallback": bool(_FORCED or _FAILED),
            "reason": _REASON,
        }


def store_present() -> bool:
    return _directory().is_dir()


def ensure() -> bool:
    """Open the embedded client. False means this process stays lexical-only."""
    with _LOCK:
        if _FORCED:
            return _fail("Chroma disabled; retrieval is lexical-only")
        if _FAILED:
            return False
        try:
            _client_locked()
        except Exception as exc:  # noqa: BLE001
            _close_locked()
            return _fail(f"Chroma did not load ({exc}); retrieval is lexical-only")
        return True


def close() -> None:
    with _LOCK:
        _close_locked()


def count(model: str = "") -> int:
    with _LOCK:
        if _FORCED or _FAILED:
            return 0
        if _CLIENT is None and not store_present():
            return 0
        if not ensure():
            return 0
        try:
            column = _existing_locked()
        except Exception as exc:  # noqa: BLE001
            _fail(f"Chroma did not load ({exc}); retrieval is lexical-only")
            return 0
        if column is None:
            return 0
        meta = column.metadata or {}
        if model and meta.get("model") != model:
            return 0
        try:
            return int(column.count())
        except Exception as exc:  # noqa: BLE001
            _fail(f"Chroma did not load ({exc}); retrieval is lexical-only")
            return 0


def upsert(model: str, pairs: list[tuple[int, list[float]]]) -> int:
    if not model or not pairs:
        return 0
    dim = len(pairs[0][1])
    if dim < 1 or any(len(vector) != dim for _, vector in pairs):
        logger.warning("Chroma upsert skipped because the vectors do not share one dimension")
        return 0
    with _LOCK:
        if not ensure():
            return 0
        try:
            column = _collection_locked(model, dim, create=True)
            client = _client_locked()
            try:
                batch = int(client.get_max_batch_size())
            except Exception:  # noqa: BLE001
                batch = 128
            batch = max(1, batch)
            written = 0
            for start in range(0, len(pairs), batch):
                chunk = pairs[start : start + batch]
                ids = [str(int(segment_id)) for segment_id, _vector in chunk]
                embeddings = [[float(value) for value in vector] for _segment_id, vector in chunk]
                column.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=[f"segment:{segment_id}" for segment_id in ids],
                    metadatas=[
                        {"model": model, "segment_id": segment_id} for segment_id in ids
                    ],
                )
                written += len(chunk)
            return written
        except Exception as exc:  # noqa: BLE001
            _fail(f"Chroma did not load ({exc}); retrieval is lexical-only")
            return 0


def delete_ids(segment_ids: list[int]) -> None:
    if not segment_ids:
        return
    with _LOCK:
        if _FORCED or _FAILED:
            return
        if _CLIENT is None and not store_present():
            return
        if not ensure():
            return
        try:
            column = _existing_locked()
            if column is None:
                return
            column.delete(ids=[str(int(segment_id)) for segment_id in segment_ids])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chroma delete failed (%s); the lexical index is unchanged", exc)


def query(model: str, vector: list[float], limit: int) -> list[tuple[str, float]]:
    """Return (segment id, cosine distance). Distance 0 is an exact match."""
    if not model or not vector or limit <= 0:
        return []
    with _LOCK:
        if not ensure():
            return []
        try:
            column = _collection_locked(model, len(vector), create=False)
            if column is None:
                return []
            total = int(column.count())
            if total <= 0:
                return []
            found = column.query(
                query_embeddings=[[float(value) for value in vector]],
                n_results=min(int(limit), total),
                include=["distances"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chroma query failed (%s); this lookup stays lexical", exc)
            return []
    ids = (found.get("ids") or [[]])[0] or []
    distances = (found.get("distances") or [[]])[0] or []
    rows: list[tuple[str, float]] = []
    for segment_id, distance in zip(ids, distances):
        try:
            rows.append((str(segment_id), float(distance)))
        except (TypeError, ValueError):
            continue
    return rows


def _directory() -> Path:
    return data_dir() / "chroma"


def _runtime():
    global _RUNTIME
    if _RUNTIME is False:
        raise ImportError("chromadb is not available")
    if _RUNTIME is None:
        try:
            # Deferred on purpose: chromadb pulls onnxruntime and grpc.
            # The default lexical process, including LITE_MODE, must not import it.
            import chroma_runtime as runtime
        except Exception as exc:  # noqa: BLE001
            _RUNTIME = False
            raise ImportError(str(exc)) from exc
        _RUNTIME = runtime
    return _RUNTIME


def _client_locked():
    global _CLIENT, _PATH
    path = str(_directory())
    if _CLIENT is not None and _PATH == path:
        return _CLIENT
    _close_locked()
    client = _open_client(path)
    _CLIENT = client
    _PATH = path
    return client


def _open_client(path: str):
    runtime = _runtime()
    settings = runtime.Settings(anonymized_telemetry=False)
    return runtime.chromadb.PersistentClient(path=path, settings=settings)


def _embedding():
    return _runtime().RemoteOnlyEmbedding()


def _existing_locked():
    client = _client_locked()
    try:
        return client.get_collection(COLLECTION, embedding_function=_embedding())
    except _runtime().NotFoundError:
        return None


def _collection_locked(model: str, dim: int, *, create: bool):
    column = _existing_locked()
    if column is not None:
        meta = column.metadata or {}
        try:
            stored_dim = int(meta.get("dim"))
        except (TypeError, ValueError):
            stored_dim = -1
        if meta.get("model") == model and stored_dim == dim:
            return column
        if not create:
            return None
        _client_locked().delete_collection(COLLECTION)
    if not create:
        return None
    return _client_locked().create_collection(
        name=COLLECTION,
        embedding_function=_embedding(),
        metadata={"model": model, "dim": int(dim)},
        configuration={"hnsw": {"space": "cosine"}},
    )


def _close_locked() -> None:
    global _CLIENT, _PATH
    client = _CLIENT
    _CLIENT = None
    _PATH = None
    if client is None:
        return
    try:
        client.close()
    except Exception:  # noqa: BLE001
        logger.warning("Chroma client close failed", exc_info=True)


def _fail(reason: str) -> bool:
    global _FAILED, _REASON, _ANNOUNCED
    _FAILED = True
    _REASON = reason
    if not _ANNOUNCED:
        _ANNOUNCED = True
        logger.warning("%s", reason)
    return False
