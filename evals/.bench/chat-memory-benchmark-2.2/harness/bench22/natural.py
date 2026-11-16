# -*- coding: utf-8 -*-
"""Natural-use board (board N): runner, judge and scoring.

A probe = a persona's history up to the cutoff turn + a short synthetic "tail" + one probe turn (tier A, the assistant replies
in the tail are fixed) or a 4-turn scripted conversation whose assistant replies are generated live by the system under test
(tier B).  Every system sees the same user turns.  The evaluator feeds history turn by turn up to the cutoff, then the tail,
asks the system for the memory text, builds the answer prompt, calls flash for the reply and rewinds the system.

    python -m bench22.natural run   --release R21DIR --natural NATDIR --system qwen-base --split sealed --run NR1
    python -m bench22.natural judge --release R21DIR --natural NATDIR --system qwen-base --split sealed --run NR1
    python -m bench22.natural summarize ...
"""
import argparse
import concurrent.futures as cf
import hashlib
import json
import math
import os
import re
import threading
import time

from .release import jl, load_histories
from .gateway import PRICES, price_cny, _priced
from .systems import REGISTRY, Gateway, IncBM25, doc_text
from . import scoring

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ANSWER_MODEL = JUDGE_MODEL = "deepseek-v4.1-flash"
LOCK = threading.Lock()
PROMPTS = {k: open(os.path.join(HERE, "prompts", f"natural_{k}.md"), encoding="utf-8").read() for k in ("judge", "nat", "verify", "confirm")}
JUDGE_SHA = hashlib.sha256("".join(PROMPTS[k] for k in sorted(PROMPTS)).encode("utf-8")).hexdigest()
SCORING_VERSION = "natural-score-v2"
CHAT_NOTE = "（这是日常聊天，像平时一样回复，通常一到四句。）"
CLASS_NAME = {"X": "该提的时候要提", "H": "只记得一部分/没说过，要说拿不准", "Y": "不该提的时候不要提", "Z": "提不提都行", "N0": "无关闲聊，不该硬塞旧事"}
CLASS_WEIGHT = {"X": 0.40, "H": 0.10, "Y": 0.30, "Z": 0.10, "N0": 0.10}
# A = harmonic mean of the recall side R (X, H) and the restraint side P (Y, N0, Z); each side is the weighted mean of its classes' item scores.
RECALL_SIDE = ("X", "H")
RESTRAINT_SIDE = ("Y", "N0", "Z")
OVER_SEVERITY = {"Y1": 1.0, "Y3": 1.0, "Y5": 1.0, "Y2": 0.8, "Y4": 0.8, "N0": 0.6}
SEVERE_MULT = 2.0
EMOTION_TRAFFIC = {"upset": 0.042, "happy": 0.216, "neutral": 0.742}     # share of user turns in the opt-in sample (aggregate statistic)


def fill(tpl, **kw):
    for k, v in kw.items():
        tpl = tpl.replace("{" + k + "}", str(v))
    return tpl


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def append(path, row):
    with LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


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


def load_natural(natdir, split, sample=0):
    suffix = "" if os.path.exists(os.path.join(natdir, "natural-probes.jsonl")) else "-dev"      # the public checkout only has the dev files
    probes = jl(os.path.join(natdir, f"natural-probes{suffix}.jsonl"))
    key = {r["id"]: r for r in jl(os.path.join(natdir, f"natural-key{suffix}.jsonl"))}
    if split != "all":
        probes = [p for p in probes if p["split"] == split]
    if sample and len(probes) > sample:
        # deterministic sample, proportional by class (so the class mix and the score weights stay comparable); same probes for every system
        import random
        rnd = random.Random(20261111)
        by = {}
        for p in sorted(probes, key=lambda x: x["id"]):
            by.setdefault(key[p["id"]]["class"], []).append(p)
        keep = []
        for c, ps in sorted(by.items()):
            rnd.shuffle(ps)
            keep += ps[:max(1, round(sample * len(ps) / len(probes)))]
        probes = sorted(keep, key=lambda x: x["id"])
    return probes, key


# --------------------------------------------------------------------------- run
def answer_prompt(memory_text, now, user_text):
    return memory_text + f"\n\n【现在】{now}\n用户：{user_text}\n{CHAT_NOTE}"


