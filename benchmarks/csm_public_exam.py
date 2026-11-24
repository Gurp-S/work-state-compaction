"""Run CSM on the public demonstration exam of Ornn8/memory-system-benchmark.

The demo ships 108 questions over one persona's history, each with an exact cutoff turn and a
rubric. This adapter plays the role of the "semantic interpreter" the CSM design leaves to the
model: it turns each dialogue turn into MemoryCandidates, commits them, then answers from CSM
retrieval only and grades with the rubric. Answers never see the answer key.

Usage:
    py -3.11 benchmarks/csm_public_exam.py [--limit N] [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / ".bench" / "memory-system-benchmark" / "demo"))
sys.path.insert(0, str(ROOT / "benchmarks"))

import read_exam  # noqa: E402  (the benchmark's own loader, with its SHA and cutoff checks)
from bench_llm import Chat  # noqa: E402
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, MemoryQuery  # noqa: E402

DEMO = ROOT / ".bench" / "memory-system-benchmark" / "demo"

EXTRACT_SYSTEM = """你是长期记忆提取器。输入是一轮对话：用户消息与助手回复。
逐条提取这一轮里所有以后可能被追问的具体信息：
- 用户陈述的事实、经历、梦境、计划、偏好、约定、数字、日期、地点、物品、感受及原因；
- 助手提出的具体建议、方案、时间、地点、做法（实体记为"助手"）。
规则：
- 只要出现具体信息就记一条；梦境、编的故事、玩笑、看似琐碎的日常都要记，不要判断"值不值得记"。
- 一句话含多个信息就拆成多条；不要把两条不同的事实合成一条。
- 不记问候、寒暄、感叹、没有具体内容的情绪。
输出 JSON 数组，元素形如：
{"entity": "实体或主题", "slot": "属性名", "value": "简洁完整的事实值，保留关键数字与时间",
 "topics": ["检索关键词"]}
entity 尽量复用"已有实体"中的写法；slot 要具体到能区分不同事实（例如"归还约定""停电时长"），
只有同一属性的新说法才复用同一 slot。
用户消息里陈述的事实一律属于实体"用户"。
确实没有任何具体信息才输出 []。"""

EXTRACT_SPECIFIC_SYSTEM = EXTRACT_SYSTEM + """
slot 写法（必须遵守）：
- slot 要具体到能单独定位这条事实。禁止用"建议""提醒""约定""事项""询问""信息"
  "内容""计划""状态""称呼""情况""安排"这类泛称作为完整 slot。
- 不同对象、不同日期、不同动作或不同建议，即使同属一类，也要用不同的具体 slot。
  例：不要把所有建议写成"建议"，要写"少打字建议""夜班前进食建议""合租合同提醒"。
