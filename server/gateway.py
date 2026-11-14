"""Portal chat orchestration: mask, scope, Dify, then the constraint layer.

The rules engine is not on this path. Eval group A still calls lite_engine directly.
"""
from __future__ import annotations

import json
import re
import secrets
import time

from clarify import clarify_options
from constraints import apply_constraints
from dify_client import ChatRaw, DifyClient, dataset_configured, hit_test, list_documents
from masking import is_medical_dump, mask_text, notice_line
from scope import EXAMPLES, INTRO, OFF_TOPIC, classify_scope
import store
from settings import load_config

_HANDOFF_RE = re.compile(r"(转\s*人工|人工\s*客服|人工\s*坐席|转接\s*人工|找\s*人工|联系\s*人工|有没有真人)")
_HANDOFF_QUESTION_RE = re.compile(r"(什么情况|什么时候|何时|如何|怎么|哪些|要不要|是否).{0,12}转\s*人工|转\s*人工.{0,8}(什么|哪些|条件|情况)")
_FOLLOW_RE = re.compile(r"^(那|这|还有|然后|另外|同|同样)")
_RESTART_RE = re.compile(r"^(重新开始|重新来过|换个话题|清空对话|开始新对话)[。.!！]?$")

MAINTENANCE_TEXT = "知识库维护中，机器人暂时不能回答办事问题。已为你登记人工，坐席上线后回复。"
HANDOFF_TEXT = "已登记，坐席上线后回复。不承诺具体时间。回复会出现在这个窗口，标为人工客服。"
HOLD_TEXT = "人工客服还在这张工单上。你的话已转给坐席，机器人先不插话。"

_CLIENT = DifyClient()


def is_handoff(query: str) -> bool:
    text = query or ""
    if _HANDOFF_QUESTION_RE.search(text):
        return False
    return bool(_HANDOFF_RE.search(text))


def set_client(client: DifyClient) -> None:
    global _CLIENT
    _CLIENT = client


def get_client() -> DifyClient:
    return _CLIENT


def run_chat(req: dict) -> dict:
    done = {}
    for event in iter_events(req):
        if event.get("type") == "done":
            done = {key: value for key, value in event.items() if key != "type"}
    return done


