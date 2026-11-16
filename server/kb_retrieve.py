"""Lexical retrieval over the SQLite knowledge base, with optional vectors.

BM25 uses the existing campus FAQ index: titles, aliases, and a small lexicon,
so 办理 / 申请 alone cannot drag in a lookalike article. Character overlap is
only a rescue when that index has no concept to score. Remote embeddings, when
configured and already stored, can break a tie or rescue a miss. They are never
required to start or to answer.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request

from lite_engine import (
    Chunk,
    FaqIndex,
    _Hit,
    _contained_chunk,
    _filter_peers,
    norm_key,
)
from settings import env
import kb_store

_CACHE: dict = {"token": None, "index": None}
_EMBEDDER = None
_FUNC_CHARS = set("的了吗呢吧啊呀我你他她它和与或及在对把被给让向从到是有就也都还很又这那个")


def get_index() -> FaqIndex:
    token = kb_store.revision()
    cached = _CACHE.get("index")
    if _CACHE.get("token") == token and cached is not None:
        return cached
    index = FaqIndex(kb_store.chunks())
    _CACHE["token"] = token
    _CACHE["index"] = index
    return index


def embedding_config() -> dict:
    key = env("EMBEDDING_API_KEY")
    base = env("EMBEDDING_BASE_URL").rstrip("/")
    model = env("EMBEDDING_MODEL", "text-embedding-3-small") or "text-embedding-3-small"
    return {"enabled": bool(key and base), "key": key, "base": base, "model": model}


def set_embedder_for_tests(fn) -> None:
    """Replace the remote embedding call. Pass None to restore it."""
    global _EMBEDDER
    _EMBEDDER = fn


def search(query: str) -> dict:
    lexical = _lexical(query)
    if lexical["action"] in ("answer", "clarify"):
        return _maybe_embeddings(query, lexical)
    if lexical["reason"] == "oov-leftover":
        return lexical
    rescued = _char_rescue(query)
    if rescued["action"] != "none":
        return rescued
    return _maybe_embeddings(query, lexical)


def rebuild_embeddings() -> tuple[int, dict]:
    """Store remote vectors for every enabled segment. Lexical search stays if this fails."""
    cfg = embedding_config()
    if not cfg["enabled"] and _EMBEDDER is None:
        return 400, {
            "ok": False,
            "error": "没有配置 EMBEDDING_API_KEY 或 EMBEDDING_BASE_URL。检索仍用词法，可以不配向量。",
        }
    rows = kb_store.segment_rows()
    pairs: list[tuple[int, list[float]]] = []
    step = 16
    for start in range(0, len(rows), step):
        batch = rows[start : start + step]
        texts = [f"{item['title']}\n{item['body']}"[:2000] for item in batch]
        vectors = embed_texts(texts)
        if not vectors:
            return 502, {"ok": False, "error": "向量接口没有返回结果。词法检索不受影响。"}
        for item, vector in zip(batch, vectors):
            pairs.append((int(item["id"]), vector))
    saved = kb_store.save_vectors(cfg["model"], pairs)
    return 200, {"ok": True, "count": saved, "model": cfg["model"]}


def embed_texts(texts: list[str]) -> list[list[float]] | None:
    """Remote embeddings. None means skipped or failed; callers keep lexical hits."""
    cleaned = [text.strip() for text in texts if text and text.strip()]
    if not cleaned:
        return None
    if _EMBEDDER is not None:
        try:
            vectors = _EMBEDDER(cleaned)
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(vectors, list) or len(vectors) != len(cleaned):
            return None
        return vectors
    cfg = embedding_config()
    if not cfg["enabled"]:
        return None
    url = cfg["base"] if cfg["base"].endswith("/embeddings") else cfg["base"] + "/embeddings"
    body = json.dumps({"model": cfg["model"], "input": cleaned}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg['key']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    ordered: list[list[float] | None] = [None] * len(cleaned)
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", 0))
        except (TypeError, ValueError):
            continue
        vector = item.get("embedding")
        if 0 <= index < len(ordered) and isinstance(vector, list) and vector:
            ordered[index] = [float(value) for value in vector]
    if any(item is None for item in ordered):
        return None
    return [item for item in ordered if item is not None]


def _lexical(query: str) -> dict:
    index = get_index()
    if not index.chunks:
        return _empty("empty")
    contained = _contained_chunk(query, index)
    if contained is not None:
        return _pack("answer", [contained], "contained-title", [99.0], "lexical")
    concepts = index.concepts(query)
    if not concepts:
        return _empty("no-concept")
    leftovers = index.leftovers(query, concepts)
    ranked: list[_Hit] = []
    for chunk, doc in zip(index.chunks, index.docs):
        levels = tuple(index.level(concept, doc) or "" for concept in concepts)
        title_n = sum(level == "title" for level in levels)
        body_n = sum(level in ("title", "body") for level in levels)
        if title_n == 0 and body_n == 0:
            continue
        ranked.append(
            _Hit(
                chunk=chunk,
                score=index.score(concepts, doc, chunk, query),
                title_n=title_n,
                body_n=body_n,
                levels=levels,
            )
        )
    if not ranked:
        return _empty("no-hit")
    if leftovers:
        narrowed = [hit for hit in ranked if all(run in norm_key(hit.chunk.title) for run in leftovers)]
        if not narrowed:
            return _empty("oov-leftover")
        ranked = narrowed
    ranked.sort(key=lambda hit: (hit.title_n, hit.body_n, hit.score), reverse=True)
    best = ranked[0]
    if best.title_n <= 0:
        body_peers = [hit for hit in ranked if hit.body_n == best.body_n and hit.title_n == 0]
        if best.body_n >= len(concepts) and len(body_peers) == 1:
            return _pack("answer", [best.chunk], "body", [best.score], "lexical")
        return _empty("body-only")
    peers = [hit for hit in ranked if hit.title_n == best.title_n and hit.levels == best.levels]
    peers = _filter_peers(peers, query)
    if len(peers) >= 2:
        chosen = peers[:3]
        return _pack("clarify", [hit.chunk for hit in chosen], "tie", [hit.score for hit in chosen], "lexical")
    if best.title_n * 2 >= len(concepts) or len(concepts) == 1:
        return _pack("answer", [best.chunk], "title", [best.score], "lexical")
    if len(ranked) == 1 or ranked[1].title_n < best.title_n:
        return _pack("answer", [best.chunk], "partial", [best.score], "lexical")
    return _pack(
        "clarify",
        [hit.chunk for hit in peers[:3]],
        "partial-tie",
        [hit.score for hit in peers[:3]],
        "lexical",
    )


def _char_rescue(query: str) -> dict:
    """Rescue a heading whose words are not in the built-in campus lexicon."""
    query_chars = _chars(query)
    if len(query_chars) < 2:
        return _empty("no-char")
    scored: list[tuple[float, Chunk]] = []
    for chunk in get_index().chunks:
        title_chars = _chars(chunk.title)
        if len(title_chars) < 2:
            continue
        overlap = query_chars & title_chars
        if len(overlap) < 2:
            continue
        cover = len(overlap) / len(title_chars)
        jaccard = len(overlap) / len(query_chars | title_chars)
        score = 0.5 * jaccard + 0.5 * cover
        if score >= 0.72 and cover >= 0.6:
            scored.append((score, chunk))
    if not scored:
        return _empty("no-char")
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) >= 2 and scored[0][0] - scored[1][0] < 0.08:
        chosen = scored[:3]
        return _pack("clarify", [item[1] for item in chosen], "char-tie", [item[0] for item in chosen], "char")
    if scored[0][0] >= 0.8:
        return _pack("answer", [scored[0][1]], "char", [scored[0][0]], "char")
    return _empty("no-char")


def _maybe_embeddings(query: str, lexical: dict) -> dict:
    cfg = embedding_config()
    model = cfg["model"]
    if _EMBEDDER is None and not cfg["enabled"]:
        return lexical
    if kb_store.vector_count(model) <= 0 and _EMBEDDER is None:
        return lexical
    vectors = kb_store.vectors_for(model)
    if not vectors:
        return lexical
    if lexical["action"] == "clarify":
        pool = lexical["chunks"]
    elif lexical["action"] == "none":
        pool = [chunk for chunk in get_index().chunks if chunk.id in vectors]
    else:
        return lexical
    if len(pool) < 2 and lexical["action"] != "none":
        return lexical
    embedded = embed_texts([query])
    if not embedded:
        return lexical
    query_vector = embedded[0]
    ranked: list[tuple[float, Chunk]] = []
    for chunk in pool:
        vector = vectors.get(chunk.id)
        if not vector or len(vector) != len(query_vector):
            continue
        ranked.append((_cosine(query_vector, vector), chunk))
    if not ranked:
        return lexical
    ranked.sort(key=lambda item: item[0], reverse=True)
    best_score, best_chunk = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else -1.0
    gap = best_score - second
    if lexical["action"] == "clarify" and best_score >= 0.55 and gap >= 0.08:
        return _pack("answer", [best_chunk], "embedding-tie", [best_score], "embedding")
    if lexical["action"] == "none" and best_score >= 0.78 and gap >= 0.05:
        return _pack("answer", [best_chunk], "embedding", [best_score], "embedding")
    return lexical


def _chars(text: str) -> set[str]:
    folded = norm_key(text)
    return {char for char in folded if char not in _FUNC_CHARS and not char.isdigit()}


def _cosine(left: list[float], right: list[float]) -> float:
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


def _empty(reason: str) -> dict:
    return _pack("none", [], reason, [], "lexical")


def _pack(action: str, chunks: list[Chunk], reason: str, scores: list[float], method: str) -> dict:
    return {
        "action": action,
        "chunks": chunks,
        "reason": reason,
        "scores": scores,
        "method": method,
    }
