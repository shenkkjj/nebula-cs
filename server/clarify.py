"""Vague campus questions become 2–3 real FAQ choices. Not a retrieval engine."""
from __future__ import annotations

import re

from faq_meta import by_title

# Patterns are intentionally narrow. A full question such as「在读证明如何办理？」
# must not match, or the gateway would skip retrieval.
_CASES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"(证明怎么开|怎么开证明|办个证明|开个证明|证明如何开|想开证明|开哪个证明)"),
        ("在读证明如何办理？", "成绩单如何申请？", "学历证明和学位证明如何办理？"),
    ),
    (
        re.compile(r"(助学贷款怎么办|贷款怎么办|哪种贷款|贷款怎么选)"),
        ("国家助学贷款如何申请？", "生源地助学贷款回执如何提交？", "助学贷款每年如何做年度确认？"),
    ),
    (
        re.compile(r"(校园卡出问题|校园卡怎么办|饭卡出问题|校园卡坏了)"),
        ("校园卡如何充值和挂失？", "校园卡如何补办？", "校园卡消磁或无法刷门禁怎么办？"),
    ),
    (
        re.compile(r"(宿舍东西坏了|宿舍坏了找谁|宿舍报修哪一种|宿舍故障找谁)"),
        ("宿舍报修怎么提交？", "宿舍空调不制冷如何报修？", "宿舍漏水紧急怎么处理？"),
    ),
    (
        re.compile(r"(成绩好像不对|成绩有问题|成绩怎么看|成绩不对)"),
        ("成绩在哪里查询？", "对成绩有异议如何复查？", "成绩单为什么少了一门课？"),
    ),
    (
        re.compile(r"(校园网上不去|校园网不行|上不了校园网|校园网怎么办)"),
        ("校园网如何认证登录？", "校园网认证页面打不开怎么办？", "校园网故障如何报修？"),
    ),
    (
        re.compile(r"(教室想用|教室怎么用|借个教室|教室怎么办)"),
        ("教室借用怎么申请？", "空闲教室如何查询？", "教室借用如何取消或改期？"),
    ),
    (
        re.compile(r"(奖学金怎么弄|奖学金怎么办|奖学金怎么申请吧)"),
        ("奖助学金如何申请？", "国家奖学金和励志奖学金有什么区别？", "助学金发放到哪里？"),
    ),
    (
        re.compile(r"(书借不出来|借不了书|借书怎么办|图书借不了)"),
        ("如何借书和续借？", "借阅权限为什么被冻结？", "图书超期怎么处理？"),
    ),
    (
        re.compile(r"^(转专业|转专业相关|转专业的事|问问转专业)[？?。!！\s]*$"),
        ("如何办理转专业？", "转专业后已修学分如何认定？"),
    ),
    (
        re.compile(r"(心理方面|心理上的事|想做心理咨询吗|心理咨询怎么办)"),
        ("心理咨询如何预约？", "心理咨询如何取消或改期？", "心理测评在哪里做，结果谁能看？"),
    ),
    (
        re.compile(r"(假期安排一下|假期怎么办|放假了校园怎么办)"),
        ("寒暑假校园作息怎么安排？", "假期食堂开放时间是什么？", "假期宿舍门禁和断电规则是什么？"),
    ),
)


def clarify_options(query: str) -> list[dict] | None:
    text = (query or "").strip()
    if not text or len(text) > 24:
        return None
    for pattern, titles in _CASES:
        if not pattern.search(text):
            continue
        options = []
        for title in titles:
            if by_title(title) is None:
                continue
            options.append({"label": title.rstrip("？?"), "query": title})
        if len(options) >= 2:
            return options[:3]
    return None
