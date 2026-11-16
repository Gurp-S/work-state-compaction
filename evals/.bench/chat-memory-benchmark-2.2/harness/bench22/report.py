# -*- coding: utf-8 -*-
"""Bench 2.2 leaderboard: short board (M01), long board (M02), natural-use board, composite, all with 95% cluster-bootstrap intervals.

    python -m bench22.report --release DIR --run R22 --split sealed --out OUTDIR [--systems a,b@run,...] [--natural-run NR22] 

A  = mean(daily score D, long-term score L)  (see scoring.py)           S = A - 3*log2(C / C_ref), C floored at C_ref/4
C_ref = Qwen base's C on the same board (score_config.json: reference_system)
Composite = 0.25*S_short + 0.25*S_long + 0.5*S_natural (score_config.json: board_weights)
Systems listed in PRIVATE_SYSTEMS (our own extra configuration) are only written with --show-private.
"""
import argparse
import json
import math
import os

from . import scoring
from .release import jl, load_items, board_name
from .gateway import PRICES, price_cny, _priced

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIN = PRICES["models"]["deepseek-v4.1-flash"]["in_per_mtok"]
CFG = scoring.CONFIG
REF = CFG.get("reference_system", "qwen-base")
W = CFG.get("board_weights", {"short": 0.25, "long": 0.25, "natural": 0.5})
FLOOR_RESTRAINT, FLOOR_FAB = CFG.get("floor_restraint_pct", 70.0), CFG.get("floor_fabrication_pct", 5.0)
PRIVATE_SYSTEMS = set()
NATURAL_ONLY = {"never-recall", "always-recall"}
NAMES = {"qwen-base": "Qwen 基础方案（参照）", "bm25-recent6": "BM25 + 最近 6 轮（本地）", "recent6": "只看最近 6 轮", "none": "无历史", "vague": "一律含糊",
         "full-context": "全塞（110k token 窗口）", "never-recall": "从不提旧事", "always-recall": "见缝就提旧事"}


def reprice(r):
    return price_cny(_priced(r["model"]), r.get("in_tokens", 0), r.get("out_tokens", 0))


def load_run(run, system, split):
    d = os.path.join(ROOT, "runs", "bench22", run, system, split)
    if not os.path.exists(os.path.join(d, "judgments.jsonl")):
        return None
    g = lambda n: jl(os.path.join(d, n)) if os.path.exists(os.path.join(d, n)) else []
    return {"dir": d, "ctx": {r["id"]: r for r in g("contexts.jsonl")}, "ans": {r["id"]: r for r in g("answers.jsonl")},
            "jud": {r["id"]: r for r in g("judgments.jsonl")}, "summary": json.load(open(os.path.join(d, "summary.json"), encoding="utf-8")) if os.path.exists(os.path.join(d, "summary.json")) else None}


def ledger_costs(run, system, persona, split):
    key = f"{system}:{persona}:{split}"
    ing = ret = 0.0
    for r in jl(os.path.join(ROOT, "runs", "bench22", "spend-ledger.jsonl")):
        if r.get("run") == run and r.get("system") == key:
            if r["phase"] == "ingest":
                ing += reprice(r)
            elif r["phase"] == "retrieve":
                ret += reprice(r)
    return ing, ret


