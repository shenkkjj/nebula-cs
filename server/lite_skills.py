#!/usr/bin/env python3
"""Local skills for the lite campus assistant.

Stdlib only: arithmetic, a campus-phrase glossary, unit conversion, and
clock wording. No model and no network. Campus rules are not invented here.
"""
from __future__ import annotations

import ast
import math
import operator
import re
from datetime import datetime
from zoneinfo import ZoneInfo

# Continuous personal identifiers. Order numbers such as SW20260001 do not match.
_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_BANK_RE = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
_MED_RE = re.compile(r"(病历|病例|化验单|出院小结|出院记录|诊断证明|诊断书)")

_NONCAMPUS_RE = re.compile(r"(火星|月球|外太空|外星人)")
_PARTY_RE = re.compile(r"(入党申请|入党志愿|思想汇报)")
_UNSAFE_RE = re.compile(
    r"(写作业|做作业|代写|写论文|写毕业论文|课程论文|代考|替考|改分|"
    r"黑客|破解密码|入侵|攻击学校)"
)
_PASSWORD_RE = re.compile(r"(密码对不对|试试这个密码|这个密码对吗|帮我试密码|试密码|猜密码)")
_DIAG_RE = re.compile(r"(是不是得了|得了什么病|帮我诊断|诊断一下|开点药|吃什么药)")
_SYMPTOM_RE = re.compile(r"(头疼|头痛|发烧|咳嗽|腹泻|失眠).{0,8}(怎么办|是不是|要不要)")
_INVEST_RE = re.compile(r"(股票|基金怎么买|比特币|彩票|炒股|怎么投资)")
_POEM_RE = re.compile(r"(写一首诗|写首诗|作一首诗|来首诗|作首诗)")
_WEATHER_RE = re.compile(r"(天气|气温|下雨|降温|会不会下雪)")
_MOVIE_RE = re.compile(r"推荐.{0,8}(电影|片子|影视|剧)")
_FOOD_RE = re.compile(r"((今晚|今天|中午|早上|下午).{0,6}吃什么|吃啥|吃什么好)")
_THANKS_RE = re.compile(r"^(谢谢|谢谢你|多谢|感谢|好的|知道了|嗯嗯)[了呀啊哦！!。.~～]*$")
_POLISH_RE = re.compile(r"^(?:请|帮我|麻烦)?(?:润色|改通顺|顺一下|理顺)(?:一下)?(?:这句|这段)?[：:\s]*(.*)$")

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}

# Longest phrase first. Campus wording only; not a general translator.
_GLOSSARY = (
    ("在读证明如何办理", "How do I apply for a certificate of enrollment?"),
    ("学籍证明和在读证明有什么区别", "What is the difference between a student-status certificate and a certificate of enrollment?"),
    ("在读证明", "certificate of enrollment"),
    ("学籍证明", "student-status certificate"),
    ("如何办理", "how to apply"),
    ("怎么办理", "how to apply"),
    ("成绩单", "academic transcript"),
    ("助学贷款", "student loan"),
    ("校园地贷款", "on-campus student loan"),
    ("生源地", "home-region student loan"),
    ("校园网", "campus network"),
    ("宿舍门禁", "dormitory access control"),
    ("门禁", "access control"),
    ("教室借用", "classroom booking"),
    ("一网通办", "the one-stop campus service portal"),
    ("寒暑假", "winter and summer break"),
    ("图书馆", "library"),
    ("宿舍", "dormitory"),
    ("水电", "dormitory water and electricity"),
    ("转人工", "transfer to a staff member"),
    ("奖学金", "scholarship"),
    ("学费", "tuition"),
)

