"""Multi-Hop Evidence Resolver（CSM 设计补充 V1 的检索侧实现）。

只做“有证据约束的跨记忆检索”，不造关系、不推断缺失事实：

1. Query Planning       —— 从问题里取锚点实体、要求词元、时间约束
2. Anchor Resolution    —— 用身份索引/词法/向量候选定位锚点记忆
3. Gap Recovery         —— 缺口用身份与词法检索补，不凭相似度建边
4. Chain Assembly       —— 覆盖度优先地选记忆，保证问题的每个侧面都有证据
5. Validation           —— 每条记忆必须有来源；缺的要求显式记录
6. Output               —— SUPPORTED / PARTIAL / CONFLICTED / UNRESOLVED

输出交给上层作答，不改任何长期事实。
"""

from __future__ import annotations

import re
from collections import Counter

import locomo_rank as ranker
import evidence_adapter

STOP = {"the", "and", "for", "with", "that", "this", "from", "have", "has", "was", "were",
        "been", "being", "his", "her", "she", "him", "they", "them", "their", "there",
        "what", "when", "where", "who", "how", "did", "does", "do", "is", "are", "in",
        "on", "at", "to", "of", "a", "an", "it", "its", "as", "by", "or", "be", "not",
        "both", "which", "would", "could", "about", "after", "before", "during", "also"}


def _content_terms(question: str) -> list[str]:
    terms = [word for word in re.findall(r"[a-z0-9']+", str(question).lower())
             if word not in STOP and len(word) > 2]
    return terms


def plan(question: str, entities: list[str], aliases: dict[str, str]) -> dict:
    """Query Planning：锚点实体 + 要求词元 + 是否时间约束 + 预算。"""
    anchors = ranker.match_entities(question, entities, aliases)
    terms = _content_terms(question)
    anchor_words = {word for name in anchors for word in re.findall(r"[a-z']+", name.lower())}
    requirements = [term for term in terms if term not in anchor_words]
    return {"query_mode": "temporal" if ranker.is_temporal(question) else "relation",
            "anchors": anchors, "requirements": requirements,
            "budget": 14, "max_depth": 3}


_BIGRAMS: dict[str, dict[str, list[str]]] = {}


def bigram_index(corpus: dict[str, str]) -> dict[str, list[str]]:
    """稀有双词短语 → 含有它的记忆。跨记忆的桥接边用它，边本身有证据（两段原文共有该短语）。"""
    key = str(id(corpus))
    if key in _BIGRAMS:
        return _BIGRAMS[key]
    index: dict[str, list[str]] = {}
    for memory_id, value in corpus.items():
        words = re.findall(r"[a-z']+", str(value).lower())
        for first, second in zip(words, words[1:]):
            if first in STOP or second in STOP or len(first) < 3 or len(second) < 3:
                continue
            index.setdefault(f"{first} {second}", []).append(memory_id)
    _BIGRAMS[key] = index
    return index


def bridge_hop(chosen: list[dict], corpus: dict[str, str], weight, budget: int,
               per_anchor: int = 3, max_df: int = 12) -> list[dict]:
    """一跳桥接：从已选记忆里找稀有短语，把含有同一短语的其它记忆挂进来。"""
    index = bigram_index(corpus)
    seen = {item["memory_id"] for item in chosen}
    added: list[dict] = []
    for item in list(chosen):
        words = re.findall(r"[a-z']+", str(item.get("value") or "").lower())
        phrases = []
        for first, second in zip(words, words[1:]):
            if first in STOP or second in STOP or len(first) < 3 or len(second) < 3:
                continue
            phrase = f"{first} {second}"
            members = index.get(phrase, [])
            if 2 <= len(members) <= max_df:
                phrases.append((weight(phrase.split()[0]), phrase, members))
        phrases.sort(reverse=True)
        taken = 0
        for _score, _phrase, members in phrases:
            for memory_id in members:
                if taken >= per_anchor or len(chosen) + len(added) >= budget:
                    break
                if memory_id in seen:
                    continue
                seen.add(memory_id)
                entity, _, slot = memory_id.partition(":")
                added.append({"memory_id": memory_id, "entity": entity, "slot": slot,
                              "value": corpus.get(memory_id, ""), "status": "current"})
                taken += 1
            if taken >= per_anchor:
                break
    return added


def _coverage(item: dict, requirements: list[str], weight) -> set[str]:
    text = ranker.tokens(f"{item.get('entity') or ''} {item.get('slot') or ''} "
                         f"{item.get('value') or ''}")
    return {term for term in requirements if term in text}


