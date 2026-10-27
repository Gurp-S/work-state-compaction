"""Rule registry and the shared byte accounting.

A rule is a module exposing ID, REVERSIBLE and apply(rows) -> (rows, actions).
Rules never touch control rows (role user/system/developer or control=True) and
never change id, kind, call_id or role; they only rewrite payload and text.
"""
from dataclasses import dataclass
from hashlib import sha256
import importlib

from ..contracts import encode, require


REVERSIBLE = {"exact", "pointer", "lossy"}


@dataclass(frozen=True)
class Action:
    rule: str
    source_id: str
    before_bytes: int
    after_bytes: int
    pointer: dict | None

    @property
    def saved(self) -> int:
        return self.before_bytes - self.after_bytes


def size(value) -> int:
    return len(encode(value).encode("utf-8"))


def row_size(row: dict) -> int:
    return size({"payload": row.get("payload"), "text": row.get("text")})


def content_sha256(row: dict) -> str:
    return sha256(encode({"payload": row.get("payload"), "text": row.get("text")}).encode("utf-8")).hexdigest()


def is_control(row: dict) -> bool:
    return row.get("control") is True or row.get("role") in {"system", "developer", "user"}


def pointer_for(row: dict, rule: str) -> dict:
    return {"rule": rule, "source_id": row["id"], "content_sha256": content_sha256(row),
            "recover": "source_read"}


def replace(row: dict, *, payload=None, text=None) -> dict:
    """Copy a row with a rewritten payload or text; identity fields are preserved."""
    result = dict(row)
    if payload is not None:
        result["payload"] = payload
    if text is not None:
        result["text"] = text
    return result


RULE_ORDER = ("strip_noise_lines", "collapse_stack", "diff_digest", "dedupe_identical",
              "dedupe_reads", "outline_json", "truncate_head_tail")


def load(name: str):
    module = importlib.import_module(f".{name}", __package__)
    require(getattr(module, "REVERSIBLE") in REVERSIBLE, "denoise_rule_reversibility_invalid")
    return module


def RULES() -> dict:
    return {name: load(name) for name in RULE_ORDER}


def apply_rules(rows, rule_ids=None, *, rules=None) -> tuple[list[dict], list[Action]]:
    """Run the requested rules in a fixed order; control rows pass through untouched."""
    table = rules if rules is not None else RULES()
    requested = list(rule_ids) if rule_ids is not None else list(RULE_ORDER)
    require(all(name in table for name in requested), "denoise_rule_unknown")
    current = list(rows)
    actions: list[Action] = []
    for name in RULE_ORDER:
        if name not in requested:
            continue
        current, produced = table[name].apply(current)
        actions.extend(produced)
    return current, actions