_NEXT_CAMPUS = (
    {"label": "在读证明", "query": "在读证明如何办理？"},
    {"label": "助学贷款", "query": "国家助学贷款如何申请？"},
    {"label": "转人工", "query": "转人工"},
)
_NEXT_WEATHER = (
    {"label": "图书馆开放时间", "query": "图书馆开放时间是什么？"},
    {"label": "假期作息", "query": "寒暑假校园作息怎么安排？"},
    {"label": "办事窗口", "query": "办事窗口在哪里，办公时间是什么？"},
)
_NEXT_FOOD = (
    {"label": "假期食堂", "query": "假期食堂开放时间是什么？"},
    {"label": "节假日食堂", "query": "法定节假日食堂和办公怎么安排？"},
)
_NEXT_MOVIE = (
    {"label": "图书馆开放时间", "query": "图书馆开放时间是什么？"},
    {"label": "体育馆", "query": "体育馆如何预约？"},
    {"label": "教室借用", "query": "教室借用怎么申请？"},
)
_NEXT_MEDICAL = (
    {"label": "预约校医院", "query": "校医院如何预约挂号？"},
    {"label": "夜间不适", "query": "夜间身体不适或心理危机找谁？"},
    {"label": "转人工", "query": "转人工"},
)
_NEXT_PASSWORD = (
    {"label": "门户密码和校园网", "query": "信息门户密码和校园网密码一样吗？"},
    {"label": "账号锁定", "query": "校园网账号锁定怎么办？"},
    {"label": "转人工", "query": "转人工"},
)
_NEXT_MONEY = (
    {"label": "学费", "query": "学费如何缴纳？"},
    {"label": "助学贷款", "query": "国家助学贷款如何申请？"},
    {"label": "转人工", "query": "转人工"},
)

_POEM = (
    "路灯沿着林荫道一盏盏亮起来，\n"
    "自习室的窗还留着一小块暖光。\n"
    "问题不必一次问完，\n"
    "我在这里，听你把事情说清楚。"
)

_UNIT_FACTORS = {
    ("公里", "米"): 1000.0,
    ("千米", "米"): 1000.0,
    ("km", "米"): 1000.0,
    ("km", "m"): 1000.0,
    ("米", "厘米"): 100.0,
    ("米", "cm"): 100.0,
    ("千克", "克"): 1000.0,
    ("公斤", "克"): 1000.0,
    ("小时", "分钟"): 60.0,
    ("小时", "秒"): 3600.0,
    ("分钟", "秒"): 60.0,
}


def contains_sensitive(text: str) -> bool:
    """True when the user pasted an ID, a card number, or a medical record."""
    raw = text or ""
    if "已隐去" in raw:
        return True
    if _ID_RE.search(raw) or _BANK_RE.search(raw):
        return True
    if _MED_RE.search(raw) and (len(raw) > 36 or "\n" in raw or re.search(r"\d{6,}", raw)):
        return True
    return False


def redact_sensitive(text: str) -> str:
    raw = text or ""
    if _MED_RE.search(raw) and (len(raw) > 36 or "\n" in raw or re.search(r"\d{6,}", raw)):
        return "［病历内容已隐去，请勿在对话中发送］"
    raw = _ID_RE.sub("［身份证号已隐去］", raw)
    raw = _BANK_RE.sub("［卡号已隐去］", raw)
    return raw


def ticket_sensitive_message(*parts: str) -> str | None:
    blob = "\n".join(p or "" for p in parts)
    if not contains_sensitive(blob):
        return None
    return (
        "请不要在工单里填写身份证号、银行卡号或病历，这次没有登记。"
        "去掉这些内容后再提交；身份核验请到窗口，或在对话里说「转人工」。"
    )


def safety_payload(redacted: str) -> dict:
    return {
        "answer": (
            "请不要在对话里发送身份证号、银行卡号或病历。这些内容我没有留下。\n\n"
            "办证、资助或就诊需要核验身份时，请到对应窗口，或转人工，由工作人员当面处理。"
            "我可以先告诉你办事窗口在哪里。"
        ),
        "intent": "safety",
        "refuse": False,
        "suggestions": (
            {"label": "办事窗口", "query": "办事窗口在哪里，办公时间是什么？"},
            {"label": "转人工", "query": "转人工"},
        ),
        "generator": "safety",
        "sensitive": True,
        "redacted_query": redacted,
    }


def _cn_to_int(text: str) -> int:
    if not text:
        raise ValueError("empty")
    total = 0
    section = 0
    number = 0
    for ch in text:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
            continue
        unit = _CN_UNITS.get(ch)
        if unit is None:
            raise ValueError("bad digit")
        if unit == 10000:
            section = (section + number) * unit
            total += section
            section = 0
            number = 0
            continue
        section += (number or 1) * unit
        number = 0
    return total + section + number


