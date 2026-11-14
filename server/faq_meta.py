"""Read the single sample FAQ file. This does not answer questions."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAQ_PATH = ROOT / "sample-kb" / "客服样例FAQ.md"
SECTION_RE = re.compile(r"^##\s+(\d+)\.\s+(.+)$", re.M)

_CACHE: list[dict] | None = None


def load_entries(force: bool = False) -> list[dict]:
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    text = FAQ_PATH.read_text(encoding="utf-8")
    matches = list(SECTION_RE.finditer(text))
    entries: list[dict] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.group(2).strip()
        entries.append(
            {
                "n": int(match.group(1)),
                "title": title,
                "body": text[start:end].strip(),
                "document": FAQ_PATH.name,
            }
        )
    _CACHE = entries
    return entries


def titles() -> list[str]:
    return [item["title"] for item in load_entries()]


def by_title(title: str) -> dict | None:
    for item in load_entries():
        if item["title"] == title:
            return item
    return None
