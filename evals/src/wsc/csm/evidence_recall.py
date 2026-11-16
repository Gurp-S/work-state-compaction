"""Read-only recall of state, unresolved proposals and verbatim source events.

Source observations are not promoted to current world state. Relevance uses
corpus information weights, not popularity of a mutable slot. No query labels,
answer keys, question-specific rules or model calls participate.
"""
from collections import Counter
import json

from . import assembly, filters, pending
from ..contracts import digest
from .contracts import parse_instant, require, validate_instant
from .recall_terms import terms, query_terms
from .recall_term_cache import cached_terms
from .source_bridge import expand_scores
from .recall_scoring import overlap_weight
from .recall_neighborhood import dialogue_bounds, prioritize_linked_observation

POLICY = "source-evidence-v2"


def _source_units(payload, *, neighborhood=False):
    if isinstance(payload, dict) and isinstance(payload.get("turns"), list):
        for index, turn in enumerate(payload["turns"]):
            if isinstance(turn, dict) and turn:
                start, end = (dialogue_bounds(payload["turns"], index) if neighborhood
                              else (max(0, index - 1), index + 1))
                yield str(turn.get("dia_id") or index), {
                    **payload,
                    "date": payload.get("date"),
                    # Preserve adjacent dialogue context without asserting that
                    # the statements belong to the same entity or are answers.
                    "turns": [dict(item)
                              for item in payload["turns"][start:end]
                              if isinstance(item, dict) and item]}
    else:
        yield "", payload


def _content(value):
    if isinstance(value, dict):
        # Structural field names, dialogue ids and timestamps are provenance,
        # not lexical evidence or bridge anchors.
        if "turns" in value:
            return " ".join(str(t.get("speaker") or "") + " " + str(t.get("text") or "")
                            + " " + str(t.get("blip_caption") or "")
                            for t in value["turns"])
        return " ".join(_content(v) for k, v in value.items()
                        if k not in {"dia_id", "date", "observed_at"})
    if isinstance(value, (list, tuple)):
        return " ".join(_content(v) for v in value)
    return str(value) if value is not None else ""


