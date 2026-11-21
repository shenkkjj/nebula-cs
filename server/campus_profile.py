"""Public campus service presets. Each record points to the school original."""
from __future__ import annotations

import re
from typing import NamedTuple

from settings import env

AUDIENCES = ("student", "staff", "shared")
DEMO_PROBE = ("在读证明如何办理？", "一网通办")
QUT_PROBE = ("学生证补办", "理工学子")


def profile() -> str:
    return "demo" if env("CAMPUS_PROFILE").lower() == "demo" else "qut"


def scope(audience: str = "") -> str:
    if profile() == "demo":
        return "demo"
    return "staff" if audience == "staff" else "student"


def probe_config(cfg: dict) -> dict:
    if profile() == "qut" and (cfg.get("probe_question"), cfg.get("probe_expect")) == DEMO_PROBE:
        return dict(cfg, probe_question=QUT_PROBE[0], probe_expect=QUT_PROBE[1])
    return cfg


def query_key(text: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "", text.lower())
    return re.sub(r"^(您好|你好)?(请问|想问一下|我想问一下)?", "", text)


class Article(NamedTuple):
    audience: str
    group: str
    source: str
    url: str
    title: str
    answer: str
    aliases: tuple[str, ...]


ARTICLES = (
    Article("student", "证件与证明", "学生工作处 · 教育管理工作业务服务流程",
            "https://xshch.qut.edu.cn/info/1103/1561.htm", "学生证补办",
            "关注「理工学子」微信公众号，进入学生证补办入口，填写本人信息并按要求上传电子照片。集中补办的时间和安排请看学校当期通知。",
            ("学生证怎么补", "学生证怎么补办", "学生证丢了怎么办", "怎么补办学生证", "怎样补办学生证", "补办学生证", "学生证如何补办")),
    Article("shared", "校园生活", "后勤管理处 · 能源与维修服务指南",
            "https://hqch.qut.edu.cn/nyywxfwzx/fwzn.htm", "宿舍及校园设施报修",
            "关注「青岛理工大学后勤」微信公众号，进入后勤公共服务平台，在线填写报修信息。该指南也列有电话报修渠道。",
            ("宿舍报修", "宿舍怎么报修", "宿舍报修怎么提交", "宿舍东西坏了怎么报修", "宿舍灯不亮了", "宿舍漏水怎么报修", "寝室怎么报修", "宿舍维修怎么申请", "校内设施怎么报修")),
    Article("student", "网络与系统", "信息化建设与管理处 · 校园网用户上网指南（学生版）",
            "https://metc.qut.edu.cn/info/1054/1987.htm", "学生校园网登录",
            "连接无线网络 QUT-POL，在弹出的认证页用智慧理工账号登录。如果没有弹出认证页，校园网指南提供了手动打开的地址和操作步骤。",
            ("校园网", "校园网怎么连", "校园网怎么登录", "校园网如何认证登录", "校园wifi怎么连", "学生怎么连校园网", "学生校园网怎么登录")),
    Article("student", "网络与系统", "信息化建设与管理处 · 校园网用户上网指南（学生版）",
            "https://metc.qut.edu.cn/info/1054/1987.htm", "学生校园网缴费",
            "关注「智慧青理在线」微信公众号，进入「校园网 → 套餐缴费」，在缴费平台选择「校园网网费」后按页面提示办理。具体套餐和金额以缴费页面为准。",
            ("校园网怎么交钱", "校园网怎么缴费", "网费怎么交", "校园网缴费", "学生校园网怎么缴费", "校园网怎么充值")),
    Article("staff", "网络与系统", "信息化建设与管理处 · 校园网用户上网指南（教工版）",
            "https://metc.qut.edu.cn/info/1054/1984.htm", "教工校园网登录",
            "连接无线网络 QUT-POL，在弹出的认证页输入智慧理工账号和密码。忘记密码可使用认证页的「忘记密码」入口。",
            ("校园网", "校园网怎么连", "校园网怎么登录", "校园网如何认证登录", "校园wifi怎么连", "教工怎么连校园网", "教职工校园网怎么登录")),
    Article("shared", "网络与系统", "信息化建设与管理处 · 智慧理工网络报修指南",
            "https://metc.qut.edu.cn/info/1030/1977.htm", "校园网报修",
            "在智慧理工进入「办事大厅 → 服务大厅 → 信息化建设与管理处 → 网络报修」，填写问题后提交。办理进度也可以在网上办事大厅查看。",
            ("网络报修", "校园网怎么报修", "校园网连不上怎么办", "校园网坏了怎么报修", "网络故障怎么报修", "校园网报修进度怎么查")),
    Article("student", "证件与证明", "研究生处 · 研究方向证明、在读证明及成绩单打印",
            "https://yjsh.qut.edu.cn/info/1362/3277.htm", "研究生带公章成绩单",
            "登录研究生信息管理系统，进入「培养 → 课务管理 → 课程成绩信息查询 → 带公章成绩单」，可下载带公章的电子成绩单。",
            ("研究生成绩单", "研究生成绩单怎么打印", "研究生成绩单怎么开", "研究生怎么打印成绩单", "研究生怎么开成绩单", "研究生成绩单哪里下载")),
    Article("student", "证件与证明", "研究生处 · 研究方向证明、在读证明及成绩单打印",
            "https://yjsh.qut.edu.cn/info/1362/3277.htm", "研究生在读证明",
            "研究生处的在读证明指南要求参考同页的研究方向证明流程。先下载原文附件 1 的模板，准备相应版本，由学院审核、签字和盖章，再提交研究生处复核。",
            ("研究生在读证明怎么办", "研究生在读证明怎么办理", "研究生在读证明怎么开", "研究生如何开在读证明", "研究生开在读证明")),
    Article("student", "校园生活", "财务处 · 收费公示",
            "https://cwc.qut.edu.cn/sfgs.htm", "学校收费公示",
            "财务处在「收费公示」栏目发布收费项目和标准。查学费或住宿费时，请在原文中确认对应的学年、层次和收费项目。",
            ("收费公示", "学费标准去哪查", "学校收费标准在哪查", "住宿费收费标准在哪查", "哪里可以看学校收费标准")),
    Article("staff", "人事事务", "人事处 · 青岛理工大学教职工考勤管理办法（修订）",
            "https://rshch.qut.edu.cn/info/1036/1412.htm", "教职工请假与销假",
            "按人事处公布的考勤管理办法，教职工请假由本人填写《青岛理工大学教职工请（续）假申请表》，提交相应证明材料，按审批权限报批。获批并安排好工作后方可离岗；返岗时填写《青岛理工大学教职工销假表》。",
            ("教职工怎么请假", "教职工请假", "教师请假怎么申请", "老师怎么请假", "教工请假", "教职工怎么销假", "教职工怎么请病假", "教工病假怎么请")),
)

ARTICLE_BY_TITLE = {item.title: item for item in ARTICLES}