def run_item(system, gw, hist_len, p, outdir, answer_fn, sysname):
    """Feed the tail, run the probe (or the live script) and rewind.  Returns nothing; rows go to files."""
    tok = system.mark()
    if hasattr(system, "begin_tail"):
        system.begin_tail()
    cutoff = p["cutoff_turn"]
    seq = cutoff
    for tt in p.get("tail") or []:
        seq += 1
        system.ingest({"turn": seq, "time": tt["time"], "user": tt["user"], "assistant": tt["assistant"]})
    turns = [p["probe"]] if p["tier"] == "A" else p["script"]
    live_replies = []
    for k, t in enumerate(turns):
        ret = system.retrieve(t["user"], t["time"], seq, item_id=p["id"])
        over = [x for x in ret.used_turns if x > seq]
        row = {"id": p["id"], "k": k, "persona": p["persona"], "cutoff_turn": cutoff, "visible_until": seq, "prompt": ret.prompt,
               "used_turns": ret.used_turns, "leak_turns_after_visible": over, "meta": ret.meta, "user": t["user"], "time": t["time"],
               "prompt_sha256": hashlib.sha256(ret.prompt.encode("utf-8")).hexdigest()}
        if p["tier"] == "A":
            answer_fn(row, async_ok=True)
        else:
            answer_fn(row, async_ok=False)
            seq += 1
            system.ingest({"turn": seq, "time": t["time"], "user": t["user"], "assistant": row["answer"]})
        live_replies.append(row)
    system.rewind(tok)
    assert system.mark() == tok, "rewind failed for " + sysname


def cmd_run(args):
    hist = load_histories(args.release)
    probes, key = load_natural(args.natural, args.split, getattr(args, "sample", 0))
    outdir = os.path.join(ROOT, "runs", "bench22", args.run, args.system, "natural-" + args.split)
    os.makedirs(outdir, exist_ok=True)
    ctx_path = os.path.join(outdir, "turns.jsonl")
    done = {(r["id"], r["k"]) for r in jl(ctx_path)} if os.path.exists(ctx_path) else set()
    done_items = {i for i, k in done}
    pool = cf.ThreadPoolExecutor(args.workers)
    futs = []

    def make_answer_fn(gwx):
        def answer(row, async_ok):
            def go():
                prompt = answer_prompt(row["prompt"], row["time"], row["user"])
                for attempt in range(3):
                    try:
                        r = gwx.chat(ANSWER_MODEL, [{"role": "user", "content": prompt}], "answer", f"{row['id']}#{row['k']}",
                                     temperature=0, max_tokens=500, thinking={"type": "disabled"})
                        break
                    except RuntimeError as e:
                        if attempt == 2:
                            raise
                        time.sleep(5)
                u = r["usage"]
                row["answer"] = r["choices"][0]["message"].get("content") or ""
                row["prompt_tokens"], row["completion_tokens"] = u["prompt_tokens"], u["completion_tokens"]
                row["mem_tokens"] = round(u["prompt_tokens"] * len(row["prompt"]) / max(1, len(prompt)), 1)
                append(ctx_path, row)
            if async_ok:
                futs.append(pool.submit(go))
            else:
                go()
        return answer

    def per_persona(persona):
        gwp = Gateway(args.gateway, args.run, f"{args.system}:{persona}:natural-{args.split}")
        system = REGISTRY[args.system](gwp)
        todo = sorted([p for p in probes if p["persona"] == persona], key=lambda p: (p["cutoff_turn"], p["id"]))
        pos, turns = 0, hist[persona]
        for p in todo:
            while pos < p["cutoff_turn"]:
                system.ingest(dict(turns[pos]))
                pos += 1
            if p["id"] in done_items:
                continue
            gwx = Gateway(args.gateway, args.run, f"{args.system}:{persona}:natural-{args.split}")
            run_item(system, gwp, len(turns), p, outdir, make_answer_fn(gwx), args.system)
            log(persona, "probe", p["id"], "cutoff", p["cutoff_turn"])

    with cf.ThreadPoolExecutor(2) as ex:
        for f in [ex.submit(per_persona, pe) for pe in ("M01", "M02")]:
            f.result()
    for f in futs:
        f.result()
    log("run done", args.system, args.split)


# --------------------------------------------------------------------------- judge
def fmt_conv(p, rows_before, row):
    lines = []
    for t in (p.get("tail") or []):
        lines.append(f"用户：{t['user']}\n小满：{t['assistant']}")
    for r in rows_before:
        lines.append(f"用户：{r['user']}\n小满：{r['answer']}")
    lines.append(f"用户：{row['user']}   ← 陪伴者要回复这一句")
    return "\n".join(lines)


