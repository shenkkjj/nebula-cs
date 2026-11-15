"""In-process token bucket. Eval callers are exempt. No Redis."""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_BUCKETS: dict[str, dict] = {}


def allow(visitor: str, user: str, cfg: dict, exempt: bool = False) -> bool:
    """Exempt only when the eval runner sets it in-process. Client user strings are not trusted."""
    if exempt or not cfg.get("rate_limit_enabled", True):
        return True
    identity = (visitor or user or "").strip()
    if not identity:
        identity = "anonymous"
    burst = float(cfg.get("rate_limit_burst") or 20)
    per_minute = float(cfg.get("rate_limit_per_minute") or 20)
    now = time.monotonic()
    with _LOCK:
        state = _BUCKETS.get(identity)
        if state is None:
            state = {"tokens": burst, "ts": now}
            _BUCKETS[identity] = state
        elapsed = max(0.0, now - state["ts"])
        state["ts"] = now
        state["tokens"] = min(burst, state["tokens"] + elapsed * (per_minute / 60.0))
        if state["tokens"] < 1:
            return False
        state["tokens"] -= 1
        return True


def reset_for_tests() -> None:
    with _LOCK:
        _BUCKETS.clear()