def recall(db, text: str, *, limit: int = 15, max_chars: int = 4000,
           until: str | None = None, record_types=None, exclude_ids=()) -> dict:
    require(isinstance(limit, int) and limit > 0, "recall_limit_invalid")
    require(isinstance(max_chars, int) and max_chars >= 256, "recall_budget_invalid")
    require(isinstance(text, str) and bool(text.strip()), "search_text_empty")
    require(record_types is None or (isinstance(record_types, (list, tuple, set, frozenset))
            and bool(record_types) and all(isinstance(item, str) for item in record_types)
            and set(record_types) <= {"source_event", "memory", "pending"}),
            "recall_record_types_invalid")
    require(isinstance(exclude_ids, (list, tuple, set, frozenset))
            and all(isinstance(item, str) for item in exclude_ids), "recall_exclude_ids_invalid")
    wanted = terms(text)
    require(wanted, "search_text_empty")
    cutoff = parse_instant(validate_instant(until, field="until")) if until else None
    sources, admitted = [], set()
    forward_windows = {}
    neighborhood = filters.enabled("recall_neighborhood")
    for event in db.execute("SELECT id, observed_at, data, digest FROM events ORDER BY seq"):
        observed = event["observed_at"]
        if cutoff and (not observed or parse_instant(observed) > cutoff):
            continue
        payload = json.loads(event["data"])
        require(digest(payload) == event["digest"], "evidence_source_digest_mismatch")
        admitted.add(event["id"])
        if neighborhood and isinstance(payload, dict) and isinstance(payload.get("turns"), list):
            forward_windows.update((f"event:{event['id']}#{suffix}", unit)
                                   for suffix, unit in _source_units(payload, neighborhood=True))
        for suffix, unit in _source_units(payload):
            sources.append({"memory_id": "event:" + event["id"] + ("#" + suffix if suffix else ""),
                "record_type": "source_event", "value": unit,
                "source_refs": [event["id"]], "effective_at": observed,
                "classification": "UNKNOWN", "confirmed": False,
                "reason": "quoted_source_observation",
                "source_scope": "dialogue_window" if suffix else "observed_event"})
    candidates = list(sources)
    for row in db.execute("SELECT p.data, i.data AS identity_data FROM projection p "
                          "JOIN identities i USING(memory_id)"):
        item = json.loads(row["data"])
        if not set(item.get("source_refs") or []).issubset(admitted):
            continue
        if cutoff and item.get("valid_from") and parse_instant(item["valid_from"]) > cutoff:
            continue
        classification, reason = filters.classify(item, item["revision"])
        if json.loads(row["identity_data"]).get("merged_into"):
            classification, reason = "HISTORICAL", "merged_into"
        # The legacy class describes the head of ONE declared identity, not
        # truth, current world state, or completeness of a collection.
        identity_classification = classification
        if classification == "CURRENT_CONFIRMED":
            classification, reason = "UNKNOWN", "identity_head_only"
        candidates.append({**item, "record_type": "memory", "confirmed": False,
                           "identity_classification": identity_classification,
                           "classification": classification, "reason": reason})
    for item in pending.listing(db, limit=10000):
        if not set(item.get("source_refs") or []).issubset(admitted):
            continue
        if "semantic_payload" not in item:
            continue
        candidates.append({"memory_id": item["pending_id"], "pending_id": item["pending_id"],
            "record_type": "pending", "entity": item.get("entity"), "slot": item.get("slot"),
            "value": item["semantic_payload"].get("value"), "source_refs": item["source_refs"],
            "classification": "PENDING_BINDING", "confirmed": False, "reason": item["reason"]})
    tokenize = cached_terms if filters.enabled("recall_term_cache") else terms
    bags = [tokenize(_content(item.get("value")) + " " +
                  str(item.get("entity") or "") + " " + str(item.get("slot") or ""))
            for item in candidates]
    wanted = query_terms(text, bags)
    frequency = Counter(term for bag in bags for term in bag)
    def score(index):
        return overlap_weight(wanted & bags[index], frequency, len(bags))
    base_scores = [score(i) for i in range(len(candidates))]
    boosts = expand_scores(candidates, bags, frequency, base_scores)
    ranked = sorted((i for i in range(len(candidates)) if base_scores[i] > 0 or i in boosts),
                    key=lambda i: (-(base_scores[i] + boosts.get(i, 0)), candidates[i]["record_type"] != "source_event",
                                   candidates[i]["memory_id"]))
    if neighborhood:
        ranked = prioritize_linked_observation(ranked, candidates, bags, frequency, base_scores)
    # Eligibility belongs before whole-record budget allocation. Keep the same
    # corpus statistics and ranking so selecting a lane cannot invent relevance.
    excluded = set(exclude_ids)
    ranked = [i for i in ranked if (record_types is None or candidates[i]["record_type"] in record_types)
              and candidates[i]["memory_id"] not in excluded]
    results = [{**candidates[i], "value": forward_windows.get(candidates[i]["memory_id"], candidates[i]["value"])}
               for i in ranked] if forward_windows else [candidates[i] for i in ranked]
    counts = dict(Counter(r["classification"] for r in results))
    packet = assembly.assemble({"results": results, "counts": counts},
                               max_items=limit, max_chars=max_chars)
    packet.update({"retrieval_scope": "ranked_sources_states_and_pending",
                   "state_scope": "identity_revisions_not_world_confirmation",
                   "completeness": "not_established", "policy": POLICY})
    for item in packet["items"]:
        item["source_refs"] = item["evidence"]
    # The serialized packet, including metadata and source references, obeys
    # the same hard budget. Whole records are omitted; no source quote is cut.
    while True:
        size = len(json.dumps(packet, ensure_ascii=False, separators=(",", ":")))
        if size > max_chars:
            require(bool(packet["items"]), "recall_metadata_exceeds_budget")
            packet["items"].pop()
            packet["omitted"] += 1
            packet["truncated"] = True
        elif packet["used_chars"] != size:
            packet["used_chars"] = size
        else:
            return packet
