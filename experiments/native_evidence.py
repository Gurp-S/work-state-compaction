"""Read native rollout evidence without importing the historical WSC runtime."""
from hashlib import sha256
import json
from pathlib import Path
from native_rollout_snapshot import capture_rollout
from native_history_projection import project_items

FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
          "output_tokens", "reasoning_output_tokens", "total_tokens")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False).encode("utf-8")).hexdigest()


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def manifest(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): file_hash(p)
            for p in sorted(root.rglob("*")) if p.is_file()
            and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def python_manifest(root):
    return {p: h for p, h in manifest(root).items() if p.startswith("python/") and p.endswith(".py")}


def records(path):
    # Provisional readers use valid records; final accounting also checks metadata.
    return capture_rollout(path).rows


def usage(rows, thread_id, *, line_numbers=None):
    by_id, duplicate_ids, compactor_ids = {}, [], []
    for line, row in zip(line_numbers if line_numbers is not None else range(1, len(rows) + 1), rows):
        if row["type"] == "token_usage_record":
            payload = row["payload"]
            if payload["thread_id"] != thread_id:
                raise ValueError("usage_thread_identity_mismatch")
            rid, value = payload["response_id"], payload["usage"]
            if not rid or any(type(value.get(k)) is not int or value[k] < 0 for k in FIELDS):
                raise ValueError("usage_unknown_or_invalid")
            if value["cached_input_tokens"] > value["input_tokens"]:
                raise ValueError("usage_cached_exceeds_input")
            if rid in by_id:
                if by_id[rid]["usage"] != value:
                    raise ValueError("usage_conflicting_response_identity")
                duplicate_ids.append(rid)
            else:
                by_id[rid] = {"response_id": rid, "rollout_line": line, "usage": value}
        elif row["type"] == "compacted":
            compactor_ids.append(row["payload"].get("compaction_response_id"))
    if any(not rid or rid not in by_id for rid in compactor_ids):
        raise ValueError("compaction_usage_binding_unknown")
    if len(set(compactor_ids)) != len(compactor_ids):
        raise ValueError("compaction_response_reused")
    receipts = list(by_id.values())
    total = lambda values: {k: sum(v["usage"][k] for v in values) for k in FIELDS}
    return {"thread_id": thread_id, "response_count": len(receipts),
            "response_receipts": receipts, "duplicate_receipt_ids": duplicate_ids,
            "compactor_response_ids": compactor_ids,
            "all_usage": total(receipts),
            "compaction_usage": total([by_id[rid] for rid in compactor_ids]),
            "cash": None, "price_status": "unknown"}


def state(rows):
    return project_items(rows)


def contains_sequence(actual, expected):
    """Exact protocol values, contiguous order, including envelope identities."""
    return any(actual[i:i + len(expected)] == expected
               for i in range(len(actual) - len(expected) + 1))


def import_evidence(actual, expected):
    """Allow only observed native additions; supplied fields remain immutable.

    Native serialization adds content:null to opaque reasoning, and transport
    identity/metadata to messages without those fields. Opaque bytes are never
    decoded or interpreted, and supplied identity fields must still match.
    """
    for start in range(len(actual) - len(expected) + 1):
        additions = []
        for ordinal, (observed, supplied) in enumerate(zip(actual[start:], expected)):
            if any(k not in observed or observed[k] != v for k, v in supplied.items()):
                break
            extra = set(observed) - set(supplied)
            allowed = {"id", "internal_chat_message_metadata_passthrough"} if supplied.get("type") == "message" else set()
            if supplied.get("type") == "reasoning" and observed.get("content") is None:
                allowed.add("content")
            if not extra <= allowed:
                break
            if extra:
                additions.append({"ordinal": ordinal, "fields": sorted(extra),
                    "supplied_sha256": digest(supplied), "observed_sha256": digest(observed)})
        else:
            return {"matched": True, "start_ordinal": start, "native_added_fields": additions,
                    "supplied_fields_unchanged": True, "exact_sequence": not additions}
    return {"matched": False, "supplied_fields_unchanged": False}
