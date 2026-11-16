# -*- coding: utf-8 -*-
"""Bench 2.2 scoring.

Board score  A = mean(D, L)
    D = daily score     : unweighted pass rate (severe items count double) over units whose last relevant mention is <= 1 day old
    L = long-term score : the same over units whose last relevant mention is > 1 day old
Units: an ordinary question is a unit by itself; questions that share a twin_id (time / premise / condition twins,
due-day + no-due control) form ONE unit that passes only when every member passes.  A control alone gives nothing.
The real-traffic weighted score (the 2.1 ranking score) is kept as an extra column (A_traffic).
Every published score carries a 95% interval from a cluster bootstrap over fact groups (the question id before '/').
Composite per board:  S = A - COST_COEF * log2(C / C_ref), C floored at C_ref * COST_FLOOR_RATIO;  C_ref = Qwen base's C.
Overall: short board 25%, long board 25%, natural-use board 50% (weights in score_config.json).
"""
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = {"cost_coef": 3.0, "cost_floor_ratio": 0.25}
CONFIG_PATH = os.path.join(HERE, "score_config.json")
if os.path.exists(CONFIG_PATH):
    CONFIG.update(json.load(open(CONFIG_PATH, encoding="utf-8")))

DAY = 86400
# Share of real-user lookups by age of the old fact (requirements doc 2026-10-30); extra column only.
TRAFFIC_BINS = [(3600, 0.54), (86400, 0.25), (4 * 86400, 0.09), (8 * 86400, 0.05), (31 * 86400, 0.06), (float("inf"), 0.01)]
SEVERE_MULT = 2.0
LONG_BUCKETS = [(3 * DAY, "1-3天"), (15 * DAY, "4-15天"), (45 * DAY, "16-45天"), (90 * DAY, "46-90天"), (float("inf"), "90天以上")]


def judge_pass(j):
    """Pass rule applied by the script (the judge model only reports facts)."""
    req = j.get("required") or []
    ok = bool(req) and all(x == "met" for x in req)
    ok = ok and not j.get("forbidden_hit") and not j.get("tempting_hit") and not j.get("unknown_asserted")
    ok = ok and not j.get("date_wrong") and not j.get("over_hedged")
    return bool(ok)


def points(j):
    req = j.get("required") or []
    if not req:
        return 0.0
    return sum({"met": 1.0, "partial": 0.5}.get(x, 0.0) for x in req) / len(req)


# ------------------------------------------------------------------ units
def group_of(item_id):
    return item_id.split("/")[0]


def build_units(items):
    """items: dicts with id, kind, twin_id, group_age_seconds, rubric.  Returns list of units
    {key, ids, group, age, severe, bucket, probe_type}.  kind == 'control' items without a twin are not scored."""
    pairs = {}
    units = []
    for it in items:
        tw = it.get("twin_id")
        if tw:
            pairs.setdefault(tw, []).append(it)
        elif it.get("kind") == "main":
            units.append([it])
    out = [u for u in units] + [m for m in pairs.values() if len(m) >= 2]
    res = []
    for mem in out:
        ages = [m.get("group_age_seconds") for m in mem if m.get("group_age_seconds") is not None]
        age = max(ages) if ages else None
        severe = any((m.get("rubric") or {}).get("severity") == "severe" for m in mem)
        pts = sorted({m.get("probe_type") or "legacy" for m in mem})
        res.append({"key": mem[0].get("twin_id") or mem[0]["id"], "ids": [m["id"] for m in mem], "group": group_of(mem[0]["id"]),
                    "age": age, "severe": severe, "bucket": "daily" if (age is not None and age <= DAY) else "long",
                    "probe_type": "+".join(pts), "pair": len(mem) > 1})
    return res


def unit_pass(u, passed):
    return all(passed.get(i) for i in u["ids"])


def _w(u):
    return SEVERE_MULT if u["severe"] else 1.0


def bucket_rate(units, passed):
    den = sum(_w(u) for u in units)
    return 100.0 * sum(_w(u) for u in units if unit_pass(u, passed)) / den if den else float("nan")


def board_scores(units, passed):
    d = bucket_rate([u for u in units if u["bucket"] == "daily"], passed)
    l = bucket_rate([u for u in units if u["bucket"] == "long"], passed)
    vals = [x for x in (d, l) if not math.isnan(x)]
    a = sum(vals) / len(vals) if vals else float("nan")
    plain = 100.0 * sum(1 for u in units if unit_pass(u, passed)) / len(units) if units else float("nan")
    return {"A": a, "D": d, "L": l, "pass_pct": plain, "A_traffic": traffic_weighted(units, passed),
            "n_units": len(units), "n_daily": sum(1 for u in units if u["bucket"] == "daily"),
            "n_long": sum(1 for u in units if u["bucket"] == "long"), "n_pairs": sum(1 for u in units if u["pair"])}


