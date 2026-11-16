"""Which answering stack the process is using.

campus is the default self-built product. lite is the old rules portal
(LITE_MODE=1 or ENGINE=lite). dify is the previous gateway, only when
ENGINE=dify. An explicit ENGINE wins over LITE_MODE so tests can select one
stack without fighting the other.
"""
from __future__ import annotations

import os

from settings import load_dotenv

_TRUTHY = ("1", "true", "yes", "on")


def engine_mode() -> str:
    load_dotenv()
    explicit = (os.environ.get("ENGINE") or "").strip().lower()
    if explicit in ("dify", "gateway"):
        return "dify"
    if explicit in ("lite", "rules"):
        return "lite"
    if explicit in ("campus", "full", "kb"):
        return "campus"
    if (os.environ.get("LITE_MODE") or "").strip().lower() in _TRUTHY:
        return "lite"
    return "campus"
