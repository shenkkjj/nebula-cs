#!/usr/bin/env python3
"""Print this process's RSS after seeding the campus knowledge base.

Linux ru_maxrss is kilobytes. Embeddings stay off, so chromadb is not imported.
A second phase, in its own process, imports chromadb and opens an empty
embedded client without the ONNX embedder. This does not start DeepSeek.
"""
from __future__ import annotations

import os
import resource
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))


def _print_rss(label: str) -> None:
    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    vm_kb = hwm_kb = 0
    status = Path("/proc/self/status")
    if status.is_file():
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                vm_kb = int(line.split()[1])
            elif line.startswith("VmHWM:"):
                hwm_kb = int(line.split()[1])
    print(f"{label}_maxrss_kb={rss_kb}", flush=True)
    print(f"{label}_maxrss_mib={rss_kb / 1024:.1f}", flush=True)
    print(f"{label}_vmrss_mib={vm_kb / 1024:.1f}", flush=True)
    print(f"{label}_vmhwm_mib={hwm_kb / 1024:.1f}", flush=True)


if os.environ.get("NEBULA_RSS_PHASE") == "chroma":
    import chroma_runtime

    path = tempfile.mkdtemp(prefix="nebula-chroma-rss-")
    client = chroma_runtime.chromadb.PersistentClient(
        path=path,
        settings=chroma_runtime.Settings(anonymized_telemetry=False),
    )
    client.create_collection(
        name="rss_probe",
        embedding_function=chroma_runtime.RemoteOnlyEmbedding(),
        metadata={"model": "none", "dim": 4},
        configuration={"hnsw": {"space": "cosine"}},
    )
    _print_rss("chroma_client")
    client.close()
    raise SystemExit(0)

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

import kb_store  # noqa: E402

info = kb_store.stats()
db_file = Path(os.environ["DATA_DIR"]) / "nebula.sqlite"
print(f"segments={info['segments']}", flush=True)
print("embeddings=off", flush=True)
print(f"chromadb_imported={'yes' if 'chromadb' in sys.modules else 'no'}", flush=True)
print(f"sqlite_bytes={db_file.stat().st_size if db_file.is_file() else 0}", flush=True)
_print_rss("faq")
rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(f"maxrss_kb={rss_kb}", flush=True)
print(f"maxrss_mib={rss_kb / 1024:.1f}", flush=True)

# Imported only after the lexical sample. Pulling chromadb in earlier would
# fold its RSS into the embeddings-off number.
import chroma_runtime  # noqa: E402

chroma_path = tempfile.mkdtemp(prefix="nebula-chroma-rss-")
chroma_client = chroma_runtime.chromadb.PersistentClient(
    path=chroma_path,
    settings=chroma_runtime.Settings(anonymized_telemetry=False),
)
chroma_client.create_collection(
    name="rss_probe",
    embedding_function=chroma_runtime.RemoteOnlyEmbedding(),
    metadata={"model": "none", "dim": 4},
    configuration={"hnsw": {"space": "cosine"}},
)
print(f"chromadb_imported={'yes' if 'chromadb' in sys.modules else 'no'}", flush=True)
_print_rss("faq_plus_chroma")
chroma_client.close()

env = os.environ.copy()
env["NEBULA_RSS_PHASE"] = "chroma"
subprocess.run([sys.executable, str(Path(__file__).resolve())], env=env, check=True)
