"""Score groups A, B, and C. Metrics are computed only from runs that actually finish.

Group A calls the pre-replace rules engine (lite_engine plus its query rewrite).
Group B is Dify without the constraint layer. Group C is this gateway.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from settings import ROOT

RESULTS_DIR = ROOT / "results"
TARGETS = {
    "in_scope_accuracy": (">=", 0.85),
    "hit_at_3": (">=", 0.90),
    "out_of_scope_refusal": (">=", 0.90),
    "false_refusal": ("<=", 0.10),
    "duplicate_citations": ("==", 0),
    "first_token_p50_ms": ("<=", 3000),
    "first_token_p95_ms": ("<=", 6000),
}
METRIC_LABELS = {
    "in_scope_accuracy": "范围内回答正确率",
    "hit_at_3": "检索命中率 Hit@3",
    "out_of_scope_refusal": "库外拒答率",
    "false_refusal": "范围内误拒率",
    "duplicate_citations": "重复引用同一文档",
    "first_token_p50_ms": "首字时间 p50",
    "first_token_p95_ms": "首字时间 p95",
}


def load_dataset(path: Path) -> tuple[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return path.stem, data
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError("数据集里没有 items")
    name = str(data.get("set") or path.stem)
    return name, items


def score_item(item: dict, outcome: dict) -> dict:
    kind = item.get("type") or "in_scope"
    refused = is_refusal(outcome)
    title = item.get("expected_title") or ""
    facts = item.get("expected_facts") or []
    hit = title_in_ranked(outcome, title) if title else False
    cited = title_in_text(_citation_blob(outcome), title) if title else False
    facts_match = all(fact and fact in (outcome.get("answer") or "") for fact in facts) if facts else True
    duplicate = has_duplicate_document(outcome.get("citations") or [])
    passed = False
    label = ""
    if kind == "out_of_scope":
        passed = refused and not (outcome.get("citations") or [])
        label = "拒答" if passed else "该拒没拒"
    elif kind == "clarify":
        passed = clarify_passed(item, outcome)
        label = "澄清" if passed else "未澄清"
    else:
        passed = (not refused) and cited and facts_match
        if refused:
            label = "误拒"
        elif not cited:
            label = "引用不对"
        elif not facts_match:
            label = "事实不一致"
        else:
            label = "通过"
    return {
        "id": item.get("id"),
        "type": kind,
        "question": item.get("question"),
        "expected_title": title,
        "pass": passed,
        "label": label,
        "refused": refused,
        "hit_at_3": hit if kind != "out_of_scope" else None,
        "duplicate": duplicate,
        "latency_ms": outcome.get("latency_ms"),
        "first_token_ms": outcome.get("first_token_ms") if outcome.get("first_token_ms") is not None else outcome.get("latency_ms"),
        "answer": (outcome.get("answer") or "")[:240],
    }


def summarize(rows: list[dict]) -> dict:
    in_scope = [row for row in rows if row["type"] in ("in_scope", "multi_turn")]
    outside = [row for row in rows if row["type"] == "out_of_scope"]
    correct = [row for row in in_scope if row["pass"]]
    refused = [row for row in in_scope if row["refused"]]
    hits = [row for row in in_scope if row.get("hit_at_3")]
    outside_ok = [row for row in outside if row["pass"]]
    duplicates = sum(1 for row in rows if row.get("duplicate"))
    times = [row["first_token_ms"] for row in rows if isinstance(row.get("first_token_ms"), (int, float))]
    metrics = {
        "in_scope_accuracy": _rate(len(correct), len(in_scope)),
        "hit_at_3": _rate(len(hits), len(in_scope)),
        "out_of_scope_refusal": _rate(len(outside_ok), len(outside)),
        "false_refusal": _rate(len(refused), len(in_scope)),
        "duplicate_citations": duplicates,
        "first_token_p50_ms": _percentile(times, 50),
        "first_token_p95_ms": _percentile(times, 95),
        "in_scope_count": len(in_scope),
        "out_of_scope_count": len(outside),
        "clarify_count": sum(1 for row in rows if row["type"] == "clarify"),
        "clarify_pass": sum(1 for row in rows if row["type"] == "clarify" and row["pass"]),
    }
    return metrics


def meets_target(name: str, value) -> bool | None:
    if value is None or name not in TARGETS:
        return None
    op, goal = TARGETS[name]
    if op == ">=":
        return value >= goal
    if op == "<=":
        return value <= goal
    if op == "==":
        return value == goal
    return None


def is_refusal(outcome: dict) -> bool:
    if outcome.get("refuse") or outcome.get("agent_action") in ("refuse", "maintenance"):
        return True
    if outcome.get("maintenance"):
        return True
    if outcome.get("agent_action") in ("scope", "assistant_intro", "safety", "clarify", "off_topic"):
        return False
    if outcome.get("citations"):
        return False
    answer = outcome.get("answer") or ""
    return any(phrase in answer for phrase in ("知识库里没有", "知识库未覆盖", "不能编"))


def title_in_ranked(outcome: dict, title: str) -> bool:
    ranked: list[str] = []
    for item in outcome.get("retrieval") or []:
        if isinstance(item, str):
            ranked.append(item)
        elif isinstance(item, dict):
            ranked.append(f"{item.get('title') or ''}\n{item.get('content') or ''}\n{item.get('document_name') or ''}")
    if outcome.get("matched_title"):
        ranked.insert(0, str(outcome["matched_title"]))
    return any(title_in_text(text, title) for text in ranked[:3])


def title_in_text(text: str, title: str) -> bool:
    if not title:
        return False
    bare = title.rstrip("？?")
    return title in (text or "") or bare in (text or "")


def _citation_blob(outcome: dict) -> str:
    parts = []
    if outcome.get("matched_title"):
        parts.append(str(outcome["matched_title"]))
    for cite in outcome.get("citations") or []:
        if not isinstance(cite, dict):
            continue
        parts.append(cite.get("content") or "")
        parts.append(cite.get("document_name") or "")
        for segment in cite.get("segments") or []:
            if isinstance(segment, dict):
                parts.append(segment.get("content") or "")
    return "\n".join(parts)


def has_duplicate_document(citations: list) -> bool:
    keys = []
    for cite in citations:
        if not isinstance(cite, dict):
            continue
        key = cite.get("document_id") or cite.get("document_name")
        if key:
            keys.append(key)
    return len(keys) != len(set(keys))


def clarify_passed(item: dict, outcome: dict) -> bool:
    expected = set(item.get("expected_titles") or [])
    action = outcome.get("agent_action") or ""
    if action == "clarify" or outcome.get("clarify"):
        options = []
        for suggestion in outcome.get("suggestions") or []:
            if isinstance(suggestion, dict):
                options.append(suggestion.get("query") or suggestion.get("label") or "")
            else:
                options.append(str(suggestion))
        if not 2 <= len(options) <= 3:
            return False
        return any(_option_matches(option, expected) for option in options)
    title = item.get("expected_title") or ""
    if title and title_in_text(_citation_blob(outcome), title) and not is_refusal(outcome):
        return True
    return False


def _option_matches(option: str, expected: set[str]) -> bool:
    for title in expected:
        if option == title or option.rstrip("？?") == title.rstrip("？?") or option in title or title in option:
            return True
    return False


def answer_group_a(item: dict) -> dict:
    """Pre-replace rules engine. Imported here so this module can load before proxy."""
    import lite_engine
    from proxy import rewrite_query_for_retrieval

    history = item.get("history") or []
    question = item.get("question") or ""
    rewritten, meta = rewrite_query_for_retrieval(question, history)
    started = time.perf_counter()
    result = lite_engine.answer_lite(rewritten or question, history=history)
    elapsed = int((time.perf_counter() - started) * 1000)
    retrieval = []
    if result.get("matched_title"):
        retrieval.append({"title": result["matched_title"], "content": result.get("answer") or ""})
    for suggestion in result.get("suggestions") or []:
        retrieval.append({"title": suggestion.get("query") or suggestion.get("label") or "", "content": ""})
    return {
        "answer": result.get("answer") or "",
        "citations": result.get("citations") or [],
        "retrieval": retrieval,
        "matched_title": result.get("matched_title"),
        "refuse": bool(result.get("refuse")),
        "agent_action": result.get("agent_action") or result.get("intent"),
        "suggestions": result.get("suggestions") or [],
        "clarify": bool(result.get("clarify")),
        "latency_ms": elapsed,
        "first_token_ms": elapsed,
        "rewrite": meta,
    }


def answer_group_b(item: dict, client) -> dict:
    raw = client.chat(_eval_query(item), user="eval-b")
    if raw.error:
        raise RuntimeError(f"Dify 直出失败：{raw.error}")
    return {
        "answer": raw.answer,
        "citations": raw.resources,
        "retrieval": raw.resources,
        "refuse": False,
        "agent_action": "dify_direct",
        "latency_ms": raw.latency_ms,
        "first_token_ms": raw.first_token_ms if raw.first_token_ms is not None else raw.latency_ms,
    }


def answer_group_c(item: dict) -> dict:
    from gateway import run_chat
    import store

    probe = store.latest_probe()
    if probe is None or not probe.get("ok"):
        raise RuntimeError("知识库自检未通过，C 组不记分。先让探针变绿，再跑评测。")
    outcome = run_chat(
        {
            "query": item.get("question") or "",
            "history": item.get("history") or [],
            "user": "eval-c",
            "visitor": "eval-c",
            "portal_session": f"eval-{item.get('id')}",
        }
    )
    return outcome


def run_group(dataset_path: Path, group: str, limit: int = 0, progress=None) -> dict:
    name, items = load_dataset(dataset_path)
    if limit > 0:
        items = items[:limit]
    rows = []
    runner = _runner(group)
    for index, item in enumerate(items, start=1):
        if progress is not None:
            progress["progress"] = index - 1
            progress["total"] = len(items)
            progress["message"] = f"{group} 组 {index - 1}/{len(items)}"
        outcome = runner(item)
        rows.append(score_item(item, outcome))
    if progress is not None:
        progress["progress"] = len(items)
        progress["message"] = f"{group} 组完成"
    payload = {
        "ran": True,
        "group": group,
        "dataset": name,
        "count": len(rows),
        "metrics": summarize(rows),
        "targets": {key: {"op": op, "value": value} for key, (op, value) in TARGETS.items()},
        "items": rows,
        "note": _group_note(group),
    }
    out = RESULTS_DIR / f"eval-{group}-{name}.json"
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["path"] = str(out)
    return payload


def render_markdown(payload: dict) -> str:
    metrics = payload.get("metrics") or {}
    lines = [
        f"# 评测 {payload.get('group')} 组 · {payload.get('dataset')}",
        "",
        payload.get("note") or "",
        "",
        "| 指标 | 目标 | 实际 | 达标 |",
        "|---|---|---|---|",
    ]
    for key, label in METRIC_LABELS.items():
        op, goal = TARGETS[key]
        actual = metrics.get(key)
        flag = meets_target(key, actual)
        mark = "是" if flag else ("否" if flag is False else "—")
        lines.append(f"| {label} | {op} { _fmt_target(key, goal) } | {_fmt_metric(key, actual)} | {mark} |")
    lines.append("")
    lines.append(f"题目 {payload.get('count')}。范围内 {metrics.get('in_scope_count')}，库外 {metrics.get('out_of_scope_count')}。")
    return "\n".join(lines) + "\n"


def render_csv(payload: dict) -> str:
    lines = ["id,type,question,expected_title,label,pass,hit_at_3,duplicate,first_token_ms"]
    for row in payload.get("items") or []:
        lines.append(",".join(_csv(row.get(key)) for key in (
            "id", "type", "question", "expected_title", "label", "pass", "hit_at_3", "duplicate", "first_token_ms",
        )))
    return "\n".join(lines) + "\n"


def agreement(auto_rows: list[dict], labels: list[dict]) -> dict:
    by_id = {row.get("id"): row for row in auto_rows}
    compared = 0
    same = 0
    for label in labels:
        row = by_id.get(label.get("question_id"))
        if row is None or "human_label" not in label:
            continue
        compared += 1
        if bool(label.get("human_label")) == bool(row.get("pass")):
            same += 1
    if compared == 0:
        return {"ran": False, "compared": 0, "agreement": None}
    return {"ran": True, "compared": compared, "agreement": same / compared}


def _runner(group: str):
    chosen = group.upper()
    if chosen == "A":
        return answer_group_a
    if chosen == "B":
        from dify_client import DifyClient

        client = DifyClient()
        if not client.configured():
            raise RuntimeError("没有 DIFY_APP_API_KEY，B 组不能跑，也不记假分数。")

        def _run(item: dict) -> dict:
            return answer_group_b(item, client)

        return _run
    if chosen == "C":
        return answer_group_c
    raise ValueError("组别只能是 A、B 或 C")


def _eval_query(item: dict) -> str:
    history = item.get("history") or []
    question = item.get("question") or ""
    previous = ""
    for turn in reversed(history):
        if isinstance(turn, dict) and (turn.get("role") or "") in ("user", "human"):
            previous = turn.get("text") or turn.get("content") or ""
            if previous:
                break
    if previous:
        return f"（追问。上一句用户问题：{previous[:80]}）{question}"
    return question


def _group_note(group: str) -> str:
    if group == "A":
        return "A 组是改造前规则引擎（git 标签 baseline-rules 的 lite_engine 与查询改写），本机直接调用，没有模型。"
    if group == "B":
        return "B 组是 Dify 直出，不经过引用校验、空检索拦截和按文档合并。"
    return "C 组是当前网关加约束层。知识库目前是单个文件，Hit@3 按检索片段是否含期望条目标题计算。"


def _rate(part: int, whole: int):
    if whole <= 0:
        return None
    return round(part / whole, 4)


def _percentile(values: list, percent: int):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (percent / 100) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return int(round(ordered[low] * (1 - weight) + ordered[high] * weight))


def _fmt_metric(key: str, value) -> str:
    if value is None:
        return "—"
    if key.endswith("_ms"):
        return f"{value} ms"
    if key == "duplicate_citations":
        return str(value)
    return f"{value * 100:.1f}%"


def _fmt_target(key: str, value) -> str:
    if key.endswith("_ms"):
        return f"{value} ms"
    if key == "duplicate_citations":
        return str(value)
    return f"{value * 100:.0f}%"


def _csv(value) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        text = "'" + text
    if any(ch in text for ch in (",", '"', "\n")):
        text = '"' + text.replace('"', '""') + '"'
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description="跑校园客服评测")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--group", required=True, choices=["A", "B", "C"])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    payload = run_group(Path(args.dataset), args.group, limit=args.limit)
    metrics = payload["metrics"]
    print(f"组别 {payload['group']} · {payload['dataset']} · {payload['count']} 题")
    for key, label in METRIC_LABELS.items():
        print(f"{label}: {_fmt_metric(key, metrics.get(key))}")
    print(f"结果文件：{payload['path']}")


if __name__ == "__main__":
    main()