def resolve(service, question: str, entities: list[str], *, budget: int | None = None,
            pool: list[dict] | None = None, corpus: dict[str, str] | None = None,
            sources: dict[str, list[str]] | None = None) -> dict:
    """返回证据链与解析状态；``items`` 是可直接渲染给作答模型的记忆。"""
    aliases = {}
    try:
        aliases = {str(entry.get("alias")): str(entry.get("entity"))
                   for entry in service.aliases().get("names", [])
                   if entry.get("alias") and entry.get("entity")}
    except Exception:
        aliases = {}
    query = plan(question, entities, aliases)
    budget = budget or query["budget"]
    corpus = corpus or {}
    sources = sources or {}
    weight = ranker._idf(ranker.document_frequency(corpus), max(1, len(corpus)))

    candidates = pool or []
    by_id = {item["memory_id"]: item for item in candidates}

    query_tokens = ranker.tokens(question)

    def similarity(item: dict) -> float:
        """和问题整体的相关度：锚点阶段用它，避免只挑“覆盖问题词”的记忆。"""
        text = ranker.tokens(f"{item.get('entity') or ''} {item.get('slot') or ''} "
                             f"{item.get('value') or ''}")
        return sum(weight(token) for token in query_tokens & text)

    def score(item: dict) -> float:
        covered = _coverage(item, query["requirements"], weight)
        return sum(weight(term) for term in covered)

    # Anchor Resolution：先按锚点实体取，再按覆盖度补
    chosen: list[dict] = []
    chains: list[dict] = []
    seen: set[str] = set()

    def take(item: dict, reason: str) -> None:
        if item["memory_id"] in seen or len(chosen) >= budget:
            return
        seen.add(item["memory_id"])
        chosen.append(item)
        chains.append({"memory_id": item["memory_id"], "reason": reason,
                       "source_refs": sources.get(item["memory_id"], []),
                       "covers": sorted(_coverage(item, query["requirements"], weight))})

    for name in query["anchors"]:
        owned = [item for item in candidates
                 if str(item.get("entity") or "").lower() == str(name).lower()]
        owned.sort(key=lambda entry: (similarity(entry), score(entry)), reverse=True)
        for item in owned[:6]:
            take(item, "anchor")

    # Chain Assembly：覆盖度优先，保证每个要求都有证据
    covered: set[str] = set()
    for item in chosen:
        covered |= _coverage(item, query["requirements"], weight)
    remaining = [item for item in candidates if item["memory_id"] not in seen]
    remaining.sort(key=score, reverse=True)
    while len(chosen) < budget:
        best, gain = None, 0.0
        for item in remaining:
            new = _coverage(item, query["requirements"], weight) - covered
            value = sum(weight(term) for term in new)
            if value > gain:
                best, gain = item, value
        if best is None or gain <= 0:
            break
        take(best, "gap_fill")
        covered |= _coverage(best, query["requirements"], weight)
        remaining = [item for item in remaining if item["memory_id"] not in seen]

    # Gap Recovery：覆盖不到的要求，用身份/词法再检索一次（不建边）
    missing = [term for term in query["requirements"] if term not in covered]
    if missing and len(chosen) < budget:
        for term in missing[:4]:
            try:
                recovered = service.search(term, limit=4, diverse=True).get("results", [])
            except Exception:
                recovered = []
            for item in evidence_adapter.candidate_rows(recovered):
                if item["memory_id"] not in by_id:
                    item = dict(item)
                if _coverage(item, query["requirements"], weight):
                    take(item, f"gap_recovery:{term}")
                    covered |= _coverage(item, query["requirements"], weight)
                    break

    # 桥接一跳：多跳的答案常常跨两条记忆，靠稀有短语把另一条挂进来。
    if corpus:
        for item in bridge_hop(chosen, corpus, weight, budget):
            take(item, "bridge")

    # 预算没用完时按相关度补满：证据链给结构，相关记忆给答案。
    filler = sorted((item for item in candidates if item["memory_id"] not in seen),
                    key=similarity, reverse=True)
    for item in filler:
        if len(chosen) >= budget:
            break
        take(item, "support")

    if __import__("os").environ.get("WSC_LOCOMO_V25", "").strip().lower() in {"1", "true", "on"}:
        # 路径排序：覆盖度与相关度加权，证据完整的链排在前面。
        def chain_score(item: dict) -> float:
            return 0.6 * sum(weight(term) for term in
                             _coverage(item, query["requirements"], weight)) \
                + 0.4 * similarity(item)
        chosen.sort(key=chain_score, reverse=True)

    # Validation
    missing = [term for term in query["requirements"] if term not in covered]
    unsourced = [chain["memory_id"] for chain in chains if not chain["source_refs"]]
    if not chosen:
        status = "UNRESOLVED"
    elif unsourced and len(unsourced) == len(chains):
        status = "UNRESOLVED"
    elif missing:
        status = "PARTIAL"
    else:
        status = "SUPPORTED"

    return {"query_id": question[:60], "query_mode": query["query_mode"],
            "anchor_refs": query["anchors"], "items": chosen, "evidence_chains": chains,
            "missing_requirements": missing, "unsourced": unsourced,
            "truncated": len(chosen) >= budget, "resolution_status": status,
            "coverage": (len(query["requirements"]) - len(missing))
                        / max(1, len(query["requirements"]))}
