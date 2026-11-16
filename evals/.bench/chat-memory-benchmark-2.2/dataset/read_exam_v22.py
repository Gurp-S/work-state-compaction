# -*- coding: utf-8 -*-
"""Bench 2.2 local validator (offline, standard library only).  read-exam-v2.2

  python read_exam_v22.py                  basic checks: exam-inputs.jsonl, histories/, manifest.json (what a participant can run)
  python read_exam_v22.py --verify-all     plus the answer-key checks (needs review-only/answer-key.jsonl)
  python read_exam_v22.py --root DIR       release directory (default: the directory of this file)

Basic
  B1 every exam row has exactly the keys {id, persona, history_file, history_sha256, now, cutoff_turn, question}
  B2 ids are unique
  B3 persona is listed in manifest; history file exists; its SHA256 equals history_sha256 and the manifest
  B4 history rows have keys {轮次, 逻辑时间, 用户消息, 助手回复, 日, 会话}; turns count from 1 without gaps; times strictly increase
  B5 `now` parses with a time zone; cutoff_turn = the last turn whose time is not later than `now`
  B6 question is a non-empty string
  B7 every file listed in manifest has the listed SHA256
Verify-all
  V1 every exam id has an answer-key row, and vice versa
  V2 anchor turns and evidence turns are <= the cutoff turn
  V3 group_age_seconds is consistent with the anchors (age of the newest anchor) within 1 day
  V4 every twin_id has >= 2 members and all members are on the same split
  V5 the question does not contain a required point verbatim (>= 8 characters)
  V6 rubric is self-consistent: required non-empty, forbidden non-empty, no item both required and forbidden
  V7 natural board (if natural/ exists): probe cutoff = last turn not later than the first tail/script time; ids unique; classes legal
  V8 report only: counts per split / probe type / daily vs long-term
"""
import argparse, collections, datetime as dt, hashlib, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KEYS = {"id", "persona", "history_file", "history_sha256", "now", "cutoff_turn", "question"}
HKEYS = {"轮次", "逻辑时间", "用户消息", "助手回复", "日", "会话"}


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def jl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def norm(s):
    return re.sub(r"[\s，。！？、；：,.!?;:“”\"'‘’（）()…—\-]", "", str(s))