def board_metrics(items, run, rd, system, persona, split, common, n_run):
    passed = {i: v["pass"] for i, v in rd["jud"].items()}
    scored = [it for it in items if it["id"] in common and it["id"] in rd["jud"]]
    units = [u for u in scoring.build_units(scored) if all(i in rd["jud"] for i in u["ids"])]
    bs = scoring.board_scores(units, passed)
    ci = scoring.bootstrap_A(units, passed, n_boot=CFG.get("bootstrap_draws", 2000))
    ing, ret = ledger_costs(run, system, persona, split)
    nq = max(1, n_run)
    ratio = (sum(a["mem_tokens"] for a in rd["ans"].values()) / max(1, sum(len(rd["ctx"][i]["prompt"]) for i in rd["ans"]))) if rd["ans"] else 0.7
    mem = sum(rd["ans"][i]["mem_tokens"] if i in rd["ans"] else ratio * len(rd["ctx"][i]["prompt"]) for i in common if i in rd["ctx"])
    c = ing + ret * (len(common) / nq) + mem * FIN / 1e6
    return {"n_units": bs["n_units"], "n_daily": bs["n_daily"], "n_long": bs["n_long"], "n_pairs": bs["n_pairs"], "A": bs["A"], "D": bs["D"], "L": bs["L"],
            "A_traffic": bs["A_traffic"], "pass_pct": bs["pass_pct"], "ci": None if ci is None else [ci["lo"], ci["hi"]],
            "D_ci": None if ci is None else [ci["D_lo"], ci["D_hi"]], "L_ci": None if ci is None else [ci["L_lo"], ci["L_hi"]],
            "draws": None if ci is None else ci["draws"][::10], "C": c, "C_parts": {"ingest": ing, "retrieve": ret * (len(common) / nq), "memory_in_prompt": mem * FIN / 1e6},
            "by_type": scoring.by_type(units, passed)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--split", default="sealed")
    ap.add_argument("--systems", default="qwen-base,bm25-recent6,recent6,none,vague,full-context")
    ap.add_argument("--natural-run", default="")
    ap.add_argument("--natural", default="", help="natural release dir (default RELEASE/natural)")
    ap.add_argument("--natural-systems", default="qwen-base,bm25-recent6,recent6,none,full-context,never-recall,always-recall")
    ap.add_argument("--show-private", action="store_true")
    ap.add_argument("--sample", type=int, default=0, help="score only the deterministic stratified sample the runner draws with --sample N (same seed)")
    ap.add_argument("--seed", type=int, default=20261109)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    want = "test" if a.split == "sealed" else "dev"
    items = [i for i in load_items(a.release) if i.get("split") == want]
    if a.sample:
        from .runner import pick_sample
        keep = set()
        for pe in ("M01", "M02"):
            keep |= pick_sample([i for i in items if i["persona"] == pe], a.sample, a.seed)
        items = [i for i in items if i["id"] in keep or i.get("kind") != "main"]
    runof = {}
    for tok in a.systems.split(","):
        n, _, rn = tok.partition("@")
        runof[n] = rn or a.run
    systems = {s: load_run(runof[s], s, a.split) for s in runof}
    systems = {s: r for s, r in systems.items() if r}
    out = {"run": a.run, "split": a.split, "score_config": CFG, "prices_version": PRICES["version"], "reference_system": REF, "boards": {}}
    for persona in ("M01", "M02"):
        pit = [i for i in items if i["persona"] == persona]
        ids = {i["id"] for i in pit}
        common = set(ids)
        for s, r in systems.items():
            common &= set(r["jud"]) | ({i for i in ids if i in r["ctx"]} if s == "full-context" else set())
        rows = {}
        for s, r in systems.items():
            n_run = len([i for i in r["ctx"] if i in ids])
            cs = common if s != "full-context" else common & set(r["jud"])
            rows[s] = board_metrics(pit, runof[s], r, s, persona, a.split, cs, n_run)
            if s == "full-context":
                full = board_metrics(pit, runof[s], r, s, persona, a.split, common, n_run)
                rows[s]["C"], rows[s]["C_parts"], rows[s]["sampled"] = full["C"], full["C_parts"], True
        ref = rows.get(REF)
        for s, m in rows.items():
            if ref:
                m["S"] = scoring.composite(m["A"], m["C"], ref["C"])
                m["S_shift"] = m["S"] - m["A"]
                m["S_ci"] = None if not m["ci"] else [m["ci"][0] + m["S_shift"], m["ci"][1] + m["S_shift"]]
        out["boards"][persona] = {"board": board_name(persona), "n_common_items": len(common), "C_ref": ref["C"] if ref else None, "systems": rows}
    # natural board
    nat = {}
    nrun = a.natural_run
    if nrun:
        for s in a.natural_systems.split(","):
            p = os.path.join(ROOT, "runs", "bench22", nrun, s, f"natural-{a.split}", "summary.json")
            if os.path.exists(p):
                nat[s] = json.load(open(p, encoding="utf-8"))
    nref = nat.get(REF)
    ndir = a.natural or os.path.join(a.release, "natural")
    try:
        n_full = sum(1 for p_ in jl(os.path.join(ndir, "natural-probes.jsonl")) if p_["split"] == a.split.replace("sealed", "sealed"))
    except Exception:
        n_full = 0
    out["natural"] = {}
    for s, n in nat.items():
        met = n["metrics"]
        c = n["cost_cny"]["total_C"]
        sampled = bool(n_full and met["n_items"] < 0.9 * n_full)
        if sampled:
            c = c * n_full / met["n_items"]          # C for the whole natural set, from the sample's measured cost
        d = {"sampled": sampled, "n_probes_run": met["n_items"], "A": met["A_nat"], "ci": met.get("A_nat_interval95"), "R": met.get("R_side"), "P": met.get("P_side"), "C": c, "by_class": met["by_class"],
             "recall": met["recall_rate"], "restraint": met["restraint_rate"], "fabrication": met["fabrication_rate"], "hedge": met["hedge_pass_rate"],
             "naturalness": met["naturalness_mean"], "x_diagnostics": met.get("x_diagnostics"), "n_items": met["n_items"], "draws": met.get("A_nat_draws")}
        if nref:
            nref_c = nref["cost_cny"]["total_C"]
            if n_full and nref["metrics"]["n_items"] < 0.9 * n_full:
                nref_c = nref_c * n_full / nref["metrics"]["n_items"]      # sampled reference: C for the whole natural set
            d["S"] = scoring.composite(met["A_nat"], c, nref_c)
            d["S_shift"] = d["S"] - met["A_nat"]
            d["S_ci"] = None if not d["ci"] else [d["ci"][0] + d["S_shift"], d["ci"][1] + d["S_shift"]]
        d["floor_ok"] = met["restraint_rate"] >= FLOOR_RESTRAINT and met["fabrication_rate"] <= FLOOR_FAB
        out["natural"][s] = d
    # composite
    comp = {}
    for s in {x for b in out["boards"].values() for x in b["systems"]} | set(out["natural"]):
        sh = out["boards"]["M01"]["systems"].get(s)
        lo = out["boards"]["M02"]["systems"].get(s)
        nt = out["natural"].get(s)
        if sh and lo and nt and "S" in sh and "S" in nt:
            c = {"S": W["short"] * sh["S"] + W["long"] * lo["S"] + W["natural"] * nt["S"], "A": W["short"] * sh["A"] + W["long"] * lo["A"] + W["natural"] * nt["A"],
                 "floor_ok": nt["floor_ok"]}
            bd = {}
            for key, m in (("short", sh), ("long", lo), ("natural", nt)):
                if m.get("draws"):
                    bd[key] = {"draws": m["draws"], "S_shift": m["S_shift"]}
            ci = scoring.composite_interval(bd, W) if len(bd) == 3 else None
            c["S_ci"] = list(ci) if ci else None
            comp[s] = c
    out["composite"] = comp
    json.dump(out, open(os.path.join(a.out, f"leaderboard-{a.split}-full.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # public view: private systems removed
    vis = lambda s: a.show_private or s not in PRIVATE_SYSTEMS
    pub = json.loads(json.dumps(out))
    for b in pub["boards"].values():
        b["systems"] = {s: m for s, m in b["systems"].items() if vis(s)}
        for m in b["systems"].values():
            m.pop("draws", None)
    pub["natural"] = {s: m for s, m in pub["natural"].items() if vis(s)}
    for m in pub["natural"].values():
        m.pop("draws", None)
    pub["composite"] = {s: m for s, m in pub["composite"].items() if vis(s)}
    json.dump(pub, open(os.path.join(a.out, f"leaderboard-{a.split}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    f1 = lambda x: "-" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.1f}"
    fci = lambda c: "-" if not c else f"{c[0]:.1f}–{c[1]:.1f}"
    L = [f"# 2.2 榜单（{a.split}，run {a.run}，价目表 {PRICES['version']}）", "",
         f"参照系统：{REF}（各榜 C_ref = 它在该榜的 C）。A = 日常分与长期分的平均；S = A − 3·log2(C / C_ref)；括号里是 95% 区间（按事实组聚类自助法）。区间只反映题目抽样的不确定性。", ""]
    for persona in ("M01", "M02"):
        b = pub["boards"][persona]
        L += [f"## {b['board']}（{persona}；共同题单元数见各行）", "",
              f"C_ref = ¥{b['C_ref']:.3f}" if b["C_ref"] else "", "",
              "| 系统 | 单元数（日常/长期，成对数） | A | A 区间 | 日常 D | 长期 L | S | S 区间 | C(¥) | 流量加权 A（附） |", "|---|---|---:|---|---:|---:|---:|---|---:|---:|"]
        for s, m in sorted(b["systems"].items(), key=lambda kv: -kv[1].get("S", kv[1]["A"])):
            L.append(f"| {NAMES.get(s, s)}{'（抽样答题）' if m.get('sampled') else ''} | {m['n_units']}（{m['n_daily']}/{m['n_long']}，{m['n_pairs']}） | {f1(m['A'])} | {fci(m['ci'])} | {f1(m['D'])} | {f1(m['L'])} | {f1(m.get('S'))} | {fci(m.get('S_ci'))} | {m['C']:.3f} | {f1(m['A_traffic'])} |")
        L.append("")
    if pub["natural"]:
        L += ["## 自然用记忆榜", "", "| 系统 | A | A 区间 | R(想起侧) | P(克制侧) | S | S 区间 | C(¥) | 想起率 | 克制率 | 编造率 | 达标底线 |", "|---|---:|---|---:|---:|---:|---|---:|---:|---:|---:|---|"]
        for s, m in sorted(pub["natural"].items(), key=lambda kv: -kv[1].get("S", kv[1]["A"])):
            L.append(f"| {NAMES.get(s, s)}{'（抽样 ' + str(m['n_probes_run']) + ' 题，C 按全部题折算）' if m.get('sampled') else ''} | {f1(m['A'])} | {fci(m['ci'])} | {f1(m['R'])} | {f1(m['P'])} | {f1(m.get('S'))} | {fci(m.get('S_ci'))} | {m['C']:.3f} | {f1(m['recall'])} | {f1(m['restraint'])} | {f1(m['fabrication'])} | {'是' if m['floor_ok'] else '否'} |")
        L += ["", "### 自然用记忆榜·X 类探针的两项诊断（挑战者最需要看的）", "",
              "| 系统 | X 探针数 | 需要的记忆进了提示词(%) | 进了之后用上了(%) | 没进却答对了(%) | 到点类(X4)记忆进了提示词(%) |", "|---|---:|---:|---:|---:|---:|"]
        for s, m in sorted(pub["natural"].items()):
            d = m.get("x_diagnostics")
            if d:
                L.append(f"| {NAMES.get(s, s)} | {d['n_X']} | {f1(d['needed_memory_reached_model_pct'])} | {f1(d['used_when_reached_pct'])} | {f1(d['used_when_not_reached_pct'])} | {f1(d['X4_due_day']['reached_pct'])} |")
        L.append("")
    if pub["composite"]:
        L += ["## 总排名（短 25% + 长 25% + 自然用记忆 50%）", "", "| 系统 | 综合 S | S 区间 | 综合 A | 自然榜底线 |", "|---|---:|---|---:|---|"]
        for s, c in sorted(pub["composite"].items(), key=lambda kv: -kv[1]["S"]):
            L.append(f"| {NAMES.get(s, s)} | {c['S']:.1f} | {fci(c['S_ci'])} | {c['A']:.1f} | {'是' if c['floor_ok'] else '否'} |")
        L.append("")
    open(os.path.join(a.out, f"leaderboard-{a.split}.md"), "w", encoding="utf-8").write("\n".join(L))
    print("\n".join(L))


if __name__ == "__main__":
    main()