def card_text(k, name):
    v = k.get(name) or {}
    if not v or not (v.get("what") or "").strip():
        return "（无）"
    return f"what：{v.get('what')}\nnot_for：{'；'.join(v.get('not_for') or []) or '（无）'}\nexamples：{'；'.join(v.get('examples') or []) or '（无）'}"


class HistoryIndex:
    def __init__(self, hist):
        self.turns = hist
        self.bm = IncBM25()
        for t in hist:
            self.bm.add(doc_text(t))

    def top(self, text, cutoff, k=4):
        out = []
        for i in self.bm.top(text, 80):
            if i < cutoff:
                out.append(self.turns[i])
            if len(out) >= k:
                break
        return out


def judge_turn(gw, p, k, rows_before, row, hidx, tag):
    ev = k.get("evidence") or "（无）"
    prompt = fill(PROMPTS["judge"], CLASS=k["subtype"], CLASSNAME=CLASS_NAME[k["class"]], NOW=row["time"], CONVERSATION=fmt_conv(p, rows_before, row),
                                     REPLY=row["answer"], TARGET=card_text(k, "target"), FORBIDDEN=card_text(k, "forbidden"),
                                     DECOYS="；".join(k.get("decoys") or []) or "（无）", OK_INSTEAD=k.get("ok_instead") or "（无）", EVIDENCE=ev)
    j = None
    for attempt in range(3):
        r = gw.chat(JUDGE_MODEL, [{"role": "user", "content": prompt}], "judge", tag, temperature=0, max_tokens=500, thinking={"type": "disabled"})
        try:
            j = parse_json(r["choices"][0]["message"].get("content"))
            break
        except ValueError:
            j = None
    if j is None:
        j = {"responsive": False, "judge_format_failure": True}
    j.setdefault("other_recalls", [])
    j["other_recalls"] = [x for x in (j.get("other_recalls") or []) if isinstance(x, str)][:4]
    recalls = []
    if j.get("target_recalled"):
        recalls.append("用上了应该用的旧事")
    if j.get("forbidden_recalled"):
        recalls.append("带出了不该带出的旧事")
    recalls += j["other_recalls"]
    # claim verification for the other recalls (history lookup, no card)
    j["claims_unsupported"] = 0
    if j["other_recalls"]:
        cutoff = row["visible_until"] if False else p["cutoff_turn"]
        snips = []
        for c in j["other_recalls"]:
            for t in hidx.top(c, cutoff, 3):
                snips.append(f"[第{t['turn']}轮 {t['time'][:16]}] 用户：{t['user'][:200]} / 小满：{t['assistant'][:120]}")
        snips = list(dict.fromkeys(snips))[:10]
        if k.get("evidence"):
            snips.append("【出题人给的历史依据】" + k["evidence"][:1500])
        vp = fill(PROMPTS["verify"], CLAIMS="\n".join(f"{n + 1}. {c}" for n, c in enumerate(j["other_recalls"])), SNIPPETS="\n".join(snips) or "（无）")
        # the tail is also history from the system's point of view
        tailtxt = "\n".join(f"[当前对话] 用户：{t['user'][:300]} / 小满：{t['assistant'][:160]}" for t in (p.get("tail") or []))
        cur = [f"[当前对话] 用户：{r['user'][:300]} / 小满：{r['answer'][:160]}" for r in rows_before] + [f"[当前对话] 用户：{row['user'][:400]}"]
        tailtxt = (tailtxt + "\n" + "\n".join(cur)).strip()
        vp =vp.replace("候选历史（第几轮、时间）：", "候选历史（第几轮、时间）：\n" + tailtxt)
        r = gw.chat(JUDGE_MODEL, [{"role": "user", "content": vp}], "judge", tag + "-verify", temperature=0, max_tokens=300, thinking={"type": "disabled"})
        try:
            v = parse_json(r["choices"][0]["message"].get("content")).get("verdicts") or []
        except ValueError:
            v = []
        j["claim_verdicts"] = v
        j["claims_unsupported"] = sum(1 for x in v if x == "unsupported")
    j["any_recall"] = bool(recalls)
    if recalls:
        vp = fill(PROMPTS["nat"], REPLY=row["answer"], RECALLS="；".join(recalls))
        r = gw.chat(JUDGE_MODEL, [{"role": "user", "content": vp}], "judge", tag + "-nat", temperature=0, max_tokens=200, thinking={"type": "disabled"})
        try:
            j["naturalness"] = int(parse_json(r["choices"][0]["message"].get("content")).get("naturalness"))
        except (ValueError, TypeError):
            j["naturalness"] = 1
    else:
        j["naturalness"] = None
    j["fabrication_raw"] = bool(j.get("fabricated")) or j["claims_unsupported"] > 0
    j["fabrication"] = confirm_fabrication(gw, p, k, rows_before, row, j, tag) if j["fabrication_raw"] else False
    return j


