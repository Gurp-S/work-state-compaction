"""Explicit native checkpoint conversion, not an in-process Codex compaction hook."""
from copy import deepcopy
import json

from ..contracts import Event, digest, encode, identifier, require
from ..passage import render as render_passage


def public_text(item: dict) -> str | None:
    kind = item.get("type")
    if kind == "message":
        content = item.get("content")
        require(isinstance(content, list), "native_message_content_invalid")
        parts = [part["text"] for part in content if isinstance(part, dict)
                 and part.get("type") in {"input_text", "output_text"} and isinstance(part.get("text"), str)]
        return "\n".join(parts) if parts else None
    if kind in {"function_call", "custom_tool_call"}:
        return encode({k: item[k] for k in ("name", "arguments", "input") if k in item})
    if kind in {"function_call_output", "custom_tool_call_output"}:
        output = item.get("output")
        return output if isinstance(output, str) else encode(output)
    return None


class CodexCheckpointAdapter:
    @staticmethod
    def capabilities() -> dict:
        return {"adapter": "codex_checkpoint_v1", "boundary": "explicit_checkpoint_recovery",
                "transparent_native_compaction": False, "opaque_prefix": "archive_only",
                "installation": "host_callback_required", "token_capacity": "host_checked"}

    def import_items(self, items: list[dict], *, thread_id: str, start_ordinal=0,
                     observed_at=None) -> list[Event]:
        identifier(thread_id)
        require(type(start_ordinal) is int and start_ordinal >= 0, "native_ordinal_invalid")
        require(isinstance(items, list), "native_items_invalid")
        require(observed_at is None or (isinstance(observed_at, (list, tuple)) and
                len(observed_at) == len(items) and all(t is None or isinstance(t, str) for t in observed_at)),
                "native_observation_times_invalid")
        result = []
        for ordinal, item in enumerate(items, start_ordinal):
            require(isinstance(item, dict), "native_item_invalid")
            native_type = item.get("type")
            role, call_id = None, None
            if native_type == "message":
                role = item.get("role")
                require(role in {"system", "developer", "user", "assistant"}, "native_role_unsupported")
                kind = "message"
            elif native_type in {"function_call", "custom_tool_call"}:
                kind, call_id = "call", identifier(item.get("call_id"))
            elif native_type in {"function_call_output", "custom_tool_call_output"}:
                kind, call_id = "result", identifier(item.get("call_id"))
            elif native_type in {"reasoning", "compaction"}:
                kind = "opaque"
            else:
                require(False, "native_item_type_unsupported")
            result.append(Event(id=f"native:{thread_id}:{ordinal}:{digest(item)}", kind=kind,
                                payload=deepcopy(item), role=role, call_id=call_id,
                                text=public_text(item),
                                observed_at=observed_at[ordinal-start_ordinal] if observed_at is not None else None,
                                control=role in {"user", "system", "developer"}))
        return result

    def render(self, body, sources, cut, locators, *, source_index, understanding_index):
        # The tail remains byte-value equivalent. In-flight calls stay in the host;
        # this checkpoint adapter deliberately refuses to interrupt their protocol.
        pending = set()
        for row in sources:
            if row["kind"] == "call":
                pending.add(row["call_id"])
            elif row["kind"] == "result":
                pending.discard(row["call_id"])
        require(not pending, "checkpoint_requires_idle_tools")
        body = body or {"sources": [], "understandings": [], "clues": []}
        control = [row["text"] for row in body["sources"]
                   if row["kind"] == "message" and row.get("control") and row.get("text")]
        ledger = [{"kind": r["kind"], "text": r["text"]} for r in body["understandings"]]
        index = [{"key": row["key"], "source_id": row["source_id"], "message": row["message"],
                  "label": row["gist"], "terms": row.get("terms", []), "text": row["text"]}
                 for row in _evidence_index(body["sources"], body.get("excerpts"), locators)]
        passage = render_passage(control=control, ledger=ledger, index=index)
        if not passage:
            return []
        # One model-visible view: control + ledger + discovery index. Package
        # locators, archive paths and hashes stay host-side.
        items = [{"type": "message", "role": "assistant", "phase": "commentary",
                  "content": [{"type": "output_text", "text": passage}]}]
        items.extend(deepcopy(row["payload"]) for row in sources if row["seq"] > cut)
        return items


def _label(row: dict) -> tuple:
    """Kind and one-line gist for discovery; bytes are fetched from the cold store."""
    text = (row.get("text") or "").strip()
    first = next((line.strip() for line in text.split("\n") if line.strip()), "")[:72]
    payload = row.get("payload") or {}
    name = payload.get("name")
    if row.get("kind") == "call" and name in ("edit", "write"):
        args = payload.get("arguments")
        try:
            args = args if isinstance(args, dict) else json.loads(args or "{}")
        except ValueError:
            args = {}
        path = next((args.get(key) for key in ("path", "file_path", "target_file")
                     if isinstance(args.get(key), str)), "")
        return "edit", f"edit {path}".strip()
    if row.get("kind") == "result":
        lowered = text.lower()
        if any(word in lowered for word in ("error", "exception", "failed", "traceback")):
            return "error", f"error {first}"
        return "result", f"result {first}"
    if row.get("kind") == "message" and row.get("control"):
        return "control", "control message"
    return "note", f"note {first}"


def _evidence_index(rows: list, excerpts, locators: dict) -> list:
    index = []
    for row in rows:
        if row["kind"] == "message":
            continue
        kind, gist = _label(row)
        if row["id"] in locators:
            index.append({"key": f"E{len(index) + 1}", "kind": kind, "gist": gist,
                      "source_id": row["id"], "message": row.get("seq", 0),
                      "text": row.get("text") or "", "terms": []})
        if len(index) >= 16:
            break
    for item in excerpts or []:
        if len(index) >= 16:
            break
        text = (item.get("text") or "").strip()
        gist = next((line.strip() for line in text.split("\n") if line.strip()), "")[:72]
        index.append({"key": f"E{len(index) + 1}", "kind": "excerpt", "gist": gist,
                      "source_id": item.get("source_id"), "message": 0,
                      "text": text, "terms": []})
    return index
