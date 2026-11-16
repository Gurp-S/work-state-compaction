"""Run CSM on Locomo-Plus (LoCoMo five factual categories + the Cognitive sixth).

The adapter plays the semantic interpreter: each LoCoMo session becomes MemoryCandidates,
questions are answered from CSM retrieval only, and the benchmark's own judge templates score
the answers (correct=1, partial=0.5, wrong=0).

    py -3.11 benchmarks/csm_locomo_plus.py qa --conversation 0
    py -3.11 benchmarks/csm_locomo_plus.py cognitive --samples 100
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / ".bench" / "Locomo-Plus"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(BENCH / "evaluation_framework"))

import locomo_multihop  # noqa: E402
import locomo_trigger  # noqa: E402
import locomo_rank as ranker  # noqa: E402
import evidence_adapter  # noqa: E402
import source_tool_loop  # noqa: E402
from bench_llm import Chat  # noqa: E402
from task_eval.prompt import PROMPT_TEMPLATES  # noqa: E402
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, MemoryQuery  # noqa: E402

CATEGORY_NAMES = {1: "multi-hop", 2: "temporal", 3: "common-sense", 4: "single-hop",
                  5: "adversarial"}
SCORES = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}

EXTRACT_SYSTEM = """你是长期对话记忆提取器。输入是一段多人对话（含日期）。
逐轮提取可被单独问到的原子事实：身份、关系、经历、偏好、计划、时间、地点、数字、物品、原因、感受。
每条事实输出：{"entity": "人物或主题", "slot": "能区分该事实的具体属性名",
"value": "一句英文事实，保留原文数字、日期、地点、物品名与原因", "topics": ["英文检索关键词"]}
规则：
- 一句话里有几个细节就拆成几条；不要概括成"讨论了……"，要写出具体内容。
- 同一人物的同一属性写一条；不同属性用不同 slot。
- entity 用对话中的真实姓名；value 与 topics 用英文。
没有可提取内容输出 []。"""

EXTRACT_SYSTEM_V3 = EXTRACT_SYSTEM.replace(
    "没有可提取内容输出 []。",
    "- 相对时间（yesterday、last week、the Sunday before、next month、two days ago 等）必须按会话日期换算成绝对日期后写进 value，例如 \"on 7 May 2023\"、\"the week before 9 June 2023\"；不要只保留 \"last week\"。\n"
    "- 会话日期只用于换算，不要写进与该事实无关的条目。\n"
    "没有可提取内容输出 []。")

EXTRACT_SYSTEM_V14 = """你是长期对话记忆提取器。输入是一段多人对话（含日期）。
按属性清单逐项检查每个参与者，把对话里明确说到的内容写成原子事实：
身份与自我认同、关系状态、家庭成员、工作与学业、健康、经济、居住与搬迁、计划与愿望、
经历与事件、偏好与厌恶、物品与礼物、地点、原因与动机、感受与评价、数字与时长。
每条输出：{"entity": "人物或主题", "slot": "属性名", "value": "一句英文事实", "topics": ["英文检索关键词"]}
规则：
- 一句话里有几个细节就拆成几条；不要概括成"讨论了……"。
- value 必须能独立回答一个具体问题，保留原文的人名、地点、数字、日期、物品名与原因。
- 同一属性写一条；不同属性用不同 slot；entity 用对话中的真实姓名；value 与 topics 用英文。
- 清单里没有对应内容的项跳过，不要编造。
没有可提取内容输出 []。"""

AUDIT_SYSTEM = """输入是一段对话和已经从它提取出的记忆条目。只做补漏：找出对话里有、但条目里没有的具体事实。
每条输出：{"entity": "人物或主题", "slot": "具体属性名", "value": "一句英文事实", "topics": ["英文检索关键词"]}。
只输出 JSON：{"items": [...]}。没有遗漏输出 {"items": []}。不要重复已有条目。"""

AUDIT_SESSION_SYSTEM = """输入是一段完整对话和已经从它提取出的记忆条目。只做补漏。
按清单逐项检查每个参与者：身份与自我认同、关系状态、家庭成员、工作与学业、健康、经济、
居住与搬迁、计划与愿望、经历与事件、偏好与厌恶、物品与礼物、地点、原因与动机、感受与评价、数字与时长。
找出对话里有、但条目里没有的具体事实，每条输出：
{"entity": "人物或主题", "slot": "属性名", "value": "一句英文事实", "topics": ["英文检索关键词"]}
只输出 JSON：{"items": [...]}。不要重复已有条目；没有遗漏输出 {"items": []}。"""

ANSWER_SYSTEM = """你只依据给出的记忆条目回答问题。条目是唯一事实来源。
信息不足就回答"我不知道"。不要编造，不要解释检索过程。用简洁英文回答。"""

ANSWER_GROUNDED = """你只依据给出的记忆条目回答问题。条目是唯一事实来源。
条目里没有直接答案时，给出最接近的一条并说明依据的是哪条记忆；不要编造。用简洁英文回答。"""

ANSWER_CITE = """你只依据给出的记忆条目回答问题。条目是唯一事实来源。
先照抄那条直接支持答案的记忆原文（一条即可），再用一句简洁英文给出答案；两者用换行分开。
条目里没有直接答案时，只写：not mentioned in the conversation。不要编造。"""

COGNITIVE_SYSTEM = """你只依据给出的记忆条目回应用户。条目是唯一事实来源。
结合相关记忆自然地回应，不要复述检索过程，不要编造。用简洁英文回答。"""

JUDGE_SYSTEM = """你是严格评分员。按模板判断预测是否正确，只输出 JSON：{"label": "correct"|"partial"|"wrong", "reason": "..."}"""


def _on_default(name: str) -> bool:
    """默认开启的开关：只有显式设成 0/false/off 才关闭。"""
    return os.environ.get(name, "1").strip().lower() not in {"0", "false", "no", "off"}


def _on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def answer_prompt() -> str:
    if _on("WSC_LOCOMO_V19"):
        return ANSWER_CITE
    return ANSWER_GROUNDED if _on("WSC_LOCOMO_ANSWER_GROUNDED") else ANSWER_SYSTEM


def _window() -> int:
    try:
        return max(1, int(os.environ.get("WSC_LOCOMO_EXTRACT_WINDOW", "8")))
    except ValueError:
        return 8


def _cache_path() -> Path | None:
    raw = os.environ.get("WSC_LOCOMO_EXTRACT_CACHE", "").strip()
    return Path(raw) if raw else None


def _load_cache(path: Path | None) -> dict:
    if not path or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(path: Path | None, cache: dict) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def parallel_map(fn, items: list, width: int) -> list:
    """保序并发；width=1 时退化成串行，保证 A/B 只有并行度这一个变量。"""
    if width <= 1 or len(items) <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(width, len(items))) as pool:
        return list(pool.map(fn, items))


def cached_extract(chat: Chat, date: str, turns: list[dict], key: str, cache: dict) -> list[dict]:
    """同一批轮次只抽一次：重跑时抽取全命中，只有问答和判分花钱。"""
    if key in cache:
        return [dict(item) for item in cache[key]]
    items = extract_session(chat, date, turns)
    cache[key] = items
    return items


RESOLVE_SYSTEM = """输入是会话日期和若干条已提取的事实。只做一件事：把事实里的相对时间换算成绝对日期。
只输出含相对时间的事实，格式 {"items": [{"slot": "原 slot", "happened_on": "7 May 2023"}]}。
happened_on 用英文日期短语，能精确到日就到日；没有相对时间的事实不要输出。没有可换算的输出 {"items": []}。"""

_WEEKDAY = r"(?:mon|tue|wed|thu|fri|sat|sun)(?:day|sday|nesday|rsday|urday)?"
RELATIVE = re.compile(
    r"\b(yesterday|today|tomorrow|tonight|recently"
    r"|last (?:week|month|year|night|weekend|" + _WEEKDAY + r")"
    r"|next (?:week|month|year|" + _WEEKDAY + r")"
    r"|this (?:past )?" + _WEEKDAY +
    r"|the (?:day|week|weekend|month|year|" + _WEEKDAY + r") (?:before|after)"
    r"|\d+ (?:days?|weeks?|months?|years?) (?:ago|before|after)"
    r"|a (?:few|couple) (?:days?|weeks?) ago)\b", re.I)


def has_relative(value: str) -> bool:
    return bool(RELATIVE.search(str(value)))


def resolve_relative(chat: Chat, date: str, items: list[dict], key: str,
                     cache: dict) -> dict[str, str]:
    """会话日期 + 事实 → slot 的绝对日期。事实本身一个字不改，所以主抽取的产出量不受影响。"""
    if key in cache:
        return {str(slot): str(day) for slot, day in cache[key].items()}
    pending = [item for item in items if has_relative(item.get("value", ""))]
    if not pending:
        cache[key] = {}
        return {}
    lines = "\n".join(f'- slot: {item["slot"]} | 事实: {item["value"]}' for item in pending)
    resolved: dict[str, str] = {}
    try:
        payload = chat.ask_json(RESOLVE_SYSTEM, f"会话日期：{date}\n事实：\n{lines}", max_tokens=800)
    except (ValueError, json.JSONDecodeError):
        payload = {}
    entries = payload.get("items") if isinstance(payload, dict) else payload
    for entry in entries or []:
        if isinstance(entry, dict) and entry.get("slot") and entry.get("happened_on"):
            resolved[str(entry["slot"])] = str(entry["happened_on"])
    if not resolved:
        # 一次失败就静默丢日期，会让时间题无从回答：换更直的问法再要一次。
        retry = ("会话日期：" + str(date) + "\n逐条给出绝对日期，只输出 JSON："
                 '{"items": [{"slot": "原 slot", "happened_on": "绝对日期"}]}\n' + lines)
        try:
            payload = chat.ask_json(RESOLVE_SYSTEM, retry, max_tokens=800)
            entries = payload.get("items") if isinstance(payload, dict) else payload
            for entry in entries or []:
                if isinstance(entry, dict) and entry.get("slot") and entry.get("happened_on"):
                    resolved[str(entry["slot"])] = str(entry["happened_on"])
        except (ValueError, json.JSONDecodeError):
            pass
    cache[key] = resolved
    _RESOLVE["pending"] += len(pending)
    _RESOLVE["resolved"] += len(resolved)
    return resolved


def audit_chunk(chat: Chat, date: str, turns: list[dict], items: list[dict], key: str,
                cache: dict) -> list[dict]:
    """补漏通道：把这一段的对话和已抽出的条目一起给模型，只要它补上漏掉的事实。"""
    if key in cache:
        return [dict(entry) for entry in cache[key]]
    lines = "\n".join(f"{turn.get('speaker', '')}: {turn.get('text', '')}" for turn in turns)
    covered = "\n".join(f"- {item.get('entity')} | {item.get('slot')} | {item.get('value')}"
                        for item in items)
    user = f"日期：{date}\n对话：\n{lines}\n已提取条目：\n{covered}"
    try:
        payload = chat.ask_json(AUDIT_SYSTEM, user, max_tokens=2000)
    except (ValueError, json.JSONDecodeError):
        payload = {}
    extra = payload.get("items") if isinstance(payload, dict) else payload
    extra = [entry for entry in (extra or [])
             if isinstance(entry, dict) and entry.get("value") and entry.get("entity")]
    cache[key] = extra
    return [dict(entry) for entry in extra]


def audit_session(chat: Chat, date: str, turns: list[dict], items: list[dict], key: str,
                  cache: dict) -> list[dict]:
    """会话级补漏：整段对话 + 已抽条目 + 属性清单，专门找跨轮才成立的漏项。"""
    if key in cache:
        return [dict(entry) for entry in cache[key]]
    lines = "\n".join(f"{turn.get('speaker', '')}: {turn.get('text', '')}" for turn in turns)
    covered = "\n".join(f"- {item.get('entity')} | {item.get('slot')} | {item.get('value')}"
                        for item in items)
    user = f"日期：{date}\n对话：\n{lines}\n已提取条目：\n{covered}"
    try:
        payload = chat.ask_json(AUDIT_SESSION_SYSTEM, user, max_tokens=2500)
    except (ValueError, json.JSONDecodeError):
        payload = {}
    extra = payload.get("items") if isinstance(payload, dict) else payload
    known = {str(item.get("value") or "").lower() for item in items}
    kept = []
    for entry in extra or []:
        if not (isinstance(entry, dict) and entry.get("value") and entry.get("entity")):
            continue
        value = str(entry["value"])
        if value.lower() in known:
            continue
        overlap = max((len(set(value.lower().split()) & set(other.split()))
                       / max(1, len(set(value.lower().split()) | set(other.split())))
                       for other in known), default=0.0)
        if overlap >= 0.8:
            continue
        known.add(value.lower())
        kept.append(entry)
    cache[key] = kept
    return [dict(entry) for entry in kept]


def sessions_of(sample: dict) -> list[tuple[str, str, list[dict]]]:
    conversation = sample["conversation"]
    out = []
    index = 1
    while f"session_{index}" in conversation:
        turns = conversation[f"session_{index}"]
        out.append((f"session_{index}", conversation.get(f"session_{index}_date_time", ""), turns))
        index += 1
    return out


def extract_session(chat: Chat, date: str, turns: list[dict]) -> list[dict]:
    lines = "\n".join(f"{turn.get('speaker', '')}: {turn.get('text', '')}" for turn in turns)
    user = f"日期：{date}\n对话：\n{lines}"
    if _on("WSC_LOCOMO_V14"):
        system = EXTRACT_SYSTEM_V14
    elif _on("WSC_LOCOMO_V3"):
        system = EXTRACT_SYSTEM_V3
    else:
        system = EXTRACT_SYSTEM
    for attempt in range(2):
        try:
            items = chat.ask_json(system, user, max_tokens=3000)
        except (ValueError, json.JSONDecodeError):
            if attempt == 0:
                continue
            return []
        if isinstance(items, dict):
            items = next((value for value in items.values() if isinstance(value, list)), [])
        if isinstance(items, list):
            break
        return []
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        entity, slot, value = (str(item.get(k) or "").strip() for k in ("entity", "slot", "value"))
        if not entity or not slot or not value:
            continue
        topics = [str(t).strip() for t in item.get("topics") or [] if str(t).strip()]
        out.append({"entity": entity, "slot": slot, "value": value, "topics": topics[:6]})
    return out


def ingest_conversation(service, chat: Chat, sample: dict, prefix: str) -> list[str]:
    entities: list[str] = []
    used: dict[tuple[str, str], int] = {}
    sessions = sessions_of(sample)
    # 抽取只吃「日期 + 这几轮」，彼此无依赖：整段并发抽完，再按会话顺序写库。
    size = max(1, int(os.environ.get("WSC_LOCOMO_CHUNK", "4")))
    chunks = [(name, date, turns[start:start + size])
              for name, date, turns in sessions
              for start in range(0, len(turns), size)]
    cache_path = _cache_path()
    cache = _load_cache(cache_path)
    width = _window()

    def one(chunk: tuple[str, str, list[dict]]) -> list[dict]:
        name, date, turns = chunk
        head = turns[0].get("dia_id") or str(turns[0].get("text", ""))[:16]
        tag = "V14/" if _on("WSC_LOCOMO_V14") else ("V3/" if _on("WSC_LOCOMO_V3") else "")
        items = cached_extract(chat, date, turns, f"{tag}{prefix}/{name}#{head}", cache)
        if _on("WSC_LOCOMO_V13"):
            items = items + audit_chunk(chat, date, turns, items,
                                        f"A/{prefix}/{name}#{head}", cache)
        if _on_default("WSC_LOCOMO_V5"):
            resolved = resolve_relative(chat, date, items, f"V5c/{prefix}/{name}#{head}", cache)
            for item in items:
                item["happened_on"] = resolved.get(item["slot"], "")
        return items

    started = time.time()
    extracted = parallel_map(one, chunks, width)
    _save_cache(cache_path, cache)
    if len(chunks) > 1:
        print(f"  extract {len(chunks)} chunks, window={width}, {time.time() - started:.1f}s",
              flush=True)
    by_session: dict[str, list[dict]] = {}
    for (name, _date, _turns), items in zip(chunks, extracted):
        by_session.setdefault(name, []).extend(items)
    for name, date, turns in sessions:
        event_id = f"{prefix}/{name}"
        service.ingest([Event(id=event_id, source_type="chat",
                              payload={"date": date, "turns": turns})])
        candidates = by_session.get(name, [])
        if _on("WSC_LOCOMO_V15"):
            extra = audit_session(chat, date, turns, candidates,
                                  f"S/{prefix}/{name}", cache)
            if extra:
                resolved = resolve_relative(chat, date, extra, f"S5/{prefix}/{name}", cache)
                for item in extra:
                    item["happened_on"] = resolved.get(item["slot"], "")
                candidates = candidates + extra
        if not candidates:
            print(f"  {event_id}: no memories extracted", flush=True)
        if candidates:
            batch = []
            happened_of: list[str] = []
            for item in candidates:
                key = (item["entity"], item["slot"])
                used[key] = used.get(key, 0) + 1
                slot = item["slot"] if used[key] == 1 else f"{item['slot']} {used[key]}"
                topics = tuple(item["topics"])
                if _on_default("WSC_LOCOMO_V2"):
                    phrase = ranker.date_phrase(date)
                    topics = topics + ((phrase,) if phrase else ())
                happened = str(item.get("happened_on") or "") if _on_default("WSC_LOCOMO_V5") else ""
                value = item["value"]
                if happened:
                    phrase = ranker.date_phrase(happened)
                    if phrase:
                        topics = topics + (phrase,)
                    if _on("WSC_LOCOMO_V6"):
                        # 只把日期贴回原句里含相对时间的那几条；其余事实保持原样。
                        value = f"{value} (on {happened})"
                batch.append(MemoryCandidate(entity=item["entity"], slot=slot,
                                             value=value, topics=topics,
                                             source_ids=(event_id,)))
                happened_of.append(happened)
            results = service.remember(batch, producer="locomo-adapter")
            if _on_default("WSC_LOCOMO_V2"):
                for result, happened in zip(results, happened_of):
                    memory_id = (result.get("pending_id") or result.get("memory_id")) if isinstance(result, dict) else None
                    if not memory_id:
                        continue
                    _DATES[str(memory_id)] = date
                    if happened:
                        _HAPPENED[str(memory_id)] = happened
            for item in candidates:
                if item["entity"] not in entities:
                    entities.append(item["entity"])
    _save_cache(cache_path, cache)
    if _RESOLVE["pending"]:
        rate = _RESOLVE["resolved"] / _RESOLVE["pending"] * 100
        print(f"  relative-time resolve: {_RESOLVE['resolved']}/{_RESOLVE['pending']} ({rate:.0f}%)",
              flush=True)
    return entities


_RESOLVE: dict[str, int] = {"pending": 0, "resolved": 0}
_DATES: dict[str, str] = {}
_HAPPENED: dict[str, str] = {}
_CORPUS: dict[str, dict[str, str]] = {}
_DB_PATH: str = ""


def _corpus() -> dict[str, str]:
    """All memory values, for IDF weights; read once per run."""
    if _DB_PATH not in _CORPUS:
        con = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        try:
            _CORPUS[_DB_PATH] = {memory_id: str(json.loads(data).get("value") or "")
                                 for memory_id, data in
                                 con.execute("select memory_id, data from revisions")}
        finally:
            con.close()
    return _CORPUS[_DB_PATH]


def _alias_map(service) -> dict[str, str]:
    try:
        names = service.aliases(include_proposals=False)["names"]
    except Exception:
        return {}
    return {str(item.get("alias")): str(item.get("entity")) for item in names
            if item.get("alias") and item.get("entity")}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9']+", str(text).lower()) if len(t) > 2}


_SOURCES: dict[str, dict[str, list[str]]] = {}
_MEMBERS: dict[str, dict[str, list[str]]] = {}


def _session_index() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """memory -> 来源会话，会话 -> 该会话的全部 memory。跨主题的连接靠它扩展。"""
    if _DB_PATH not in _SOURCES:
        con = sqlite3.connect(f"file:{_DB_PATH}?mode=ro", uri=True)
        sources: dict[str, list[str]] = {}
        members: dict[str, list[str]] = {}
        try:
            for memory_id, data in con.execute("select memory_id, data from revisions"):
                refs = [str(ref) for ref in (json.loads(data).get("source_refs") or [])]
                sources[memory_id] = refs
                for ref in refs:
                    members.setdefault(ref, []).append(memory_id)
        finally:
            con.close()
        _SOURCES[_DB_PATH] = sources
        _MEMBERS[_DB_PATH] = members
    return _SOURCES[_DB_PATH], _MEMBERS[_DB_PATH]


def expand_by_session(pool: list[dict], question: str, matched: list[str] | None = None,
                      seeds: int = 6, per_session: int = 40) -> list[dict]:
    """把高分候选所在会话里的其它记忆也放进候选池：一条事实的上下文往往在同一个会话里。

    ``bridge`` 模式只扩展「同一会话里同时出现过两个以上被问到的实体」的会话——
    那才是跨主题的关联桥；单实体问题没有桥，扩展只会塞进无关记忆。
    """
    sources, members = _session_index()
    corpus = _corpus()
    wanted = _tokens(question)
    ordered = sorted(pool, key=lambda item: len(wanted & _tokens(item.get("value") or "")),
                     reverse=True)
    seen = {item["memory_id"] for item in pool}
    sessions: list[str] = []
    if os.environ.get("WSC_LOCOMO_V8_MODE", "all").strip().lower() == "bridge":
        wanted_entities = {str(name).lower() for name in (matched or [])}
        for ref, ids in members.items():
            present = {str(memory_id).partition(":")[0].lower() for memory_id in ids}
            if len(present & wanted_entities) >= 2:
                sessions.append(ref)
    else:
        for item in ordered[:seeds]:
            for ref in sources.get(item["memory_id"], []):
                if ref not in sessions:
                    sessions.append(ref)
    added: list[dict] = []
    for ref in sessions:
        for memory_id in members.get(ref, [])[:per_session]:
            if memory_id in seen:
                continue
            seen.add(memory_id)
            entity, _, slot = memory_id.partition(":")
            added.append({"memory_id": memory_id, "entity": entity, "slot": slot,
                          "value": corpus.get(memory_id, ""), "status": "current",
                          "score": 0.0})
    return pool + added


_RERANK: dict | None = None


def _rerank_cache() -> dict:
    global _RERANK
    if _RERANK is None:
        _RERANK = _load_cache(_cache_path())
    return _RERANK


RERANK_SYSTEM = """输入是一个问题和若干条带序号记忆。只做选择：挑出回答问题真正需要的记忆，最多 12 条。
只输出 JSON：{"indices": [序号, ...]}，序号就是记忆前面的数字。不要解释，不要改写记忆内容。"""


def llm_rerank(chat, question: str, pool: list[dict], key: str, cache: dict,
               limit: int = 12) -> list[dict]:
    """让模型在候选池上挑，而不是靠词元重合。候选池不变，只是把对的那几条排到前面。"""
    if key in cache:
        indices = [int(value) for value in cache[key]]
    else:
        rows = "\n".join(f'{index}. {str(item.get("value"))[:170]}'
                         for index, item in enumerate(pool[:48]))
        try:
            payload = chat.ask_json(RERANK_SYSTEM, f"问题：{question}\n记忆：\n{rows}",
                                    max_tokens=400)
        except (ValueError, json.JSONDecodeError):
            payload = {}
        raw = payload.get("indices") if isinstance(payload, dict) else payload
        indices = []
        for value in raw or []:
            try:
                indices.append(int(value))
            except (TypeError, ValueError):
                continue
        cache[key] = indices
    picked = [pool[index] for index in indices if 0 <= index < len(pool)]
    return picked[:limit]


def candidate_pool(service, question: str, entities: list[str]) -> list[dict]:
    """The candidate set before truncation: free-text search plus identity lookups."""
    pool: dict[str, dict] = {}
    for item in evidence_adapter.candidate_rows(service.search(question, limit=40, diverse=True)["results"]):
        pool[item["memory_id"]] = item
    if _on_default("WSC_LOCOMO_V2"):
        matched = ranker.match_entities(question, entities, _alias_map(service))
    else:
        lowered = question.lower()
        matched = [name for name in entities
                   if name and name.split()[0].lower() in lowered]
    for name in matched:
        for item in evidence_adapter.candidate_rows(service.query(MemoryQuery(entity=name, limit=60))["results"]):
            pool.setdefault(item["memory_id"], item)
    items = list(pool.values())
    if _on("WSC_LOCOMO_V8"):
        items = expand_by_session(items, question, matched)
    return items


def retrieve_wide(service, question: str, entities: list[str], limit: int = 12,
                  chat=None) -> list[dict]:
    """宽召回 + 重排：引擎只给候选，这里决定哪 12 条进窗口。"""
    if _on("WSC_LOCOMO_V24"):
        question = ranker.normalize_query(question, _alias_map(service), entities)
    pool = {item["memory_id"]: item for item in candidate_pool(service, question, entities)}
    if _on_default("WSC_LOCOMO_V2"):
        values = _corpus()
        cap = int(os.environ.get("WSC_LOCOMO_V2_ENTITY_CAP", "99"))
        frequency = ranker.document_frequency(values)
        if _on("WSC_LOCOMO_V18"):
            # 会话级上下文装配：先用检索定位最相关的会话，再把该会话的记忆整体挂进来。
            everything = ranker.rank(list(pool.values()), question, values, frequency,
                                     limit=len(pool), per_entity=cap)
            sources, members = _session_index()
            corpus = _corpus()
            budget = int(os.environ.get("WSC_LOCOMO_V18_BUDGET", "45"))
            per_session = int(os.environ.get("WSC_LOCOMO_V18_PER", "20"))
            rank_of = {item["memory_id"]: position for position, item in enumerate(everything)}
            sessions: list[str] = []
            matched = ranker.match_entities(question, entities, _alias_map(service))
            if _on("WSC_LOCOMO_V20") and len(matched) >= 2 \
                    and not ranker.is_temporal(question):
                # 多实体问题：每个实体各定位一个会话，否则一侧的会话会被另一侧挤掉。
                for name in matched:
                    for item in everything:
                        if str(item.get("entity") or "").lower() != str(name).lower():
                            continue
                        for ref in sources.get(item["memory_id"], []):
                            if ref not in sessions:
                                sessions.append(ref)
                        break
            for item in everything[:8]:
                for ref in sources.get(item["memory_id"], []):
                    if ref not in sessions:
                        sessions.append(ref)
                if len(sessions) >= 3:
                    break
            chosen: list[dict] = []
            seen: set[str] = set()

            def add(item: dict) -> None:
                if item["memory_id"] not in seen and len(chosen) < budget:
                    seen.add(item["memory_id"])
                    chosen.append(item)

            for ref in sessions[:3]:
                ordered = sorted(members.get(ref, []), key=lambda mid: rank_of.get(mid, 10 ** 6))
                for memory_id in ordered[:per_session]:
                    entity, _, slot = memory_id.partition(":")
                    add({"memory_id": memory_id, "entity": entity, "slot": slot,
                         "value": corpus.get(memory_id, ""), "status": "current"})
            for item in everything:
                if len(chosen) >= budget:
                    break
                add(item)
            return chosen
        if _on("WSC_LOCOMO_V17"):
            # 实体状态整体挂载：问题点名的实体，把它名下的记忆按相关度挂进来，
            # 而不是让全局 Top-K 把某个实体的状态切碎。
            matched = ranker.match_entities(question, entities, _alias_map(service))
            everything = ranker.rank(list(pool.values()), question, values, frequency,
                                     limit=len(pool), per_entity=cap)
            budget = int(os.environ.get("WSC_LOCOMO_V17_BUDGET", "40"))
            per = int(os.environ.get("WSC_LOCOMO_V17_PER", "18"))
            chosen: list[dict] = []
            seen: set[str] = set()

            def add(item: dict) -> None:
                if item["memory_id"] not in seen and len(chosen) < budget:
                    seen.add(item["memory_id"])
                    chosen.append(item)

            for name in matched:
                taken = 0
                for item in everything:
                    if taken >= per:
                        break
                    if str(item.get("entity") or "").lower() == str(name).lower():
                        add(item)
                        taken += 1
            for item in everything[:limit]:
                add(item)
            for item in everything:
                if len(chosen) >= budget:
                    break
                add(item)
            return chosen
        if _on("WSC_LOCOMO_V10"):
            matched = ranker.match_entities(question, entities, _alias_map(service))
            ordered = ranker.rank_bm25(list(pool.values()), question, values, frequency,
                                       limit=limit, per_entity=cap,
                                       matched=matched if _on("WSC_LOCOMO_V11") else None)
        else:
            ordered = ranker.rank(list(pool.values()), question, values, frequency,
                                  limit=max(limit, 48) if _on("WSC_LOCOMO_V9") else limit,
                                  per_entity=cap)
        if chat is not None and _on("WSC_LOCOMO_V9"):
            # 先按词法取前 48，再让模型在「已经相关的 48 条」里挑——否则它看到的是随机子集。
            return llm_rerank(chat, question, ordered, f"R3/{question}",
                              _rerank_cache(), limit)
        return ordered
    query_tokens = _tokens(question)

    def score(item: dict) -> float:
        text = _tokens(" ".join(str(item.get(k) or "") for k in ("entity", "slot", "value")))
        return len(query_tokens & text) + 0.15 * float(item.get("score") or 0)

    return sorted(pool.values(), key=score, reverse=True)[:limit]


_TRIGGERS: dict[str, dict] = {}
_TRIGGER_ITEMS: dict[str, dict] = {}


def prepare_triggers(chat, service, entities: list[str]) -> None:
    """写入侧一次性提出 Trigger Profile；之后的查询只做触发与适用性判断。"""
    if not _on("WSC_LOCOMO_V23") or _TRIGGERS:
        return
    for name in entities:
        for item in evidence_adapter.candidate_rows(service.query(MemoryQuery(entity=name, limit=200))["results"]):
            _TRIGGER_ITEMS[item["memory_id"]] = item
    cache = _load_cache(_cache_path()) or {}
    _TRIGGERS.update(locomo_trigger.derive_triggers(chat, list(_TRIGGER_ITEMS.values()), cache))
    _save_cache(_cache_path(), cache)


def trigger_context(question: str, entities: list[str]) -> list[dict]:
    """CTR + AR：按情境触发候选，再判定能否使用。"""
    frame = locomo_trigger.context_frame(question, entities)
    hits = locomo_trigger.trigger_hits(frame, _TRIGGERS, _TRIGGER_ITEMS)
    kept = []
    for hit in hits:
        result = locomo_trigger.resolve_applicability(frame, hit)
        if result["verdict"] == "APPLICABLE" and result["usage_mode"] != "DO_NOT_USE":
            kept.append({**hit, "usage_mode": result["usage_mode"]})
    kept.sort(key=lambda item: item["usage_mode"] != "HARD_CONSTRAINT")
    return kept[:8]


def oracle_sessions(service, question: str, evidence: list[str], prefix: str,
                    limit: int = 12) -> list[dict]:
    """会话级上限：证据轮所在会话的全部记忆都给模型，量「检索定位对了会话」能到多少分。"""
    sources, members = _session_index()
    corpus = _corpus()
    wanted = _tokens(question)
    sessions: list[str] = []
    for dia in evidence or []:
        match = re.match(r"D(\d+):", str(dia))
        if match:
            sessions.append(f"{prefix}/session_{match.group(1)}")
    candidates: list[tuple[float, dict]] = []
    seen: set[str] = set()
    for session in sessions:
        for memory_id in members.get(session, []):
            if memory_id in seen:
                continue
            seen.add(memory_id)
            value = corpus.get(memory_id, "")
            entity, _, slot = memory_id.partition(":")
            score = len(wanted & _tokens(value))
            candidates.append((score, {"memory_id": memory_id, "entity": entity,
                                       "slot": slot, "value": value, "status": "current"}))
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    limit = int(os.environ.get("WSC_LOCOMO_ORACLE_LIMIT", str(limit)))
    return [item for _score, item in candidates[:limit]]


def oracle_items(service, question: str, gold: str, entities: list[str],
                 limit: int = 12) -> list[dict]:
    """上限探针：直接给覆盖参考答案的记忆，用来区分“检索不够”和“抽取/作答不够”。"""
    pool = {item["memory_id"]: item for item in candidate_pool(service, question, entities)}
    values = _corpus()
    weight = ranker._idf(ranker.document_frequency(values), max(1, len(values)))
    wanted = ranker.tokens(gold)
    scored = []
    for memory_id, value in values.items():
        present = ranker.tokens(value)
        got = sum(weight(token) for token in wanted if token in present)
        if got <= 0:
            continue
        item = pool.get(memory_id) or {"memory_id": memory_id,
                                       "entity": memory_id.partition(":")[0],
                                       "slot": memory_id.partition(":")[2],
                                       "value": value, "status": "current"}
        scored.append((got, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in scored[:limit]]


def _retrieve_legacy(service, question: str, entities: list[str], limit: int = 12,
             chat=None) -> list[dict]:
    if _on("WSC_LOCOMO_RETRIEVE_WIDE"):
        return retrieve_wide(service, question, entities, limit, chat)
    seen: dict[str, dict] = {}
    for item in evidence_adapter.candidate_rows(service.search(question, limit=12)["results"]):
        seen[item["memory_id"]] = item
    for name in entities:
        if name and name.split()[0] in question:
            for item in evidence_adapter.candidate_rows(service.query(MemoryQuery(entity=name, limit=8))["results"]):
                seen.setdefault(item["memory_id"], item)
    return sorted(seen.values(), key=lambda item: -item.get("score", 0))[:limit]


_RETRIEVAL_FLAGS = ("WSC_LOCOMO_RETRIEVE_WIDE", "WSC_LOCOMO_V18", "WSC_LOCOMO_V21",
                    "WSC_LOCOMO_V23", "WSC_LOCOMO_V24", "WSC_LOCOMO_ORACLE")


def _validate_retrieval_config():
    evidence_adapter.validate_config(_RETRIEVAL_FLAGS)
    if (_on("WSC_LOCOMO_V18") or _on("WSC_LOCOMO_V24")) and not _on("WSC_LOCOMO_RETRIEVE_WIDE"):
        raise ValueError("V18/V24 require WSC_LOCOMO_RETRIEVE_WIDE=1; refusing silently inactive features")


def retrieve(service, question: str, entities: list[str], limit: int = 12, chat=None):
    _validate_retrieval_config()
    if evidence_adapter.source_only():
        return evidence_adapter.retrieve(service, question, limit=limit)
    primary = _retrieve_legacy(service, question, entities, limit, chat)
    return evidence_adapter.fuse(service, question, primary) if evidence_adapter.enabled() else primary


def qa_context(service, chat, question, entities, conversation=0):
    """One router for both backends: enhancements run before evidence fusion."""
    _validate_retrieval_config()
    text = question["question"]
    category = CATEGORY_NAMES.get(question["category"], "single-hop")
    if evidence_adapter.source_only():
        return evidence_adapter.retrieve(service, text, limit=12)
    if _on("WSC_LOCOMO_V23") and category == "common-sense":
        primary = trigger_context(text, entities)
        if len(primary) < 6:
            primary = primary + _retrieve_legacy(service, text, entities, chat=chat)
    elif _on("WSC_LOCOMO_V21") and category == "multi-hop":
        pool = candidate_pool(service, text, entities)
        primary = locomo_multihop.resolve(service, text, entities, pool=pool,
            budget=int(os.environ.get("WSC_LOCOMO_V21_BUDGET", "24")),
            corpus=_corpus(), sources=_session_index()[0])["items"]
    elif os.environ.get("WSC_LOCOMO_ORACLE", "").strip().lower() == "session":
        primary = oracle_sessions(service, text, question.get("evidence") or [], f"conv{conversation}")
    elif _on("WSC_LOCOMO_ORACLE"):
        primary = oracle_items(service, text, question.get("answer", ""), entities)
    else:
        primary = _retrieve_legacy(service, text, entities, chat=chat)
    return evidence_adapter.fuse(service, text, primary) if evidence_adapter.enabled() else primary


def render(items: list[dict]) -> str:
    if isinstance(items, evidence_adapter.FusedRows):
        return evidence_adapter.render_fused(items, render(list(items.primary)))
    if isinstance(items, evidence_adapter.EvidenceRows):
        return evidence_adapter.render(items)
    rows = []
    for item in items:
        row = {"entity": item.get("entity"), "slot": item.get("slot"),
               "value": item.get("value"), "status": item.get("status")}
        if item.get("record_type") == "pending":
            row.update({key: item.get(key) for key in ("record_type", "classification", "pending_id", "confirmed", "source_refs")})
        said_on = _DATES.get(str(item.get("memory_id")))
        if said_on:
            row["said_on"] = said_on
        happened_on = _HAPPENED.get(str(item.get("memory_id")))
        if happened_on and _on_default("WSC_LOCOMO_V7"):
            # 存储不动，只在给模型的这一份里把日期贴回事实旁边。
            row["value"] = f"{row['value']} (on {happened_on})"
        elif happened_on:
            row["happened_on"] = happened_on
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False)


def judge(chat: Chat, category: str, gold: str, pred: str, evidence: str) -> dict:
    template = PROMPT_TEMPLATES.get(category) or PROMPT_TEMPLATES["default"]
    prompt = template.format(gold=gold or "", pred=pred or "", evidence=evidence or "")
    try:
        verdict = chat.ask_json(JUDGE_SYSTEM, prompt, max_tokens=200)
    except (ValueError, json.JSONDecodeError):
        return {"label": "wrong", "reason": "judge_unparseable"}
    label = str(verdict.get("label", "")).strip().lower()
    return {"label": label if label in SCORES else "wrong",
            "reason": str(verdict.get("reason", ""))[:200]}


def summarize(records: list[dict], started: float, chat: Chat, **extra) -> dict:
    by_category: dict[str, dict] = {}
    for record in records:
        bucket = by_category.setdefault(record["category"], {"total": 0, "score": 0.0})
        bucket["total"] += 1
        bucket["score"] += SCORES.get(record["judge"]["label"], 0.0)
    for bucket in by_category.values():
        bucket["accuracy"] = round(bucket["score"] / bucket["total"], 4)
    total = len(records)
    return {"benchmark": "Locomo-Plus", **extra,
            "questions": total,
            "accuracy": round(sum(SCORES.get(r["judge"]["label"], 0.0) for r in records) / total, 4)
            if total else None,
            "by_category": by_category,
            "calls": chat.calls, "seconds": round(time.time() - started, 1),
            "judge": "Locomo-Plus task_eval templates"}


def run_qa(conversation: int, out: Path, db: Path) -> dict:
    _validate_retrieval_config()
    started = time.time()
    data = json.loads((BENCH / "data" / "locomo10.json").read_text(encoding="utf-8"))
    sample = data[conversation]
    chat = Chat()
    service = CSM(CsmStore(db, namespace=f"locomo{conversation}"))
    entities = ingest_conversation(service, chat, sample, f"conv{conversation}")
    if not evidence_adapter.source_only():
        prepare_triggers(chat, service, entities)
    questions = sample["qa"]
    print(f"conversation {conversation}: {len(questions)} QA, {len(entities)} entities", flush=True)

    def one(question: dict) -> dict:
        items = qa_context(service, chat, question, entities, conversation)
        source_run = None
        if source_tool_loop.enabled():
            source_run = source_tool_loop.answer(chat, service, question['question'], items,
                                                  render(items), answer_prompt())
            answer = source_run['answer']
        else:
            answer = chat.ask(answer_prompt(), f"Question: {question['question']}\nMemories: {render(items)}",
                              max_tokens=800)
        category = CATEGORY_NAMES.get(question["category"], "single-hop")
        verdict = judge(chat, category, question.get("answer", ""), answer,
                        " ".join(str(e) for e in question.get("evidence", [])))
        return {"question": question["question"], "gold": question.get("answer", ""),
                "prediction": answer, "category": category, "judge": verdict,
                "primary_retrieved": [r["memory_id"] for r in items.primary] if isinstance(items, evidence_adapter.FusedRows) else None,
                "supplement_retrieved": [r["memory_id"] for r in items.supplement["items"]] if isinstance(items, evidence_adapter.FusedRows) else None,
                "context_chars": len(render(items)),
                "retrieved": [item["memory_id"] for item in items],
                **({'source_tool': source_run['source_tool']} if source_run is not None else {})}

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(one, questions))
    if _RERANK is not None:
        _save_cache(_cache_path(), _RERANK)
    summary = summarize(records, started, chat, dataset="locomo10 conversation %d" % conversation,
                        pipeline=evidence_adapter.configuration(),
                        retrieval_flags={name: os.environ.get(name, "0") for name in _RETRIEVAL_FLAGS},
                        retrieval=evidence_adapter.policy() if evidence_adapter.enabled() else
                                  "identity query + lexical search over CSM")
    out.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return summary


def run_cognitive(count: int, out: Path, db: Path) -> dict:
    _validate_retrieval_config()
    started = time.time()
    data = json.loads((BENCH / "data" / "locomo10.json").read_text(encoding="utf-8"))
    cognitive = json.loads((BENCH / "data" / "locomo_plus.json").read_text(encoding="utf-8"))[:count]
    sample = data[0]
    chat = Chat()
    service = CSM(CsmStore(db, namespace="locomo-cognitive"))
    entities = ingest_conversation(service, chat, sample, "conv0")
    print(f"cognitive: {len(cognitive)} triggers over conversation 0", flush=True)
    for index, item in enumerate(cognitive):
        service.ingest([Event(id=f"cue/{index:03d}", source_type="chat",
                              payload={"cue": item["cue_dialogue"]})])
        service.remember([MemoryCandidate(entity=f"cue-{index:03d}", slot="dialogue",
                                          value=item["cue_dialogue"], topics=("cue",),
                                          source_ids=(f"cue/{index:03d}",))],
                         producer="locomo-adapter")
        entities.append(f"cue-{index:03d}")

    def one(item: dict) -> dict:
        question = item["trigger_query"]
        items = retrieve(service, question, entities)
        answer = chat.ask(COGNITIVE_SYSTEM,
                          f"User: {question}\nMemories: {render(items)}", max_tokens=200)
        verdict = judge(chat, "Cognitive", "", answer, item["cue_dialogue"])
        return {"question": question, "gold": item["cue_dialogue"], "prediction": answer,
                "category": "Cognitive", "judge": verdict,
                "retrieved": [entry["memory_id"] for entry in items]}

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(one, cognitive))
    summary = summarize(records, started, chat, dataset="locomo_plus cue/trigger subset",
                        pipeline=evidence_adapter.configuration(),
                        retrieval=evidence_adapter.policy() if evidence_adapter.enabled() else
                        "identity query + lexical search over CSM")
    out.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    qa = sub.add_parser("qa")
    qa.add_argument("--conversation", type=int, default=0)
    cog = sub.add_parser("cognitive")
    cog.add_argument("--samples", type=int, default=100)
    for parser_ in (qa, cog):
        parser_.add_argument("--out", type=Path)
        parser_.add_argument("--db", type=Path)
    args = parser.parse_args()
    results = ROOT / "benchmarks" / "results"
    results.mkdir(exist_ok=True)
    if args.command == "qa":
        out = args.out or results / f"locomo-qa-conv{args.conversation}.json"
        db = args.db or results / f"locomo-qa-conv{args.conversation}.db"
        global _DB_PATH
        _DB_PATH = str(db)
        for path in (db,):
            if path.exists():
                path.unlink()
        summary = run_qa(args.conversation, out, db)
    else:
        out = args.out or results / f"locomo-cognitive-{args.samples}.json"
        db = args.db or results / f"locomo-cognitive-{args.samples}.db"
        _DB_PATH = str(db)
        if db.exists():
            db.unlink()
        summary = run_cognitive(args.samples, out, db)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