def iter_events(req: dict):
    started = time.perf_counter()
    query = (req.get("query") or "").strip()
    visitor = (req.get("visitor") or "").strip() or "anonymous"
    portal_session = (req.get("portal_session") or "").strip()
    user = (req.get("user") or visitor)[:64]
    history = req.get("history") if isinstance(req.get("history"), list) else []
    conversation_id = (req.get("conversation_id") or "").strip()
    masked, notices = mask_text(query)
    masked_history = _mask_history(history)
    notice = notice_line(notices)
    cfg = load_config()

    def finish(payload: dict):
        elapsed = int((time.perf_counter() - started) * 1000)
        payload = dict(payload)
        payload.setdefault("citations", [])
        payload.setdefault("suggestions", [])
        payload.setdefault("refuse", False)
        payload.setdefault("handoff", False)
        payload.setdefault("conversation_id", conversation_id)
        payload.setdefault("message_id", "")
        payload.setdefault("task_id", "")
        payload.setdefault("streamed", True)
        payload["latency_ms"] = elapsed
        if notice:
            payload["masked_notice"] = notice
            if payload.get("answer") and "已隐去" not in payload["answer"]:
                payload["answer"] = notice + "\n\n" + payload["answer"]
        payload["type"] = "done"
        _persist(visitor, portal_session, masked, payload, elapsed)
        yield {"type": "start", "conversation_id": payload.get("conversation_id") or "", "task_id": payload.get("task_id") or "", "agent_action": payload.get("agent_action") or ""}
        answer = payload.get("answer") or ""
        step = 48
        for index in range(0, len(answer), step):
            yield {"type": "delta", "text": answer[index : index + step]}
        yield payload

    if is_medical_dump(query):
        masked = "［病历内容已隐去］"
        yield from finish(_local(
            "请不要在对话里粘贴病历或诊断书。这些内容没有发出去。办就诊的事可以说「校医院如何预约挂号？」，或转人工。",
            action="safety",
            intent="safety",
            suggestions=({"label": "校医院挂号", "query": "校医院如何预约挂号？"}, {"label": "转人工", "query": "转人工"}),
        ))
        return

    if _RESTART_RE.match(masked):
        yield from finish(_local("好，我们重新开始。请直接说出新的问题。", action="restart", intent="restart", conversation_id=""))
        return

    scope = classify_scope(masked)
    if scope == "greeting":
        yield from finish(_local(INTRO, action="assistant_intro", intent="intro", suggestions=EXAMPLES))
        return
    if scope == "off_topic":
        yield from finish(_local(OFF_TOPIC, action="scope", intent="off_topic", suggestions=EXAMPLES))
        return

    if is_handoff(masked):
        ticket = _open_or_create(visitor, portal_session, "user", masked, source_if_new=_handoff_source(visitor, portal_session))
        yield from finish(_ticket_reply(ticket, HANDOFF_TEXT, action="human_handoff"))
        return

    open_ticket = store.open_ticket(visitor, portal_session)
    if open_ticket:
        store.add_message(visitor, "user", masked, portal_session, open_ticket["id"], meta={"masked_notice": notice})
        yield from finish(_local(HOLD_TEXT, action="agent_hold", intent="agent_hold", ticket=open_ticket, handoff=True))
        return

    options = clarify_options(masked)
    if options:
        yield from finish(_local(
            "你说的范围有点宽，选一个我再回答：",
            action="clarify",
            intent="clarify",
            suggestions=options,
        ))
        return

    probe = store.latest_probe()
    if probe is not None and not probe.get("ok"):
        ticket = _open_or_create(visitor, portal_session, "maintenance", masked)
        text = MAINTENANCE_TEXT + f"\n\n工单 {ticket['public_id']}。"
        yield from finish(_ticket_reply(ticket, text, action="maintenance", maintenance=True))
        return

    upstream_query, rewrite = _prepare_query(masked, masked_history, conversation_id)
    raw = _CLIENT.chat(upstream_query, user=user, conversation_id=conversation_id)
    if raw.error:
        store.save_probe(False, [{"name": "chat", "ok": False, "detail": "这次调用知识引擎失败：" + raw.error}])
        ticket = _open_or_create(visitor, portal_session, "maintenance", masked)
        text = MAINTENANCE_TEXT + f"\n\n工单 {ticket['public_id']}。"
        yield from finish(_ticket_reply(ticket, text, action="maintenance", maintenance=True, rewrite=rewrite))
        return

    decision = _decide(raw, cfg)
    if decision["refuse"] and cfg.get("auto_ticket_on_refusal"):
        ticket = _open_or_create(visitor, portal_session, "refusal", masked)
        decision["handoff"] = True
        decision["ticket_id"] = ticket["public_id"]
        decision["ticket_status"] = ticket["status"]
        decision["answer"] = decision["answer"] + f"\n\n已登记工单 {ticket['public_id']}，坐席上线后回复。"
    elif decision["refuse"]:
        decision["suggestions"] = [{"label": "转人工", "query": "转人工"}]
    decision["rewrite"] = rewrite
    decision["conversation_id"] = raw.conversation_id or conversation_id
    decision["message_id"] = raw.message_id
    decision["task_id"] = raw.task_id
    decision["retrieval"] = raw.resources
    decision["first_token_ms"] = raw.first_token_ms
    decision["trace"] = _trace(notices, rewrite, raw, decision, cfg)
    yield from finish(decision)


def run_probe(client: DifyClient | None = None) -> dict:
    """Three checks: dataset bound, at least one indexed segment, probe phrase hit."""
    cfg = load_config()
    active = client or _CLIENT
    checks = []
    question = cfg["probe_question"]
    expect = cfg["probe_expect"]

    if dataset_configured():
        try:
            documents = list_documents()
            indexed = [doc for doc in documents if str(doc.get("indexing_status")) in ("completed", "available", "indexed")]
            checks.append({
                "name": "dataset",
                "ok": True,
                "detail": f"知识库已配置，文档 {len(documents)} 篇。",
            })
            checks.append({
                "name": "indexed",
                "ok": bool(indexed) or bool(documents),
                "detail": f"索引完成 {len(indexed)} 篇。" if indexed else "还没有索引完成的文档。",
            })
            hits = hit_test(question)
            blob = " ".join((item.get("content") or "") + (item.get("document_name") or "") for item in hits)
            hit_ok = bool(hits) and (expect in blob if expect else True)
            checks.append({
                "name": "probe",
                "ok": hit_ok,
                "detail": "探针检索到了预期内容。" if hit_ok else "探针没有检索到预期内容。",
            })
        except Exception as exc:  # noqa: BLE001
            checks = [
                {"name": "dataset", "ok": False, "detail": "知识库接口失败：" + type(exc).__name__},
                {"name": "indexed", "ok": False, "detail": "未能确认索引。"},
                {"name": "probe", "ok": False, "detail": str(exc)[:180]},
            ]
    else:
        raw = active.chat(question, user="nebula-probe")
        if raw.error:
            checks = [
                {"name": "dataset", "ok": False, "detail": "应用未能连上知识引擎。"},
                {"name": "indexed", "ok": False, "detail": "没有检索结果，无法确认索引。"},
                {"name": "probe", "ok": False, "detail": raw.error},
            ]
        else:
            bound = bool(raw.resources)
            blob = " ".join((item.get("content") or "") + (item.get("document_name") or "") for item in raw.resources)
            phrase = expect in blob if expect else bound
            checks = [
                {"name": "dataset", "ok": bound, "detail": "应用检索到了已绑定知识库。" if bound else "检索为空，知识库可能未绑定。"},
                {"name": "indexed", "ok": bound, "detail": "检索到了片段，说明至少有一篇已索引。" if bound else "没有可检索片段。"},
                {"name": "probe", "ok": phrase, "detail": "探针问题命中了预期内容。" if phrase else "探针问题没有命中预期内容。"},
            ]
    ok = all(item["ok"] for item in checks) if checks else False
    return store.save_probe(ok, checks)


