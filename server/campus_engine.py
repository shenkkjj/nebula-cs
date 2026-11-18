"""Self-built campus assistant: intent, retrieval, grounded answers, handoff.

DeepSeek is optional. Campus rules are answered from the SQLite knowledge base.
Everyday chat can use the model, and is not allowed to invent school rules.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.request

from constraints import merge_citations
from followup import (
    is_back,
    is_followup_query,
    is_handoff_intent,
    is_restart,
    last_user_turns,
    rewrite_query_for_retrieval,
)
import chroma_store
from kb_retrieve import confidence, embedding_config, get_index, related_segments, search, topic_terms
from lite_engine import (
    _BARE_CLARIFY,
    _clarify_text,
    _display_score,
    _is_social,
    _policy_shaped,
    _split_lead,
    norm_key,
    try_skill,
)
from lite_skills import contains_sensitive, safety_payload
from masking import is_medical_dump, mask_text, notice_line
from ratelimit import allow as allow_rate
from settings import env, load_config
import kb_store
import store

_GUARD = threading.Lock()
_STOPS: set[str] = set()
_RESPONSES: dict[str, object] = {}

_CREATIVE_RE = re.compile(
    r"写一首|写首诗|帮我写诗|写诗|讲个笑话|讲个故事|推荐一部电影|推荐电影|"
    r"今天天气|帮我翻译|翻译成|译成英文|译成中文|写一段代码|帮我编程|"
    r"写作文|写一篇|帮我写一份|帮我写一个|帮我写篇|润色一下|润色："
)
_HARD_ADMIN_RE = re.compile(r"怎么办|如何办理|怎么办理|规定|流程是什么")
_ADMIN_RE = re.compile(
    r"怎么办|如何|怎么|办理|申请|规定|政策|能不能|可不可以|收费|多少钱|材料|"
    r"哪里|哪儿|流程|请假|证明|奖学金|贷款|宿舍|图书馆|校园网|校园卡|选课|"
    r"成绩|报修|门禁|学费|休学|转专业|毕业|缓考|补考|重修|病假|销假|一网通办"
)
# School questions the sample knowledge base does not contain. A miss here is a
# refusal, not small talk. Words that already hit a real article are answered first.
_OUTSIDE_CAMPUS_RE = re.compile(r"保研|考研|推免|校车|机场|查重|等级考试|论文格式|格式模板")
_SOFT_CHARS = set("想怎样般指哪儿否能可")
_BRIDGE_SKIP = (
    "怎么办",
    "什么时候",
    "如何",
    "哪里",
    "什么",
    "怎么",
    "怎样",
    "一下",
    "请问",
    "可以",
    "是否",
    "有没有",
    "需要",
    "呢",
    "吗",
    "想",
)
_THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_NUM_RE = re.compile(r"\d+(?:[:：.]\d+)?")
_CN_AMOUNT_RE = re.compile(r"[零一二三四五六七八九十]{1,3}个")
_BANNED_RE = re.compile(r"沈凯杰|王瑞康|美团|腾讯|阿里巴巴|阿里云|淘宝")
_LEAK_RE = re.compile(r"\d+\s*个工作日|一网通办|教务处窗口|必须携带校园卡")
_MARK_RE = re.compile(r"\[\d+\]")
_CONTENT_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
_BASIS_RE = re.compile(r"依据：[^\n]*")
_WRITE_LEAD_RE = re.compile(
    r"^(?:请)?(?:帮我|给我|替我)?(?:写一份|写一个|写篇|写一篇|起草一份|草拟一份|拟一份)"
)
_FUNC_EDGE = "的了吗呢吧啊呀我你他她它和与或及在对把被给让向从到是有就也都还很又这那个请约可把"

INTRO = (
    "你好，我是校园助手。\n\n"
    "办事上的口径，我按虚构的星云大学知识库来说，并标上出处。"
    "闲聊、写东西、把一段话写顺，也可以，语气不用那么正式。\n\n"
    "校规和办事步骤我只按知识库说。库里没有的，我会说明原因；你可以把话说具体一点，或转人工。"
)
HANDOFF_TEXT = "已登记，坐席上线后回复。不承诺具体时间。回复会出现在这个窗口，标为人工客服。"
HOLD_TEXT = "人工客服还在这张工单上。你的话已转给坐席，机器人先不插话。"
MAINTENANCE_TEXT = "知识库维护中，机器人暂时不能回答办事问题。已为你登记人工，坐席上线后回复。"
OFFLINE_CHAT = (
    "这句是日常聊天或写东西，我可以接，语气不用那么正式。\n\n"
    "当前没有配置对话模型，所以我不能现写一段稿子。校园办事我仍然按知识库回答。"
    "要启用闲聊和写作，在服务环境里设置 DEEPSEEK_API_KEY 后重启。"
)
LEAK_TEXT = "学校的办事口径我不能凭印象说。你直接问要办的事，我按知识库查；没有条目我会说明，也可以转人工。"

POLICY_SYSTEM = (
    "你是「校园助手」，在虚构的星云大学帮同学。语气自然，像平时说话，别端着。\n"
    "这一问已经检索到知识库片段。办事规定、时限、金额、地点、材料只许使用片段里写明的内容。\n"
    "先用一句人话回答，再补充片段里的细节。关键事实用 [1] 标出。\n"
    "片段里没有的数字、窗口、材料和期限，一个字都不要补。\n"
    "如果片段不够回答，就说知识库里没有这条，不要编。\n"
    "不要提到美团、腾讯、阿里，也不要提同学或同事的姓名。不要输出 <think>。"
)
CHAT_SYSTEM = (
    "你是「校园助手」，在虚构的星云大学和同学聊天。语气自然、放松，别写成公文。\n"
    "闲聊、开玩笑、写一段话、解释普通概念、翻译、起草练习用的文字都可以。\n"
    "草稿只是练习，不要说成学校的正式规定。\n"
    "星云大学的办事规定、时限、金额、材料、成绩和办件进度，一律不要凭记忆说。"
    "对方要问这些，就请对方直接问办事问题。\n"
    "看不到实时天气，不能核对密码，不能诊断病情。不要每句话都建议转人工。\n"
    "不要提到美团、腾讯、阿里。用中文。不要输出 <think>。"
)
_ACTION_LABEL = {
    "refuse": "拒答",
    "human_handoff": "转人工",
    "knowledge_qa": "办事问答",
    "clarify": "澄清",
    "general_skill": "日常",
    "assistant_intro": "问候",
    "safety": "敏感信息",
    "agent_hold": "等待坐席",
    "maintenance": "知识库维护",
    "restart": "重新开始",
    "rate_limit": "过于频繁",
    "campus_faq": "办事问答",
    "unknown_policy": "库内无依据",
    "intro": "问候",
    "chitchat": "日常聊天",
    "needs_model": "需要对话模型",
}


def _label(code: str) -> str:
    return _ACTION_LABEL.get(code or "", code or "")


_CHIPS = (
    {"label": "在读证明", "query": "在读证明如何办理？"},
    {"label": "助学贷款", "query": "国家助学贷款如何申请？"},
    {"label": "宿舍报修", "query": "宿舍报修怎么提交？"},
    {"label": "校园网", "query": "校园网如何认证登录？"},
    {"label": "转人工", "query": "转人工"},
)


def request_stop(task_id: str) -> bool:
    if not task_id:
        return False
    with _GUARD:
        _STOPS.add(task_id)
        response = _RESPONSES.get(task_id)
    if response is not None:
        close = getattr(response, "close", None)
        if callable(close):
            try:
                close()
            except OSError:
                pass
    return True


def _stopped(task_id: str) -> bool:
    with _GUARD:
        return bool(task_id) and task_id in _STOPS


def answer(req: dict | str) -> dict:
    """Blocking helper for tests and non-streaming callers."""
    payload = req if isinstance(req, dict) else {"query": req}
    payload.setdefault("visitor", "eval-campus")
    payload.setdefault("user", "eval-campus")
    payload.setdefault("portal_session", "s-" + secrets.token_hex(4))
    done: dict = {}
    for event in iter_events(payload):
        if event.get("type") == "done":
            done = {key: value for key, value in event.items() if key != "type"}
    return done


def iter_events(req: dict):
    started = time.perf_counter()
    task_id = "campus-" + secrets.token_hex(4)
    visitor = (req.get("visitor") or "").strip() or "anonymous"
    store.create_visitor(visitor)
    portal_session = str(req.get("portal_session") or "")[:80]
    conversation_id = (req.get("conversation_id") or "").strip()
    if not conversation_id:
        conversation_id = "c-" + hashlib.sha256(visitor.encode("utf-8")).hexdigest()[:12]
    yield {
        "type": "start",
        "conversation_id": conversation_id,
        "message_id": "",
        "task_id": task_id,
        "agent_action": "",
        "engine": "campus",
    }
    try:
        if _stopped(task_id):
            yield from _emit(req, _stopped_payload(conversation_id), task_id, started)
            return
        yield {"type": "status", "phase": "retrieving"}
        payload = _decide(req, task_id, conversation_id)
        if payload.get("generator") == "deepseek":
            yield {"type": "status", "phase": "generating"}
        yield from _emit(req, payload, task_id, started)
    finally:
        with _GUARD:
            _STOPS.discard(task_id)
            _RESPONSES.pop(task_id, None)


def run_probe() -> dict:
    kb_store.ensure_seeded()
    info = kb_store.stats()
    cfg = load_config()
    question = str(cfg.get("probe_question") or "")
    expect = str(cfg.get("probe_expect") or "")
    found = search(question) if question else {"action": "none", "chunks": []}
    blob = " ".join((chunk.content or "") + (chunk.title or "") for chunk in found.get("chunks") or [])
    hit = found.get("action") == "answer" and (expect in blob if expect else True)
    checks = [
        {
            "name": "dataset",
            "ok": info["segments"] > 0,
            "detail": f"自建知识库 {info['documents']} 篇、{info['segments']} 段。",
        },
        {
            "name": "indexed",
            "ok": info["segments"] > 0,
            "detail": "词法索引已按当前分段建好。" if info["segments"] else "没有可检索分段。",
        },
        {
            "name": "probe",
            "ok": bool(hit),
            "detail": "探针检索到了预期内容。" if hit else "探针没有检索到预期内容。",
        },
    ]
    return store.save_probe(all(item["ok"] for item in checks), checks)


def health_payload() -> dict:
    embed = embedding_config()
    if embed["enabled"]:
        kb_store.migrate_legacy_vectors()
        if not chroma_store.describe()["fallback"]:
            chroma_store.ensure()
    info = kb_store.stats()
    probe = store.latest_probe()
    backend = chroma_store.describe()
    if not embed["enabled"]:
        embeddings = "off"
    elif backend["fallback"]:
        embeddings = "lexical_fallback"
    elif chroma_store.count(embed["model"]):
        embeddings = "ready"
    else:
        embeddings = "configured_unindexed"
    if backend["fallback"]:
        chroma_state = "lexical_fallback"
    elif backend["loaded"]:
        chroma_state = "open"
    else:
        chroma_state = "standby"
    features = [
        "kb",
        "bm25",
        "query_rewrite",
        "human_handoff",
        "streaming",
        "citations",
        "everyday_chat",
    ]
    if chroma_state == "open":
        features.append("chroma")
    return {
        "ok": True,
        "service": "nebula-cs",
        "engine": "campus",
        "streaming": True,
        "agent": True,
        "maintenance": bool(probe and not probe.get("ok")),
        "probe": probe,
        "lite_mode": False,
        "features": features,
        "components": {
            "knowledge_base": "up" if info["segments"] else "empty",
            "documents": info["documents"],
            "segments": info["segments"],
            "deepseek": "configured" if env("DEEPSEEK_API_KEY") else "optional_missing",
            "embeddings": embeddings,
            "chroma": chroma_state,
            "database": "up",
        },
    }


def _decide(req: dict, task_id: str, conversation_id: str) -> dict:
    raw = (req.get("query") or "").strip()
    history = _mask_history(req.get("history") if isinstance(req.get("history"), list) else [])
    visitor = (req.get("visitor") or "").strip() or "anonymous"
    user = (req.get("user") or visitor)[:64]
    portal_session = str(req.get("portal_session") or "")[:80]
    masked, notices = mask_text(raw)
    cfg = load_config()
    if _stopped(task_id):
        return _stopped_payload(conversation_id)

    if is_medical_dump(raw) or contains_sensitive(raw):
        spec = safety_payload(masked)
        return _base(
            spec["answer"],
            action="safety",
            intent="safety",
            conversation_id=conversation_id,
            suggestions=list(spec.get("suggestions") or []),
            generator="safety",
            notices=notices,
            reason="敏感信息未进入检索",
        )

    if is_restart(masked):
        payload = _base(
            "好，之前的话题先放下。\n\n" + INTRO,
            action="restart",
            intent="restart",
            conversation_id="",
            suggestions=list(_CHIPS),
            generator="intro",
            notices=notices,
        )
        return payload

    if is_handoff_intent(masked):
        ticket, _ = store.open_or_create_ticket(visitor, portal_session, "user", masked)
        return _ticket_payload(ticket, HANDOFF_TEXT, "human_handoff", conversation_id, notices, reason="访客要求转人工")

    if _is_social(masked):
        return _base(
            INTRO,
            action="assistant_intro",
            intent="intro",
            conversation_id=conversation_id,
            suggestions=list(_CHIPS),
            generator="intro",
            notices=notices,
        )

    if is_back(masked):
        rewritten, rewrite = rewrite_query_for_retrieval(masked, history)
        if rewrite and rewrite.get("missing"):
            return _base(
                "还没有上一条可以回去。你直接说就行。",
                action="general_skill",
                intent="chitchat",
                conversation_id=conversation_id,
                generator="skill",
                notices=notices,
                rewrite=rewrite,
            )
    else:
        rewritten, rewrite = rewrite_query_for_retrieval(masked, history)

    target = rewritten or masked
    skill = try_skill(target)
    if skill is not None:
        return _base(
            skill.get("answer") or "",
            action="general_skill",
            intent=skill.get("intent") or "chitchat",
            conversation_id=conversation_id,
            suggestions=list(skill.get("suggestions") or []),
            generator=skill.get("generator") or "skill",
            notices=notices,
            rewrite=rewrite,
            reason="本地小能力，不引用校规",
        )

    if not allow_rate(visitor, user, cfg):
        return _base(
            "问得有点密，先休息一下再问。我还在，不着急。",
            action="rate_limit",
            intent="rate_limit",
            conversation_id=conversation_id,
            notices=notices,
            rewrite=rewrite,
        )

    if _stopped(task_id):
        return _stopped_payload(conversation_id)

    writing = _creative(target)
    if writing and not _mentions_admin(target):
        return _everyday(target, history, task_id, conversation_id, notices, rewrite, cfg)

    open_ticket = store.open_ticket(visitor, portal_session)
    if open_ticket:
        store.add_message(visitor, "user", masked, portal_session, open_ticket["id"])
        return _base(
            HOLD_TEXT,
            action="agent_hold",
            intent="agent_hold",
            conversation_id=conversation_id,
            ticket=open_ticket,
            handoff=True,
            notices=notices,
            rewrite=rewrite,
            reason="已有未结束的人工工单",
        )

    lookup = _without_writing_lead(target) if writing else target
    found = search(lookup)
    if not _outside_campus(lookup):
        found = _with_history(lookup, history, found)
    if found.get("action") == "answer" and found.get("chunks") and not _clears_threshold(found, cfg):
        found = {
            "action": "none",
            "chunks": [],
            "scores": [],
            "reason": "below-threshold",
            "method": found.get("method") or "",
        }
    maintenance = _maintenance_on()
    if maintenance and _needs_kb(target, found):
        ticket, _ = store.open_or_create_ticket(visitor, portal_session, "maintenance", masked)
        return _ticket_payload(
            ticket,
            MAINTENANCE_TEXT,
            "maintenance",
            conversation_id,
            notices,
            rewrite,
            maintenance=True,
        )

    if found["action"] == "answer" and found["chunks"]:
        chunk = found["chunks"][0]
        if not _query_fits_chunk(lookup, chunk):
            return _clarify(
                [chunk],
                conversation_id,
                notices,
                rewrite,
                "问句里有这条标题没有写到的字，先确认是不是这一件。",
            )
        payload = _policy(found, lookup, history, task_id, conversation_id, notices, rewrite, cfg)
        if writing:
            payload["answer"] = "这件办事我按知识库说，不另写一份正式文书。\n\n" + payload["answer"]
            payload["reason"] = "写作请求里点到了办事条目，改按知识库回答"
        return payload
    if found["action"] == "clarify" and found["chunks"]:
        return _clarify(found["chunks"], conversation_id, notices, rewrite, "有几条都像，先选一条。")
    if found.get("reason") == "below-threshold":
        if writing:
            return _everyday(target, history, task_id, conversation_id, notices, rewrite, cfg)
        return _refuse(
            cfg,
            conversation_id,
            notices,
            rewrite,
            "相关度低于当前引用阈值，这次不附引用。",
            visitor,
            portal_session,
            masked,
        )
    if writing:
        return _everyday(target, history, task_id, conversation_id, notices, rewrite, cfg)

    bare = _BARE_CLARIFY.get(_norm(target))
    if bare is not None:
        prompt, chips = bare
        return _base(
            prompt,
            action="clarify",
            intent="clarify",
            conversation_id=conversation_id,
            suggestions=list(chips),
            clarify=True,
            generator="clarify",
            notices=notices,
            rewrite=rewrite,
            reason="问得太宽，先澄清",
        )

    if _ADMIN_RE.search(target) or _policy_query(target) or _outside_campus(target):
        return _refuse(cfg, conversation_id, notices, rewrite, "知识库里没有和这句话对得上的条目。", visitor, portal_session, masked)

    return _everyday(target, history, task_id, conversation_id, notices, rewrite, cfg)


def cards_for_chunks(pairs: list, max_cards: int = 3) -> list[dict]:
    """One card per document. The highest score stays open; the rest fold."""
    resources = []
    titles: dict[str, str] = {}
    for chunk, score in pairs:
        shown = _display_score(float(score or 0))
        resources.append(
            {
                "document_name": chunk.document_name,
                "dataset_name": chunk.dataset_name,
                "segment_id": str(chunk.id),
                "score": shown,
                "content": (chunk.content or "")[:480],
            }
        )
        titles[str(chunk.id)] = chunk.title
    limit = max_cards if max_cards > 0 else 3
    cards = merge_citations(resources, max_cards=limit)
    for index, card in enumerate(cards, start=1):
        card["mark"] = index
        card["title"] = titles.get(str(card.get("segment_id") or ""), "")
    return cards


def _policy(found: dict, query: str, history: list, task_id: str, conversation_id: str, notices: list, rewrite, cfg: dict) -> dict:
    chunk = found["chunks"][0]
    template = _policy_text(chunk)
    text = template
    generator = "template"
    if env("DEEPSEEK_API_KEY") and not _stopped(task_id):
        model = _complete(
            POLICY_SYSTEM,
            query,
            history,
            context=chunk.content,
            temperature=0.2,
            task_id=task_id,
        )
        source = f"{chunk.title}\n{chunk.answer}"
        if model and _accept_policy(model, source):
            text = model if "依据：" in model else model.rstrip() + f"\n\n依据：{chunk.document_name} · {chunk.title}"
            generator = "deepseek"
    scores = list(found.get("scores") or [])
    pairs = []
    for index, item in enumerate(found.get("chunks") or []):
        pairs.append((item, scores[index] if index < len(scores) else 1.0))
    limit = int(cfg.get("max_citations") or 3)
    citations = cards_for_chunks(pairs, max_cards=limit)
    _attach_related(citations, chunk)
    return _base(
        text,
        action="knowledge_qa",
        intent="campus_faq",
        conversation_id=conversation_id,
        citations=citations,
        generator=generator,
        notices=notices,
        rewrite=rewrite,
        title=chunk.title,
        reason=f"{found['method']} · {found['reason']}",
        retrieval=citations,
    )


def _clarify(chunks: list, conversation_id: str, notices: list, rewrite, detail: str) -> dict:
    chosen = list(chunks[:3])
    suggestions = [{"label": chunk.title, "query": chunk.question} for chunk in chosen]
    return _base(
        _clarify_text(chosen),
        action="clarify",
        intent="clarify",
        conversation_id=conversation_id,
        suggestions=suggestions,
        clarify=True,
        generator="clarify",
        notices=notices,
        rewrite=rewrite,
        reason=detail,
    )


def _refuse(cfg: dict, conversation_id: str, notices: list, rewrite, why: str, visitor: str, portal_session: str, question: str) -> dict:
    base = str(cfg.get("refusal_text") or "知识库里没有这条办事说明，我不能编规定。")
    text = f"{base}\n\n原因：{why}\n下一步：把事情说具体一点，例如要办的证明或业务名称；如果这件事要人来处理，可以说「转人工」。"
    ticket = None
    if cfg.get("auto_ticket_on_refusal"):
        ticket, _ = store.open_or_create_ticket(visitor, portal_session, "refusal", question)
        text += f"\n\n已登记工单 {ticket['public_id']}，坐席上线后回复。"
    return _base(
        text,
        action="refuse" if ticket is None else "human_handoff",
        intent="unknown_policy",
        conversation_id=conversation_id,
        suggestions=[{"label": "转人工", "query": "转人工"}],
        refuse=True,
        handoff=ticket is not None,
        ticket=ticket,
        generator="refuse",
        notices=notices,
        rewrite=rewrite,
        reason=why,
    )


def _everyday(query: str, history: list, task_id: str, conversation_id: str, notices: list, rewrite, cfg: dict) -> dict:
    del cfg
    if not env("DEEPSEEK_API_KEY"):
        return _base(
            OFFLINE_CHAT,
            action="general_skill",
            intent="needs_model",
            conversation_id=conversation_id,
            generator="unavailable",
            notices=notices,
            rewrite=rewrite,
            reason="日常聊天需要对话模型",
        )
    if _stopped(task_id):
        return _stopped_payload(conversation_id)
    model = _complete(CHAT_SYSTEM, query, history, context="", temperature=0.6, task_id=task_id)
    text = (model or "").strip()
    generator = "deepseek"
    if not text:
        text = OFFLINE_CHAT
        generator = "unavailable"
    elif _banned(text):
        text = OFFLINE_CHAT
        generator = "guard"
    elif _LEAK_RE.search(text):
        text = LEAK_TEXT
        generator = "guard"
    return _base(
        text,
        action="general_skill",
        intent="needs_model" if generator == "unavailable" else "chitchat",
        conversation_id=conversation_id,
        generator=generator,
        notices=notices,
        rewrite=rewrite,
        reason="日常聊天，不引用校规",
    )


def _policy_text(chunk) -> str:
    lead, rest = _split_lead(chunk.answer)
    if lead and "[1]" not in lead:
        lead = f"{lead} [1]"
    parts = [lead]
    if rest:
        parts.append(rest)
    parts.append(f"依据：{chunk.document_name} · {chunk.title}")
    return "\n\n".join(part for part in parts if part)


def _accept_policy(answer: str, source: str) -> bool:
    text = _clean(answer)
    if not text or _banned(text):
        return False
    if any(phrase in text for phrase in ("知识库里没有", "不能编", "没有这条")):
        return False
    visible = _BASIS_RE.sub("", _MARK_RE.sub("", text))
    if set(_NUM_RE.findall(visible)) - set(_NUM_RE.findall(source)):
        return False
    if set(_CN_AMOUNT_RE.findall(visible)) - set(_CN_AMOUNT_RE.findall(source)):
        return False
    for run in _content_runs(visible):
        if run not in source:
            return False
    return True


def _complete(system: str, query: str, history: list, context: str, temperature: float, task_id: str) -> str | None:
    key = env("DEEPSEEK_API_KEY")
    if not key or _stopped(task_id):
        return None
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(_history_messages(history, query))
    if context:
        user = f"用户问题：{query}\n\n知识库片段：\n{context}"
    else:
        user = query
    messages.append({"role": "user", "content": user})
    body = {
        "model": env("DEEPSEEK_MODEL", "deepseek-chat") or "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 700,
        "stream": False,
    }
    url = env("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions")
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=45)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None
    with _GUARD:
        _RESPONSES[task_id] = response
        already = task_id in _STOPS
    if already:
        _close_response(task_id)
        return None
    try:
        raw = response.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError):
        return None
    finally:
        _close_response(task_id)
    if _stopped(task_id):
        return None
    try:
        payload = json.loads(raw)
        choices = payload.get("choices") or []
        if not choices:
            return None
        content = ((choices[0].get("message") or {}).get("content") or "").strip()
    except (json.JSONDecodeError, AttributeError, IndexError, TypeError):
        return None
    return _clean(content) or None


def _emit(req: dict, payload: dict, task_id: str, started: float):
    visitor = (req.get("visitor") or "").strip() or "anonymous"
    portal_session = str(req.get("portal_session") or "")[:80]
    question, _notices = mask_text((req.get("query") or "").strip())
    elapsed = int((time.perf_counter() - started) * 1000)
    body = dict(payload)
    body.setdefault("citations", [])
    body.setdefault("suggestions", [])
    body.setdefault("refuse", False)
    body.setdefault("handoff", False)
    body.setdefault("conversation_id", "")
    body["task_id"] = task_id
    body["message_id"] = ""
    body["streamed"] = True
    body["engine"] = "campus"
    body["latency_ms"] = elapsed
    body["trace"] = body.get("trace") or _trace(body, elapsed)
    if _stopped(task_id) and body.get("agent_action") not in ("safety",):
        body["answer"] = "（已停止生成）"
        body["stopped"] = True
    body["server_message_id"] = _persist(visitor, portal_session, question, body, elapsed)
    answer = body.get("answer") or ""
    step = 48
    for index in range(0, len(answer), step):
        if _stopped(task_id) and index:
            break
        yield {"type": "delta", "text": answer[index : index + step]}
    done = dict(body)
    done["type"] = "done"
    yield done


def _persist(visitor: str, portal_session: str, question: str, payload: dict, latency_ms: int) -> int:
    ticket = store.open_ticket(visitor, portal_session)
    ticket_id = ticket["id"] if ticket else None
    if payload.get("agent_action") != "agent_hold":
        store.add_message(visitor, "user", question, portal_session, ticket_id)
    message_id = store.add_message(
        visitor,
        "bot",
        payload.get("answer") or "",
        portal_session,
        ticket_id,
        author="校园助手",
        meta={
            "agent_action": payload.get("agent_action"),
            "refuse": payload.get("refuse"),
            "citations": payload.get("citations") or [],
            "suggestions": payload.get("suggestions") or [],
            "ticket_id": payload.get("ticket_id") or "",
            "engine": "campus",
        },
    )
    rewrite = payload.get("rewrite") if isinstance(payload.get("rewrite"), dict) else {}
    trace = payload.get("trace") or []
    if payload.get("maintenance"):
        decision = "知识库维护"
    elif payload.get("refuse"):
        decision = "拒答"
    elif payload.get("agent_action") == "human_handoff":
        decision = "转人工"
    else:
        decision = _label(str(payload.get("agent_action") or "通过"))
    store.add_judgment(
        visitor,
        portal_session,
        question,
        str(rewrite.get("rewritten") or ""),
        decision,
        str(payload.get("reason") or payload.get("intent") or ""),
        trace,
        latency_ms,
        ticket_id=ticket_id,
        message_id=message_id,
    )
    citations = payload.get("citations") or []
    source = "、".join(item.get("document_name") or "" for item in citations[:3])
    store.add_audit(
        "qa",
        actor="访客",
        session_ref=(portal_session or visitor)[:24],
        question=question,
        decision=decision,
        source=source,
        latency_ms=latency_ms,
        detail={"trace": trace, "ticket_id": payload.get("ticket_id") or "", "engine": "campus"},
    )
    return message_id


def _trace(payload: dict, latency_ms: int) -> list:
    rewrite = payload.get("rewrite") if isinstance(payload.get("rewrite"), dict) else None
    citations = payload.get("citations") or []
    titles = "、".join(item.get("title") or item.get("document_name") or "" for item in citations[:3])
    return [
        {"step": "打码", "ok": True, "detail": payload.get("masked_notice") or "没有手机号或证件号", "ms": 0},
        {"step": "意图", "ok": True, "detail": _label(str(payload.get("intent") or "")), "ms": 0},
        {"step": "改写", "ok": True, "detail": rewrite["rewritten"] if rewrite else "按原问题检索", "ms": 0},
        {
            "step": "检索",
            "ok": not payload.get("refuse"),
            "detail": titles or _label(str(payload.get("reason") or "未命中")),
            "ms": 0,
        },
        {"step": "约束", "ok": True, "detail": str(payload.get("reason") or "按路由作答"), "ms": 0},
        {"step": "输出", "ok": True, "detail": _label(str(payload.get("agent_action") or "")), "ms": latency_ms},
    ]


def _base(
    answer: str,
    *,
    action: str,
    intent: str,
    conversation_id: str,
    suggestions=(),
    citations=None,
    refuse: bool = False,
    clarify: bool = False,
    handoff: bool = False,
    ticket: dict | None = None,
    generator: str = "template",
    notices: list | None = None,
    rewrite=None,
    title: str | None = None,
    reason: str = "",
    retrieval=None,
    maintenance: bool = False,
) -> dict:
    notice = notice_line(notices or [])
    text = answer or ""
    if notice and "已隐去" not in text:
        text = notice + "\n\n" + text
    payload = {
        "answer": text,
        "citations": list(citations or []),
        "suggestions": list(suggestions or []),
        "refuse": refuse,
        "clarify": clarify,
        "handoff": handoff or action == "human_handoff",
        "agent_action": action,
        "intent": intent,
        "engine": "campus",
        "generator": generator,
        "conversation_id": conversation_id,
        "matched_title": title,
        "reason": reason,
        "rewrite": rewrite,
        "retrieval": list(retrieval or citations or []),
        "maintenance": maintenance,
        "queue": bool(ticket) or action in ("human_handoff", "maintenance"),
        "masked_notice": notice,
    }
    if ticket:
        payload["ticket_id"] = ticket.get("public_id") or ""
        payload["ticket_status"] = ticket.get("status") or ""
        payload["handoff"] = True
    return payload


def _ticket_payload(ticket: dict, text: str, action: str, conversation_id: str, notices: list, rewrite=None, maintenance: bool = False, reason: str = "") -> dict:
    full = text
    public_id = ticket.get("public_id") or ""
    if public_id and public_id not in full:
        full = f"{text}\n\n工单 {public_id}。"
    return _base(
        full,
        action=action,
        intent=action,
        conversation_id=conversation_id,
        ticket=ticket,
        handoff=True,
        maintenance=maintenance,
        notices=notices,
        rewrite=rewrite,
        reason=reason or _label(action),
        generator="handoff",
    )


def _stopped_payload(conversation_id: str) -> dict:
    return _base(
        "（已停止生成）",
        action="general_skill",
        intent="stopped",
        conversation_id=conversation_id,
        generator="stopped",
        reason="访客停止了生成",
    )


def _maintenance_on() -> bool:
    probe = store.latest_probe()
    return bool(probe and not probe.get("ok"))


def _needs_kb(query: str, found: dict) -> bool:
    if found.get("action") in ("answer", "clarify"):
        return True
    return bool(_ADMIN_RE.search(query))


def _creative(query: str) -> bool:
    if not _CREATIVE_RE.search(query or ""):
        return False
    return _HARD_ADMIN_RE.search(query or "") is None


def _mentions_admin(query: str) -> bool:
    return bool(_ADMIN_RE.search(query or "") or _policy_query(query))


def _without_writing_lead(query: str) -> str:
    stripped = _WRITE_LEAD_RE.sub("", query or "").strip()
    return stripped or query


def _content_runs(text: str) -> list[str]:
    runs: list[str] = []
    for raw in _CONTENT_RUN_RE.findall(text or ""):
        run = raw.strip(_FUNC_EDGE)
        if len(run) >= 2:
            runs.append(run)
    return runs


def _query_fits_chunk(query: str, chunk) -> bool:
    """Short queries must not add a character the matched segment never uses.

    Longer questions are left to the lexical index. Paraphrase particles such as
    想 / 怎样 are not extra constraints. A real extra word on a short question
    still blocks the hit.
    """
    if _chars_fit(query, chunk):
        return True
    folded = (query or "").replace("不凉", "不制冷").replace("不冷", "不制冷").replace("想改期", "改期")
    return folded != (query or "") and _chars_fit(folded, chunk)


def _chars_fit(query: str, chunk) -> bool:
    raw = [
        char
        for char in norm_key(query)
        if "\u4e00" <= char <= "\u9fff" and char not in _FUNC_EDGE
    ]
    if len(raw) > 4:
        return True
    chars = [char for char in raw if char not in _SOFT_CHARS]
    if not chars:
        return True
    blob = norm_key(f"{chunk.title}\n{chunk.answer}")
    return all(char in blob for char in chars)


def _clears_threshold(found: dict, cfg: dict) -> bool:
    scores = list(found.get("scores") or [])
    if not scores:
        return False
    try:
        bar = float(cfg.get("score_threshold") if cfg.get("score_threshold") is not None else 0.5)
    except (TypeError, ValueError):
        bar = 0.5
    best = confidence(float(scores[0]), str(found.get("method") or ""), str(found.get("reason") or ""))
    return best >= bar


def _outside_campus(query: str) -> bool:
    return bool(_OUTSIDE_CAMPUS_RE.search(query or ""))


def _attach_related(citations: list, chunk) -> None:
    if not citations:
        return
    card = citations[0]
    if card.get("document_name") != getattr(chunk, "document_name", ""):
        return
    seen = {(card.get("content") or "").strip()}
    for segment in card.get("segments") or []:
        if isinstance(segment, dict):
            seen.add((segment.get("content") or "").strip())
    for extra in related_segments(chunk, limit=2):
        text = (extra.answer or "").strip()
        if not text or text in seen:
            continue
        card.setdefault("segments", []).append(
            {
                "content": text[:800],
                "score": 0.5,
                "segment_id": extra.id,
                "title": extra.title,
            }
        )
        seen.add(text)


def _previous_user(history: list, current: str) -> str:
    current_key = (current or "").strip()
    for text in reversed(last_user_turns(history, 6)):
        cleaned = text.strip()
        if not cleaned or cleaned == current_key or norm_key(cleaned) == norm_key(current_key):
            continue
        if is_followup_query(cleaned):
            continue
        return cleaned
    return ""


def _bridge_tokens(text: str) -> list[str]:
    folded = norm_key(text)
    folded = folded.replace("不凉", "不制冷").replace("不冷", "不制冷").replace("想改期", "改期")
    for skip in sorted(_BRIDGE_SKIP, key=len, reverse=True):
        piece = norm_key(skip)
        if piece:
            folded = folded.replace(piece, "|")
    return [part for part in folded.split("|") if len(part) >= 2]


def _history_pack(chunk) -> dict:
    return {
        "action": "answer",
        "chunks": [chunk],
        "reason": "history",
        "scores": [4.0],
        "method": "lexical",
    }


def _with_history(lookup: str, history: list, found: dict) -> dict:
    if not history:
        return found
    if found.get("action") == "clarify":
        chosen = _history_candidate(found, history, lookup)
        return chosen if chosen is not None else found
    if found.get("action") != "none":
        return found
    if len(norm_key(lookup)) > 18:
        return found
    bridged = _history_bridge(lookup, history)
    return bridged if bridged is not None else found


def _history_candidate(found: dict, history: list, lookup: str) -> dict | None:
    prev = _previous_user(history, lookup)
    if not prev:
        return None
    chunks = list(found.get("chunks") or [])
    for concept in topic_terms(prev):
        hits = [chunk for chunk in chunks if concept in norm_key(chunk.title)]
        if len(hits) == 1:
            return _history_pack(hits[0])
    return None


def _history_bridge(lookup: str, history: list) -> dict | None:
    prev = _previous_user(history, lookup)
    if not prev:
        return None
    concepts = topic_terms(prev)
    tokens = _bridge_tokens(lookup)
    if not concepts or not tokens:
        return None
    hits = []
    for chunk in get_index().chunks:
        title = norm_key(chunk.title)
        if not any(concept in title for concept in concepts):
            continue
        if not any(token in title for token in tokens):
            continue
        hits.append(chunk)
    if len(hits) == 1:
        return _history_pack(hits[0])
    return None


def _policy_query(query: str) -> bool:
    return _policy_shaped(query)


def _norm(text: str) -> str:
    return norm_key(text)


def _banned(text: str) -> bool:
    return bool(_BANNED_RE.search(text or ""))


def _clean(text: str) -> str:
    return _THINK_RE.sub("", text or "").strip()


def _mask_history(history: list) -> list:
    safe = []
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        for field in ("text", "content", "query"):
            if copied.get(field):
                copied[field], _ignored = mask_text(str(copied[field]))
        safe.append(copied)
    return safe


def _history_messages(history: list, query: str) -> list[dict]:
    turns: list[dict] = []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or "").lower()
        if role == "bot":
            role = "assistant"
        if role not in ("user", "assistant"):
            continue
        text = (item.get("text") or item.get("content") or "").strip()
        if text:
            turns.append({"role": role, "content": text[:800]})
    if turns and turns[-1]["role"] == "user" and turns[-1]["content"] == (query or "").strip():
        turns.pop()
    return turns


def _close_response(task_id: str) -> None:
    with _GUARD:
        response = _RESPONSES.pop(task_id, None)
    if response is None:
        return
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except OSError:
            pass
