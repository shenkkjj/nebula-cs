"""Mask phone numbers and national ID numbers before they leave the process."""
from __future__ import annotations

import re

# Continuous 11-digit mobiles. Order numbers such as SW20260001 do not match.
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d[\s-]?\d{4}[\s-]?\d{4}(?!\d)")
_ID_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_MED_RE = re.compile(r"(病历|病例|化验单|出院小结|出院记录|诊断证明|诊断书)")
_LONG_DIGIT_RE = re.compile(r"\d{6,}")


def is_medical_dump(text: str) -> bool:
    raw = text or ""
    if not _MED_RE.search(raw):
        return False
    return len(raw) > 36 or "\n" in raw or bool(_LONG_DIGIT_RE.search(raw))


def mask_text(text: str) -> tuple[str, list[str]]:
    """Return masked text and short notices. The original digits are not kept."""
    raw = text or ""
    notices: list[str] = []

    def _phone(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) != 11:
            return match.group(0)
        if "手机号" not in notices:
            notices.append("手机号")
        return f"{digits[:3]}****{digits[-4:]}"

    def _ident(match: re.Match[str]) -> str:
        if "证件号" not in notices:
            notices.append("证件号")
        return "［证件号已隐去］"

    masked = _ID_RE.sub(_ident, raw)
    masked = _PHONE_RE.sub(_phone, masked)
    return masked, notices


def notice_line(notices: list[str]) -> str:
    if not notices:
        return ""
    joined = "、".join(notices)
    return f"已隐去{joined}，不会发给模型和日志。"


def contains_secret(text: str) -> bool:
    masked, notices = mask_text(text or "")
    return bool(notices) or is_medical_dump(text or "") or masked != (text or "")
