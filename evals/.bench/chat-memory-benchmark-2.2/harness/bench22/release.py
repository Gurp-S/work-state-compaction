# -*- coding: utf-8 -*-
"""Load a Bench 2.2 release directory: histories, exam rows (public view) and the answer key (private view)."""
import hashlib
import json
import os


def jl(p):
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                out.append(json.loads(line))
    return out


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_histories(root):
    man = json.load(open(os.path.join(root, "manifest.json"), encoding="utf-8"))
    hist = {}
    for p, info in man["personas"].items():
        rows = jl(os.path.join(root, info["history_file"]))
        hist[p] = [{"turn": r["轮次"], "time": r["逻辑时间"], "user": r["用户消息"], "assistant": r["助手回复"]} for r in rows]
    return hist


def load_items(root, with_key=True):
    """Items = exam row (+ answer-key row when with_key).  'split' is dev/test/new-dev/new-test."""
    exam = jl(os.path.join(root, "exam-inputs.jsonl"))
    items = {r["id"]: dict(r) for r in exam}
    if with_key:
        for k in jl(os.path.join(root, "review-only", "answer-key.jsonl")):
            if k["id"] in items:
                it = items[k["id"]]
                it.update({x: k[x] for x in k if x not in it})
                ages = [a["age_seconds"] for a in k.get("anchors") or [] if a.get("age_seconds") is not None]
                it["group_age_seconds"] = k.get("group_age_seconds", min(ages) if ages else None)
    return list(items.values())


def board_name(persona):
    return {"M01": "短对话榜", "M02": "长对话榜"}[persona]