def _cn_to_number(text: str) -> float:
    token = (text or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", token):
        return float(token) if "." in token else int(token)
    if "点" in token:
        whole, frac = token.split("点", 1)
        if not frac or any(ch not in _CN_DIGITS for ch in frac):
            raise ValueError("bad decimal")
        base = _cn_to_int(whole) if whole else 0
        digits = "".join(str(_CN_DIGITS[ch]) for ch in frac)
        return float(f"{base}.{digits}")
    return _cn_to_int(token)


def _fmt_num(value: float) -> str:
    if isinstance(value, float) and math.isfinite(value) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return f"{value:.6g}"


_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("const")
        if abs(node.value) > 1e12:
            raise ValueError("big")
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > 8 or abs(left) > 1e6:
                raise ValueError("pow")
            return left ** right
        fn = _BINOPS.get(type(node.op))
        if fn is None:
            raise ValueError("op")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise ZeroDivisionError
        return fn(left, right)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id != "sqrt":
            raise ValueError("call")
        if len(node.args) != 1 or node.keywords:
            raise ValueError("args")
        value = _eval_node(node.args[0])
        if value < 0:
            raise ValueError("sqrt")
        return math.sqrt(value)
    raise ValueError("node")


def _safe_calc(expr: str) -> float:
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree)


def _strip_math_wrapper(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"^(请问|帮我|请|麻烦|算一下|计算一下|帮我算|计算|算一算)\s*", "", s)
    s = re.sub(r"(是多少|等于多少|等于几|是几|得多少)[？?。!！]*$", "", s)
    return s.strip("？?。!！ ")


def _normalize_expr(text: str) -> str:
    s = text.replace("×", "*").replace("÷", "/").replace("＋", "+").replace("－", "-")
    s = s.replace("（", "(").replace("）", ")").replace("x", "*").replace("X", "*")
    s = s.replace("√", "sqrt").replace("^", "**")
    s = re.sub(r"\s+", "", s)
    s = s.replace("sqrt", "sqrt")
    return s


def _try_math(query: str) -> dict | None:
    if re.search(r"\b(SW|BX|JY)\d{6,}\b", query, re.IGNORECASE):
        return None
    s = _strip_math_wrapper(query)
    if not s or len(s) > 64:
        return None

    root = re.fullmatch(r"(.+?)的平方根", s)
    square = re.fullmatch(r"(.+?)的平方", s)
    cube = re.fullmatch(r"(.+?)的立方", s)
    shown = s
    expr = ""
    try:
        if root:
            number = _cn_to_number(root.group(1))
            if number < 0:
                raise ValueError("sqrt")
            value = math.sqrt(number)
            shown = f"{root.group(1)}的平方根"
        elif square:
            number = _cn_to_number(square.group(1))
            value = number ** 2
            shown = f"{square.group(1)}的平方"
        elif cube:
            number = _cn_to_number(cube.group(1))
            if abs(number) > 1e6:
                raise ValueError("pow")
            value = number ** 3
            shown = f"{cube.group(1)}的立方"
        else:
            pair = re.fullmatch(
                r"(.+?)(加上|减去|乘以|除以|加|减|乘|除)(.+)",
                s,
            )
            if pair and re.search(r"[\u4e00-\u9fff]", s):
                left = _cn_to_number(pair.group(1))
                right = _cn_to_number(pair.group(3))
                op = pair.group(2)
                if op in ("加", "加上"):
                    value = left + right
                elif op in ("减", "减去"):
                    value = left - right
                elif op in ("乘", "乘以"):
                    value = left * right
                else:
                    if right == 0:
                        raise ZeroDivisionError
                    value = left / right
                shown = s
            else:
                expr = _normalize_expr(s)
                if not re.fullmatch(r"(?:sqrt\(\d+(?:\.\d+)?\)|[\d.+\-*/%()])+", expr):
                    return None
                if not re.search(r"\d", expr):
                    return None
                if not re.search(r"[+\-*/]|sqrt", expr):
                    return None
                value = _safe_calc(expr)
                shown = expr.replace("**", "^")
    except (ValueError, ZeroDivisionError, SyntaxError, OverflowError):
        if re.fullmatch(r"[\d\s.+\-*/×÷xX＋－%％()（）^√]+", s) or s.endswith("的平方根"):
            return {
                "answer": "这个算式我没有算成。可以写成 15*24+8，或「二十五的平方根」。",
                "intent": "math",
                "refuse": False,
                "suggestions": (),
                "generator": "skill",
            }
        return None
    if not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value) > 1e12:
        return {
            "answer": "这个数太大了，我没有继续算。",
            "intent": "math",
            "refuse": False,
            "suggestions": (),
            "generator": "skill",
        }
    return {
        "answer": (
            f"{shown} = {_fmt_num(value)}。\n\n"
            "这是本地计算，不是校园规定，也没有知识库出处。"
        ),
        "intent": "math",
        "refuse": False,
        "suggestions": (),
        "generator": "skill",
    }