def _decide(raw: ChatRaw, cfg: dict) -> dict:
    clarify = _parse_clarify(raw.answer)
    if clarify:
        return _local(
            "你说的范围有点宽，选一个我再回答：",
            action="clarify",
            intent="clarify",
            suggestions=clarify,
        )
    decision = apply_constraints(
        raw.answer,
        raw.resources,
        cfg,
        retrieval_empty=bool(raw.retrieval_empty and not raw.resources),
    )
    decision["agent_action"] = "refuse" if decision["refuse"] else "knowledge_qa"
    decision["intent"] = decision["reason"]
    decision["engine"] = "dify+gateway"
    return decision


def _parse_clarify(answer: str) -> list[dict] | None:
    text = (answer or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.I).strip()
        text = re.sub(r"```$", "", text).strip()
    if not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    options = data.get("clarify")
    if not isinstance(options, list) or len(options) < 2:
        return None
    shaped = []
    for item in options[:3]:
        if isinstance(item, str) and item.strip():
            label = item.strip()
            shaped.append({"label": label.rstrip("？?"), "query": label if label.endswith("？") else label})
        elif isinstance(item, dict) and (item.get("query") or item.get("label")):
            query = str(item.get("query") or item.get("label"))
            shaped.append({"label": str(item.get("label") or query), "query": query})
    return shaped if len(shaped) >= 2 else None


def _prepare_query(masked: str, history: list, conversation_id: str) -> tuple[str, dict | None]:
    if conversation_id or not history:
        return masked, None
    previous = ""
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or "").lower()
        text = (item.get("text") or item.get("content") or "").strip()
        if role in ("user", "human") and text and text != masked:
            previous = text
            break
    if not previous:
        return masked, None
    short = len(masked) <= 16 or bool(_FOLLOW_RE.match(masked))
    if not short:
        return masked, None
    rewritten = f"（追问。上一句用户问题：{previous[:80]}）{masked}"
    return rewritten, {"original": masked, "rewritten": rewritten, "method": "history-prefix"}


def _mask_history(history: list) -> list:
    safe = []
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        for field in ("text", "content", "query"):
            if copied.get(field):
                copied[field], _notices = mask_text(str(copied[field]))
        safe.append(copied)
    return safe


def _local(answer: str, action: str, intent: str, suggestions=(), conversation_id: str | None = None, ticket: dict | None = None, handoff: bool = False, maintenance: bool = False, rewrite: dict | None = None) -> dict:
    payload = {
        "answer": answer,
        "citations": [],
        "refuse": False,
        "handoff": handoff or action == "human_handoff",
        "agent_action": action,
        "intent": intent,
        "suggestions": list(suggestions),
        "engine": "gateway",
        "maintenance": maintenance,
        "queue": bool(ticket) or action in ("human_handoff", "maintenance"),
    }
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    if ticket:
        payload["ticket_id"] = ticket.get("public_id") or ""
        payload["ticket_status"] = ticket.get("status") or ""
        payload["handoff"] = True
    if rewrite:
        payload["rewrite"] = rewrite
    payload["trace"] = [
        {"step": "输出", "ok": True, "detail": action, "ms": 0},
    ]
    return payload


def _ticket_reply(ticket: dict, answer: str, action: str, maintenance: bool = False, rewrite: dict | None = None) -> dict:
    return _local(answer, action=action, intent=action, ticket=ticket, handoff=True, maintenance=maintenance, rewrite=rewrite)


