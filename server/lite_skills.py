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

_LIMIT_RE = re.compile(r"(代考|替考|改分|黑客|破解密码|入侵|攻击学校)")
_PASSWORD_RE = re.compile(r"(密码对不对|试试这个密码|这个密码对吗|帮我试密码|试密码|猜密码)")
_DIAG_RE = re.compile(r"(是不是得了|得了什么病|帮我诊断|诊断一下|开点药|吃什么药)")
_WEATHER_RE = re.compile(r"(天气怎么样|天气如何|今天天气|气温多少|会不会下雨|会不会下雪|降温了吗)")
_THANKS_RE = re.compile(r"^(谢谢|谢谢你|多谢|感谢)[了呀啊哦！!。.~～]*$")
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
        "answer": f"{shown} = {_fmt_num(value)}。",
        "intent": "math",
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
        "answer": line,
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
        "answer": line,
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
            "answer": "把要整理的句子发在冒号后面，例如：润色：我明天去教务处取在读证明。",
            "intent": "polish",
            "refuse": False,
            "suggestions": (),
            "generator": "skill",
        }
    cleaned = re.sub(r"[ \t]+", " ", body)
    cleaned = cleaned.replace(",", "，").replace(".", "。")
    cleaned = re.sub(r"\s*\n\s*", "\n", cleaned).strip()
    return {
        "answer": f"我只整理了标点和空白：\n\n{cleaned}",
        "intent": "polish",
        "refuse": False,
        "suggestions": (),
        "generator": "skill",
    }


def _exact_gloss(source: str, target: str) -> str | None:
    """Only phrases stored in the campus glossary. Anything else needs a model."""
    phrase = (source or "").strip()
    if target in ("中文", "汉语"):
        for zh, en in _GLOSSARY:
            if phrase.lower() == en.lower():
                return zh
        return None
    for zh, en in _GLOSSARY:
        if phrase == zh:
            return en
    return None


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
        return None
    rendered = _exact_gloss(hit.group(1).strip(), hit.group(2))
    if rendered is None:
        return None
    return {
        "answer": rendered,
        "intent": "translate",
        "refuse": False,
        "suggestions": (),
        "generator": "skill",
    }


def _skill(answer: str, intent: str) -> dict:
    return {
        "answer": answer,
        "intent": intent,
        "refuse": False,
        "suggestions": (),
        "generator": "skill",
    }


def try_skill(query: str) -> dict | None:
    """Deterministic helpers only. Open chat returns None so a model can take it."""
    q = (query or "").strip()
    if not q:
        return None
    if _WEATHER_RE.search(q):
        return _skill("我看不到实时天气，没法告诉你今天怎么样。", "weather")
    if _LIMIT_RE.search(q):
        return _skill("改分、代考和攻击系统这些我做不了。", "limit")
    if _PASSWORD_RE.search(q):
        return _skill("我没法帮你对密码，也别把密码发在对话里。", "limit")
    if _DIAG_RE.search(q):
        return _skill("我判断不了你是不是生病了，也不能开药。", "limit")
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
    if _THANKS_RE.match(q):
        return _skill("不客气。", "chitchat")
    return None
