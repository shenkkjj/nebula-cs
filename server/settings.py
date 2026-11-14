"""Runtime settings: local .env, server/config.json, and Dify URLs.

Secrets stay in the environment or a gitignored .env. config.json holds
only the constraint knobs an admin can change.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

_CONFIG_CACHE: dict | None = None
_CONFIG_MTIME: float | None = None

_DEFAULTS = {
    "score_threshold": 0.5,
    "max_citations": 3,
    "refusal_text": "知识库里没有这条办事说明，我不能编规定。需要的话可以转人工，值班老师会回复你。",
    "auto_ticket_on_refusal": False,
    "probe_question": "在读证明如何办理？",
    "probe_expect": "一网通办",
    "probe_interval_seconds": 600,
}


def load_dotenv() -> None:
    """Fill missing environment variables from the repo .env. Never overrides."""
    path = ROOT / ".env"
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def data_dir() -> Path:
    load_dotenv()
    raw = (os.environ.get("DATA_DIR") or "").strip()
    path = Path(raw) if raw else ROOT / "data"
    path.mkdir(parents=True, exist_ok=True)
    return path


def env(name: str, default: str = "") -> str:
    load_dotenv()
    return (os.environ.get(name) or default).strip()


def dify_chat_url() -> str:
    return env("DIFY_CHAT_URL", "http://127.0.0.1/v1/chat-messages")


def dify_app_key() -> str:
    key = env("DIFY_APP_API_KEY")
    if key:
        return key
    key_file = env("DIFY_APP_API_KEY_FILE", "/tmp/dify-app-api-key.txt")
    path = Path(key_file)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def dify_dataset_key() -> str:
    return env("DIFY_DATASET_API_KEY")


def dify_dataset_id() -> str:
    return env("DIFY_DATASET_ID")


def dify_api_base() -> str:
    """http://host/v1 from the chat-messages URL."""
    url = dify_chat_url()
    marker = "/chat-messages"
    if marker in url:
        return url.split(marker, 1)[0]
    return url.rstrip("/")


def ollama_host() -> str:
    return env("OLLAMA_HOST", "http://127.0.0.1:11434")


def load_config() -> dict:
    """Reload when config.json changes so an admin save applies immediately."""
    global _CONFIG_CACHE, _CONFIG_MTIME
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return dict(_DEFAULTS)
    if _CONFIG_CACHE is not None and _CONFIG_MTIME == mtime:
        return dict(_CONFIG_CACHE)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    cfg = dict(_DEFAULTS)
    if isinstance(raw, dict):
        cfg.update({key: raw[key] for key in _DEFAULTS if key in raw})
    cfg["score_threshold"] = _clamp_float(cfg["score_threshold"], 0.0, 1.0, 0.5)
    cfg["max_citations"] = _clamp_int(cfg["max_citations"], 1, 8, 3)
    cfg["probe_interval_seconds"] = _clamp_int(cfg["probe_interval_seconds"], 60, 86400, 600)
    cfg["auto_ticket_on_refusal"] = bool(cfg["auto_ticket_on_refusal"])
    cfg["refusal_text"] = str(cfg["refusal_text"] or _DEFAULTS["refusal_text"])[:400]
    cfg["probe_question"] = str(cfg["probe_question"] or _DEFAULTS["probe_question"])[:200]
    cfg["probe_expect"] = str(cfg["probe_expect"] or _DEFAULTS["probe_expect"])[:80]
    _CONFIG_CACHE = dict(cfg)
    _CONFIG_MTIME = mtime
    return dict(cfg)


def save_config(updates: dict) -> dict:
    global _CONFIG_CACHE, _CONFIG_MTIME
    current = load_config()
    allowed = set(_DEFAULTS)
    for key, value in updates.items():
        if key in allowed:
            current[key] = value
    current["score_threshold"] = _clamp_float(current["score_threshold"], 0.0, 1.0, 0.5)
    current["max_citations"] = _clamp_int(current["max_citations"], 1, 8, 3)
    current["probe_interval_seconds"] = _clamp_int(current["probe_interval_seconds"], 60, 86400, 600)
    current["auto_ticket_on_refusal"] = bool(current["auto_ticket_on_refusal"])
    current["refusal_text"] = str(current["refusal_text"])[:400]
    current["probe_question"] = str(current["probe_question"])[:200]
    current["probe_expect"] = str(current["probe_expect"])[:80]
    CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _CONFIG_CACHE = None
    _CONFIG_MTIME = None
    return load_config()


def _clamp_float(value, low: float, high: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(high, max(low, number))


def _clamp_int(value, low: int, high: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return min(high, max(low, number))
