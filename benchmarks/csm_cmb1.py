"""Run CSM on the public 1.0 exam of Ornn8/chat-memory-benchmark (714 questions).

Three parallel phases:
  1. extract: every history turn of all six personas is extracted concurrently;
  2. build:   per persona, events and memory candidates are written to one CSM namespace;
  3. answer:  all 714 questions are answered concurrently from as-of retrieval at their cutoff.
Answers are written as JSONL for the upstream grading tools; this adapter never reads the
answer key.

Usage:
    python benchmarks/csm_cmb1.py --outdir benchmarks/results/cmb1-<run> [--only P01] [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "experiments" / "cmb" / "datasets" / "natural-timegrid-20261101-v2"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "benchmarks"))
sys.path.insert(0, str(ROOT / "experiments" / "cmb" / "demo"))

from bench_llm import BASE_URL, MODEL  # noqa: E402
from cmb_llm import ThrottledChat
from csm_public_exam import (  # noqa: E402
    ANSWER_SYSTEM, SELECT_SYSTEM, _on, cached_extract, extract_cache_key,
    extract_window, interpret, render, retrieve)
from parallel_eval import parallel_map, workers  # noqa: E402
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate  # noqa: E402


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines()
            if line.strip()]


def load_exam(only: set[str] | None, limit: int | None):
    questions = rows(DATA / "exam-inputs.jsonl")
    histories: dict[str, list[dict]] = {}
    verified: set[str] = set()
    for question in questions:
        name = question["history_file"]
        if name not in verified:
            content = (DATA / name).read_bytes()
            if hashlib.sha256(content).hexdigest() != question["history_sha256"]:
                raise ValueError(f"history_sha256_mismatch: {name}")
            histories[name] = rows(DATA / name)
            verified.add(name)
    if only:
        questions = [q for q in questions if q["persona"] in only]
    questions.sort(key=lambda q: (q["persona"], q["cutoff_turn"], q["id"]))
    if limit:
        questions = questions[:limit]
    return questions, histories


def load_answers(path: Path) -> set[str]:
    return {row["id"] for row in rows(path)} if path.exists() else set()


def append_answers(path: Path, new_rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for row in new_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_cache(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_cache(path: Path, cache: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def extract_sequential(questions, histories, outdir: Path, caches: dict[str, dict],
                       chat) -> dict[str, list[dict]]:
    """One persona at a time, so the prompt sees the property names already in use.

    Six personas still run concurrently; only the turns inside one persona are ordered.
    Extraction writes the slot names as produced; the engine's property registry makes the
    binding stable, so the adapter no longer merges or rewrites names.
    """
    persona_files = {question["persona"]: question["history_file"] for question in questions}
    started = time.time()

    def run_persona(persona: str) -> tuple[str, dict]:
        history = histories[persona_files[persona]]
        cache = caches[persona]
        known = ["用户"]
        slot_index: dict[str, set[str]] = {}
        for number, turn in enumerate(history, start=1):
            event_id = f"{persona}/turn/{number:04d}"
            items = cached_extract(chat, turn, known, event_id, cache, slot_index)
            for item in items:
                slot_index.setdefault(item["entity"], set()).add(item["slot"])
                if item["entity"] not in known:
                    known.append(item["entity"])
            if number % 50 == 0:
                save_cache(outdir / f"extract-{persona}.json", cache)
                print(f"extract {persona} {number}/{len(history)} "
                      f"({round(time.time() - started)}s, {chat.calls} calls)", flush=True)
        save_cache(outdir / f"extract-{persona}.json", cache)
        return persona, cache

    width = min(workers(), len(persona_files))
    with ThreadPoolExecutor(max_workers=width) as pool:
        for persona, _cache in pool.map(run_persona, sorted(persona_files)):
            print(f"extract {persona} done", flush=True)
    return caches


def extract_phase(questions, histories, outdir: Path, chat) -> dict[str, dict]:
    persona_turns: dict[str, list[dict]] = {}
    for question in questions:
        persona_turns.setdefault(question["persona"], histories[question["history_file"]])
    caches = {persona: read_cache(outdir / f"extract-{persona}.json")
              for persona in persona_turns}
    if _on("WSC_CSM_EXTRACT_SEQ"):
        extract_sequential(questions, histories, outdir, caches, chat)
        return caches
    tasks = [(persona, number, turn)
             for persona, history in persona_turns.items()
             for number, turn in enumerate(history, start=1)]
    print(f"extract: {len(tasks)} turns, width {workers()}", flush=True)
    started = time.time()

    def work(task):
        persona, number, turn = task
        return cached_extract(chat, turn, ["用户"], f"{persona}/turn/{number:04d}",
                              caches[persona])

    batch = 100
    for start in range(0, len(tasks), batch):
        parallel_map(work, tasks[start:start + batch])
        for persona, cache in caches.items():
            save_cache(outdir / f"extract-{persona}.json", cache)
        print(f"extract {min(start + batch, len(tasks))}/{len(tasks)} "
              f"({round(time.time() - started)}s, {chat.calls} calls)", flush=True)
    return caches


def build_phase(questions, histories, outdir: Path, caches: dict[str, dict]) -> dict[str, list[str]]:
    started = time.time()
    entities: dict[str, list[str]] = {}
    for persona in sorted(caches):
        history = histories[f"histories/{persona}.jsonl"]
        db_path = outdir / f"csm-{persona}.db"
        if db_path.exists():
            db_path.unlink()
        service = CSM(CsmStore(db_path, namespace=f"cmb1:{persona}"))
        known: list[str] = []
        seen: set[str] = set()
        for number, turn in enumerate(history, start=1):
            event_id = f"{persona}/turn/{number:04d}"
            service.ingest([Event(id=event_id, source_type="chat",
                                  payload={"user": turn["用户消息"], "assistant": turn["助手回复"]},
                                  observed_at=turn["逻辑时间"])])
            candidates = [dict(item)
                          for item in caches[persona].get(extract_cache_key(event_id)) or []]
            if not candidates:
                continue
            service.remember([MemoryCandidate(
                entity=item["entity"], slot=item["slot"], value=item["value"],
                contexts=(), topics=tuple(item["topics"]), source_ids=(event_id,))
                for item in candidates], producer="benchmark-adapter")
            for item in candidates:
                if item["entity"] not in seen:
                    seen.add(item["entity"])
                    known.append(item["entity"])
        entities[persona] = known
        print(f"build {persona}: {number} turns, {len(known)} entities, "
              f"{round(time.time() - started)}s", flush=True)
    return entities


def select(chat, question: str, items: list[dict]) -> list[dict]:
    """Relevance pass with a budget that leaves room for reasoning models to emit JSON."""
    listing = json.dumps([{"id": position, "entity": item.get("entity"), "slot": item.get("slot"),
                           "value": item.get("value")}
                          for position, item in enumerate(items, start=1)], ensure_ascii=False)
    try:
        data = chat.ask_json(SELECT_SYSTEM, f"问题：{question}\n记忆条目：{listing}",
                             max_tokens=600)
        wanted = {int(number) for number in data.get("ids") or []}
    except (ValueError, json.JSONDecodeError, AttributeError, TypeError):
        return items
    picked = [item for position, item in enumerate(items, start=1) if position in wanted]
    return picked or items


def answer_phase(questions, histories, outdir: Path, entities, done: set[str],
                 chat: Chat) -> int:
    answers_path = outdir / "answers.jsonl"
    clues_path = outdir / "clues.json"
    clues_cache = read_cache(clues_path)
    stores = {persona: CSM(CsmStore(outdir / f"csm-{persona}.db", namespace=f"cmb1:{persona}"))
              for persona in entities}
    todo = [question for question in questions if question["id"] not in done]
    started = time.time()

    def attempt(question):
        persona = question["persona"]
        history = histories[question["history_file"]]
        ask_time = history[question["cutoff_turn"] - 1].get("逻辑时间")
        clues = interpret(chat, question["question"], entities[persona], clues_cache)
        if "我" in question["question"]:
            clues["entities"] = list(dict.fromkeys(["用户", *clues["entities"]]))
        began = time.time()
        chosen = retrieve(stores[persona], question["question"], entities[persona],
                          clues, until=ask_time)
        retrieve_seconds = round(time.time() - began, 3)
        if _on("WSC_CSM_TWOPASS"):
            chosen = select(chat, question["question"], chosen)
        text = chat.ask(ANSWER_SYSTEM,
                        f"问题：{question['question']}\n记忆条目：{render(chosen)}",
                        max_tokens=600)
        times = [item.get("effective_at") for item in chosen if item.get("effective_at")]
        latest = max(times) if times else None
        return {"id": question["id"], "answer": text.strip(), "cutoff_time": ask_time,
                "latest_memory_time": latest, "leaked": bool(latest and latest > ask_time),
                "candidates": len(chosen), "retrieve_seconds": retrieve_seconds,
                "pending": sum(1 for item in chosen
                               if item.get("classification") == "PENDING_BINDING")}

    def work(question):
        error = None
        for _ in range(2):
            try:
                return attempt(question)
            except Exception as failure:  # one undecidable question must not stop the exam
                error = failure
        return {"id": question["id"], "answer": "我不记得", "cutoff_time": None,
                "error": f"{type(error).__name__}: {error}"}

    batch = 24
    for start in range(0, len(todo), batch):
        chunk = todo[start:start + batch]
        produced = parallel_map(work, chunk)
        append_answers(answers_path, produced)
        done.update(row["id"] for row in produced)
        save_cache(clues_path, clues_cache)
        print(f"answer {len(done)}/{len(questions)} "
              f"({round(time.time() - started)}s, {chat.calls} calls)", flush=True)
    return len(done)


def run(args) -> dict:
    questions, histories = load_exam(
        {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None,
        args.limit)
    outdir: Path = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    answers_path = outdir / "answers.jsonl"
    done = load_answers(answers_path)
    chat = ThrottledChat()
    started = time.time()
    (outdir / "run.json").write_text(json.dumps({
        "benchmark": "Ornn8/chat-memory-benchmark 1.0",
        "dataset": str(DATA.relative_to(ROOT)),
        "model": MODEL, "base_url": BASE_URL,
        "questions": len(questions), "already_answered": len(done),
        "retrieval": "CSM property identity + term index + evidence (as-of cutoff)",
        "short_term_window": "none",
        "extract_window": extract_window(), "workers": workers(),
        "flags": {name: _on(name) for name in (
            "WSC_CSM_EXTRACT_SEQ", "WSC_CSM_TWOPASS")},
        "min_interval": os.environ.get("CSM_BENCH_MIN_INTERVAL", "0.4"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    caches = extract_phase(questions, histories, outdir, chat)
    entities = build_phase(questions, histories, outdir, caches)
    answered = answer_phase(questions, histories, outdir, entities, done, chat)
    summary = {"answered": answered, "questions": len(questions),
               "calls": chat.calls, "prompt_tokens": chat.prompt_tokens,
               "completion_tokens": chat.completion_tokens,
               "seconds": round(time.time() - started, 1), "outdir": str(outdir)}
    (outdir / "run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path,
                        default=ROOT / "benchmarks" / "results" / f"cmb1-{int(time.time())}")
    parser.add_argument("--only", default=None, help="comma separated personas, e.g. P01,P12")
    parser.add_argument("--limit", type=int, default=None)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