def traffic_weighted(units, passed):
    """2.1 ranking score kept as an extra column: units binned by the real-traffic age shares, severe x2."""
    counts = {}
    for u in units:
        counts[traffic_bin(u["age"])] = counts.get(traffic_bin(u["age"]), 0) + 1
    if not counts:
        return float("nan")
    share = sum(TRAFFIC_BINS[b][1] for b in counts)
    tot = got = 0.0
    for u in units:
        b = traffic_bin(u["age"])
        w = TRAFFIC_BINS[b][1] / share / counts[b] * _w(u)
        tot += w
        got += w if unit_pass(u, passed) else 0.0
    return 100.0 * got / tot if tot else float("nan")


def traffic_bin(age_seconds):
    for i, (hi, _) in enumerate(TRAFFIC_BINS):
        if age_seconds is None or age_seconds < hi:
            return i
    return len(TRAFFIC_BINS) - 1


def long_bucket(age):
    for hi, name in LONG_BUCKETS:
        if age is not None and age <= hi:
            return name
    return LONG_BUCKETS[-1][1]


def by_type(units, passed):
    out = {}
    for u in units:
        o = out.setdefault(u["probe_type"], [0, 0])
        o[0] += 1
        o[1] += 1 if unit_pass(u, passed) else 0
    return {k: {"n": v[0], "pass_pct": round(100.0 * v[1] / v[0], 1)} for k, v in sorted(out.items())}


# ------------------------------------------------------------------ cluster bootstrap
def bootstrap_A(units, passed, n_boot=2000, seed=20261111, alpha=0.05):
    """Cluster bootstrap over fact groups.  Returns dict(lo, hi, se, draws) for A (and D, L intervals)."""
    clusters = {}
    for u in units:
        clusters.setdefault(u["group"], []).append(u)
    keys = sorted(clusters)
    if not keys:
        return None
    rng = random.Random(seed)
    # precompute per cluster: (w*pass, w) for daily / long
    pre = []
    for k in keys:
        a = [0.0, 0.0, 0.0, 0.0]
        for u in clusters[k]:
            i = 0 if u["bucket"] == "daily" else 2
            a[i] += _w(u) if unit_pass(u, passed) else 0.0
            a[i + 1] += _w(u)
        pre.append(a)
    draws, dd, ll = [], [], []
    n = len(keys)
    for _ in range(n_boot):
        s = [0.0] * 4
        for _ in range(n):
            c = pre[rng.randrange(n)]
            for j in range(4):
                s[j] += c[j]
        d = 100.0 * s[0] / s[1] if s[1] else None
        l = 100.0 * s[2] / s[3] if s[3] else None
        v = [x for x in (d, l) if x is not None]
        if v:
            draws.append(sum(v) / len(v))
        if d is not None:
            dd.append(d)
        if l is not None:
            ll.append(l)

    def q(xs, p):
        xs = sorted(xs)
        return xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))] if xs else float("nan")
    return {"lo": q(draws, alpha / 2), "hi": q(draws, 1 - alpha / 2), "D_lo": q(dd, alpha / 2), "D_hi": q(dd, 1 - alpha / 2),
            "L_lo": q(ll, alpha / 2), "L_hi": q(ll, 1 - alpha / 2), "n_clusters": n, "draws": draws}


def composite(a, c, c_ref):
    floor = c_ref * CONFIG["cost_floor_ratio"]
    c_eff = max(c, floor)
    return a - CONFIG["cost_coef"] * math.log2(c_eff / c_ref)


def composite_interval(boards, weights, alpha=0.05, seed=7):
    """boards: {name: {'draws': [...A draws], 'S_shift': S-A (cost term), 'S': point}}; independent resampling of each board."""
    rng = random.Random(seed)
    names = [n for n in weights if n in boards and boards[n].get("draws")]
    if not names:
        return None
    m = min(len(boards[n]["draws"]) for n in names)
    tot = []
    for _ in range(m):
        tot.append(sum(weights[n] * (rng.choice(boards[n]["draws"]) + boards[n]["S_shift"]) for n in names) / sum(weights[n] for n in names))
    tot.sort()
    return tot[int(alpha / 2 * (m - 1))], tot[int((1 - alpha / 2) * (m - 1))]


def paired_rate(items, passed):
    """Share of twin pairs where both members pass (kept for the sentinel/diagnostic views)."""
    groups = {}
    for it in items:
        if it.get("twin_id"):
            groups.setdefault(it["twin_id"], []).append(it["id"])
    full = [g for g in groups.values() if len(g) >= 2]
    if not full:
        return None, 0
    ok = sum(1 for g in full if all(passed.get(i) for i in g))
    return 100.0 * ok / len(full), len(full)
