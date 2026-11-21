"""Lexical retrieval over the SQLite knowledge base, with optional Chroma vectors.

BM25 uses the existing campus FAQ index: titles, aliases, and a small lexicon,
so 办理 / 申请 alone cannot drag in a lookalike article. Character overlap is
only a rescue when that index has no concept to score. When remote embeddings
are configured and already stored in embedded Chroma, a vector hit can break a
lexical tie or rescue a miss. Embeddings are never required to start or to answer.
If Chroma cannot load, the result stays lexical.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import chroma_store
from campus_profile import query_key, scope
from lite_engine import (
    Chunk,
    FaqIndex,
    _Hit,
    _contained_chunk,
    _display_score,
    _filter_peers,
    norm_key,
)
from settings import env
import kb_store

_CACHE: dict[str, tuple[tuple[str, int], FaqIndex]] = {}
_EMBEDDER = None
_FUNC_CHARS = set("的了吗呢吧啊呀我你他她它和与或及在对把被给让向从到是有就也都还很又这那个")


def get_index(audience: str = "") -> FaqIndex:
    selected = scope(audience)
    token = kb_store.revision()
    cached = _CACHE.get(selected)
    if cached and cached[0] == token:
        return cached[1]
    index = FaqIndex(kb_store.chunks(audience))
    _CACHE[selected] = (token, index)
    return index


def catalog(audience: str = "") -> dict:
    chunks = get_index(audience).chunks
    groups: dict[str, list[dict]] = {}
    shortcuts: list[dict] = []
    for chunk in chunks:
        entry = {"id": chunk.id, "title": chunk.title, "query": chunk.question, "keywords": list(chunk.aliases)}
        groups.setdefault(chunk.category or "其他办事", []).append(entry)
        if chunk.category and (not shortcuts or all(item["group"] != chunk.category for item in shortcuts)):
            shortcuts.append({"group": chunk.category, "label": chunk.title, "query": chunk.question})
    return {
        "categories": [{"name": name, "items": items} for name, items in groups.items()],
        "shortcuts": shortcuts[:4],
        "count": len(chunks),
    }


def embedding_config() -> dict:
    key = env("EMBEDDING_API_KEY")
    base = env("EMBEDDING_BASE_URL").rstrip("/")
    model = env("EMBEDDING_MODEL", "text-embedding-3-small") or "text-embedding-3-small"
    return {"enabled": bool(key and base), "key": key, "base": base, "model": model}


def set_embedder_for_tests(fn) -> None:
    """Replace the remote embedding call. Pass None to restore it."""
    global _EMBEDDER
    _EMBEDDER = fn


# Vague complaints. They are not extra title words, so "校园卡出问题了" can
# still clarify among 校园卡 articles. A real leftover such as 加急 stays blocking.
_VAGUE_LEFTOVERS = ("出问题", "有问题", "东西坏", "好像不对", "上不去", "坏了", "不对")


def _vague_leftover(leftovers: list[str]) -> bool:
    if not leftovers:
        return False
    for run in leftovers:
        if not any(symptom in run or run in symptom for symptom in _VAGUE_LEFTOVERS):
            return False
    return True


# Spoken paraphrases of a title. Applied only when the rewritten question
# contains that title whole. A looser rewrite must not turn a clarify into a guess.
_PARAPHRASES = (
    ("想申请", "如何申请"),
    ("怎样", "如何"),
    ("能不能", "可以"),
    ("可不可以", "可以"),
    ("去哪儿", "在哪里"),
    ("去哪", "在哪里"),
    ("哪儿", "哪里"),
    ("指的是", "是"),
    ("一般何时", "什么时候"),
    ("何时", "什么时候"),
    ("不凉", "不制冷"),
    ("不冷", "不制冷"),
)


def search(query: str, audience: str = "") -> dict:
    index = get_index(audience)
    key = query_key(query)
    for chunk in index.chunks:
        if chunk.curated and any(key == query_key(form) for form in (chunk.title, *chunk.aliases)):
            return _pack("answer", [chunk], "contained-title", [99.0], "lexical")
    lexical = _lexical(query, index)
    repaired = _repair_wording(query, index)
    if repaired is not None:
        lexical = repaired
    alt, alt_query = _contained_paraphrase(query, lexical, index)
    if alt is not None:
        return _apply_chroma(alt_query, alt, index)
    if lexical["action"] in ("answer", "clarify"):
        return _apply_chroma(query, lexical, index)
    if lexical["reason"] == "oov-leftover":
        return lexical
    rescued = _char_rescue(query, index)
    if rescued["action"] != "none":
        return _apply_chroma(query, rescued, index)
    return _apply_chroma(query, lexical, index)


def confidence(score: float, method: str, reason: str) -> float:
    """Map a retrieval score onto the 0–1 citation threshold.

    Cosine similarity and the character-overlap rescue are already 0–1.
    A contained title is stored as 99 and BM25 often lands between 1 and 20.
    Comparing those raw numbers with 0.99 would never filter, and pushing
    every lexical hit under 0.5 would drop ordinary title matches.
    """
    number = float(score or 0)
    kind = reason or ""
    how = method or ""
    if kind in ("chroma", "chroma-tie") or how == "char" or kind in ("char", "char-tie"):
        if number > 1:
            number = number / 100.0
        return max(0.0, min(1.0, number))
    return _display_score(number)


def topic_terms(text: str) -> list[str]:
    """Lexicon words actually written in the question, longest first.

    ``concepts()`` keeps only a non-overlapping cover, so a whole title can
    hide the shorter word a follow-up still shares. Generic verbs are left out
    so they cannot break a real tie by themselves.
    """
    index = get_index()
    skip = _GENERIC_TERMS | {
        "如何",
        "怎么",
        "怎样",
        "怎么办",
        "申请",
        "办理",
        "查询",
        "哪里",
        "什么",
        "如何办理",
        "怎么办理",
        "如何申请",
        "怎么申请",
        "怎么处理",
        "如何处理",
    }
    present = [term for term in index._present(text) if len(term) >= 2 and term not in skip]
    present.sort(key=len, reverse=True)
    return present


def related_segments(chunk: Chunk, limit: int = 2, audience: str = "") -> list[Chunk]:
    """Other paragraphs of the same document that share this article's topic.

    An empty list means there is nothing to fold. Callers must not invent a
    second paragraph from the one segment they already have.
    """
    if chunk is None or limit <= 0:
        return []
    index = get_index(audience)
    core = _core_term(chunk.title, index)
    if len(core) < 3:
        return []
    found: list[Chunk] = []
    for other in index.chunks:
        if other.id == chunk.id or other.document_name != chunk.document_name or other.source_url != chunk.source_url:
            continue
        title = other.title or ""
        if core in title or core in (other.question or ""):
            found.append(other)
        if len(found) >= limit:
            break
    return found


def rebuild_embeddings() -> tuple[int, dict]:
    """Store remote vectors in embedded Chroma. Lexical search stays if this fails."""
    cfg = embedding_config()
    if not cfg["enabled"] and _EMBEDDER is None:
        return 400, {
            "ok": False,
            "error": "没有配置 EMBEDDING_API_KEY 或 EMBEDDING_BASE_URL。检索仍用词法，可以不配向量。",
        }
    if not chroma_store.ensure():
        return 503, {
            "ok": False,
            "error": "Chroma 没有加载，这次不请求嵌入接口。检索仍用词法。",
            "fallback": "lexical",
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
    if saved != len(pairs):
        return 502, {
            "ok": False,
            "error": "向量没有全部写入 Chroma。词法检索不受影响。",
            "count": saved,
            "fallback": "lexical",
        }
    return 200, {"ok": True, "count": saved, "model": cfg["model"], "backend": "chroma"}


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


def _lexical(query: str, index: FaqIndex) -> dict:
    if not index.chunks:
        return _empty("empty")
    contained = _contained_chunk(query, index)
    if contained is not None and not contained.curated:
        return _pack("answer", [contained], "contained-title", [99.0], "lexical")
    concepts = index.concepts(query)
    if not concepts:
        return _empty("no-concept")
    leftovers = index.leftovers(query, concepts)
    ranked: list[_Hit] = []
    for chunk, doc in zip(index.chunks, index.docs):
        if chunk.curated:
            continue
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
            if not _vague_leftover(leftovers):
                return _empty("oov-leftover")
        else:
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


def _char_rescue(query: str, index: FaqIndex) -> dict:
    """Rescue a heading whose words are not in the built-in campus lexicon."""
    query_chars = _chars(query)
    if len(query_chars) < 2:
        return _empty("no-char")
    scored: list[tuple[float, Chunk]] = []
    for chunk in index.chunks:
        if chunk.curated:
            continue
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


def _apply_chroma(query: str, lexical: dict, index: FaqIndex) -> dict:
    """Blend Chroma cosine similarity into the lexical decision.

    A confident lexical answer is kept. A tie can be broken, and a lexical
    miss can be rescued, only when the embedded index has a clear neighbor.
    """
    by_id = {chunk.id: chunk for chunk in index.chunks if not chunk.curated}
    if not by_id:
        return lexical
    neighbors = _neighbors(query)
    if not neighbors:
        return lexical
    neighbors = [(segment_id, score) for segment_id, score in neighbors if segment_id in by_id]
    if not neighbors:
        return lexical
    if lexical["action"] == "clarify":
        pool = {chunk.id for chunk in lexical["chunks"]}
        ranked = [
            (score, by_id[segment_id])
            for segment_id, score in neighbors
            if segment_id in pool and segment_id in by_id
        ]
        if len(ranked) < 2:
            return lexical
        best, second = ranked[0][0], ranked[1][0]
        if best >= 0.55 and best - second >= 0.08:
            return _pack("answer", [ranked[0][1]], "chroma-tie", [best], "hybrid")
        return lexical
    if lexical["action"] == "answer":
        top = lexical["chunks"][0]
        if neighbors[0][0] == top.id and neighbors[0][1] >= 0.55:
            return _pack("answer", lexical["chunks"], lexical["reason"], list(lexical["scores"]), "hybrid")
        return lexical
    if lexical["action"] == "none":
        best_id, best = neighbors[0]
        second = neighbors[1][1] if len(neighbors) > 1 else -1.0
        chunk = by_id.get(best_id)
        if chunk is not None and best >= 0.78 and best - second >= 0.05:
            return _pack("answer", [chunk], "chroma", [best], "hybrid")
    return lexical


def _neighbors(query: str) -> list[tuple[str, float]] | None:
    """Segment id and cosine similarity, best first. None when vectors are off."""
    cfg = embedding_config()
    if _EMBEDDER is None and not cfg["enabled"]:
        return None
    if chroma_store.describe()["fallback"]:
        return None
    kb_store.migrate_legacy_vectors()
    if chroma_store.describe()["fallback"]:
        return None
    model = cfg["model"]
    if chroma_store.count(model) <= 0:
        return None
    embedded = embed_texts([query])
    if not embedded:
        return None
    rows = chroma_store.query(model, embedded[0], 8)
    if not rows:
        return None
    ranked = [(segment_id, max(0.0, 1.0 - distance)) for segment_id, distance in rows]
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked


def _repair_wording(query: str, index: FaqIndex) -> dict | None:
    """「东西坏了」means a repair, not every article that mentions the place."""
    if "东西坏了" not in (query or ""):
        return None
    alt = _lexical((query or "").replace("东西坏了", "报修"), index)
    if alt.get("action") not in ("answer", "clarify") or not alt.get("chunks"):
        return None
    if not any("报修" in (chunk.title or "") for chunk in alt["chunks"]):
        return None
    return alt


def _paraphrases(query: str) -> list[str]:
    text = query or ""
    folded = text
    for source, target in _PARAPHRASES:
        folded = folded.replace(source, target)
    variants: list[str] = []
    if folded != text:
        variants.append(folded)
    swapped = folded.replace("怎么", "如何")
    if swapped != folded and swapped not in variants:
        variants.append(swapped)
    only_swap = text.replace("怎么", "如何")
    if only_swap != text and only_swap not in variants:
        variants.append(only_swap)
    return variants


def _contained_paraphrase(query: str, lexical: dict, index: FaqIndex) -> tuple[dict | None, str]:
    if lexical.get("action") == "answer":
        return None, query
    for variant in _paraphrases(query):
        alt = _lexical(variant, index)
        if alt.get("action") == "answer" and alt.get("reason") == "contained-title" and alt.get("chunks"):
            return alt, variant
    return None, query


_GENERIC_TERMS = {"怎么办", "如何", "什么", "哪里", "这个", "那个", "可以", "同学", "校园"}


def _core_term(title: str, index) -> str:
    folded = norm_key(title)
    for term in index.terms_by_len:
        if len(term) < 3 or term in _GENERIC_TERMS:
            continue
        if term in folded:
            return term
    return ""


def _chars(text: str) -> set[str]:
    folded = norm_key(text)
    return {char for char in folded if char not in _FUNC_CHARS and not char.isdigit()}


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