- 只有同一属性会被新值取代时才复用已有 slot（例如"生日""当前状态""称呼"的更正）。
- "已有属性"里列出的写法，只有确属同一属性才复用；否则另起具体名称。
- 用户改口、纠正、否定先前说法时（如"其实是X，不是Y"），以最新说法为准输出一条，
  slot 复用该属性原来的写法，value 写新值；不要输出被否定的旧值。"""

CORRECTION = re.compile(r"其实|不是|改成|改回|纠正|更正|说错|记错|应该是")
ANSWER_SYSTEM = """你只依据给出的记忆条目回答问题。条目是唯一事实来源。
信息不足就回答"我不记得"。不要编造，不要解释检索过程。用简洁中文回答。"""

SELECT_SYSTEM = """从记忆条目里挑出与问题有关的条目。
返回 JSON：{"ids": [条目编号...]}，编号从 1 开始；一条都不相关就返回 {"ids": []}。"""

JUDGE_STRIP = str.maketrans("", "", " \t\r\n，。！？；：、“”‘’（）()【】[]…—-·.,!?;:\"'")


def normalize(text: str) -> str:
    return text.translate(JUDGE_STRIP)


def judge(answer: str, rubric: dict) -> tuple[bool, str]:
    """Rubric match: every required clause, or an acceptable alternative; never a forbidden claim."""
    text = normalize(answer)
    required_ok = all(normalize(clause) in text
                      for item in rubric.get("required", [])
                      for clause in item.split("；") if normalize(clause))
    acceptable_ok = any(normalize(item) in text for item in rubric.get("acceptable", []) if normalize(item))
    forbidden = [item for item in rubric.get("forbidden", []) if normalize(item) in text]
    passed = (required_ok or acceptable_ok) and not forbidden
    reason = ("forbidden:" + ",".join(forbidden)) if forbidden else (
        "required" if required_ok else "acceptable" if acceptable_ok else "missing")
    return passed, reason


JUDGE_SYSTEM = """你是严格的评分员。根据 rubric 判断考生回答是否通过。
required：必须全部命中的要点，允许同义表述，不要求逐字相同。
acceptable：整体可替代的表述，命中任一即视为满足 required。
forbidden：回答出现该内容即不通过。
unknown：未被记忆确认的信息；回答若断言这些内容则不通过。
只输出 JSON：{"pass": true 或 false, "reason": "一句话理由"}"""


def judge_llm(chat: Chat, question: str, answer: str, rubric: dict) -> tuple[bool, str]:
    payload = json.dumps({"question": question, "answer": answer, "rubric": rubric},
                         ensure_ascii=False)
    for _ in range(2):
        try:
            verdict = chat.ask_json(JUDGE_SYSTEM, payload, max_tokens=400)
            value = verdict.get("pass")
            passed = value if isinstance(value, bool) else str(value).strip().lower() in ("true", "yes", "pass")
            return passed, str(verdict.get("reason", ""))[:200]
        except (ValueError, json.JSONDecodeError):
            continue
    passed, reason = judge(answer, rubric)
    return passed, "lexical_fallback:" + reason


def load_answers() -> dict[str, dict]:
    path = DEMO / "review-only" / "answer-key.jsonl"
    return {row["id"]: row for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())}


def extract(chat: Chat, turn: dict, known: list[str],
            slots: dict[str, set[str]] | None = None) -> list[dict]:
    slot_line = ""
    if slots:
        shown = []
        for entity in sorted(slots, key=lambda name: (name != "用户", name != "助手", name))[:4]:
            names = sorted(slots[entity])[-20:]
            if names:
                shown.append(f"{entity}: {'、'.join(names)}")
        if shown:
            slot_line = "已有属性：" + "；".join(shown) + "\n"
    user = (f"已有实体：{'、'.join(known[-80:]) or '（无）'}\n"
            f"{slot_line}"
            f"本轮时间：{turn['逻辑时间']}\n"
            f"用户：{turn['用户消息']}\n助手：{turn['助手回复']}")
    system = EXTRACT_SPECIFIC_SYSTEM
    items = []
    for attempt in range(2):
        try:
            items = chat.ask_json(system, user, max_tokens=2500)
        except (ValueError, json.JSONDecodeError, RuntimeError, OSError):
            items = []
        # 抽取会随机返回空数组或抛错，整轮事实随之静默丢失；内容够长时再试一次。
        content = str(turn.get("用户消息") or "") + str(turn.get("助手回复") or "")
        if items or len(content) <= 8:
            break
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        entity = str(item.get("entity") or "").strip()
        slot = str(item.get("slot") or "").strip()
        value = item.get("value")
        if not entity or not slot or value in (None, ""):
            continue
        topics = [str(t).strip() for t in item.get("topics") or [] if str(t).strip()]
        entry = {"entity": entity, "slot": slot, "value": value, "topics": topics[:6]}
        out.append(entry)
    return out


def extract_window() -> int:
    """一次并行抽取多少轮；1 = 逐轮串行（原行为）。"""
    try:
        return max(1, int(os.environ.get("WSC_CSM_EXTRACT_WINDOW", "1")))
    except ValueError:
        return 1


def extract_cache_key(key: str) -> str:
    """Cache key includes the prompt version, so a prompt change never reuses old rows."""
    return "v2:" + key


def cached_extract(chat: Chat, turn: dict, known: list[str], key: str, cache: dict,
                   slots: dict[str, set[str]] | None = None) -> list[dict]:
    """按事件 id 缓存抽取结果：同一轮对话只抽一次，A/B 重跑不必重抽。"""
    key = extract_cache_key(key)
    if key in cache:
        return [dict(item) for item in cache[key]]
    items = extract(chat, turn, known, slots)
    cache[key] = [dict(item) for item in items]
    return [dict(item) for item in items]


QUERY_SYSTEM = """从问题中识别记忆查询线索。"我"/"我的"指实体"用户"。
entities 填问题直接涉及的实体；没有则空数组。
topics 填 3-6 个可能出现在记忆条目里的词：同义改写、上位词、相关物品或动作。不能为空。
输出 JSON：{"entities": ["..."], "topics": ["..."]}"""


def interpret(chat: Chat, question: str, entities: list[str], cache: dict | None = None) -> dict:
    """Query clues. Cached per question because the clue prompt is arm-independent.

    Re-sampling it per arm changes which memory sources get queried, which moves the fused
    candidate set by more than the flag under test.
    """
    if cache is not None and question in cache:
        return {key: list(cache[question][key]) for key in ("entities", "topics")}
    user = f"已有实体：{'、'.join(entities[-80:]) or '（无）'}\n问题：{question}"
    try:
        # 600, not 120: this model spends most of a small budget before emitting the JSON and
        # then returns empty content, which the fallback below silently turns into "no clues".
        data = chat.ask_json(QUERY_SYSTEM, user, max_tokens=600)
        clues = {"entities": [str(e).strip() for e in data.get("entities") or [] if str(e).strip()],
                 "topics": [str(t).strip() for t in data.get("topics") or [] if str(t).strip()]}
    except (ValueError, json.JSONDecodeError, AttributeError, RuntimeError):
        clues = {"entities": [], "topics": []}
    if cache is not None:
        cache[question] = clues
    return clues


def select_rows(chat: Chat, question: str, items: list[dict]) -> list[dict]:
    """Decide relevance once, explicitly, instead of leaving it to the answer pass.

    The answer prompt treats "no row states this directly" as "no information", so a memory
    that answers the question in different words gets discarded with the rest. A separate
    pass can weigh a row on content alone and hand back only what bears on the question.
    """
    listing = json.dumps([{"id": position, "entity": item.get("entity"), "slot": item.get("slot"),
                           "value": item.get("value")}
                          for position, item in enumerate(items, start=1)], ensure_ascii=False)
    try:
        data = chat.ask_json(SELECT_SYSTEM, f"问题：{question}\n记忆条目：{listing}", max_tokens=120)
        wanted = {int(number) for number in data.get("ids") or []}
    except (ValueError, json.JSONDecodeError, AttributeError, TypeError, RuntimeError):
        return items
    picked = [item for position, item in enumerate(items, start=1) if position in wanted]
    return picked or items


def retrieve(service, question: str, entities: list[str], clues: dict, limit: int = 15,
             until: str | None = None) -> list[dict]:
    """Term-indexed search fused with anchor lookups; every row carries its source excerpt.

    The core ranks by indexed terms and selects each row at the event-time cutoff. Entity
    anchors are queried separately because a question about "我" rarely repeats the entity
    name. The two lists use different scales, so they are fused by rank, not by score.
    """
    window = (None, until) if until else None
    text = " ".join([question, *clues["topics"]]).strip()
    sources = [service.search(text, limit=limit, window=window)["results"]]
    known = set(entities)
    for name in clues["entities"]:
        if name not in known:
            continue
        sources.append(service.query(MemoryQuery(entity=name, limit=limit, text=text,
                                                 valid_at=until))["results"])
    items: dict[str, dict] = {}
    fused: dict[str, float] = {}
    for source in sources:
        for rank, item in enumerate(source):
            memory_id = item.get("memory_id")
            if memory_id is None:
                continue
            items.setdefault(memory_id, item)
            fused[memory_id] = fused.get(memory_id, 0.0) + 1.0 / (60 + rank)
    ordered = sorted(fused, key=lambda memory_id: (-fused[memory_id], memory_id))
    return [items[memory_id] for memory_id in ordered[:limit]]


def render(items: list[dict]) -> str:
    """Rows for the answer prompt: what the engine believes plus the words it came from."""
    rows = []
    seen_evidence: set[str] = set()
    for item in items:
        row = {"entity": item.get("entity"), "slot": item.get("slot"),
               "value": item.get("value"), "time": item.get("effective_at")}
        if item.get("status") is not None:
            row["status"] = item["status"]
        if item.get("property_kind"):
            row["kind"] = item["property_kind"]
        evidence = []
        for entry in item.get("evidence") or []:
            text = entry.get("text")
            if not text or text in seen_evidence:
                continue
            seen_evidence.add(text)
            evidence.append(text)
        if evidence:
            row["evidence"] = "\n".join(evidence)[:400]
        rows.append(row)
    return json.dumps(rows, ensure_ascii=False)


def _on(name: str) -> bool:
    """The adapter opts into a bypass only when its flag is on; the engine stays neutral."""
    return os.environ.get(name, "0").strip().lower() in {"1", "true", "yes", "on"}


def resume_state(db_path: Path) -> dict[str, tuple[list[str], int]]:
    """Entities and ingested turn count per persona, so an existing graph can be reused.

    Extraction is LLM sampling: two runs over the same conversations produce materially
    different graphs. Reusing one graph is the only way an A/B over read-path flags measures
    retrieval instead of extraction noise.
    """
    state: dict[str, tuple[list[str], int]] = {}
    if not db_path.exists():
        return state
    entities: list[str] = []
    turns: dict[str, int] = {}
    with sqlite3.connect(db_path) as connection:
        for (data,) in connection.execute("SELECT data FROM identities ORDER BY rowid"):
            entity = json.loads(data)["entity"]
            if entity not in entities:
                entities.append(entity)
        for (event_id,) in connection.execute("SELECT id FROM events"):
            persona, _, tail = str(event_id).rpartition("/turn/")
            if persona and tail.isdigit():
                turns[persona] = max(turns.get(persona, 0), int(tail))
    for persona, count in turns.items():
        state[persona] = (list(entities), count)
    return state


def run(limit: int | None, out: Path, db_path: Path, judge_mode: str = "llm",
        reuse: bool = False, only: set[str] | None = None) -> dict:
    questions, histories = read_exam.load()
    answers = load_answers()
    if only:
        questions = [question for question in questions if question["id"] in only]
    if limit:
        questions = questions[:limit]
    questions.sort(key=lambda q: (q["persona"], q["cutoff_turn"]))

    chat = Chat()
    resumed = resume_state(db_path) if reuse else {}
    clue_path = Path(os.environ.get("CSM_EXAM_CLUES") or out.with_name("clues.json"))
    clue_cache: dict = json.loads(clue_path.read_text(encoding="utf-8")) if clue_path.exists() else {}
    cache_path = Path(os.environ.get("CSM_EXAM_EXTRACT_CACHE") or out.with_name("extract-cache.json"))
    cache: dict = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    stores: dict[str, tuple[CSM, list[str], set[str]]] = {}
    results: list[dict] = []
    done_turns: dict[str, int] = {}
    slot_index: dict[str, set[str]] = {}
    pending: list[tuple[dict, list[dict]]] = []
    from parallel_eval import parallel_map
    started = time.time()

    for index, question in enumerate(questions, 1):
        persona = question["persona"]
        if persona not in stores:
            resumed_entities, resumed_turns = resumed.get(persona, ([], 0))
            done_turns[persona] = resumed_turns
            stores[persona] = (CSM(CsmStore(db_path, namespace=f"public-exam:{persona}")),
                               list(resumed_entities), set(resumed_entities))
        service, entities, seen_entities = stores[persona]
        rows = histories[question["history_file"]][0]
        first = done_turns.get(persona, 0)
        window = extract_window()
        prefetched: dict[int, list[dict]] = {}
        for number in range(first + 1, question["cutoff_turn"] + 1):
            turn = rows[number - 1]
            event_id = f"{persona}/turn/{number:04d}"
            service.ingest([Event(id=event_id, source_type="chat",
                                  payload={"user": turn["用户消息"], "assistant": turn["助手回复"]},
                                  observed_at=turn["逻辑时间"])])
            if window > 1:
                if number not in prefetched:
                    # 窗口并行抽取：提示里的实体表取窗口起点快照，写入仍严格按轮次顺序。
                    chunk = list(range(number, min(number + window,
                                                   question["cutoff_turn"] + 1)))
                    hint = list(entities)
                    got = parallel_map(
                        lambda n, hint=hint: cached_extract(
                            chat, rows[n - 1], hint, f"{persona}/turn/{n:04d}", cache,
                            slot_index),
                        chunk, width=window)
                    prefetched.update(dict(zip(chunk, got)))
                candidates = prefetched.pop(number)
            else:
                candidates = cached_extract(chat, turn, entities, event_id, cache, slot_index)
            if candidates:
                written = service.remember([MemoryCandidate(
                    entity=item["entity"], slot=item["slot"], value=item["value"],
                    contexts=(), topics=tuple(item["topics"]), source_ids=(event_id,))
                    for item in candidates], producer="benchmark-adapter")
                for item in candidates:
                    slot_index.setdefault(item["entity"], set()).add(item["slot"])
                    if item["entity"] not in seen_entities:
                        seen_entities.add(item["entity"])
                        entities.append(item["entity"])
        done_turns[persona] = max(done_turns.get(persona, 0), question["cutoff_turn"])

        clues = interpret(chat, question["question"], entities, clue_cache)
        clue_path.parent.mkdir(parents=True, exist_ok=True)
        clue_path.write_text(json.dumps(clue_cache, ensure_ascii=False, indent=2), encoding="utf-8")
        if "我" in question["question"]:
            clues["entities"] = list(dict.fromkeys(["用户", *clues["entities"]]))
        ask_time = rows[question["cutoff_turn"] - 1].get("逻辑时间") if rows else None
        items = retrieve(service, question["question"], entities, clues, until=ask_time)
        if _on("WSC_CSM_TWOPASS"):
            items = select_rows(chat, question["question"], items)
        pending.append((question, items))
        following = questions[index] if index < len(questions) else None
        if (following is None or following["persona"] != persona
                or following["cutoff_turn"] != question["cutoff_turn"]):
            # 同一截止轮次的问题共享同一份记忆快照，彼此独立，可以并行作答/判分。
            def work(entry, answers=answers, judge_mode=judge_mode):
                current, chosen = entry
                answer = chat.ask(
                    ANSWER_SYSTEM,
                    f"问题：{current['question']}\n记忆条目：{render(chosen)}", max_tokens=200)
                rubric = answers[current["id"]]["rubric"]
                if judge_mode == "llm":
                    passed, reason = judge_llm(chat, current["question"], answer, rubric)
                else:
                    passed, reason = judge(answer, rubric)
                print(f"{current['id']} {'PASS' if passed else 'FAIL'} ({reason})", flush=True)
                return {"id": current["id"], "case": answers[current["id"]]["case_id"],
                        "interval_days": answers[current["id"]]["interval_days"],
                        "tags": answers[current["id"]].get("content_tags"),
                        "question": current["question"], "answer": answer,
                        "passed": passed, "reason": reason,
                        "retrieved": [item["memory_id"] for item in chosen],
                        "context_chars": len(render(chosen))}

            results.extend(parallel_map(work, pending))
            pending = []

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    total = len(results)
    passed = sum(1 for item in results if item["passed"])
    by_interval: dict[str, dict] = {}
    for item in results:
        bucket = by_interval.setdefault(str(item["interval_days"]), {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += item["passed"]
    summary = {"benchmark": "Ornn8/memory-system-benchmark demo (PUB01)",
               "questions": total, "passed": passed, "pipeline": "event log + property identity",
               "accuracy": round(passed / total, 4) if total else None,
               "by_interval_days": by_interval,
               "calls": chat.calls, "prompt_tokens": chat.prompt_tokens,
               "completion_tokens": chat.completion_tokens,
               "seconds": round(time.time() - started, 1),
               "retrieval": "term index + identity anchors + source evidence (as-of cutoff)",
               "extract_window": extract_window(), "extract_cache_entries": len(cache),
               "judge": "llm rubric" if judge_mode == "llm" else "lexical rubric"}
    out.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, default=ROOT / "benchmarks" / "results" / "public-exam.json")
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--judge", choices=("llm", "lexical"), default="llm")
    parser.add_argument("--reuse-db", action="store_true",
                        help="keep an existing graph and only evaluate retrieval over it")
    parser.add_argument("--only", default=None,
                        help="comma separated question ids; evaluates just those")
    args = parser.parse_args()
    db_path = args.db or Path(__file__).with_name("results") / f"public-exam-{int(time.time())}.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists() and not args.reuse_db:
        db_path.unlink()
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    summary = run(args.limit, args.out, db_path, judge_mode=args.judge, reuse=args.reuse_db,
                  only=only)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