def confirm_fabrication(gw, p, k, rows_before, row, j, tag):
    """Second look at a flagged turn: only a confirmed invention counts (the first-pass flags were about half false positives in the audit)."""
    suspects = []
    if j.get("fabricated"):
        suspects.append("判分员认为：" + str(j.get("reason") or ""))
    for c, v in zip(j.get("other_recalls") or [], j.get("claim_verdicts") or []):
        if v == "unsupported":
            suspects.append("历史检索没找到依据的说法：" + c)
    vp = fill(PROMPTS["confirm"], CONVERSATION=fmt_conv(p, rows_before, row), REPLY=row["answer"], EVIDENCE=k.get("evidence") or "（无）",
              SUSPECTS=chr(10).join(suspects) or "（无）")
    r = gw.chat(JUDGE_MODEL, [{"role": "user", "content": vp}], "judge", tag + "-confirm", temperature=0, max_tokens=250, thinking={"type": "disabled"})
    try:
        out = parse_json(r["choices"][0]["message"].get("content"))
    except ValueError:
        return True
    j["fabrication_quote"] = out.get("quote")
    return bool(out.get("confirmed"))


def _content_ok(j):
    return j.get("target_content") in ("correct", True, "true", "正确")


def turn_score(k, j):
    """Score in [0,1] for one judged turn."""
    cls, sub = k["class"], k["subtype"]
    if not j.get("responsive") or j.get("fabrication"):
        return 0.0
    nat = j.get("naturalness")
    if cls == "X":
        if not j.get("target_recalled"):
            return 0.0
        if not _content_ok(j):
            return 0.2
        return 0.5 + 0.3 + 0.2 * ((nat if nat is not None else 1) / 2)
    if cls == "H":
        wrong = j.get("target_recalled") and not _content_ok(j)
        if j.get("hedged") and not wrong:
            return 1.0
        if sub in ("H1", "H3") and j.get("target_recalled") and _content_ok(j):
            return 0.7
        return 0.0
    if cls == "Y":
        return 1.0 - OVER_SEVERITY[sub] if j.get("forbidden_recalled") else 1.0
    if cls == "Z":
        if j.get("target_recalled") and not _content_ok(j):
            return 0.0
        if not j.get("any_recall"):
            return 1.0
        return 1.0 if (nat or 0) >= 1 else 0.5
    if cls == "N0":
        return 1.0 - OVER_SEVERITY["N0"] if (j.get("forbidden_recalled") or j.get("other_recalls")) else 1.0
    raise ValueError(cls)


def over_recalled(k, j):
    """For the restraint rate: did the turn recall something it should not (Y and N0 only)."""
    if k["class"] == "Y":
        return bool(j.get("forbidden_recalled"))
    if k["class"] == "N0":
        return bool(j.get("forbidden_recalled") or j.get("other_recalls"))
    return None


def cmd_confirm(args):
    """Retro-apply the confirmation pass to existing judgments (turns whose first-pass flag is set but no confirmation yet)."""
    hist = load_histories(args.release)
    probes, key = load_natural(args.natural, args.split, getattr(args, "sample", 0))
    byid = {p["id"]: p for p in probes}
    outdir = os.path.join(ROOT, "runs", "bench22", args.run, args.system, "natural-" + args.split)
    turns = jl(os.path.join(outdir, "turns.jsonl"))
    jp = os.path.join(outdir, "judgments.jsonl")
    js = jl(jp)
    bysid = {}
    for r in sorted(turns, key=lambda r: (r["id"], r["k"])):
        bysid.setdefault(r["id"], []).append(r)
    gw = Gateway(args.gateway, args.run, f"{args.system}:judge:natural-{args.split}")

    def one(r):
        j = r["judge"]
        if "fabrication_raw" in j or not j.get("fabrication"):
            j.setdefault("fabrication_raw", bool(j.get("fabrication")))
            return
        j["fabrication_raw"] = True
        p, k = byid[r["id"]], key[r["id"]]
        rows = bysid[r["id"]]
        n = [x["k"] for x in rows].index(r["k"])
        j["fabrication"] = confirm_fabrication(gw, p, k, rows[:n], rows[n], j, f"{r['id']}#{r['k']}")
        r["score"] = turn_score(k, j)

    with cf.ThreadPoolExecutor(args.workers) as ex:
        list(ex.map(one, js))
    with open(jp, "w", encoding="utf-8") as f:
        for r in js:
            f.write(json.dumps(r, ensure_ascii=False) + chr(10))
    log("confirm done", args.system, args.split, sum(1 for r in js if r["judge"].get("fabrication")), "confirmed of", sum(1 for r in js if r["judge"].get("fabrication_raw")))


