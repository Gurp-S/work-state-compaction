"""Acceptance tests for the capabilities added on top of the V1 core.

Covers: LINK routing, REINTERPRET history correction, Event Group commit units, scope
intersection, the explicit Tree Evolution Controller pass, bounded context assembly and
the WSC event bridge.
"""
from __future__ import annotations

import pytest

from wsc.csm import CSM, CsmStore, Event, MemoryCandidate, MemoryQuery
from wsc.csm import bridge
from wsc.csm.contracts import CSMError


@pytest.fixture
def svc(tmp_path):
    return CSM(CsmStore(tmp_path / "memory.sqlite", namespace="test"))


def _event(svc, event_id="evt_1", **payload):
    svc.ingest([Event(id=event_id, source_type="doc", payload=payload or {"text": "source"})])
    return event_id


def _memory(svc, entity="factory_001", slot="products", value="chopsticks",
            contexts=("project:X",), evidence="evt_1", **extra):
    return svc.remember([MemoryCandidate(entity=entity, slot=slot, value=value,
                                         source_ids=(evidence,), contexts=contexts,
                                         **extra)])[0]


def test_link_intent_creates_typed_edge(svc):
    _event(svc)
    left = _memory(svc)
    right = _memory(svc, entity="factory_003", value="bowls")
    result = svc.remember([MemoryCandidate(entity="factory_001", slot="products", value=None,
                                           source_ids=("evt_1",), contexts=("project:X",),
                                           intent="link", link_kind="PRODUCES",
                                           link_object=right["memory_id"])])[0]
    assert result["operation"] == "LINK"
    assert result["changed"] is True
    edges = svc.relations(f"memory:{left['memory_id']}", kinds=("PRODUCES",))
    assert [edge["object"] for edge in edges] == [f"memory:{right['memory_id']}"]
    assert edges[0]["confirmed"] is False  # a proposal is not a confirmed fact


def test_link_rejects_self_and_unknown_subject(svc):
    _event(svc)
    memory = _memory(svc)
    with pytest.raises(CSMError, match="relation_self"):
        svc.remember([MemoryCandidate(entity="factory_001", slot="products", value=None,
                                      source_ids=("evt_1",), contexts=("project:X",),
                                      intent="link", link_kind="PRODUCES",
                                      link_object=memory["memory_id"])])
    parked = svc.remember([MemoryCandidate(entity="factory_999", slot="products", value=None,
                                           source_ids=("evt_1",), contexts=("project:X",),
                                           intent="link", link_kind="PRODUCES",
                                           link_object=memory["memory_id"])])[0]
    assert parked["operation"] == "DEFER"
    assert parked["reason"] == "identity_unknown"


def test_reinterpret_keeps_memory_and_records_history(svc):
    _event(svc)
    memory = _memory(svc)
    corrected = svc.reinterpret(memory["memory_id"], contexts=("project:Y",),
                                evidence=("evt_1",), reason="the label named the wrong workspace")
    assert corrected["operation"] == "REINTERPRET"
    assert corrected["previous_contexts"] == ["project:x"]
    assert corrected["contexts"] == ["project:y"]
    read = svc.memory(memory["memory_id"], history=True)
    assert read["head_revision"] == 1
    assert read["identity"]["contexts"] == ["project:y"]
    assert read["reinterpretations"][0]["reason"] == "the label named the wrong workspace"
    assert read["reinterpretations"][0]["previous_contexts"] == ["project:x"]


def test_reinterpret_requires_reason_evidence_and_change(svc):
    _event(svc)
    memory = _memory(svc)
    with pytest.raises(CSMError, match="reinterpret_reason_missing"):
        svc.reinterpret(memory["memory_id"], contexts=("project:Y",), evidence=("evt_1",),
                        reason="  ")
    with pytest.raises(CSMError, match="identity_reinterpret_noop"):
        svc.reinterpret(memory["memory_id"], contexts=("project:X",), evidence=("evt_1",),
                        reason="no actual change")
    with pytest.raises(CSMError, match="identity_evidence_missing"):
        svc.reinterpret(memory["memory_id"], contexts=("project:Y",), evidence=(), reason="x")
    with pytest.raises(CSMError, match="evidence_source_unknown"):
        svc.reinterpret(memory["memory_id"], contexts=("project:Y",), evidence=("evt_missing",),
                        reason="x")


def test_reinterpret_conflict_with_live_identity(svc):
    _event(svc)
    _memory(svc, contexts=("project:X",))
    other = _memory(svc, contexts=("project:Y",))
    with pytest.raises(CSMError, match="identity_reinterpret_conflict"):
        svc.reinterpret(other["memory_id"], contexts=("project:X",), evidence=("evt_1",),
                        reason="collides with a live identity")


def test_event_group_commits_certain_members_and_parks_the_rest(svc):
    _event(svc)
    outcome = svc.remember_group([
        MemoryCandidate(entity="factory_001", slot="products", value="chopsticks",
                        source_ids=("evt_1",), contexts=("project:X",), event_group="g1"),
        MemoryCandidate(entity="factory_001", slot="capacity", value="100",
                        source_ids=("evt_1",), contexts=("project:X",), intent="update",
                        event_group="g1")], group_id="g1")
    assert outcome["group"]["status"] == "partial"
    assert len(outcome["group"]["members"]) == 1
    assert len(outcome["group"]["deferred"]) == 1
    assert outcome["results"][0]["operation"] == "create"
    assert outcome["results"][1]["operation"] == "DEFER"
    assert svc.group("g1")["status"] == "partial"
    # A settled group is not re-applied.
    again = svc.remember_group([
        MemoryCandidate(entity="factory_001", slot="products", value="chopsticks",
                        source_ids=("evt_1",), contexts=("project:X",), event_group="g1")],
        group_id="g1")
    assert again["group"]["changed"] is False
    assert [group["group_id"] for group in svc.groups()] == ["g1"]