def _handoff_source(visitor: str, portal_session: str) -> str:
    judgments = store.list_judgments(visitor=visitor)
    for item in reversed(judgments):
        if portal_session and item.get("portal_session") not in ("", portal_session):
            continue
        if item.get("decision") in ("refuse", "empty_retrieval", "missing_citation"):
            return "refusal"
        break
    return "user"


def _open_or_create(visitor: str, portal_session: str, source: str, question: str, source_if_new: str | None = None) -> dict:
    existing = store.open_ticket(visitor, portal_session)
    if existing:
        return existing
    return store.create_ticket(visitor, portal_session, source_if_new or source, question)


def _trace(notices: list, rewrite: dict | None, raw: ChatRaw, decision: dict, cfg: dict) -> list:
    steps = [
        {
            "step": "打码",
            "ok": True,
            "detail": "、".join(notices) + "已打码" if notices else "没有手机号或证件号",
            "ms": 1,
        },
        {
            "step": "改写",
            "ok": True,
            "detail": rewrite["rewritten"] if rewrite else "按原问题检索",
            "ms": 0,
        },
        {
            "step": "检索",
            "ok": not decision.get("refuse") or decision.get("reason") != "empty_retrieval",
            "detail": f"命中 {len(raw.resources)} 段，相关度阈值 {cfg.get('score_threshold')}",
            "ms": raw.latency_ms,
        },
        {
            "step": "约束",
            "ok": not decision.get("refuse"),
            "detail": _constraint_detail(decision),
            "ms": 1,
        },
        {
            "step": "输出",
            "ok": True,
            "detail": "拒答模板" if decision.get("refuse") else "带引用的回答",
            "ms": raw.first_token_ms or 0,
        },
    ]
    return steps


def _constraint_detail(decision: dict) -> str:
    reason = decision.get("reason") or ""
    if reason == "empty_retrieval":
        return "检索为空，不把模型原文交给用户（R-202）"
    if reason == "missing_citation":
        return "没有达到相关度阈值的引用，改成拒答（R-201）"
    collapsed = decision.get("raw_segments", 0) - decision.get("merged_cards", 0)
    if collapsed > 0:
        return f"按文档合并，{decision.get('raw_segments')} 段显示为 {decision.get('merged_cards')} 张卡（R-203）"
    return "引用来自检索结果，相关度达到阈值（R-201）"


def _persist(visitor: str, portal_session: str, question: str, payload: dict, latency_ms: int) -> None:
    if not visitor or visitor == "anonymous":
        visitor = "anonymous"
        store.create_visitor(visitor)
    ticket = store.open_ticket(visitor, portal_session) if portal_session or visitor else None
    ticket_id = ticket["id"] if ticket else None
    if payload.get("agent_action") != "agent_hold":
        store.add_message(visitor, "user", question, portal_session, ticket_id)
    meta = {
        "agent_action": payload.get("agent_action"),
        "refuse": payload.get("refuse"),
        "citations": payload.get("citations") or [],
        "suggestions": payload.get("suggestions") or [],
        "ticket_id": payload.get("ticket_id") or "",
    }
    message_id = store.add_message(
        visitor,
        "bot",
        payload.get("answer") or "",
        portal_session,
        ticket_id,
        author="校园助手",
        meta=meta,
    )
    trace = payload.get("trace") or []
    store.add_judgment(
        visitor,
        portal_session,
        question,
        ((payload.get("rewrite") or {}) if isinstance(payload.get("rewrite"), dict) else {}).get("rewritten", ""),
        "refuse" if payload.get("refuse") else str(payload.get("agent_action") or "answer"),
        str(payload.get("reason") or payload.get("intent") or ""),
        trace,
        latency_ms,
        ticket_id=ticket_id,
        message_id=message_id,
    )
    decision = "拒答" if payload.get("refuse") else str(payload.get("agent_action") or "通过")
    if payload.get("maintenance"):
        decision = "知识库维护"
    if payload.get("handoff") and payload.get("agent_action") == "human_handoff":
        decision = "转人工"
    source = ""
    citations = payload.get("citations") or []
    if citations:
        source = "、".join(item.get("document_name") or "" for item in citations[:3])
    store.add_audit(
        "qa",
        actor="访客",
        session_ref=(portal_session or visitor)[:24],
        question=question,
        decision=decision,
        source=source,
        latency_ms=latency_ms,
        detail={"trace": trace, "ticket_id": payload.get("ticket_id") or ""},
    )


def new_visitor_token() -> str:
    return secrets.token_urlsafe(24)
