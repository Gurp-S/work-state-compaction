"""State bundle publication: the model receives state, not only raw turns."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_csm_source_inspection import MemoryStore
from wsc.csm import CSM, CsmStore, Event, MemoryCandidate
from wsc.csm.cem.commitment_ingestion import CommitmentDraft, stage_commitment
from wsc.csm.cem.commitment_projection import PROPERTY_KEY
from wsc.csm.cem.entity_registry import EntityRegistry
from wsc.csm.cem.property_journal import PropertyJournal
from wsc.csm.cem.semantic_contract import PropertySpec, SourceSpan
from wsc.csm.cem.state_bundle import build_state_bundle, render_state_items

CLOCK = "2026-11-13T22:00:00+08:00"


class StateBundleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.core = CSM(CsmStore(Path(directory.name) / "memory.db", namespace="user:lea"),
                        clock=lambda: CLOCK)
        self.core.ingest([
            Event("chat/1", "chat", {"user": "一诺生日下个月3号", "assistant": "好"},
                  observed_at="2026-11-01T10:00:00+08:00"),
            Event("chat/2", "chat", {"user": "我是阳历4月17", "assistant": "记下了"},
                  observed_at="2026-11-13T21:00:00+08:00"),
        ])
        self.core.remember([
            MemoryCandidate("一诺", "生日", "12月3日", source_ids=("chat/1",)),
            MemoryCandidate("用户", "生日", "4月17日", source_ids=("chat/2",)),
        ])

    def test_clock_and_entities_are_published_together(self):
        bundle = build_state_bundle(
            self.core, now=CLOCK, source_until=CLOCK,
            visible_source_ids={"chat/1", "chat/2"}, question="我生日是哪天",
        )
        self.assertEqual("CLOCK", bundle["items"][0]["kind"])
        self.assertIn("【当前时间】", bundle["text"])
        self.assertIn("用户 / 生日 = 4月17日", bundle["text"])
        self.assertIn("一诺 / 生日 = 12月3日", bundle["text"])
        self.assertNotIn("用户 / 生日 = 12月3日", bundle["text"])
        self.assertEqual((1, 2), bundle["turns"])
        self.assertTrue(all("kind" in item and "text" in item for item in bundle["items"]))

    def test_empty_state_still_publishes_the_clock(self):
        core = CSM(CsmStore(Path(tempfile.mkdtemp()) / "empty.db", namespace="user:lea"))
        bundle = build_state_bundle(
            core, now=CLOCK, source_until=CLOCK, visible_source_ids=(), question="今天几号",
        )
        self.assertIn(f"【当前时间】{CLOCK}", bundle["text"])
        self.assertEqual("CLOCK", bundle["items"][0]["kind"])
        self.assertIn("NO_CONFIRMED_STATE", [item["kind"] for item in bundle["items"]])
        self.assertEqual((), bundle["turns"])

    def test_revision_state_uses_visible_sources_before_resolving_same_clock_versions(self):
        stamp = '2026-11-13T21:00:00+08:00'
        self.core.ingest([
            Event('chat/3', 'chat', {'user': '账本标签以前说是木头。'}, observed_at=stamp),
            Event('chat/4', 'chat', {'user': '更正，账本标签是黄铜。'}, observed_at=stamp),
        ])
        base = self.core.remember([MemoryCandidate(
            '用户', '账本标签材质', '木头', source_ids=('chat/3',), valid_from=stamp)])[0]
        self.core.remember_explicit(MemoryCandidate(
            '用户', '账本标签材质', '黄铜', source_ids=('chat/4',), valid_from=stamp, expected_revision=1),
            operation='replace', target_memory_id=base['memory_id'], binding_source_ids=('chat/4',))
        def bundle(visible, max_chars=1200):
            return build_state_bundle(self.core, now=CLOCK, source_until=stamp, visible_source_ids=visible,
                                      question='账本标签是什么材质', revision_state=True, max_chars=max_chars)['items']
        self.assertEqual([('CURRENT_CONFIRMED', '木头', (3,))],
                         [(i['kind'], i['value'], i['source_turns']) for i in bundle({'chat/3'})[1:]])
        visible = {'chat/3', 'chat/4'}
        full = bundle(visible)
        self.assertEqual([('CURRENT_CONFIRMED', '黄铜', (4,)), ('HISTORICAL', '木头', (3,))],
                         [(i['kind'], i['value'], i['source_turns']) for i in full[1:]])
        current_only = bundle(visible, len(render_state_items(full[:2])))
        self.assertEqual('黄铜', current_only[1]['value'])
        self.assertEqual('state_budget', current_only[1]['history_omitted'])
        older_only_budget = len(render_state_items([full[0], full[2]]))
        self.assertEqual(['CLOCK', 'NO_CONFIRMED_STATE'],
                         [i['kind'] for i in bundle(visible, older_only_budget)])

    def test_separate_declared_scopes_can_hold_different_current_values(self):
        self.core.ingest([
            Event('chat/3', 'chat', {'user': '工作室门牌是黄铜。'}, observed_at=CLOCK),
            Event('chat/4', 'chat', {'user': '家里的门牌是木头。'}, observed_at=CLOCK),
        ])
        self.core.remember([
            MemoryCandidate('用户', '门牌材质', '黄铜', contexts=('工作室',), source_ids=('chat/3',)),
            MemoryCandidate('用户', '门牌材质', '木头', contexts=('家里',), source_ids=('chat/4',)),
        ])
        for revision_state in (False, True):
            bundle = build_state_bundle(
                self.core, now=CLOCK, source_until=CLOCK, visible_source_ids={'chat/3', 'chat/4'},
                question='两处的门牌材质', revision_state=revision_state)
            items = bundle['items'][1:]
            self.assertTrue(all(item['kind'] == 'CURRENT_CONFIRMED' for item in items))
            self.assertEqual({(('工作室',), '黄铜'), (('家里',), '木头')},
                             {(item['contexts'], item['value']) for item in items})


class DueStateTests(unittest.TestCase):
    def test_reviewed_commitment_is_published_as_due(self):
        store = MemoryStore()
        self.addCleanup(store.db.close)
        core = CSM(store, clock=lambda: "2026-01-03T00:00:00Z")
        core.ingest([Event("chat/1", "chat", {"user": "资料后天到，到了我去拿"},
                          observed_at="2026-01-01T08:00:00Z")])
        source = SourceSpan("chat/1", ("user",), "资料后天到，到了我去拿")
        registry = EntityRegistry(core)
        registry.initialize()
        owner = registry.create(request_id="owner", label="用户", evidence=(source,))["ref"]
        journal = PropertyJournal(core)
        journal.initialize()
        journal.register(PropertySpec(PROPERTY_KEY, "single"), evidence=(source,))
        draft = CommitmentDraft(source, owner, "delivery", "领取资料", "scheduled",
                                "unconditional", "后天")
        proposal = stage_commitment(core, draft, request_id="delivery",
                                    source_until="2026-01-01T12:00:00Z")
        journal.review(proposal["proposal_id"], expected_digest=proposal["digest"],
                       decision="accepted", reviewer="test",
                       reason="Reviewed the source commitment.", evidence=(source,))
        journal.commit(proposal["proposal_id"], expected_digest=proposal["digest"])
        bundle = build_state_bundle(
            core, now="2026-01-03T12:00:00Z", source_until="2026-01-03T12:00:00Z",
            visible_source_ids={"chat/1"}, question="今天要拿什么",
        )
        self.assertIn("[DUE]", bundle["text"])
        self.assertIn("领取资料", bundle["text"])
        self.assertIn("来源轮次 1", bundle["text"])
        candidate = build_state_bundle(
            core, now="2026-01-02T12:00:00Z", source_until="2026-01-02T12:00:00Z",
            visible_source_ids={"chat/1"}, question="那件事怎么样了", commitment_owner=owner,
        )["items"][1]
        self.assertEqual(candidate["kind"], "PENDING_BINDING")
        self.assertEqual(candidate["candidates"][0]["applicability"], "BEFORE_NAMED_DATE")
        self.assertEqual(candidate["source_turns"], (1,))


if __name__ == "__main__":
    unittest.main()
