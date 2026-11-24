"""并行作答：同一截止轮次的问题彼此独立，串行跑纯属浪费。

检索留在主线程（SQLite 连接不能跨线程），只把 LLM 调用并行化。
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor


def workers() -> int:
    try:
        return max(1, int(os.environ.get("WSC_CSM_WORKERS", "6")))
    except ValueError:
        return 6


def parallel_map(function, entries, width: int | None = None):
    """按顺序返回结果；width<=1 时退化为串行，便于 A/B。"""
    entries = list(entries)
    width = workers() if width is None else width
    if width <= 1 or len(entries) <= 1:
        return [function(entry) for entry in entries]
    with ThreadPoolExecutor(max_workers=min(width, len(entries))) as pool:
        return list(pool.map(function, entries))
