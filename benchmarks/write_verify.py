"""写后自检与补抽：本轮每个子句都必须有记忆条目着落，没有就再抽一次。

设计 §16.1 缺的正是这条判据：抽完不核对原文，丢失永远不可见。
开关：WSC_CSM_WRITE_VERIFY=1
"""
from __future__ import annotations

import re

from semantic_check import missing_clauses

SPLIT = re.compile(r"[，。；！？、,.!?]")
REPAIR_SYSTEM = """你是长期记忆提取器。上一轮抽取遗漏了下面这些内容，请只针对遗漏部分补充提取。
规则：每一条遗漏内容至少对应一条记忆；条件、数量、时间、否定都要写进 value。
输出 JSON 数组，元素形如 {"entity": "实体或主题", "slot": "属性名", "value": "完整事实值", "topics": ["关键词"]}。
用户陈述的事实一律属于实体"用户"。确实无法提取才输出 []。"""


def clauses_of(turn: dict, min_len: int = 4) -> list[str]:
    text = str(turn.get("用户消息") or "") + "。" + str(turn.get("助手回复") or "")
    return [c for c in SPLIT.split(text) if len(c) >= min_len]


def repair(chat, turn: dict, missing: list[str]) -> list[dict]:
    """对遗漏子句做一次定向补抽。"""
    if not missing:
        return []
    body = (f"本轮时间：{turn.get('逻辑时间')}\n用户：{turn.get('用户消息')}\n"
            f"助手：{turn.get('助手回复')}\n遗漏内容：\n" + "\n".join(f"- {c}" for c in missing))
    try:
        items = chat.ask_json(REPAIR_SYSTEM, body, max_tokens=600)
    except Exception:
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity") or "").strip()
        slot = str(item.get("slot") or "").strip()
        value = item.get("value")
        if not entity or not slot or value in (None, ""):
            continue
        topics = [str(t).strip() for t in item.get("topics") or [] if str(t).strip()]
        out.append({"entity": entity, "slot": slot, "value": value, "topics": topics[:6]})
    return out


def verify(chat, turn: dict, candidates: list[dict]) -> list[str]:
    """返回本轮里没有对应记忆条目的子句。"""
    return missing_clauses(chat, clauses_of(turn), [str(c["value"]) for c in candidates])
