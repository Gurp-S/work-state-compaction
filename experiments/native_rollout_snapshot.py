"""Parse and archive exactly one byte observation of a native JSONL rollout."""
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class RolloutSnapshot:
    rows: list
    line_numbers: list[int]
    metadata: dict


def parse_rollout(raw, *, exists=True):
    rows, line_numbers = [], []
    parts = raw.split(b"\n")
    tail_status = "terminated" if not parts[-1].strip() else "complete_unterminated"
    for line, data in enumerate(parts, 1):
        if not data.strip():
            continue
        try:
            value = json.loads(data.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if line == len(parts):
                tail_status = "incomplete_or_invalid"
                break
            raise ValueError(f"rollout_record_invalid:line={line}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise ValueError(f"rollout_record_shape_invalid:line={line}")
        rows.append(value)
        line_numbers.append(line)
    return RolloutSnapshot(rows, line_numbers, {
        "sha256": sha256(raw).hexdigest(), "byte_length": len(raw), "exists": exists,
        "tail_status": tail_status, "parse_complete": exists and tail_status != "incomplete_or_invalid",
        "records": len(rows), "snapshot_scope": "single_read_bytes_not_cross_file_atomic"})


def capture_rollout(path, *, archive=None):
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return parse_rollout(b"", exists=False)
    if archive is not None:
        archive = Path(archive)
        archive.parent.mkdir(parents=True, exist_ok=True)
        # Preserve invalid bytes too. Parsing/accounting never observes a later read.
        with archive.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return parse_rollout(raw)