def cmd_judge(args):
    hist = load_histories(args.release)
    probes, key = load_natural(args.natural, args.split, getattr(args, "sample", 0))
    byid = {p["id"]: p for p in probes}
    outdir = os.path.join(ROOT, "runs", "bench22", args.run, args.system, "natural-" + args.split)
    turns = jl(os.path.join(outdir, "turns.jsonl"))
    jp = os.path.join(outdir, "judgments.jsonl")
    done = {(r["id"], r["k"]) for r in jl(jp)} if os.path.exists(jp) else set()
    idx = {pe: HistoryIndex(hist[pe]) for pe in hist}
    bysid = {}
    for r in sorted(turns, key=lambda r: (r["id"], r["k"])):
        bysid.setdefault(r["id"], []).append(r)
    gw = Gateway(args.gateway, args.run, f"{args.system}:judge:natural-{args.split}")

    def one(item_id):
        p, k = byid[item_id], key[item_id]
        rows = bysid[item_id]
        for n, row in enumerate(rows):
            if (item_id, row["k"]) in done:
                continue
            j = judge_turn(gw, p, k, rows[:n], row, idx[p["persona"]], f"{item_id}#{row['k']}")
            s = turn_score(k, j)
            append(jp, {"id": item_id, "k": row["k"], "judge": j, "score": s, "scoring_version": SCORING_VERSION, "judge_sha": JUDGE_SHA})

    with cf.ThreadPoolExecutor(args.workers) as ex:
        list(ex.map(one, [i for i in bysid if i in byid]))
    log("judge done", args.system, args.split)


# --------------------------------------------------------------------------- scoring / summary
def item_scores(probes, key, judgments):
    """id -> final item score in [0,1] (tier B: mean over turns, repeats cap Y2/Y3)."""
    by = {}
    for r in judgments:
        by.setdefault(r["id"], []).append(r)
    out = {}
    for pid, rows in by.items():
        k = key.get(pid)
        if not k:
            continue
        rows.sort(key=lambda r: r["k"])
        sc = [r["score"] for r in rows]
        s = sum(sc) / len(sc)
        if len(rows) > 1 and k["class"] == "Y":
            reps = sum(1 for r in rows if r["judge"].get("forbidden_recalled"))
            if reps >= 2:
                s = min(s, 0.3)
        out[pid] = s
    return out


