"""语义级覆盖核对器：判断要点是否被记忆条目“陈述”，而不是字面包含。

字面 bigram 匹配会把「十点前别催」判成缺失，而库里存的是「十点之前不要催其回复」。
所有覆盖率数字都应经过这里核对。
"""
from __future__ import annotations

CHECK_SYSTEM = """下面给出若干子句和一批记忆条目。
逐条判断该子句是否已被某个记忆条目**陈述**：同义改写、不同措辞、数值以别的方式表达都算已陈述；
只提到相关事物、但没有陈述该子句的意思，算未陈述。
输出 JSON：{"missing": [未陈述的子句编号...]}，编号从 1 开始；全部已陈述输出 {"missing": []}。"""


def missing_clauses(chat, clauses: list[str], values: list[str], max_tokens: int = 200) -> list[str]:
    """返回未被任何条目陈述的子句。空输入直接返回空。"""
    clauses = [c.strip() for c in clauses if c.strip()]
    if not clauses:
        return []
    body = "子句：\n" + "\n".join(f"{i + 1}. {c}" for i, c in enumerate(clauses))
    body += "\n记忆条目：\n" + ("\n".join(f"- {v}" for v in values) if values else "（无）")
    try:
        verdict = chat.ask_json(CHECK_SYSTEM, body, max_tokens=max_tokens)
    except Exception:
        return []
    raw = verdict.get("missing")
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        try:
            index = int(item) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(clauses):
            out.append(clauses[index])
    return out
