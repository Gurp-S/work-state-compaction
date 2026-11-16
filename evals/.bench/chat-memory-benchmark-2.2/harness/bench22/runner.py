# -*- coding: utf-8 -*-
"""Bench 2.2 evaluator.

For every exam point the evaluator hands the system ONLY the history up to the cutoff turn
(turn by turn, in order); the system never sees the history file.  Exam points are visited in
cutoff order so the memory state at an exam point is exactly "what the system saw before it".
After retrieval the evaluator builds the answer prompt, calls the answer model (DeepSeek flash)
and the judge (DeepSeek flash) through the metering gateway, and records cost.

    python -m bench22.runner --release DIR --system qwen-base --split sealed --run R1
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import sys
import threading
import time

from . import scoring
from .release import board_name, jl, load_histories, load_items
from .gateway import price_cny, _priced
from .systems import REGISTRY, Gateway, Unavailable, CeilingExceeded

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ANSWER_MODEL = JUDGE_MODEL = "deepseek-v4.1-flash"
JUDGE_TEMPLATE = open(os.path.join(HERE, "prompts", "judge.md"), encoding="utf-8").read()
JUDGE_SHA = hashlib.sha256(JUDGE_TEMPLATE.encode("utf-8")).hexdigest()
SCORING_VERSION = "bench22-score-v1"
LOCK = threading.Lock()
MEM_TOK_PER_CHAR = 0.70


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def append(path, row):
    with LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def numbered(xs):
    return "\n".join(f"[{i}] {x}" for i, x in enumerate(xs)) if xs else "（无）"


def date_check(item):
    dm = item.get("date_math")
    if not dm:
        return "无"
    keep = {k: dm[k] for k in ("event_date", "event_weekday", "what", "speaker_date", "speaker_weekday") if k in dm}
    return json.dumps(keep, ensure_ascii=False)


def judge_prompt(item, answer):
    r = item["rubric"]
    return JUDGE_TEMPLATE.format(
        now=item["now"], question=item["question"], required=numbered(r.get("required")),
        forbidden=numbered(r.get("forbidden")), tempting=numbered(r.get("tempting_fabrications")),
        unknown=numbered(r.get("unknown")), acceptable=numbered(r.get("acceptable")),
        date_check=date_check(item), reference=item.get("reference_answer") or "（无）", answer=answer)


def parse_json(text):
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except ValueError:
        s, e = t.find("{"), t.rfind("}")
        return json.loads(t[s:e + 1])


def pick_sample(items, n, seed):
    """Deterministic stratified sample of about n main items; twin members (a scoring unit) are always taken together."""
    rnd = random.Random(seed)
    main = sorted([i for i in items if i.get("kind") == "main"], key=lambda x: x["id"])
    units = {}
    for i in main:
        units.setdefault(i.get("twin_id") or i["id"], []).append(i)
    ulist = sorted(units.values(), key=lambda u: u[0]["id"])
    rnd.shuffle(ulist)
    by = {}
    for u in ulist:
        by.setdefault(u[0].get("interval_days"), []).append(u)
    out, cnt = set(), 0
    while cnt < n and any(by.values()):
        for key in sorted(by, key=str):
            if by[key] and cnt < n:
                u = by[key].pop()
                out |= {m["id"] for m in u}
                cnt += len(u)
    return out


def run_persona(args, release, hist, persona, items, outdir, gw, sample_ids):
    sysname = args.system
    system = REGISTRY[sysname](gw)
    todo = sorted([i for i in items if i["persona"] == persona and (sample_ids is None or i["id"] in sample_ids)], key=lambda x: (x["cutoff_turn"], x["id"]))   # with --sample only the sampled questions are retrieved (and billed)
    ctx_path = os.path.join(outdir, "contexts.jsonl")
    done_ctx = {r["id"] for r in jl(ctx_path)} if os.path.exists(ctx_path) else set()
    pos, turns = 0, hist[persona]
    contexts = {}
    leaks = []
    for it in todo:
        while pos < it["cutoff_turn"]:        # feed strictly up to the cutoff, never beyond
            system.ingest(dict(turns[pos]))
            pos += 1
        if it["id"] in done_ctx:
            continue
        gw.system = f"{sysname}:{persona}:{args.split}"
        try:
            ret = system.retrieve(it["question"], it["now"], it["cutoff_turn"], item_id=it["id"])
        except Unavailable as e:
            append(os.path.join(outdir, "unavailable.jsonl"), {"id": it["id"], "reason": str(e)})
            continue
        over = [t for t in ret.used_turns if t > it["cutoff_turn"]]
        rec = {"id": it["id"], "persona": persona, "cutoff_turn": it["cutoff_turn"], "used_turns": ret.used_turns,
               "meta": ret.meta, "leak_turns_after_cutoff": over, "prompt": ret.prompt,
               "prompt_sha256": hashlib.sha256(ret.prompt.encode("utf-8")).hexdigest()}
        append(ctx_path, rec)
        if over:
            leaks.append(it["id"])
        log(persona, "retrieved", it["id"], "cutoff", it["cutoff_turn"], "turns shown", len(ret.used_turns))
    return leaks


def answer_and_judge(args, items, outdir, gw, sample_ids):
    ctx = {r["id"]: r for r in jl(os.path.join(outdir, "contexts.jsonl"))}
    ans_path, jud_path = os.path.join(outdir, "answers.jsonl"), os.path.join(outdir, "judgments.jsonl")
    done_a = {r["id"] for r in jl(ans_path)} if os.path.exists(ans_path) else set()
    done_j = {r["id"] for r in jl(jud_path)} if os.path.exists(jud_path) else set()
    answers = {r["id"]: r for r in (jl(ans_path) if os.path.exists(ans_path) else [])}
    by_id = {i["id"]: i for i in items}
    work = [i for i in items if i["id"] in ctx and (sample_ids is None or i["id"] in sample_ids)]

    def one(it):
        c = ctx[it["id"]]
        tag = it["id"]
        gwx = Gateway(gw.base, gw.run, f"{args.system}:{it['persona']}:{args.split}", evaluator=True)
        if it["id"] not in answers:
            prompt = c["prompt"] + f"\n\n【现在】{it['now']}\n用户：{it['question']}"
            r = gwx.chat(ANSWER_MODEL, [{"role": "user", "content": prompt}], "answer", tag,
                         temperature=0, max_tokens=700, thinking={"type": "disabled"})
            u = r["usage"]
            mem_tok = u["prompt_tokens"] * len(c["prompt"]) / max(1, len(prompt))
            row = {"id": it["id"], "answer": r["choices"][0]["message"].get("content") or "",
                   "prompt_tokens": u["prompt_tokens"], "completion_tokens": u["completion_tokens"],
                   "mem_tokens": round(mem_tok, 1), "model": r.get("model"),
                   "prompt_sha256": c["prompt_sha256"], "leak_turns_after_cutoff": c["leak_turns_after_cutoff"]}
            append(ans_path, row)
            answers[it["id"]] = row
        a = answers[it["id"]]
        if it["id"] not in done_j and it.get("rubric"):
            jp = judge_prompt(it, a["answer"])
            for attempt in range(3):
                r = gwx.chat(JUDGE_MODEL, [{"role": "user", "content": jp}], "judge", tag, temperature=0,
                             max_tokens=700, thinking={"type": "disabled"})
                try:
                    j = parse_json(r["choices"][0]["message"].get("content"))
                    break
                except ValueError:
                    j = None
            if j is None:
                j = {"required": [], "reason": "judge-format-failure"}
            row = {"id": it["id"], "judge": j, "pass": scoring.judge_pass(j), "points": scoring.points(j),
                   "judge_prompt_sha256": JUDGE_SHA, "scoring_version": SCORING_VERSION,
                   "answer_sha256": hashlib.sha256(a["answer"].encode("utf-8")).hexdigest()}
            append(jud_path, row)

    with cf.ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(one, it) for it in work]
        for n, f in enumerate(cf.as_completed(futs), 1):
            f.result()
            if n % 25 == 0:
                log("answered/judged", n, "/", len(work))


def summarize(args, items, outdir, release, run, sample_ids, all_ctx_items):
    ctx = {r["id"]: r for r in jl(os.path.join(outdir, "contexts.jsonl"))}
    ans = {r["id"]: r for r in jl(os.path.join(outdir, "answers.jsonl"))}
    jud = {r["id"]: r for r in jl(os.path.join(outdir, "judgments.jsonl"))}
    passed = {k: v["pass"] for k, v in jud.items()}
    out = {"system": args.system, "split": args.split, "run": run, "scoring_version": SCORING_VERSION,
           "judge_prompt_sha256": JUDGE_SHA, "score_config": scoring.CONFIG, "boards": {}}
    # ledger -> system-side cost (ingest + retrieve)
    led = jl(os.path.join(ROOT, "runs", "bench22", "spend-ledger.jsonl"))
    for persona in sorted({i["persona"] for i in items}):
        pit = [i for i in items if i["persona"] == persona]
        scored = [i for i in pit if i["id"] in jud]
        main = [i for i in scored if i.get("kind") == "main"]
        ctl = [i for i in scored if i.get("kind") == "control"]
        key = f"{args.system}:{persona}:{args.split}"
        sysrows = [r for r in led if r.get("run") == run and r.get("system") == key and r.get("phase") in ("ingest", "retrieve")]
        sys_cost = sum(price_cny(_priced(r["model"]), r.get("in_tokens", 0), r.get("out_tokens", 0)) for r in sysrows)
        from .gateway import PRICES
        fin = PRICES["models"]["deepseek-v4.1-flash"]["in_per_mtok"]
        # memory text billed at flash input price: exact for answered items, estimated for the rest
        answered = [ans[i["id"]] for i in pit if i["id"] in ans]
        ratio = (sum(a["mem_tokens"] for a in answered) /
                 max(1, sum(len(ctx[a["id"]]["prompt"]) for a in answered))) if answered else MEM_TOK_PER_CHAR
        mem_tok_all = sum(ans[i["id"]]["mem_tokens"] if i["id"] in ans else ratio * len(ctx[i["id"]]["prompt"])
                          for i in pit if i["id"] in ctx)
        mem_cost = mem_tok_all * fin / 1e6
        pairs, npairs = scoring.paired_rate(scored, passed)
        units = [u for u in scoring.build_units(scored) if all(i in jud for i in u["ids"])]
        bs = scoring.board_scores(units, passed)
        ci = scoring.bootstrap_A(units, passed, n_boot=scoring.CONFIG.get("bootstrap_draws", 2000))
        leaks = [i["id"] for i in pit if i["id"] in ctx and ctx[i["id"]]["leak_turns_after_cutoff"]]
        # time-twin sentinel: the early member must not show anything that was only said after its cutoff
        twin_leaks = []
        for i in pit:
            toks = i.get("leak_tokens") or []
            if i.get("twin_role") == "early" and toks and i["id"] in ctx:
                txt = ctx[i["id"]]["prompt"] + (ans[i["id"]]["answer"] if i["id"] in ans else "")
                if any(t in txt for t in toks):
                    twin_leaks.append(i["id"])
        up = os.path.join(outdir, "unavailable.jsonl")
        n_unav = len([x for x in jl(up) if x["id"].startswith(persona)]) if os.path.exists(up) else 0
        board = {"board": board_name(persona), "n_items": len(pit), "n_unavailable": n_unav, "n_scored_main": len(main),
                 "n_control": len(ctl), "sampled": sample_ids is not None,
                 "A": round(bs["A"], 2), "D_daily": round(bs["D"], 2), "L_long": round(bs["L"], 2), "pass_pct": round(bs["pass_pct"], 2),
                 "A_traffic": round(bs["A_traffic"], 2), "n_units": bs["n_units"], "n_daily": bs["n_daily"], "n_long": bs["n_long"], "n_pairs": bs["n_pairs"],
                 "A_interval95": None if ci is None else [round(ci["lo"], 2), round(ci["hi"], 2)],
                 "by_type": scoring.by_type(units, passed),
                 "mean_points": round(sum(jud[i["id"]]["points"] for i in main) / len(main), 4) if main else None,
                 "cost_cny": {"system_calls": round(sys_cost, 4), "memory_in_prompt": round(mem_cost, 4),
                              "total_C": round(sys_cost + mem_cost, 4),
                              "memory_tokens_total": round(mem_tok_all), "estimated_for_unanswered": len(pit) - len(answered)},
                 "leak_flags": leaks, "time_twin_leak_flags": twin_leaks, "judge_format_failures": sum(1 for i in scored if not jud[i["id"]]["judge"].get("required")),
                 "avg_seconds_note": "latency is listed in the gateway ledger, not scored"}
        out["boards"][persona] = board
    json.dump(out, open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out


def build_sentinel(items, hist, n_per_persona, seed):
    """Plant a canary into the turn right AFTER the cutoff of n sealed exam points per persona.
    The canary repeats the question verbatim, so anything that reads past the cutoff retrieves it at rank 1."""
    rnd = random.Random(seed)
    hist2 = {p: [dict(t) for t in v] for p, v in hist.items()}
    canaries = []
    for p in hist:
        pool = sorted([i for i in items if i["persona"] == p and i.get("kind") == "main"], key=lambda x: x["cutoff_turn"])
        pool = [i for i in pool if i["cutoff_turn"] < len(hist[p]) - 1]
        seen, picks = set(), []
        rnd.shuffle(pool)
        for it in pool:
            if it["cutoff_turn"] not in seen and len(picks) < n_per_persona:
                seen.add(it["cutoff_turn"]); picks.append(it)
        for it in picks:
            nonce = "CANARY-" + hashlib.sha256(f"{seed}:{it['id']}".encode()).hexdigest()[:8]
            pos = it["cutoff_turn"]            # 0-based index of turn cutoff+1
            hist2[p][pos]["user"] = it["question"] + f" （{nonce}）"
            hist2[p][pos]["assistant"] = f"好的，记下了 {nonce}。" + it["question"]
            canaries.append({"id": it["id"], "persona": p, "cutoff_turn": it["cutoff_turn"], "canary_turn": pos + 1, "nonce": nonce})
    return hist2, canaries


def run_sentinel(args, items_all, hist, outdir, gw):
    hist2, canaries = build_sentinel(items_all, hist, args.sentinel_n, args.seed)
    ids = {c["id"] for c in canaries}
    items = [i for i in items_all if i["id"] in ids]
    byid = {c["id"]: c for c in canaries}
    rows, leaks = [], []
    for persona in sorted({i["persona"] for i in items}):
        system = REGISTRY[args.system](Gateway(args.gateway, args.run, f"{args.system}:{persona}:sentinel"))
        if args.leaky:
            system.leaky = True                          # positive control: handed the future on purpose
            for t in hist2[persona]:
                system.ingest(dict(t))
            pos = len(hist2[persona])
        else:
            pos = 0
        for it in sorted([i for i in items if i["persona"] == persona], key=lambda x: x["cutoff_turn"]):
            while pos < it["cutoff_turn"]:               # enforced protocol: feed only up to the cutoff
                system.ingest(dict(hist2[persona][pos])); pos += 1
            ret = system.retrieve(it["question"], it["now"], it["cutoff_turn"])
            c = byid[it["id"]]
            future = [x for x in canaries if x["persona"] == persona and x["canary_turn"] > it["cutoff_turn"]]
            seen = [x["nonce"] for x in future if x["nonce"] in ret.prompt]
            seen_turn = [t for t in ret.used_turns if t > it["cutoff_turn"]]
            r = {"id": it["id"], "persona": persona, "cutoff_turn": it["cutoff_turn"], "canary_turn": c["canary_turn"],
                 "leaked_nonces": seen, "turns_after_cutoff": seen_turn, "own_canary_leaked": c["nonce"] in ret.prompt}
            rows.append(r)
            if seen or seen_turn:
                leaks.append(it["id"])
            log("sentinel", it["id"], "cutoff", it["cutoff_turn"], "LEAK" if (seen or seen_turn) else "clean")
    out = {"system": args.system, "mode": "leaky-positive-control" if args.leaky else "enforced", "n_points": len(rows),
           "n_leaks": len(leaks), "leaks": leaks, "rows": rows}
    json.dump(out, open(os.path.join(outdir, "sentinel-" + ("leaky" if args.leaky else "enforced") + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log("sentinel done:", out["mode"], f"{out['n_leaks']}/{out['n_points']} exam points saw future content")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", required=True)
    ap.add_argument("--system", required=True, choices=sorted(REGISTRY))
    ap.add_argument("--split", required=True, choices=["dev", "sealed"])
    ap.add_argument("--persona", default="both")
    ap.add_argument("--run", required=True)
    ap.add_argument("--gateway", default=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:18877/v1"))
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--sample", type=int, default=0, help="answer/judge only a stratified sample of N main items per board")
    ap.add_argument("--seed", type=int, default=20261109)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only-new", action="store_true", help="only the 2.1 new questions")
    ap.add_argument("--sentinel", action="store_true", help="retrieval-only leak sentinel run")
    ap.add_argument("--leaky", action="store_true", help="with --sentinel: positive control, system is handed future turns")
    ap.add_argument("--sentinel-n", type=int, default=12)
    args = ap.parse_args()
    want = "test" if args.split == "sealed" else "dev"
    items_all = [i for i in load_items(args.release) if i.get("split") == want]
    if args.only_new:
        items_all = [i for i in items_all if i.get("probe_type") not in (None, "legacy")]
    if args.limit:
        items_all = sorted(items_all, key=lambda x: x["id"])[:args.limit]
    hist = load_histories(args.release)
    outdir = os.path.join(ROOT, "runs", "bench22", args.run, args.system, args.split)
    os.makedirs(outdir, exist_ok=True)
    if args.sentinel:
        run_sentinel(args, items_all, hist, outdir, Gateway(args.gateway, args.run, args.system))
        return
    personas = ["M01", "M02"] if args.persona == "both" else [args.persona]
    gw = Gateway(args.gateway, run=args.run, system=args.system)
    sample_ids = None
    if args.sample:
        sample_ids = set()
        for p in personas:
            sample_ids |= pick_sample([i for i in items_all if i["persona"] == p], args.sample, args.seed)
        json.dump(sorted(sample_ids), open(os.path.join(outdir, "sample-ids.json"), "w"))
    leaks = []
    try:
        with cf.ThreadPoolExecutor(len(personas)) as ex:
            futs = [ex.submit(run_persona, args, args.release, hist, p, items_all, outdir, Gateway(args.gateway, args.run, args.system), sample_ids) for p in personas]
            for f in futs:
                leaks += f.result()
        answer_and_judge(args, [i for i in items_all if i["persona"] in personas], outdir, gw, sample_ids)
    except CeilingExceeded as e:
        json.dump({"system": args.system, "run": args.run, "split": args.split, "ceiling_cny": scoring.CONFIG.get("run_cost_ceiling_cny"), "error": str(e)[:300], "result": "stopped, no score"},
                  open(os.path.join(outdir, "CEILING-EXCEEDED.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        sp = os.path.join(outdir, "summary.json")
        if os.path.exists(sp):
            os.remove(sp)
        log("RUN COST CEILING reached: run stopped, no score (deposit kept, nothing more owed)")
        sys.exit(3)
    out = summarize(args, [i for i in items_all if i["persona"] in personas], outdir, args.release, args.run, sample_ids, items_all)
    log(json.dumps({p: {k: b[k] for k in ("A", "D_daily", "L_long", "A_interval95", "cost_cny")} for p, b in out["boards"].items()}, ensure_ascii=False))
    log("leak flags:", leaks)


if __name__ == "__main__":
    main()