def aggregate(probes, key, judgments, turns=None, n_boot=2000):
    sc = item_scores(probes, key, judgments)
    items = [p for p in probes if p["id"] in sc]
    by_class = {}
    for p in items:
        by_class.setdefault(key[p["id"]]["class"], []).append(p)

    def wmean(ps, emo_reweight=False):
        w = []
        for p in ps:
            k = key[p["id"]]
            ww = SEVERE_MULT if k.get("severity") == "严重" else 1.0
            w.append(ww)
        if emo_reweight:
            cnt = {}
            for p in ps:
                e = key[p["id"]]["emotion"]
                cnt[e] = cnt.get(e, 0) + 1
            w = [ww * EMOTION_TRAFFIC[key[p["id"]]["emotion"]] / cnt[key[p["id"]]["emotion"]] for ww, p in zip(w, ps)]
        tot = sum(w)
        return sum(ww * sc[p["id"]] for ww, p in zip(w, ps)) / tot if tot else float("nan")

    def side(classes, emo):
        num = den = 0.0
        for c in classes:
            if c in by_class:
                num += CLASS_WEIGHT[c] * wmean(by_class[c], emo)
                den += CLASS_WEIGHT[c]
        return num / den if den else float("nan")

    def combine(emo):
        """Returns (A, R, P): A = 100 * harmonic mean of R and P."""
        r, p = side(RECALL_SIDE, emo), side(RESTRAINT_SIDE, emo)
        a = 200.0 * r * p / (r + p) if (r + p) > 0 else 0.0
        return a, 100.0 * r, 100.0 * p

    def arith(emo):
        num = den = 0.0
        for c, wt in CLASS_WEIGHT.items():
            if c in by_class:
                num += wt * wmean(by_class[c], emo)
                den += wt
        return 100.0 * num / den if den else float("nan")

    # sub-scores over judged turns
    turns_j = [(key[r["id"]], r["judge"]) for r in judgments if r["id"] in key]
    xs = [j for k, j in turns_j if k["class"] == "X"]
    over = [over_recalled(k, j) for k, j in turns_j if over_recalled(k, j) is not None]
    hs = [j for k, j in turns_j if k["class"] == "H"]
    nats = [j["naturalness"] for k, j in turns_j if j.get("naturalness") is not None]
    (a_main, r_side, p_side), (a_traffic, _, _) = combine(False), combine(True)
    out = {"n_items": len(items), "A_nat": a_main, "A_nat_traffic": a_traffic, "R_side": r_side, "P_side": p_side,
           "A_nat_arithmetic": arith(False),
           "A_nat_plain": 100.0 * sum(sc[p["id"]] for p in items) / len(items) if items else float("nan"),
           "by_class": {c: round(100.0 * wmean(ps), 1) for c, ps in by_class.items()},
           "recall_rate": 100.0 * sum(1 for j in xs if j.get("target_recalled") and j.get("responsive")) / len(xs) if xs else float("nan"),
           "restraint_rate": 100.0 * (1 - sum(over) / len(over)) if over else float("nan"),
           "fabrication_rate": 100.0 * sum(1 for k, j in turns_j if j.get("fabrication")) / len(turns_j) if turns_j else float("nan"),
           "hedge_pass_rate": 100.0 * sum(1 for j in hs if j.get("hedged")) / len(hs) if hs else float("nan"),
           "naturalness_mean": sum(nats) / len(nats) if nats else float("nan"), "n_turns_judged": len(turns_j),
           "judge_format_failures": sum(1 for k, j in turns_j if j.get("judge_format_failure"))}

    # ---- 95% interval: cluster bootstrap over the fact group each probe was written from
    import random as _rnd
    cl = {}
    for p in items:
        cl.setdefault(key[p["id"]].get("case_id") or key[p["id"]].get("source_slot") or p["id"], []).append(p)
    ckeys = sorted(cl)
    rng = _rnd.Random(20261111)

    def a_of(sample):
        bc = {}
        for p in sample:
            bc.setdefault(key[p["id"]]["class"], []).append(p)
        r_, p_ = None, None
        def sd(classes):
            num = den = 0.0
            for c in classes:
                if c in bc:
                    num += CLASS_WEIGHT[c] * wmean(bc[c], False)
                    den += CLASS_WEIGHT[c]
            return num / den if den else float("nan")
        r_, p_ = sd(RECALL_SIDE), sd(RESTRAINT_SIDE)
        return 200.0 * 100.0 * r_ * p_ / (r_ + p_) / 100.0 if (r_ + p_) > 0 else 0.0
    draws = []
    if ckeys:
        for _ in range(n_boot):
            smp = []
            for _ in range(len(ckeys)):
                smp += cl[ckeys[rng.randrange(len(ckeys))]]
            draws.append(a_of(smp))
        draws.sort()
        out["A_nat_interval95"] = [round(draws[int(0.025 * (len(draws) - 1))], 2), round(draws[int(0.975 * (len(draws) - 1))], 2)]
        out["A_nat_draws"] = [round(x, 3) for x in draws[::10]]
    # ---- diagnostics on X probes: did the needed memory reach the model, and was it used when it did
    if turns is not None:
        used = {}
        for r in turns:
            used.setdefault(r["id"], set()).update(r.get("used_turns") or [])
        recalled = {}
        for r in judgments:
            if r["judge"].get("target_recalled") and r["judge"].get("responsive"):
                recalled[r["id"]] = True
        xr = [p["id"] for p in items if key[p["id"]]["class"] == "X"]
        ev = {i: {int(n) for n in re.findall(r"第(\d+)轮", key[i].get("evidence") or "")} for i in xr}
        reached = [i for i in xr if ev[i] and (ev[i] & used.get(i, set()))]
        not_reached = [i for i in xr if i not in set(reached)]
        out["x_diagnostics"] = {"n_X": len(xr), "needed_memory_reached_model_pct": round(100.0 * len(reached) / len(xr), 1) if xr else None,
                                "used_when_reached_pct": round(100.0 * sum(1 for i in reached if recalled.get(i)) / len(reached), 1) if reached else None,
                                "used_when_not_reached_pct": round(100.0 * sum(1 for i in not_reached if recalled.get(i)) / len(not_reached), 1) if not_reached else None,
                                "n_reached": len(reached),
                                "X4_due_day": {"n": sum(1 for i in xr if key[i]["subtype"] == "X4"),
                                               "reached_pct": round(100.0 * sum(1 for i in reached if key[i]["subtype"] == "X4") / max(1, sum(1 for i in xr if key[i]["subtype"] == "X4")), 1)}}
    return out, sc


