"""CSM acceptance measurement (§16.1-16.6): correctness on scripted cases + timings.

Run: PYTHONPATH=src py -3.11 benchmarks/csm_acceptance.py [--memories 2000]
Prints one JSON object: classification accuracy, identity routing accuracy, dependency
impact result, tree evolution result, and ingest/query latency percentiles.
"""
from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, MemoryQuery

CONTEXTS = ("project:alpha", "project:beta")


def timed(fn):
    started = time.perf_counter()
    value = fn()
    return value, (time.perf_counter() - started) * 1000.0


def percentile(values, share):
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(share * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def build(count: int) -> tuple[CSM, float, float]:
    root = Path(tempfile.mkdtemp())
    service = CSM(CsmStore(root / "bench.sqlite", namespace="bench"))
    events = [Event(id=f"evt_{i:05d}", source_type="doc", payload={"i": i})
              for i in range(count)]
    _, ingest_ms = timed(lambda: service.ingest(events))
    candidates = [
        MemoryCandidate(entity=f"entity_{i % 200:03d}", slot=f"slot_{i % 5}",
                        value=f"value_{i}", source_ids=(f"evt_{i:05d}",),
                        contexts=(CONTEXTS[i % 2],))
        for i in range(count)]
    _, remember_ms = timed(lambda: service.remember(candidates))
    return service, ingest_ms, remember_ms


def classification(service: CSM) -> dict:
    cases = []
    # Current fact: the second write at the same identity is the head revision.
    service.remember([MemoryCandidate(entity="case_current", slot="s", value="one",
                                      source_ids=("evt_00000",))])
    service.remember([MemoryCandidate(entity="case_current", slot="s", value="two",
                                      source_ids=("evt_00001",))])
    cases.append(("current", MemoryQuery(entity="case_current", slot="s"), "CURRENT_CONFIRMED"))
    cases.append(("historical", MemoryQuery(entity="case_current", slot="s",
                                            include_history=True), "HISTORICAL"))
    cases.append(("unknown_time", MemoryQuery(entity="case_current", slot="s",
                                              valid_at="2000-01-01T00:00:00Z"), "UNKNOWN"))
    cases.append(("unknown_identity", MemoryQuery(entity="case_missing", slot="s"), None))
    # Ambiguous attribution: two context variants, candidate names none.
    service.remember([MemoryCandidate(entity="case_amb", slot="s", value="a",
                                      source_ids=("evt_00000",), contexts=("project:alpha",))])
    service.remember([MemoryCandidate(entity="case_amb", slot="s", value="b",
                                      source_ids=("evt_00001",), contexts=("project:beta",))])
    parked = service.remember([MemoryCandidate(entity="case_amb", slot="s", value="c",
                                               source_ids=("evt_00002",))])
    cases.append(("pending", MemoryQuery(entity="case_amb", slot="s"), "PENDING_BINDING"))
    correct, failures = 0, []
    for name, query, expected in cases:
        result = service.query(query)
        classes = set(result["counts"])
        if expected is None:
            ok = not result["results"] and not classes
        else:
            ok = expected in classes and (name != "current" or result["counts"].get(expected) == 1)
        correct += int(ok)
        if not ok:
            failures.append({"case": name, "expected": expected, "got": sorted(classes)})
    assert parked[0]["operation"] == "DEFER"
    return {"cases": len(cases), "correct": correct,
            "accuracy": round(correct / len(cases), 4), "failures": failures}


def identity_routing(service: CSM) -> dict:
    cases, correct = 0, 0
    created = service.remember([MemoryCandidate(entity="route", slot="s", value="v",
                                                source_ids=("evt_00000",),
                                                contexts=("project:alpha",))])[0]
    cases += 1
    correct += int(created["operation"] == "create")
    updated = service.remember([MemoryCandidate(entity="route", slot="s", value="v2",
                                                source_ids=("evt_00001",),
                                                contexts=("project:alpha",))])[0]
    cases += 1
    correct += int(updated["operation"] == "update" and updated["memory_id"] == created["memory_id"])
    deferred = service.remember([MemoryCandidate(entity="route", slot="s", value="v3",
                                                 source_ids=("evt_00002",))])[0]
    cases += 1
    correct += int(deferred["operation"] == "DEFER")
    target = service.remember([MemoryCandidate(entity="route_target", slot="s", value="x",
                                               source_ids=("evt_00000",),
                                               contexts=("project:alpha",))])[0]
    linked = service.remember([MemoryCandidate(entity="route", slot="s", value=None,
                                               source_ids=("evt_00000",),
                                               contexts=("project:alpha",), intent="link",
                                               link_kind="ABOUT",
                                               link_object=f"memory:{target['memory_id']}")])[0]
    cases += 1
    correct += int(linked["operation"] == "LINK")
    rebound = service.reinterpret(created["memory_id"], contexts=("project:beta",),
                                  evidence=("evt_00001",), reason="benchmark correction")
    cases += 1
    correct += int(rebound["operation"] == "REINTERPRET")
    return {"cases": cases, "correct": correct, "accuracy": round(correct / cases, 4)}


def dependency(service: CSM) -> dict:
    rule = service.remember([MemoryCandidate(entity="dep_rule", slot="s", value="cap=100",
                                             source_ids=("evt_00000",))])[0]
    plan = service.remember([MemoryCandidate(entity="dep_plan", slot="s", value="ship 80",
                                             source_ids=("evt_00001",))])[0]
    service.link(kind="CONSTRAINT", subject=f"memory:{rule['memory_id']}",
                 object=f"memory:{plan['memory_id']}", evidence=("evt_00000",), confirmed=True)
    result = service.impact(rule["memory_id"])
    return {"effects": [item["effect"] for item in result.get("effects", [])],
            "objects": [item["object"] for item in result.get("effects", [])],
            "cascaded": result.get("cascaded")}


def tree_evolution(service: CSM) -> dict:
    node = service.create_node(name="Bench products", scope_description="bench entities",
                               accepted_relations=("ABOUT",), evidence=("evt_00000",))
    for entity in ("tree_0", "tree_1", "tree_2"):
        memory = service.remember([MemoryCandidate(entity=entity, slot="slot_0", value="v",
                                                   source_ids=("evt_00000",))])[0]
        service.mount(memory["memory_id"], node_id=node["node_id"], relation="ABOUT",
                      allow_candidate=True)
    outcome, evolve_ms = timed(service.evolve)
    promoted = [item for item in service.tree()["nodes"] if item["node_id"] == node["node_id"]]
    return {"changed": outcome["changed"], "evolve_ms": round(evolve_ms, 3),
            "status": promoted[0]["status"] if promoted else None,
            "counts": outcome["counts"]}


def latency(service: CSM, count: int) -> dict:
    queries = [MemoryQuery(entity=f"entity_{i % 200:03d}", slot=f"slot_{i % 5}")
               for i in range(500)]
    samples, sizes = [], []
    for query in queries:
        result, elapsed = timed(lambda q=query: service.query(q))
        samples.append(elapsed)
        sizes.append(sum(result["counts"].values()))
    return {"queries": len(samples), "p50_ms": percentile(samples, 0.50),
            "p95_ms": percentile(samples, 0.95), "max_ms": round(max(samples), 3),
            "avg_results": round(statistics.mean(sizes), 2), "memories": count}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memories", type=int, default=2000)
    args = parser.parse_args()
    service, ingest_ms, remember_ms = build(args.memories)
    report = {"memories": args.memories,
              "ingest_ms": round(ingest_ms, 3), "remember_ms": round(remember_ms, 3),
              "classification": classification(service),
              "identity_routing": identity_routing(service),
              "dependency": dependency(service),
              "tree": tree_evolution(service),
              "query": latency(service, args.memories)}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
