#!/usr/bin/env python3
"""Build dev/test/smoke eval sets from the single sample FAQ.

The 12 baseline questions stay in smoke-set.json only. They are not copied
into the test set. Run from the repo root:

    python3 scripts/build_eval_sets.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from faq_meta import load_entries  # noqa: E402

OUT = ROOT / "tests" / "eval"
FACT_RE = re.compile(
    r"\d+\s*个工作日|\d{1,2}:\d{2}[–\-]\d{1,2}:\d{2}|\d{1,2}:\d{2}|\d+(?:\.\d+)?\s*元|一网通办|6677|\d+\s*分钟|\d+\s*天"
)

# Exact strings from docs/evidence/2026-11-14-baseline-probe.md. Not for the test set.
SMOKE = [
    {"id": "S-01", "type": "in_scope", "question": "我想开个在校证明，去哪弄？", "expected_title": "在读证明如何办理？", "should_refuse": False},
    {"id": "S-02", "type": "in_scope", "question": "宿舍空调坏了找谁修", "expected_title": "宿舍报修怎么提交？", "should_refuse": False},
    {"id": "S-03", "type": "in_scope", "question": "书最多能借多久", "expected_title": "如何借书和续借？", "should_refuse": False},
    {"id": "S-04", "type": "in_scope", "question": "挂科了怎么办", "expected_title": "补考和重修有什么区别？", "should_refuse": False},
    {"id": "S-05", "type": "in_scope", "question": "饭卡丢了怎么办", "expected_title": "校园卡如何充值和挂失？", "should_refuse": False},
    {"id": "S-06", "type": "in_scope", "question": "想换个专业，有什么条件", "expected_title": "如何办理转专业？", "should_refuse": False},
    {"id": "S-07", "type": "in_scope", "question": "奖学金一般什么时候评", "expected_title": "国家奖学金和励志奖学金有什么区别？", "should_refuse": False},
    {"id": "S-08", "type": "in_scope", "question": "连不上校园网", "expected_title": "校园网故障如何报修？", "should_refuse": False},
    {"id": "S-09", "type": "in_scope", "question": "晚上几点前必须回宿舍", "expected_title": "宿舍门禁时间是什么？", "should_refuse": False},
    {"id": "S-10", "type": "out_of_scope", "question": "出国交换需要准备什么材料", "expected_title": "", "should_refuse": True},
    {"id": "S-11", "type": "out_of_scope", "question": "怎么请病假", "expected_title": "", "should_refuse": True},
    {"id": "S-12", "type": "out_of_scope", "question": "毕业论文查重率要求多少", "expected_title": "", "should_refuse": True},
]
SMOKE_TEXT = {item["question"] for item in SMOKE}

OUT_OF_SCOPE = [
    "军训服装在哪里领",
    "保研需要什么条件",
    "研究生导师怎么选",
    "实验室门禁怎么开",
    "港澳通行证在学校怎么办理",
    "社团活动经费怎么报销",
    "怎么转学到其他大学",
    "毕业典礼哪一天举行",
    "宿舍可以养宠物吗",
    "有没有去机场的校车",
    "教材费怎么退",
    "可以申请提前毕业吗",
    "论文格式模板去哪下载",
    "学校用的什么查重系统",
    "毕业答辩时间在哪看",
    "户口怎么迁到学校",
    "党组织关系怎么转出",
    "入党申请书交给谁",
    "教师资格证怎么报名",
    "计算机等级考试在哪考",
    "学生票优惠怎么核验",
    "食堂饭菜不干净怎么投诉赔偿",
    "快递丢了学校会赔吗",
    "校内创业场地怎么申请",
    "社团招新摊位怎么批",
    "电动车允许进校园吗",
    "校园停车怎么收费",
    "校友卡怎么办理",
    "签证邀请函怎么开",
    "学校是托福考点吗",
    "创新创业大赛怎么报名",
    "体测不及格能不能毕业",
    "交换生名额怎么申请",
    "校外住宿怎么打申请",
    "给辅导员发邮件请假用哪个模板",
    "毕业论文盲审没过怎么办",
    "英语角每周几举办",
    "学校篮球联赛怎么报名",
    "毕业照统一在哪拍",
    "考研报名费学校代收吗",
]

MULTI = [
    ("在读证明如何办理？", "那成绩单呢？", "成绩单如何申请？"),
    ("如何借书和续借？", "超期了怎么办", "图书超期怎么处理？"),
    ("校园卡如何充值和挂失？", "那补办呢", "校园卡如何补办？"),
    ("宿舍报修怎么提交？", "空调不凉呢", "宿舍空调不制冷如何报修？"),
    ("校园网如何认证登录？", "页面打不开怎么办", "校园网认证页面打不开怎么办？"),
    ("心理咨询如何预约？", "想改期", "心理咨询如何取消或改期？"),
    ("教室借用怎么申请？", "考试周还能借吗", "考试周还可以申请教室吗？"),
    ("国家助学贷款如何申请？", "回执交到哪", "生源地助学贷款回执如何提交？"),
    ("如何办理转专业？", "转完学分怎么办", "转专业后已修学分如何认定？"),
    ("图书馆开放时间是什么？", "分馆呢", "图书馆分馆开放时间是什么？"),
    ("休学和复学怎么办理？", "那退学呢", "退学如何办理？"),
    ("奖助学金如何申请？", "奖学金和励志有啥区别", "国家奖学金和励志奖学金有什么区别？"),
    ("校园卡如何充值和挂失？", "挂失后付款码呢", "校园卡挂失后付款码还能用吗？"),
    ("VPN 如何使用？", "客户端去哪下", "VPN 客户端在哪里下载？"),
    ("校医院开放时间是什么？", "怎么挂号", "校医院如何预约挂号？"),
    ("假期留校怎么申请？", "食堂开不开", "假期食堂开放时间是什么？"),
]

CLARIFY = [
    ("证明怎么开？", ["在读证明如何办理？", "成绩单如何申请？", "学历证明和学位证明如何办理？"]),
    ("怎么开证明", ["在读证明如何办理？", "成绩单如何申请？", "学历证明和学位证明如何办理？"]),
    ("助学贷款怎么办", ["国家助学贷款如何申请？", "生源地助学贷款回执如何提交？", "助学贷款每年如何做年度确认？"]),
    ("校园卡出问题了", ["校园卡如何充值和挂失？", "校园卡如何补办？", "校园卡消磁或无法刷门禁怎么办？"]),
    ("宿舍东西坏了", ["宿舍报修怎么提交？", "宿舍空调不制冷如何报修？", "宿舍漏水紧急怎么处理？"]),
    ("成绩好像不对", ["成绩在哪里查询？", "对成绩有异议如何复查？", "成绩单为什么少了一门课？"]),
    ("校园网上不去", ["校园网如何认证登录？", "校园网认证页面打不开怎么办？", "校园网故障如何报修？"]),
    ("教室想用一下", ["教室借用怎么申请？", "空闲教室如何查询？", "教室借用如何取消或改期？"]),
    ("奖学金怎么弄", ["奖助学金如何申请？", "国家奖学金和励志奖学金有什么区别？", "助学金发放到哪里？"]),
    ("书借不出来", ["如何借书和续借？", "借阅权限为什么被冻结？", "图书超期怎么处理？"]),
    ("转专业", ["如何办理转专业？", "转专业后已修学分如何认定？"]),
    ("心理方面的事", ["心理咨询如何预约？", "心理咨询如何取消或改期？", "心理测评在哪里做，结果谁能看？"]),
]


def paraphrase(title: str, taken: set[str]) -> str:
    body = title.rstrip("？?")
    replacements = (
        ("如何办理", "要怎么去办"),
        ("如何申请", "想申请"),
        ("如何预约", "怎么预约"),
        ("如何查询", "在哪查"),
        ("怎么办理", "该怎么办"),
        ("怎么办", "该如何处理"),
        ("有什么区别", "差别在哪里"),
        ("是什么", "指的是什么"),
        ("在哪里", "去哪儿"),
        ("什么时候", "一般何时"),
        ("有哪些", "都包括什么"),
        ("如何使用", "怎么用"),
        ("如何", "怎样"),
        ("可以", "能不能"),
    )
    changed = body
    for src, dst in replacements:
        if src in changed:
            changed = changed.replace(src, dst, 1)
            break
    question = changed if changed.endswith("？") else changed + "？"
    if question == title or question in SMOKE_TEXT or question in taken:
        question = f"同学想问，{title}"
    if question in taken or question in SMOKE_TEXT:
        question = f"想确认一下：{title}"
    taken.add(question)
    return question


def facts_for(body: str) -> list[str]:
    found: list[str] = []
    for match in FACT_RE.finditer(body):
        text = match.group(0)
        if text not in found:
            found.append(text)
        if len(found) == 2:
            return found
    if found:
        return found
    clause = body.split("。", 1)[0].strip()
    if 4 <= len(clause) <= 28 and clause in body:
        return [clause]
    return [body[:12]]


def pack(items: list[dict], name: str, prefix: str) -> dict:
    numbered = []
    for index, item in enumerate(items, start=1):
        row = dict(item)
        row["id"] = f"{prefix}-{index:03d}"
        numbered.append(row)
    return {
        "set": name,
        "count": len(numbered),
        "source": "sample-kb/客服样例FAQ.md",
        "note": "知识库是这一个文件里的 144 条，不是 144 个文件。基线 12 题只在 smoke-set.json。",
        "items": numbered,
    }


def main() -> None:
    entries = load_entries()
    by_title = {item["title"]: item for item in entries}
    taken: set[str] = set()
    in_scope = []
    for entry in entries:
        question = paraphrase(entry["title"], taken)
        in_scope.append(
            {
                "type": "in_scope",
                "question": question,
                "expected_title": entry["title"],
                "expected_doc": "客服样例FAQ.md",
                "expected_facts": facts_for(entry["body"]),
                "should_refuse": False,
            }
        )
    outside = [
        {
            "type": "out_of_scope",
            "question": text,
            "expected_title": "",
            "expected_doc": "",
            "expected_facts": [],
            "should_refuse": True,
        }
        for text in OUT_OF_SCOPE
    ]
    multi = []
    for previous, question, title in MULTI:
        body = by_title[title]["body"]
        multi.append(
            {
                "type": "multi_turn",
                "question": question,
                "history": [
                    {"role": "user", "text": previous},
                    {"role": "assistant", "text": "好，我按上一问的办事说明接着说。"},
                ],
                "expected_title": title,
                "expected_doc": "客服样例FAQ.md",
                "expected_facts": facts_for(body),
                "should_refuse": False,
            }
        )
    clarify = [
        {
            "type": "clarify",
            "question": question,
            "expected_titles": titles,
            "expected_title": titles[0],
            "expected_doc": "客服样例FAQ.md",
            "expected_facts": [],
            "should_refuse": False,
        }
        for question, titles in CLARIFY
    ]
    test_items = []
    dev_items = []
    for entry, item in zip(entries, in_scope):
        (test_items if entry["n"] % 2 == 0 else dev_items).append(item)
    test_items.extend(outside[:20])
    dev_items.extend(outside[20:])
    test_items.extend(multi[:8])
    dev_items.extend(multi[8:])
    test_items.extend(clarify[:7])
    dev_items.extend(clarify[7:])
    smoke_items = []
    for item in SMOKE:
        title = item["expected_title"]
        facts = facts_for(by_title[title]["body"]) if title else []
        smoke_items.append(
            {
                "type": item["type"],
                "question": item["question"],
                "expected_title": title,
                "expected_doc": "客服样例FAQ.md" if title else "",
                "expected_facts": facts,
                "should_refuse": item["should_refuse"],
            }
        )
    OUT.mkdir(parents=True, exist_ok=True)
    for name, items, prefix in (
        ("test", test_items, "T"),
        ("dev", dev_items, "D"),
        ("smoke", smoke_items, "S"),
    ):
        payload = pack(items, name, prefix)
        (OUT / f"{name}-set.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {payload['count']}")
    bad = OUT / "bad-cases.json"
    if not bad.exists():
        bad.write_text("[]\n", encoding="utf-8")


if __name__ == "__main__":
    main()