def system_cost(run, system, split, rows):
    """C for one board run: system calls (ingest + retrieve, repriced with the current price table) + memory text at the flash input price."""
    fin = PRICES["models"]["deepseek-v4.1-flash"]["in_per_mtok"]
    led = jl(os.path.join(ROOT, "runs", "bench22", "natural", "spend-ledger.jsonl"))
    ing = ret = 0.0
    for r in led:
        if r.get("run") == run and r.get("system", "").startswith(f"{system}:") and r.get("system", "").endswith(f":natural-{split}") and r.get("phase") in ("ingest", "retrieve"):
            c = price_cny(_priced(r["model"]), r.get("in_tokens", 0), r.get("out_tokens", 0))
            if r["phase"] == "ingest":
                ing += c
            else:
                ret += c
    mem = sum(r.get("mem_tokens", 0) for r in rows) * fin / 1e6
    return {"ingest": round(ing, 4), "retrieve": round(ret, 4), "memory_in_prompt": round(mem, 4), "total_C": round(ing + ret + mem, 4),
            "memory_tokens_total": round(sum(r.get("mem_tokens", 0) for r in rows))}


def cmd_summarize(args):
    probes, key = load_natural(args.natural, args.split, getattr(args, "sample", 0))
    outdir = os.path.join(ROOT, "runs", "bench22", args.run, args.system, "natural-" + args.split)
    turns = jl(os.path.join(outdir, "turns.jsonl"))
    judg = jl(os.path.join(outdir, "judgments.jsonl"))
    agg, sc = aggregate(probes, key, judg, turns)
    cost = system_cost(args.run, args.system, args.split, turns)
    leaks = sorted({r["id"] for r in turns if r["leak_turns_after_visible"]})
    # tail contamination: another item's tail text must never appear in this item's memory prompt
    tails = {}
    for p in probes:
        for t in (p.get("tail") or []):
            if len(t["user"]) >= 10:
                tails.setdefault(p["id"], []).append(t["user"])
    contam = []
    for r in turns:
        for pid, ts in tails.items():
            if pid != r["id"] and any(t in r["prompt"] for t in ts):
                contam.append([r["id"], pid])
                break
    out = {"system": args.system, "split": args.split, "run": args.run, "scoring_version": SCORING_VERSION, "judge_sha": JUDGE_SHA,
           "metrics": agg, "cost_cny": cost, "leak_flags": leaks, "tail_contamination": contam[:20], "n_contaminated": len(contam)}
    json.dump(out, open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(json.dumps({"A_nat": round(agg["A_nat"], 1), "recall": round(agg["recall_rate"], 1), "restraint": round(agg["restraint_rate"], 1),
                    "fab": round(agg["fabrication_rate"], 1), "C": cost["total_C"], "leaks": len(leaks), "contam": len(contam)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "judge", "confirm", "summarize"])
    ap.add_argument("--release", required=True)
    ap.add_argument("--natural", required=True)
    ap.add_argument("--system", required=True)
    ap.add_argument("--split", default="sealed", choices=["dev", "sealed", "all"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--gateway", default=os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:18878/v1"))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--sample", type=int, default=0, help="run/judge/summarize only a class-proportional sample of N probes of the split")
    args = ap.parse_args()
    {"run": cmd_run, "judge": cmd_judge, "confirm": cmd_confirm, "summarize": cmd_summarize}[args.cmd](args)


if __name__ == "__main__":
    main()
