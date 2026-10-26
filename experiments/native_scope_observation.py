"""Producer declarations and archived observations use the existing source graph."""
from dataclasses import asdict
import json
from pathlib import Path

from wsc.contracts import Event, digest, encode, require
from native_generation_scope import generation_scope


def scope_observation(snapshot, phase, generator_workspace, *, observed_at):
    require(isinstance(observed_at, str) and bool(observed_at.strip()), "scope_observation_time_missing")
    meta = [row["payload"] for row in snapshot.rows if row["type"] == "session_meta"]
    require(len(meta) == 1 and meta[0].get("id") == phase["thread_id"], "scope_observation_thread_mismatch")
    scope = generation_scope(snapshot, phase, generator_workspace)
    turn = scope["source_execution"]["turn_id"]
    matches = [(line, row) for line, row in zip(snapshot.line_numbers, snapshot.rows)
               if row["type"] == "turn_context" and row["payload"].get("turn_id") == turn]
    require(len(matches) == 1, "scope_observation_context_ambiguous")
    line, context = matches[0]
    public = {"schema": "wsc.native_generation_scope_observation/1", "producer": "native_generation_scope",
        "observed_at": observed_at, "scope": scope,
        "fact_kinds": {"generator_workspace": "registered_directory_not_execution_receipt",
                       "source_execution": "archived_observation", "continuation_execution": "registration_status"},
        "evidence": {"rollout_sha256": snapshot.metadata["sha256"], "turn_context_line": line,
                     "turn_context_sha256": digest(context), "native_observed_at": context.get("timestamp")}}
    # No user/developer role or synthetic task instruction is invented. Identity
    # includes observation time, so same-record replay is idempotent while a new
    # observation or registration is a distinct historical fact.
    # The exact source row stays in cold payload, while the producer's public
    # projection omits unrelated native configuration/instruction text.
    payload = {**public, "native_turn_context": json.loads(encode(context))}
    return Event("native-scope:" + digest(payload), "observation", payload,
                 text=encode(public), observed_at=observed_at)


def record_scope(core, snapshot, phase, generator_workspace, *, observed_at):
    event = scope_observation(snapshot, phase, generator_workspace, observed_at=observed_at)
    require(core.store.workspace == str(Path(event.payload["scope"]["source_execution"]["workspace"]).resolve()),
            "scope_observation_task_workspace_mismatch")
    core.ingest([event])
    with core.store.connect() as db:
        row = db.execute("SELECT seq,data FROM events WHERE id=?", (event.id,)).fetchone()
    require(row is not None and json.loads(row["data"]) == json.loads(encode(asdict(event))),
            "scope_observation_record_changed")
    return {"source_id": event.id, "source": f"s{row['seq']}", "record_sha256": digest(asdict(event)),
            "public_value_sha256": digest(json.loads(event.text)), "observed_at": event.observed_at}


def request_scope(material, binding, expected_scope):
    records = [event for event in material["events"] if event["id"] == binding["source_id"]]
    require(len(records) == 1, "scope_observation_source_missing")
    record = records[0]
    require(f"s{record['seq']}" == binding["source"] and record["kind"] == "observation"
            and record["observed_at"] == binding["observed_at"], "scope_observation_binding_changed")
    value = json.loads(record["text"])
    require(value["scope"] == expected_scope and digest(value) == binding["public_value_sha256"],
            "scope_observation_value_changed")
    return {"source": binding["source"]}
