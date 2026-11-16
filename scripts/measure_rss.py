#!/usr/bin/env python3
"""Print this process's peak RSS after seeding the campus knowledge base.

Linux ru_maxrss is kilobytes. This does not start DeepSeek or a local model.
"""
from __future__ import annotations

import os
import resource
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="nebula-rss-")
os.environ["ENGINE"] = "campus"
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["EMBEDDING_API_KEY"] = ""

import campus_engine  # noqa: E402

QUESTIONS = [
    "在读证明如何办理？",
    "那成绩单呢？",
    "怎么请病假？",
    "申请",
    "帮我写一首短诗",
    "宿舍报修怎么提交？",
    "图书馆开放时间是什么？",
    "转人工",
]
for query in QUESTIONS:
    campus_engine.answer(query)

rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(f"maxrss_kb={rss_kb}")
print(f"maxrss_mib={rss_kb / 1024:.1f}")
