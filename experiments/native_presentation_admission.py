"""Offline admission for the factual view before any native model request."""
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.contracts import require
from wsc.events import rows
from wsc.snapshots import view_record


def presentation_evidence(core, view_id, package, resolved):
    with core.store.connect() as db:
        view = view_record(db, view_id)
        sources = rows(db)
    body = view["body"]
    body["excerpt_locators"] = package.get("excerpt_evidence", {})
    legacy = CodexCheckpointAdapter().render(body, sources, view["binding"]["cut"], package["evidence"],
        source_index=package["source_index"], understanding_index=package["understanding_index"])
    actual = package["items"]
    index = sum(row["kind"] == "message" for row in body["sources"])
    require(legacy[:index] == actual[:index] and legacy[index+1:] == actual[index+1:],
            "presentation_changed_controls_or_tail")
    before, after = legacy[index]["content"][0]["text"], actual[index]["content"][0]["text"]
    require(all(e["text"] in after for e in resolved), "presentation_observation_missing")
    require(all(r["text"] in after for r in body["understandings"]), "presentation_understanding_missing")
    require(all(locator["file_path"] in after for locator in package.get("excerpt_evidence", {}).values()),
            "presentation_excerpt_locator_missing")
    reduction = 1 - len(after) / len(before)
    require(reduction >= .2, "presentation_size_gate_failed")
    return {"controls_and_tail_unchanged": True, "observation_and_understanding_texts_preserved": True,
            "excerpt_paths_visible": True, "legacy_chars": len(before), "candidate_chars": len(after),
            "reduction": reduction, "package_digest": package["package_digest"],
            "scope": "offline_presentation_not_semantic_benefit"}