def _translate_with_glossary(source: str, target: str) -> str:
    text = source.strip()
    if target in ("中文", "汉语"):
        return (
            "我这边没有在线翻译，本地词表是从校园用语译向英文，译不回任意中文。\n\n"
            "可以把校园里的中文说法发我，例如「在读证明如何办理」。"
        )
    pieces: list[str] = []
    known = 0
    remaining = text
    while remaining:
        matched = False
        for zh, en in _GLOSSARY:
            if remaining.startswith(zh):
                pieces.append(en)
                known += len(zh)
                remaining = remaining[len(zh) :]
                matched = True
                break
        if matched:
            continue
        unknown: list[str] = []
        while remaining and not any(remaining.startswith(zh) for zh, _en in _GLOSSARY):
            ch = remaining[0]
            remaining = remaining[1:]
            if ch.strip() and ch not in "，。、？?！!：:；;「」\"“”":
                unknown.append(ch)
        if unknown:
            pieces.append("〔" + "".join(unknown) + "〕")
    if not text:
        return "把要翻译的校园说法放在引号里，例如：把「在读证明如何办理」译成英文。"
    if known == 0 or known / max(1, len(re.sub(r"\s+", "", text))) < 0.45:
        partial = " ".join(pieces).strip()
        extra = f"\n\n能对上词表的只有：{partial}" if known else ""
        return (
            "我没有在线翻译引擎，本地只有校园办事词表，这句话译不全。"
            f"{extra}\n\n"
            "可以缩短成「在读证明」「助学贷款」这种说法，或转人工。"
        )
    english = " ".join(pieces).strip()
    return (
        f"「{text}」可译为：{english}\n\n"
        "这是本地校园词表的直译，不是在线翻译。办理规则仍以知识库中文说明为准。"
    )


def _try_translate(query: str) -> dict | None:
    quoted = re.search(
        r"(?:把|将)\s*[「\"“『](.+?)[」\"”』]\s*(?:译成|翻译成|翻成)\s*(英文|英语|中文|汉语)",
        query,
    )
    plain = None
    if quoted is None:
        plain = re.search(
            r"(?:把|将)\s*(.+?)\s*(?:译成|翻译成|翻成)\s*(英文|英语|中文|汉语)\s*$",
            query.strip(),
        )
    hit = quoted or plain
    if hit is None:
        if re.fullmatch(r"(?:帮我)?翻译一下[：:\s]*.+", query.strip()) or query.strip() in ("翻译", "帮我翻译"):
            return {
                "answer": (
                    "可以说：把「在读证明如何办理」译成英文。\n\n"
                    "我没有在线翻译，只能用本地校园词表直译常见办事说法。"
                ),
                "intent": "translate",
                "refuse": False,
                "suggestions": ({"label": "译在读证明", "query": "把「在读证明如何办理」译成英文"},),
                "generator": "skill",
            }
        return None
    source, target = hit.group(1).strip(), hit.group(2)
    return {
        "answer": _translate_with_glossary(source, target),
        "intent": "translate",
        "refuse": False,
        "suggestions": (),
        "generator": "skill",
    }