def P(t):
    return dt.datetime.fromisoformat(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=HERE)
    ap.add_argument("--verify-all", action="store_true")
    a = ap.parse_args()
    R = a.root
    errs, rep = [], {}
    man = json.load(open(os.path.join(R, "manifest.json"), encoding="utf-8"))
    exam = jl(os.path.join(R, "exam-inputs.jsonl"))
    ids = [e["id"] for e in exam]
    if len(set(ids)) != len(ids):
        errs.append("B2 duplicate ids")
    hist, times = {}, {}
    for p, info in man["personas"].items():
        hp = os.path.join(R, info["history_file"])
        if not os.path.exists(hp):
            errs.append(f"B3 missing {hp}")
            continue
        if sha256(hp) != info["sha256"]:
            errs.append(f"B3 history sha mismatch {p}")
        rows = jl(hp)
        for i, r in enumerate(rows, 1):
            if set(r) != HKEYS:
                errs.append(f"B4 {p} row {i} keys {sorted(r)}")
                break
            if r["轮次"] != i:
                errs.append(f"B4 {p} turn numbering at {i}")
                break
        ts = [P(r["逻辑时间"]) for r in rows]
        if any(b <= a_ for a_, b in zip(ts, ts[1:])):
            errs.append(f"B4 {p} times not strictly increasing")
        hist[p], times[p] = rows, ts
    for e in exam:
        if set(e) != KEYS:
            errs.append(f"B1 {e.get('id')} keys {sorted(set(e) ^ KEYS)}")
            continue
        if e["persona"] not in man["personas"]:
            errs.append(f"B3 {e['id']} persona")
            continue
        if e["history_sha256"] != man["personas"][e["persona"]]["sha256"]:
            errs.append(f"B3 {e['id']} history_sha256")
        try:
            now = P(e["now"])
            if now.tzinfo is None:
                errs.append(f"B5 {e['id']} now has no time zone")
        except ValueError:
            errs.append(f"B5 {e['id']} now unparsable")
            continue
        ts = times[e["persona"]]
        n = sum(1 for t in ts if t <= now)
        if n != e["cutoff_turn"]:
            errs.append(f"B5 {e['id']} cutoff {e['cutoff_turn']} but last turn <= now is {n}")
        if not isinstance(e["question"], str) or not e["question"].strip():
            errs.append(f"B6 {e['id']} empty question")
    for rel, h in man["files"].items():
        fp = os.path.join(R, rel)
        if not os.path.exists(fp):
            errs.append(f"B7 missing {rel}")
        elif sha256(fp) != h:
            errs.append(f"B7 sha mismatch {rel}")
    if a.verify_all:
        kp = os.path.join(R, "review-only", "answer-key.jsonl")
        key = {k["id"]: k for k in jl(kp)}
        if set(key) != set(ids):
            errs.append(f"V1 exam/key id mismatch: {len(set(ids) - set(key))} without key, {len(set(key) - set(ids))} key without exam")
        em = {e["id"]: e for e in exam}
        twins = collections.defaultdict(list)
        c = collections.Counter()
        for i, k in key.items():
            e = em.get(i)
            if not e:
                continue
            for an in k.get("anchors") or []:
                if an.get("last_turn", 0) > e["cutoff_turn"]:
                    errs.append(f"V2 {i} anchor after cutoff")
            if any(t > e["cutoff_turn"] for t in k.get("evidence_turns") or []):
                errs.append(f"V2 {i} evidence after cutoff")
            ages = [an["age_seconds"] for an in k.get("anchors") or [] if an.get("age_seconds") is not None]
            if ages and k.get("group_age_seconds") is not None and k["group_age_seconds"] > min(ages) + 86400:
                errs.append(f"V3 {i} group_age_seconds {k['group_age_seconds']} vs anchors {min(ages)}")
            r = k.get("rubric") or {}
            if not r.get("required") or not r.get("forbidden"):
                errs.append(f"V6 {i} rubric empty required/forbidden")
            if set(map(norm, r.get("required", []))) & set(map(norm, r.get("forbidden", []))):
                errs.append(f"V6 {i} required and forbidden share an item")
            qn = norm(e["question"])
            for rq in r.get("required", []):
                x = norm(rq)
                if len(x) >= 8 and x in qn:
                    errs.append(f"V5 {i} question contains a required point")
            if k.get("twin_id"):
                twins[k["twin_id"]].append(k)
            age = k.get("group_age_seconds")
            c[(k.get("split"), k.get("probe_type") or "legacy")] += 1
            c[(k.get("split"), "daily" if (age is not None and age <= 86400) else "long")] += 1
        for t, mem in twins.items():
            if len(mem) != 2:
                errs.append(f"V4 twin {t} has {len(mem)} members (must be exactly 2)")
            if len({m.get("split") for m in mem}) > 1:
                errs.append(f"V4 twin {t} spans splits")
        rep = {f"{a_}|{b}": v for (a_, b), v in sorted(c.items(), key=str)}
        nat = os.path.join(R, "natural")
        if os.path.exists(os.path.join(nat, "natural-key.jsonl")):
            nk = {k["id"]: k for k in jl(os.path.join(nat, "natural-key.jsonl"))}
            nps = jl(os.path.join(nat, "natural-probes.jsonl"))
            if len({p["id"] for p in nps}) != len(nps):
                errs.append("V7 natural duplicate ids")
            for p in nps:
                t0 = P(p["tail"][0]["time"] if p["tier"] == "A" else p["script"][0]["time"])
                n = sum(1 for t in times[p["persona"]] if t <= t0)
                if n != p["cutoff_turn"]:
                    errs.append(f"V7 {p['id']} cutoff {p['cutoff_turn']} but {n}")
                if p["id"] not in nk or nk[p["id"]]["class"] not in ("X", "Y", "H", "Z", "N0"):
                    errs.append(f"V7 {p['id']} key/class")
            rep["natural"] = dict(collections.Counter((p["split"], nk[p["id"]]["class"]) for p in nps if p["id"] in nk).most_common())
            rep["natural"] = {f"{a_}|{b}": v for (a_, b), v in sorted(collections.Counter((p["split"], nk[p["id"]]["class"]) for p in nps if p["id"] in nk).items())}
    print(json.dumps({"errors": len(errs), "exam_rows": len(exam), "report": rep}, ensure_ascii=False, indent=1))
    for e in errs[:60]:
        print("ERR", e)
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
