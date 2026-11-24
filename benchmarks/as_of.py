"""as-of 检索：按题目的截止轮次取“当时的值”，而不是只读当前投影。

CSM 的 revisions 存了完整历史（434 条 / 376 个记忆），但检索只读 projection，
于是“那周十点前别催”这类被后续班次覆盖的事实，问过去时就取不到了。
本模块只用 revisions + identities，不改动核心存储。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

TURN = re.compile(r"turn/(\d+)")


def _latest_turn(data: dict) -> int | None:
    turns = [int(m.group(1)) for ref in data.get("source_refs") or [] if (m := TURN.search(str(ref)))]
    return max(turns) if turns else None


def rows_as_of(db_path: str | Path, cutoff_turn: int) -> list[tuple[str, str, str]]:
    """返回截止到 cutoff_turn 时每个记忆的最新值：(entity, slot, value)。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    identities = {mid: (entity, slot) for mid, entity, slot in
                  con.execute("select memory_id, entity, slot from identities")}
    latest: dict[str, tuple[int, object]] = {}
    for memory_id, data in con.execute("select memory_id, data from revisions"):
        payload = json.loads(data)
        turn = _latest_turn(payload)
        if turn is None or turn > cutoff_turn:
            continue
        value = payload.get("value")
        if value in (None, ""):
            continue
        if memory_id not in latest or turn >= latest[memory_id][0]:
            latest[memory_id] = (turn, value)
    rows = []
    for memory_id, (_, value) in latest.items():
        entity, slot = identities.get(memory_id, ("", ""))
        rows.append((str(entity), str(slot), str(value)))
    return rows


def diff_against_projection(db_path: str | Path, cutoff_turn: int) -> list[str]:
    """as-of 能取到、当前投影取不到的值（用于量化覆盖损失）。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    current = {str(json.loads(d).get("value")) for (d,) in con.execute("select data from projection")}
    return [v for _, _, v in rows_as_of(db_path, cutoff_turn) if v not in current]


def rows_missing_from_projection(db_path: str | Path, cutoff_turn: int) -> list[tuple[str, str, str]]:
    """只返回当前投影里已经没有的历史值，避免把现存值重复塞进上下文。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    current = {str(json.loads(d).get("value")) for (d,) in con.execute("select data from projection")}
    return [row for row in rows_as_of(db_path, cutoff_turn) if row[2] not in current]
