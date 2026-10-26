"""One metered generation probe; no task continuation, B/C pair, or retry.

The source is the already archived pre-repair history. The model selects its
own observations; no hand-authored selection or required-observation list is
supplied. This does not establish continuation quality or automatic net value.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from wsc import WSC, Store, Limits, Usage
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import WSCError, require
from wsc.publication import check_evidence
from wsc.quote_selection import QuoteSelectionGenerator, SelectionDraft
from wsc.span_selection_facts import FULL_SOURCE_EFFECT, SPAN_EFFECT
from native_evidence import read, save, file_hash, manifest, digest
from native_rollout_snapshot import capture_rollout
from native_rpc import NativeRPC
from native_thread_archive import archive_threads
from run_native_pair import MODEL, SETTINGS, initialize, phase, verify_pins, audit_host


def output_schema(material=None, selection_format="quote"):
    string = {"type": "string"}
    strings = {"type": "array", "items": string}
    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties),
                "additionalProperties": False}
    schema = obj({"source_ids": strings, "understanding_refs": strings,
        "new_understandings": {"type": "array", "items": obj({"text": string, "kind": string,
                                                                  "sources": strings})},
        "clues": {"type": "array", "items": obj({"text": string, "sources": strings})},
        "quotes": {"type": "array", "items": obj({"key": string, "source_id": string,
            "text": {"type": "string", "description": "Exact unique substring of this source's offered text."}})}})
    if selection_format == "span":
        schema['properties']['source_ids'] = {**schema['properties']['source_ids'], 'description': FULL_SOURCE_EFFECT}
        refs = [span["ref"] for event in material["events"] for span in event["spans"]]
        schema["properties"].pop("quotes")
        schema["properties"]["span_refs"] = {"type": "array", "items":
            {"type": "string", "enum": refs} if refs else {"type": "string"},
            "description": SPAN_EFFECT,
            **({} if refs else {"maxItems": 0})}
        schema["required"] = list(schema["properties"])
    return schema


class SchemaServer:
    """Apply the verified per-turn schema to the existing bounded phase reader."""
    def __init__(self, server, schema=None):
        self.server = server
        self.schema = schema if schema is not None else output_schema()

    def call(self, method, params, **kwargs):
        if method == "turn/start":
            params = {**params, "outputSchema": self.schema}
        return self.server.call(method, params, **kwargs)

    def event(self, **kwargs):
        return self.server.event(**kwargs)

    def send(self, value):
        return self.server.send(value)


def run(source_path, origin_registration, executable, area, *, view_budget_bytes=32768,
        include_selection_facts=False, selection_format="quote"):
    require(selection_format in {"quote", "span"}, "selection_format_invalid")
    area.mkdir(parents=True, exist_ok=False)
    source, original = read(source_path), read(origin_registration)
    require(file_hash(source["rollout_path"]) == source["rollout_sha256"], "source_rollout_changed")
    snapshot = capture_rollout(source["rollout_path"])
    history = [r for r in snapshot.rows if r["type"] == "response_item"]
    require(snapshot.metadata["parse_complete"] and [r["payload"] for r in history] == source["items"],
            "source_boundary_changed")
    require(len(history) == 20 and source["items"][-1].get("phase") == "final_answer",
            "pre_repair_boundary_required")
    for folder in ("workspace", "frozen-workspace", "generation"):
        (area / folder).mkdir()
    core = WSC(Store(area / "state.db", session_id=area.name, workspace=str(area / "workspace")),
               access=lambda *args: True)
    batch = CodexCheckpointAdapter().import_items(source["items"], thread_id=source["thread_id"],
        observed_at=[r.get("timestamp") for r in history])
    core.ingest(batch)
    core.presented("archived-diagnostic-presentation", tuple(e.id for e in batch if e.kind == "result"),
                   receiver="historical_native_diagnostic:" + source["thread_id"])
    captured = core.capture()
    save(area / "original-material.json", core.material(captured))
    pins = [source_path, origin_registration, Path(source["rollout_path"]), executable,
            *HERE.glob("*.py"), *(HERE.parent / "src").rglob("*.py")]
    config = Path.home() / ".codex/config.toml"
    if config.exists():
        pins.append(config)
    reg = {"origin": str(area), "workspace": str(area / "workspace"), "initial_manifest": {},
        "pins": {str(p.resolve()): file_hash(p) for p in pins},
        "registered_utc": datetime.now(timezone.utc).isoformat(), "model": MODEL, "effort": "max",
        "purpose": "automatic_selection_generation_only", "source_items_sha256": digest(source["items"]),
        "response_cap": 2, "wall_seconds": 180, "retries": 0,
        "view_budget_bytes": view_budget_bytes, "include_selection_facts": include_selection_facts,
        "selection_format": selection_format, "span_max_chars": 1024 if selection_format == "span" else None,
        "native_comparison": False, "source_semantics": "historical_pre_repair_only",
        "generation_workspace": "empty_read_only_no_task_execution", "cash": None}
    save(area / "registration.json", reg)
    opened = {}
    result = {"status": "not_started", "generation_cost": "unknown", "semantic_review": "pending"}

    def generate(material):
        save(area / "offered-material.json", material)
        schema = output_schema(material, selection_format)
        save(area / "output-schema.json", schema)
        request = {"operation": "working_state_selection", "task_request": original["continuation_request"],
            "source_status": "Archived observations before the task repair; source selection only, no current task execution.",
            "output_contract": {"source_ids": "Original public events selected for the view, by offered id.",
                "understanding_refs": "Existing model records selected by exact ref.",
                "new_understandings": "Model-authored working understanding with its source handles; revisable and semantically unverified.",
                "clues": "Model-selected discovery text with source handles.",
                "quotes": "Model-selected exact unique substrings of offered event text; hashes and offsets are computed outside the model."},
            "material": material}
        if selection_format == "span":
            request["output_contract"].pop("quotes")
            request["output_contract"]["span_refs"] = "Selected offered content-bound span identities; their exact original text and source bindings are copied by the runtime."
        request_text = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        save(area / "generation-request.json", request)
        phase_reg = {**reg, "shared_request": request_text}
        with NativeRPC(executable, cwd=reg["workspace"], stderr_path=area / "stderr.txt",
                       settings=SETTINGS) as server:
            save(area / "initialize.json", initialize(server))
            save(area / "quota-before.json", server.call("account/rateLimits/read", {}))
            value = server.call("thread/start", {"cwd": reg["workspace"], "model": MODEL,
                "allowProviderModelFallback": False, "approvalPolicy": "never", "sandbox": "read-only",
                "runtimeWorkspaceRoots": [reg["workspace"]], "ephemeral": False, "dynamicTools": []}, timeout=40)
            opened["generation"] = value
            save(area / "thread-start.json", value)
            try:
                require(value["model"] == MODEL and value.get("reasoningEffort") == "max"
                        and value["sandbox"]["type"] == "readOnly", "generation_configuration_mismatch")
                # The retained phase cap is ten minus already-spent responses.
                outcome = phase(SchemaServer(server, schema), value, phase_reg, area / "generation", None,
                                time.monotonic() + reg["wall_seconds"], spent_responses=8)
            finally:
                save(area / "thread-archive.json", archive_threads(area, opened))
        known = Usage()
        if outcome.get("usage_complete"):
            totals = outcome["receipts"]["all_usage"]
            known = Usage(totals["input_tokens"] - totals["cached_input_tokens"],
                          totals["cached_input_tokens"], totals["output_tokens"])
        result["generation_cost"] = asdict(known)
        try:
            require(outcome.get("usage_complete"), "generation_usage_unknown")
            require(outcome["completed"] and not outcome["failure"] and len(outcome["finals"]) == 1,
                    "generation_turn_incomplete")
            require(outcome["receipts"]["response_count"] <= reg["response_cap"], "generation_response_cap_exceeded")
            audit_host(area / "generation")
            draft = json.loads(outcome["finals"][0]["text"])
            save(area / "model-draft.json", draft)
            verify_pins(reg)
            require(manifest(area / "workspace") == {}, "generation_workspace_changed")
            return SelectionDraft(draft, known)
        except Exception as exc:
            exc.usage = known
            raise

    try:
        selector = QuoteSelectionGenerator(generate)
        if selection_format == "span":
            from wsc.span_selection import SpanSelectionGenerator
            selector = SpanSelectionGenerator(generate)
        view = core.generate(captured, selector, producer="native_model:" + MODEL,
                            limits=Limits(max_view_bytes=view_budget_bytes),
                            include_selection_facts=include_selection_facts)
        operation = core.stage(view, directory=area / "exports", adapter=CodexCheckpointAdapter())
        package = core.package(operation)
        check_evidence(core, package)
        save(area / "package.json", package)
        result.update(status="generated_compiled_exported", view=view, operation=operation,
            exact_quotes=len(package.get("excerpt_evidence", {})),
            item_text_characters=sum(len(json.dumps(i, ensure_ascii=False)) for i in package["items"]),
            source_count=len(batch), source_times_preserved=True, installation="not_performed")
    except Exception as exc:
        result.update(status="failed_preserved_no_retry", error=type(exc).__name__ + ":" + str(exc))
    finally:
        result["wsc_status"] = core.status()
        save(area / "result.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "wsc_status"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--origin-registration", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--view-budget-bytes", type=int, default=32768)
    parser.add_argument("--selection-facts", action="store_true")
    parser.add_argument("--selection-format", choices=("quote", "span"), default="quote")
    args = parser.parse_args()
    run(args.source.resolve(), args.origin_registration.resolve(), args.executable.resolve(), args.output.resolve(),
        view_budget_bytes=args.view_budget_bytes, include_selection_facts=args.selection_facts,
        selection_format=args.selection_format)