def _try_unit(query: str) -> dict | None:
    text = query.strip().rstrip("？?。")
    temp_c = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(?:摄氏度|℃|度C)\s*(?:等于|是|换算成)?\s*多少\s*(?:华氏度|℉)", text, re.I)
    temp_f = re.fullmatch(r"(-?\d+(?:\.\d+)?)\s*(?:华氏度|℉|度F)\s*(?:等于|是|换算成)?\s*多少\s*(?:摄氏度|℃)", text, re.I)
    if temp_c:
        value = float(temp_c.group(1)) * 9 / 5 + 32
        return _unit_answer(f"{temp_c.group(1)} 摄氏度 = {_fmt_num(value)} 华氏度。")
    if temp_f:
        value = (float(temp_f.group(1)) - 32) * 5 / 9
        return _unit_answer(f"{temp_f.group(1)} 华氏度 = {_fmt_num(value)} 摄氏度。")
    hit = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*([A-Za-z]{1,8}|[\u4e00-\u9fff]{1,4})\s*(?:等于|是|换算成)\s*多少\s*([A-Za-z]{1,8}|[\u4e00-\u9fff]{1,4})",
        text,
        re.I,
    )
    if not hit:
        return None
    amount = float(hit.group(1))
    src = hit.group(2).lower() if hit.group(2).isascii() else hit.group(2)
    dst = hit.group(3).lower() if hit.group(3).isascii() else hit.group(3)
    factor = _UNIT_FACTORS.get((src, dst))
    if factor is None:
        return None
    return _unit_answer(f"{_fmt_num(amount)} {hit.group(2)} = {_fmt_num(amount * factor)} {hit.group(3)}。")


def _unit_answer(line: str) -> dict:
    return {
        "answer": line + "\n\n这是单位换算，不是校园规定。",
        "intent": "unit",
        "refuse": False,
        "suggestions": (),
        "generator": "skill",
    }


def _try_clock(query: str) -> dict | None:
    text = query.strip().rstrip("？?。!！")
    if re.search(r"(开放|门禁|食堂|办公|作息|放假)", text):
        return None
    if text not in ("现在几点", "现在几点了", "现在什么时间", "现在是什么时间", "今天几号", "今天日期", "今天星期几", "今天周几"):
        return None
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    week = "一二三四五六日"[now.weekday()]
    if text.startswith("现在"):
        line = f"现在是北京时间 {now:%H:%M}（{now:%Y-%m-%d}）。"
    elif "星期" in text or "周几" in text:
        line = f"今天是北京时间 {now:%Y-%m-%d}，星期{week}。"
    else:
        line = f"今天是北京时间 {now:%Y年%m月%d日}，星期{week}。"
    return {
        "answer": line + "\n\n我只能报服务器上的北京时间，不能查看天气。",
        "intent": "datetime",
        "refuse": False,
        "suggestions": (),
        "generator": "skill",
    }


def _try_polish(query: str) -> dict | None:
    hit = _POLISH_RE.match(query.strip())
    if hit is None:
        return None
    body = (hit.group(1) or "").strip()
    if not body:
        return {
            "answer": "把要整理的句子发在后面，例如：润色：我明天去教务处取在读证明。我只整理标点和空白，不改写意思，也不代写申请。",
            "intent": "polish",
            "refuse": False,
            "suggestions": (),
            "generator": "skill",
        }
    cleaned = re.sub(r"[ \t]+", " ", body)
    cleaned = cleaned.replace(",", "，").replace(".", "。")
    cleaned = re.sub(r"\s*\n\s*", "\n", cleaned).strip()
    return {
        "answer": (
            f"只整理了标点和空白，意思没有改：\n\n{cleaned}\n\n"
            "我没有通用润色模型，不能替你重写内容。"
        ),
        "intent": "polish",
        "refuse": False,
        "suggestions": (),
        "generator": "skill",
    }


def _refuse(answer: str, intent: str, suggestions: tuple[dict, ...] = _NEXT_CAMPUS) -> dict:
    return {
        "answer": answer,
        "intent": intent,
        "refuse": True,
        "suggestions": suggestions,
        "generator": "refuse",
    }


