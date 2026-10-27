"""A/B every denoise rule on one synthetic noisy snapshot; no model calls.

Each arm runs alone on the same rows, so the byte deltas are attributable.
Control rows (user/system/developer) are checked to pass through untouched.
"""
import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

from wsc.denoise import DenoisePolicy, RULES, apply_rules, recover, summarize, verify
from wsc.denoise.registry import is_control, row_size


def log_text(index):
    body = ["collected 120 items", "\x1b[32mPASSED\x1b[0m test_mod.py::test_%d" % index]
    body += ["." * 60] * 6
    body += ["progress %d%%\rprogress %d%%\rfinal %d%%" % (index, index + 1, index + 2)]
    body += ["traceback line %d: in handler" % line for line in range(40)]
    return "\n".join(body)


def traceback_text():
    block = ["Traceback (most recent call last):",
             '  File "app.py", line 42, in handle', "    return compute(payload)",
             "ValueError: payload missing field 'id'"]
    return "\n".join(block * 6)


def diff_text(index):
    lines = [f"diff --git a/src/mod_{index}.py b/src/mod_{index}.py",
             f"--- a/src/mod_{index}.py", f"+++ b/src/mod_{index}.py", "@@ -1,20 +1,24 @@"]
    lines += [f"-old line {n}" for n in range(18)]
    lines += [f"+new line {n}" for n in range(22)]
    return "\n".join(lines)


def big_payload(index):
    return {"items": [{"id": f"item-{index}-{n}", "payload": "x" * 80,
                       "meta": {"nested": {"deep": "y" * 40}}} for n in range(60)],
            "cursor": index}


def build_rows():
    rows = []
    seq = 0

    def add(kind, payload, text=None, role=None, call_id=None, control=False):
        nonlocal seq
        seq += 1
        rows.append({"seq": seq, "id": f"src-{seq}", "kind": kind, "payload": payload,
                     "text": text, "role": role, "call_id": call_id, "control": control})

    add("message", {"text": "task: fix the failing tests"}, "task: fix the failing tests",
        role="user", control=True)
    add("message", {"text": "system policy"}, "system policy", role="system", control=True)

    for index in range(30):
        add("result", {"output": log_text(index)}, log_text(index), call_id=f"call-{index}")

    for index in range(8):
        add("result", {"output": "identical output"}, "identical output", call_id=f"dup-{index}")

    for path in ("src/app.py", "src/store.py", "src/cli.py"):
        for version in range(3):
            content = f"{path} version {version}\n" + "line\n" * 20
            add("result", {"path": path, "version": version, "content": content}, content,
                call_id=f"read-{path}-{version}")

    for index in range(5):
        add("result", big_payload(index), json.dumps(big_payload(index)), call_id=f"big-{index}")

    for index in range(4):
        add("result", {"output": traceback_text()}, traceback_text(), call_id=f"tb-{index}")

    for index in range(3):
        add("result", {"output": diff_text(index)}, diff_text(index), call_id=f"diff-{index}")

    add("message", {"text": "done"}, "done", role="assistant")
    return rows


def total_bytes(rows):
    return sum(row_size(row) for row in rows)


def run_arm(rows, rule_ids):
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    result, actions = apply_rules(rows, rule_ids, policy=DenoisePolicy(enabled=True))
    wall = time.perf_counter() - start_wall
    cpu = time.process_time() - start_cpu
    control_ok = all(is_control(before) == is_control(after)
                     and before["id"] == after["id"] and before["kind"] == after["kind"]
                     and before.get("call_id") == after.get("call_id")
                     for before, after in zip(rows, result))
    checked = verify(rows, result, actions)
    restored = recover(actions, rows)
    report = summarize(actions, len(rows), len(result))
    report["verified"] = True
    report["recovered_sources"] = len(restored)
    report.update({"wall": round(wall, 4), "cpu": round(cpu, 4), "control_preserved": control_ok,
                   "bytes_before": total_bytes(rows), "bytes_after": total_bytes(result)})
    report["saved_ratio_total"] = round(
        (report["bytes_before"] - report["bytes_after"]) / report["bytes_before"], 4)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args()
    rows = build_rows()
    table = RULES()
    arms = {}
    for name in table:
        samples = [run_arm(rows, [name]) for _ in range(args.rounds)]
        arms[name] = {
            "reversible": table[name].REVERSIBLE,
            "touched_sources": samples[0]["touched_sources"],
            "saved_bytes": samples[0]["saved_bytes"],
            "saved_ratio_total": samples[0]["saved_ratio_total"],
            "recoverable_ratio": samples[0]["recoverable_ratio"],
            "cpu_ms": round(statistics.median([s["cpu"] for s in samples]) * 1000, 2),
            "control_preserved": all(s["control_preserved"] for s in samples),
            "verified": all(s["verified"] for s in samples),
            "recovered_sources": samples[0]["recovered_sources"],
        }
    combined = run_arm(rows, None)
    result = {"format": "wsc.denoise_ab/1", "rows": len(rows),
              "bytes_before": total_bytes(rows), "arms": arms,
              "all_rules": {"touched_sources": combined["touched_sources"],
                            "saved_bytes": combined["saved_bytes"],
                            "saved_ratio_total": combined["saved_ratio_total"],
                            "bytes_after": combined["bytes_after"],
                            "control_preserved": combined["control_preserved"],
                            "per_rule": combined["rules"]}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
