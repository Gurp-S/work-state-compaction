"""Contextual Trigger Retrieval + Applicability Resolver（CSM 设计补充实现）。

写入阶段为记忆提出 Trigger Profile（触发元数据，不是新事实）；
检索阶段按当前 Context Frame 触发候选，再由 Applicability Resolver 判定能否使用。

触发命中不等于适用：verdict 与 usage_mode 分开给。
"""

from __future__ import annotations

import json
import re

import locomo_rank as ranker

TRIGGER_SYSTEM = """输入是若干条记忆。为每条记忆判断：在什么情境下，这条记忆值得被重新检查？
只输出 JSON：{"items": [{"id": 序号, "trigger_kind": "EXPLICIT_CONSTRAINT|FUTURE_ACTION|ENTITY_RELATION|TEMPORAL_EVENT|CONTEXTUAL_SCOPE|RETRIEVAL_CUE",
"domains": ["英文领域词"], "cues": ["英文触发词"], "usage": "HARD_CONSTRAINT|SOFT_PREFERENCE|CONTEXT_ONLY"}]}
约束/禁止/过敏/偏好类用 EXPLICIT_CONSTRAINT 或 SOFT_PREFERENCE；计划承诺用 FUTURE_ACTION；
时间节点用 TEMPORAL_EVENT；其余用 RETRIEVAL_CUE。domains 与 cues 各不超过 3 个词。"""

ACTION_WORDS = {
    "recommend": "recommend", "suggest": "recommend", "plan": "plan", "planning": "plan",
    "going": "plan", "buy": "purchase", "choose": "choose", "advice": "advise",
    "pursue": "career", "work": "career", "study": "career", "eat": "dining",
    "restaurant": "dining", "travel": "travel", "trip": "travel", "camping": "travel",
}

DOMAIN_HINTS = {
    "dining": {"food", "eat", "restaurant", "meal", "dinner", "lunch", "allergy", "peanut"},
    "travel": {"camping", "trip", "travel", "roadtrip", "hike", "vacation"},
    "career": {"work", "job", "career", "school", "study", "counseling", "education"},
    "health": {"health", "mental", "therapy", "allergy", "doctor"},
    "family": {"family", "kids", "children", "mom", "dad", "husband", "wife"},
}


def context_frame(question: str, entities: list[str]) -> dict:
    """Context Frame：只从问题里取可信字段，缺失就留空，不猜。"""
    lowered = str(question).lower()
    words = set(re.findall(r"[a-z']+", lowered))
    domains = sorted({domain for domain, hints in DOMAIN_HINTS.items() if words & hints})
    actions = sorted({action for word, action in ACTION_WORDS.items() if word in words})
    return {"query_text": question, "entities": list(entities), "domains": domains,
            "actions": actions, "temporal": ranker.is_temporal(question)}


def derive_triggers(chat, memories: list[dict], cache: dict, batch: int = 12) -> dict:
    """写入侧：为记忆提出 Trigger Profile。批量做，结果按 memory_id 存。"""
    profiles: dict[str, dict] = {}
    pending = [item for item in memories if item["memory_id"] not in cache]
    for start in range(0, len(pending), batch):
        chunk = pending[start:start + batch]
        lines = "\n".join(f'{index}. [{item.get("entity")}] {item.get("slot")} | '
                          f'{str(item.get("value"))[:150]}'
                          for index, item in enumerate(chunk))
        key = f"T/{chunk[0]['memory_id']}"
        if key in cache:
            raw = cache[key]
        else:
            try:
                payload = chat.ask_json(TRIGGER_SYSTEM, f"记忆：\n{lines}", max_tokens=1200)
            except (ValueError, json.JSONDecodeError):
                payload = {}
            raw = payload.get("items") if isinstance(payload, dict) else payload
            cache[key] = raw or []
        for entry in raw or []:
            try:
                item = chunk[int(entry.get("id"))]
            except (KeyError, IndexError, TypeError, ValueError):
                continue
            profiles[item["memory_id"]] = {
                "trigger_kind": str(entry.get("trigger_kind") or "RETRIEVAL_CUE"),
                "domains": [str(word) for word in (entry.get("domains") or [])][:3],
                "cues": [str(word) for word in (entry.get("cues") or [])][:3],
                "usage": str(entry.get("usage") or "CONTEXT_ONLY")}
    for memory_id in [item["memory_id"] for item in memories]:
        if memory_id in cache:
            pass
    return profiles


def trigger_hits(frame: dict, profiles: dict, memories: dict[str, dict]) -> list[dict]:
    """CTR：按当前情境发现候选——领域/动作/线索命中，不看表面相似度。"""
    hits: list[dict] = []
    for memory_id, profile in profiles.items():
        item = memories.get(memory_id)
        if not item:
            continue
        matched: list[str] = []
        if frame["domains"] and set(profile["domains"]) & set(frame["domains"]):
            matched.append("domain")
        cues = {str(cue).lower() for cue in profile["cues"]}
        if cues and cues & set(re.findall(r"[a-z']+", frame["query_text"].lower())):
            matched.append("cue")
        if profile["trigger_kind"] == "TEMPORAL_EVENT" and frame["temporal"]:
            matched.append("temporal")
        if matched:
            hits.append({**item, "trigger_matched": matched, "profile": profile})
    return hits


def resolve_applicability(frame: dict, candidate: dict) -> dict:
    """AR：身份、范围、时间、来源四项检查；缺证据就是 UNRESOLVED，不硬转。"""
    profile = candidate.get("profile") or {}
    matched, failed, unknown = [], [], []
    entity = str(candidate.get("entity") or "").lower()
    if frame["entities"] and entity in {str(name).lower() for name in frame["entities"]}:
        matched.append("identity")
    elif frame["entities"]:
        unknown.append("identity_not_named")
    if set(profile.get("domains") or []) & set(frame["domains"]):
        matched.append("scope")
    elif frame["domains"]:
        unknown.append("scope_unclear")
    if candidate.get("source_refs"):
        matched.append("evidence")
    else:
        unknown.append("no_source")

    if unknown:
        verdict = "UNRESOLVED"
    elif failed:
        verdict = "NOT_APPLICABLE"
    else:
        verdict = "APPLICABLE"
    usage = profile.get("usage") or "CONTEXT_ONLY"
    if verdict != "APPLICABLE":
        usage = "CONTEXT_ONLY"
    return {"memory_identity_id": candidate["memory_id"], "verdict": verdict,
            "usage_mode": usage, "matched_conditions": matched,
            "failed_conditions": failed, "unknown_conditions": unknown}
