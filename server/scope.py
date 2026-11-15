"""Greetings and non-campus requests stay on the gateway. The model is not asked."""
from __future__ import annotations

import re

_GREET_RE = re.compile(
    r"^(你好|您好|嗨|哈喽|在吗|早上好|下午好|晚上好|谢谢|谢谢你|多谢|辛苦了|再见)"
    r"[呀啊哦！!。.~\s]*$"
)
_OFF_RE = re.compile(
    r"(写一首|写首诗|帮我写诗|作一首诗|写首现代诗|"
    r"帮我翻译|翻译成|译成英文|译成中文|"
    r"帮我算|算一下|计算一下|"
    r"今天天气|天气怎么样|"
    r"写一段代码|帮我编程|"
    r"写一篇作文|帮我写作文|"
    r"讲个笑话|讲个故事)"
)
_MATH_RE = re.compile(r"^\s*\d+\s*[\+\-\*/×÷]\s*\d+")

INTRO = (
    "你好，我是校园助手。我只回答星云大学的办事问题，比如在读证明、图书馆借阅、宿舍报修和校园网。"
    "直接说你要办的事就行。"
)
OFF_TOPIC = (
    "我只回答校园办事问题，不能写诗、翻译、算题或闲聊。"
    "你可以问「在读证明如何办理？」或「图书馆开放时间是什么？」。"
)
EXAMPLES = (
    {"label": "在读证明", "query": "在读证明如何办理？"},
    {"label": "图书馆", "query": "图书馆开放时间是什么？"},
    {"label": "宿舍报修", "query": "宿舍报修怎么提交？"},
)


def classify_scope(query: str) -> str | None:
    text = (query or "").strip()
    if not text:
        return None
    if _GREET_RE.match(text):
        return "greeting"
    if _MATH_RE.match(text) or _OFF_RE.search(text):
        return "off_topic"
    return None