def test_event_group_rejects_mismatched_member(svc):
    _event(svc)
    with pytest.raises(CSMError, match="event_group_mismatch"):
        svc.remember_group([MemoryCandidate(entity="a", slot="s", value="v",
                                            source_ids=("evt_1",), event_group="other")],
                           group_id="g1")


def test_scope_intersection_reports_axes_without_equivalence(svc):
    _event(svc)
    left = svc.create_node(name="Factory products", scope_description="products of factory",
                           accepted_relations=("PRODUCES",), evidence=("evt_1",))
    right = svc.create_node(name="Factory sales", scope_description="sales of factory",
                            accepted_relations=("ABOUT", "PRODUCES"), evidence=("evt_1",))
    memory = _memory(svc)
    svc.mount(memory["memory_id"], node_id=left["node_id"], relation="PRODUCES",
              allow_candidate=True)
    result = svc.scope_intersection(left["node_id"], right["node_id"])
    assert result["axes"]["relations"]["shared"] == ["PRODUCES"]
    assert result["axes"]["coverage"]["left"] == 1
    assert result["axes"]["coverage"]["right"] == 0
    assert result["axes"]["coverage"]["jaccard"] == 0.0
    assert result["semantic_equivalence"] is False
    assert result["note"] == "coverage_overlap_is_not_semantic_equivalence"


def test_evolve_mounts_unmounted_identity_and_is_idempotent(svc):
    _event(svc)
    _memory(svc)
    first = svc.evolve()
    assert first["changed"] is True
    assert {"action": "mount", "memory_id": "factory_001:products@project_x",
            "node_id": first["actions"][0]["node_id"], "changed": True} == first["actions"][0]
    paths = svc.paths("factory_001:products@project_x")
    assert paths and paths[0]["node_id"] == first["actions"][0]["node_id"]
    second = svc.evolve()
    assert second["changed"] is False
    assert second["actions"] == []


def test_evolve_promotes_candidate_with_contract_and_coverage(svc):
    _event(svc)
    first = _memory(svc)
    second = _memory(svc, entity="factory_002", value="bowls")
    node = svc.create_node(name="Factory products", scope_description="factory products",
                           accepted_relations=("PRODUCES",), evidence=("evt_1",))
    for memory in (first, second):
        svc.mount(memory["memory_id"], node_id=node["node_id"], relation="PRODUCES",
                  allow_candidate=True)
    outcome = svc.evolve()
    assert any(action["action"] == "promote" and action["changed"]
               for action in outcome["actions"])
    assert svc.tree()["nodes"][0]["node_id"] == "MemorySpace"
    promoted = [item for item in svc.tree()["nodes"] if item["node_id"] == node["node_id"]][0]
    assert promoted["status"] == "active"


def test_evolve_resolves_parked_mount_once_one_candidate_remains(svc):
    _event(svc)
    memory = _memory(svc)
    left = svc.create_node(name="Entity left", node_type="entity",
                           entity_anchor="factory_001", evidence=("evt_1",))
    right = svc.create_node(name="Entity right", node_type="entity",
                            entity_anchor="factory_001", evidence=("evt_1",))
    parked = svc.mount(memory["memory_id"], candidates=(left["node_id"], right["node_id"]),
                       evidence=("evt_1",))
    assert parked["pending_id"]
    svc.retire_node(right["node_id"], evidence=("evt_1",))
    outcome = svc.evolve()
    resolved = [action for action in outcome["actions"] if action["action"] == "resolve_mount"]
    assert resolved and resolved[0]["node_id"] == left["node_id"]
    assert svc.paths(memory["memory_id"])[0]["node_id"] == left["node_id"]


def test_assemble_respects_budget_and_reports_omissions(svc):
    _event(svc)
    for index in range(3):
        _memory(svc, entity=f"factory_{index:03d}", value=f"value {index}",
                topics=("items",))
    bounded = svc.assemble(MemoryQuery(topics=("items",)), max_items=1)
    assert len(bounded["items"]) == 1
    assert bounded["omitted"] == 2
    assert bounded["truncated"] is True
    assert bounded["items"][0]["evidence"] == ["evt_1"]
    tiny = svc.assemble(MemoryQuery(topics=("items",)), max_chars=50)
    assert tiny["items"] == [] and tiny["omitted"] == 3
    with pytest.raises(CSMError, match="assembly_budget_invalid"):
        svc.assemble(MemoryQuery(topics=("items",)), max_chars=0)


def test_wsc_bridge_is_stable_and_idempotent(svc):
    event = bridge.from_wsc_event({"id": "w1", "type": "chat", "payload": {"text": "hi"},
                                   "ts": "2026-01-01T00:00:00Z", "session": "s1"})
    assert event.id == "wsc:w1"
    assert event.source_type == "wsc:chat"
    assert event.observed_at == "2026-01-01T00:00:00Z"
    assert event.metadata == {"session": "s1"}
    assert bridge.from_wsc_event({"id": "w2", "ts": 123}).observed_at is None
    with pytest.raises(CSMError, match="wsc_event_id_missing"):
        bridge.from_wsc_event({"payload": {}})
    first = svc.ingest_wsc([{"id": "w1", "type": "chat", "payload": {"text": "hi"}}])
    second = svc.ingest_wsc([{"id": "w1", "type": "chat", "payload": {"text": "hi"}}])
    assert first["ingested"] == ["wsc:w1"]
    assert second["existing"] == ["wsc:w1"]