def try_skill(query: str) -> dict | None:
    """Match a local skill or a narrow refusal. None means the FAQ router may run."""
    q = (query or "").strip()
    if not q:
        return None
    if _NONCAMPUS_RE.search(q):
        return {
            "answer": (
                "这个不在校园客服能回答的范围内，我也没有相关依据。\n\n"
                "校园办事、简单计算和校园用语短翻译可以继续问；需要工作人员就转人工。"
            ),
            "intent": "boundary",
            "refuse": False,
            "suggestions": _NEXT_CAMPUS,
            "generator": "skill",
        }
    if _PARTY_RE.search(q):
        return _refuse(
            "我不能代写入党申请书或思想汇报，也不会把它说成已经有的办事说明。"
            "知识库里没有这类文书，我不能编一份正式口径。\n\n"
            "材料请按组织员或学院通知准备。我能继续查在读证明、奖助和宿舍；需要人处理就转人工。",
            "refuse",
        )
    if _UNSAFE_RE.search(q):
        return _refuse(
            "这件事我不能做：代写作业或论文、改分、代考，以及任何攻击系统的要求，都不在客服范围内。\n\n"
            "你可以问具体的校园办事，或把你自己写好的一句话发来，我只能做标点和空白整理。需要老师或工作人员时请转人工。",
            "refuse",
        )
    if _PASSWORD_RE.search(q):
        return _refuse(
            "我不能帮你试密码，也不会判断对不对。请不要在对话里发送密码，我没有核对过任何口令。\n\n"
            "如果是校园网或信息门户登录不上，可以看下面的说明，或转人工。",
            "refuse",
            _NEXT_PASSWORD,
        )
    if _DIAG_RE.search(q) or _SYMPTOM_RE.search(q):
        return _refuse(
            "我不能判断病情，也不能建议吃药。\n\n"
            "需要就诊可以先看校医院怎么预约；紧急情况请联系校医院急诊或转人工。我这里没有诊断依据。",
            "refuse",
            _NEXT_MEDICAL,
        )
    if _INVEST_RE.search(q):
        return _refuse(
            "我不能提供股票、基金或彩票方面的投资建议。\n\n"
            "和钱有关、我能按知识库回答的，是学费、奖助和助学贷款怎么办理，不是理财。需要工作人员就转人工。",
            "refuse",
            _NEXT_MONEY,
        )
    if _POEM_RE.search(q):
        return {
            "answer": "好，这是一段闲聊小诗，不是校园规定：\n\n" + _POEM,
            "intent": "poem",
            "refuse": False,
            "suggestions": (),
            "generator": "skill",
        }
    if _WEATHER_RE.search(q):
        return {
            "answer": (
                "我查不到实时天气，也不能编一个预报。\n\n"
                "如果是要出门办事，我可以按知识库说明图书馆、食堂或窗口的开放安排。直接点下面的问题就行。"
            ),
            "intent": "weather",
            "refuse": False,
            "suggestions": _NEXT_WEATHER,
            "generator": "skill",
        }
    math_hit = _try_math(q)
    if math_hit is not None:
        return math_hit
    translated = _try_translate(q)
    if translated is not None:
        return translated
    unit = _try_unit(q)
    if unit is not None:
        return unit
    clock = _try_clock(q)
    if clock is not None:
        return clock
    polished = _try_polish(q)
    if polished is not None:
        return polished
    if _MOVIE_RE.search(q):
        return {
            "answer": (
                "我没有影片库，不能认真推荐具体的一部电影。\n\n"
                "想安排在学校里的时间，可以问图书馆、体育馆或教室借用，我按知识库回答。"
            ),
            "intent": "chitchat",
            "refuse": False,
            "suggestions": _NEXT_MOVIE,
            "generator": "skill",
        }
    if _FOOD_RE.search(q):
        return {
            "answer": (
                "我不能替你决定吃什么，也没有食堂菜单。\n\n"
                "想查食堂什么时候开，点下面的问题，我按知识库说明。"
            ),
            "intent": "chitchat",
            "refuse": False,
            "suggestions": _NEXT_FOOD,
            "generator": "skill",
        }
    if _THANKS_RE.match(q):
        return {
            "answer": "不客气。还有办事问题可以直接问，或者说转人工。",
            "intent": "chitchat",
            "refuse": False,
            "suggestions": _NEXT_CAMPUS[:2],
            "generator": "skill",
        }
    return None
