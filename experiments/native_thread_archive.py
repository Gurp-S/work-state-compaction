"""Every opened native thread has an archive observation or an explicit gap."""
from pathlib import Path

from native_evidence import file_hash, usage
from native_rollout_snapshot import capture_rollout


def archive_threads(area, opened):
    evidence = {}
    for name, value in opened.items():
        destination = Path(area) / "native-rollout-archive" / (name + ".jsonl")
        try:
            snapshot = capture_rollout(value["thread"]["path"], archive=destination)
            if not snapshot.metadata["exists"]:
                evidence[name] = {"accounting_error": "rollout_missing", "sha256": None,
                                  "known_response_count": None}
                continue
            receipt = usage(snapshot.rows, value["thread"]["id"], line_numbers=snapshot.line_numbers)
            evidence[name] = {"receipts": receipt, "sha256": snapshot.metadata["sha256"],
                              "rollout_snapshot": snapshot.metadata}
            if not snapshot.metadata["parse_complete"]:
                evidence[name]["accounting_error"] = "rollout_incomplete"
        except Exception as exc:
            evidence[name] = {"accounting_error": str(exc), "sha256": None}
            try:
                if destination.exists():
                    evidence[name]["sha256"] = file_hash(destination)
            except OSError as read_error:
                evidence[name]["archive_read_error"] = type(read_error).__name__
    return evidence
