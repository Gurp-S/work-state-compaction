"""Failure triage: was the needed fact stored, retrieved, or lost between the two?"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "benchmarks")]

from csm_public_exam import load_answers  # noqa: E402
from wsc.csm.retrieval import _terms  # noqa: E402

DB = ROOT / "benchmarks" / "results" / "public-exam-v3.db"


def memories(db):
    rows = db.execute("SELECT memory_id, data FROM identities").fetchall()
    out = []
    for row in rows:
        identity = json.loads(row["data"])
        head = db.execute(
            "SELECT data FROM revisions WHERE memory_id=? ORDER BY revision DESC LIMIT 1",
            (row["memory_id"],)).fetchone()
        if head:
            record = json.loads(head["data"])
            out.append((identity["entity"] + ":" + identity["slot"],
                        str(record.get("value") or "")))
    return out


def main(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    answers = load_answers()
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    store = memories(db)
    buckets = {}
    for record in data["results"]:
        if record["passed"]:
            continue
        rubric = answers[record["id"]]["rubric"]
        wanted = " ".join(rubric.get("required", []) + rubric.get("acceptable", []))
        terms = set(_terms(wanted))
        stored = [key for key, text in store if terms & set(_terms(text))]
        retrieved = set(record.get("retrieved") or [])
        if not stored:
            cause = "fact_not_stored"
        elif not (set(stored) & retrieved):
            cause = "stored_not_retrieved"
        else:
            cause = "retrieved_not_answered"
        buckets.setdefault(cause, []).append(record["id"])
        print(f"{cause:22} {record['id']:20} stored={len(stored)} retrieved={len(retrieved)}")
    print(json.dumps({k: len(v) for k, v in buckets.items()}, ensure_ascii=False))
    print(json.dumps(buckets, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1])
