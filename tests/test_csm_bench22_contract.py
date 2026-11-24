"""Contract: the Bench 2.2 adapter publishes state and evidence separately."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'benchmarks'), str(ROOT / 'src'),
                str(ROOT / '.bench/chat-memory-benchmark-2.2/benchmark-2.2/harness')]
from csm_bench22 import CsmBench22, StateRetrieval  # noqa: E402
from wsc.csm import MemoryCandidate  # noqa: E402
from wsc.csm.cem.state_extraction import parse_state_items  # noqa: E402


class BenchContractTests(unittest.TestCase):
    def test_state_vector_cache_reuses_exact_text_and_respects_current_input(self):
        import numpy as np
        from csm_bench22_revision_relevance import rank_revisions

        class Embedder:
            def __init__(self):
                self.documents = []

            def embed(self, texts):
                self.documents.extend(texts)
                return np.array([[float('四楼' in text), float('四楼' not in text)] for text in texts])

            def query(self, text):
                return np.array([[1., 0.]])

        embedder = Embedder()
        cache = {}
        row = dict(entity='用户', slot='住所', contexts=[], value='四楼', classification='SPECULATIVE')
        changed = {**row, 'value': '五楼'}
        for visible in ([row], [row], [changed]):
            self.assertEqual(visible, rank_revisions('住几楼？', visible, embedder=embedder, vector_cache=cache))
        self.assertEqual(['用户 住所 四楼', '用户 住所 五楼'], embedder.documents)

    def test_revision_relevance_keeps_single_character_fallback_and_excludes_history(self):
        from csm_bench22_revision_relevance import rank_revisions

        row = {'entity': '用户', 'slot': '住所', 'contexts': [], 'value': '四楼',
               'classification': 'SPECULATIVE'}
        old = {**row, 'value': '三楼', 'classification': 'HISTORICAL'}
        self.assertEqual([row], rank_revisions('住几楼？', [old, row]))

    def test_batch_runner_replays_shared_boundaries_before_reading(self):
        import json
        from tempfile import TemporaryDirectory
        from types import SimpleNamespace
        from unittest.mock import patch

        from bench22 import runner
        from csm_bench22_batch_runner import run_batch_persona

        calls = []

        class System:
            def __init__(self, gateway):
                self.last = 0

            def ingest_batch(self, turns):
                calls.append(tuple(turn['turn'] for turn in turns))
                self.last = turns[-1]['turn']

            def retrieve(self, question, now, cutoff_turn, item_id):
                assert self.last == cutoff_turn
                calls.append(item_id)
                return SimpleNamespace(prompt=question, used_turns=[self.last], meta={})

        history = {'P': [{'turn': turn} for turn in range(1, 9)]}
        items = [dict(id=f'q{stop}', persona='P', cutoff_turn=stop, question='test', now='now')
                 for stop in (3, 8)]
        args = SimpleNamespace(system='batch-test', split='dev')
        with TemporaryDirectory() as output, patch.dict(runner.REGISTRY, {'batch-test': System}):
            path = Path(output) / 'contexts.jsonl'
            path.write_text(json.dumps({'id': 'q3'}) + '\n', encoding='utf-8')
            returned = run_batch_persona(args, None, history, 'P', items, output, SimpleNamespace(),
                                         None, boundaries={'P': [3, 5, 8]})
            self.assertEqual([], returned)
            self.assertEqual([(1, 2, 3), (4, 5), (6, 7, 8), 'q8'], calls)
            self.assertEqual([8], list(runner.jl(str(path)))[-1]['used_turns'])

    def test_batch_writes_each_source_revision_before_reading(self):
        import json
        from csm_bench22_batch_revision import BatchRevisionBench22

        class Gateway:
            calls = 0

            def chat(self, model, messages, phase, tag, **kwargs):
                self.calls += 1
                assert phase == 'ingest'
                sources = json.loads(messages[1]['content'])['sources']
                assert [source['id'] for source in sources] == ['chat/1', 'chat/2']
                deltas = {source['id']: [
                    {'new_entity': 'source.speaker', 'slot': 'database', 'value': source['text'],
                     'confidence': 0.9}] for source in sources}
                return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(deltas)}}]}

        gateway = Gateway()
        system = BatchRevisionBench22(gateway)
        now = '2026-11-16T00:00:00Z'
        system.ingest_batch([{'turn': turn, 'time': now, 'user': value, 'assistant': ''}
                             for turn, value in enumerate(('MySQL', 'PostgreSQL'), 1)])
        self.assertIn('r1 = MySQL', system.retrieve('database', now, 1).state_text)
        self.assertIn('r2 = PostgreSQL', system.retrieve('database', now, 2).state_text)
        self.assertNotIn('PostgreSQL', system.retrieve('database', now, 1).prompt)
        self.assertEqual(1, gateway.calls)

    def test_write_revisions_bind_the_speaker_and_keep_named_contexts_separate(self):
        import json
        from csm_bench22_flat_revision import FlatRevisionBench22

        class Gateway:
            def chat(self, model, messages, phase, tag, **kwargs):
                source = json.loads(messages[1]['content'])['source']
                name, observation = source['text'].split('：', 1)
                delta = {'target': None, 'new_entity': 'source.speaker', 'slot': '阅读进度',
                         'contexts': [name], 'value': observation, 'confidence': 0.95}
                return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps([delta])}}]}

        system = FlatRevisionBench22(Gateway())
        now = '2026-11-16T00:00:00Z'
        for turn, text in enumerate(('《山路》：读到第70页', '《夜航》：读到第112页'), 1):
            system.ingest({'turn': turn, 'user': text, 'assistant': '', 'time': now})
        result = system.retrieve('《山路》阅读进度是多少页？', now, 2)
        self.assertIn('[SPECULATIVE] 用户 / 阅读进度 (《山路》)', result.state_text)
        self.assertIn('第70页', result.evidence)
        self.assertNotIn('夜航', result.prompt)
        self.assertEqual([1], result.used_turns)

    def test_write_revision_arm_reads_the_cutoff_and_discards_natural_branch(self):
        import json
        from csm_bench22_flat_revision import FlatRevisionBench22

        class Gateway:
            calls = 0

            def chat(self, model, messages, phase, tag, **kwargs):
                self.calls += 1
                assert phase == 'ingest'
                assert messages[0]['role'] == 'system'
                payload = json.loads(messages[1]['content'])
                assert 'injected assistant' not in str(payload)
                target = payload['entities'][0]['memory_id'] if payload['entities'] else None
                value = payload['source']['text'].split()[-1]
                delta = {'target': target, 'new_entity': 'Harbor', 'slot': 'database',
                         'contexts': [], 'value': value, 'confidence': 0.95}
                return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps([delta])}}]}

        gateway = Gateway()
        system = FlatRevisionBench22(gateway)
        day1, day2 = '2026-11-16T00:00:00Z', '2026-11-17T00:00:00Z'
        system.ingest({'turn': 1, 'user': 'Harbor database MySQL',
                       'assistant': 'injected assistant', 'time': day1})
        system.begin_tail()
        system.ingest({'turn': 2, 'user': 'Harbor database PostgreSQL', 'assistant': '', 'time': day2})
        branch = system.retrieve('Harbor database', day2, 2)
        self.assertIn('[speculative] harbor / database r2 = postgresql', branch.state_text.lower())
        self.assertNotIn('MySQL', branch.prompt)
        self.assertEqual([2], branch.used_turns)
        self.assertIn('Harbor database PostgreSQL', branch.evidence)
        self.assertIn('MySQL', system.retrieve('Harbor database', day2, 1).prompt)
        system.rewind(1)
        self.assertIn('MySQL', system.retrieve('Harbor database', day2, 2).prompt)
        self.assertEqual(2, gateway.calls)

    def test_reviewed_timed_rule_composes_with_memory_without_leaking(self):
        from csm_bench22_raw_memory import RawMemoryBench22
        from csm_bench22_timed_rule import retrieve_with_timed_rule
        from wsc.csm.cem.semantic_contract import SourceSpan

        system = RawMemoryBench22(annotate_evidence_dates=True)
        start = '2026-12-16T09:00:00+08:00'
        stop = '2026-12-17T09:00:00+08:00'
        quote = '这段时间请用临时入口。'
        system.ingest({'turn': 1, 'time': start, 'user': quote, 'assistant': ''})
        system.ingest({'turn': 2, 'time': start, 'user': '会议在蓝厅。', 'assistant': ''})
        binding = {'source': SourceSpan('chat/1', ('user',), quote), 'scope': '临时入口',
                   'valid_from': start, 'valid_until': stop}
        question = '会议在哪，该走哪个入口？'
        baseline = system.retrieve(question, start, 2)
        active = retrieve_with_timed_rule(system, question, now=start, cutoff_turn=2, binding=binding)
        self.assertEqual('CLOCK', active.state_items[0]['kind'])
        self.assertIn('CONDITIONAL_RULE', [item['kind'] for item in active.state_items])
        self.assertIn(quote, active.evidence)
        self.assertIn('会议在蓝厅。', active.evidence)
        self.assertIn('deadline_annotations', baseline.meta)
        self.assertIn('deadline_annotations', active.meta)
        self.assertNotIn('CONDITIONAL_RULE', baseline.state_text)
        for now, cutoff in ((start, 0), (stop, 2)):
            inactive = retrieve_with_timed_rule(system, question, now=now, cutoff_turn=cutoff, binding=binding)
            self.assertEqual(system.retrieve(question, now, cutoff).prompt, inactive.prompt)
        historical = retrieve_with_timed_rule(system, question, now=stop, cutoff_turn=2,
                                               binding=binding, historical=True)
        self.assertEqual('HISTORICAL', historical.state_items[1]['kind'])
        self.assertIn(quote, historical.evidence)
        for now, cutoff in ((start, 2), (stop, 0)):
            historical = retrieve_with_timed_rule(system, question, now=now, cutoff_turn=cutoff,
                                                   binding=binding, historical=True)
            self.assertEqual(system.retrieve(question, now, cutoff).prompt, historical.prompt)
        bad = {**binding, 'source': SourceSpan('chat/1', ('user',), '并不存在的原话')}
        with self.assertRaisesRegex(ValueError, 'reviewed_source_quote_mismatch'):
            retrieve_with_timed_rule(system, question, now=start, cutoff_turn=2, binding=bad)

    def test_semantic_candidates_apply_visibility_before_top_k(self):
        import numpy as np

        from csm_bench22_semantic_candidates import SemanticCandidates

        class Embedder:
            def embed(self, texts):
                return np.array([[0, 1], [1, 0], [1, 0]], dtype=np.float32)

            def query_batch(self, texts):
                return np.array([[1, 0]] * len(texts), dtype=np.float32)

        history = [{'turn': turn, 'user': str(turn)} for turn in (1, 2, 3)]
        index = SemanticCandidates(history, Embedder())
        self.assertEqual([[1], [2], []], index.rank(['x'] * 3, [{0}, {2, 1}, set()], limit=1))

    def test_negative_projection_requires_literal_user_support_in_pilot(self):
        from csm_bench22_negative_claims import scope_negative_claims

        def item(quote, *, field='user', status='source_projection'):
            return {'kind': 'CURRENT_CONFIRMED', 'entity': '用户', 'slot': '维修',
                    'text': '[CURRENT_CONFIRMED] 到了店门口，尚未修好', 'value': '到了店门口，尚未修好',
                    'status': status, 'source_turns': [1], 'citations': [{'field': field, 'quote': quote, 'turn': 1}]}

        for unsupported in (item('到了店门口'), item('尚未修好', field='assistant')):
            pending, = scope_negative_claims([unsupported])
            self.assertEqual('PENDING_BINDING', pending['kind'])
            self.assertNotIn('value', pending)
            self.assertEqual(unsupported['citations'], pending['citations'])
        for supported in (item('我到了店门口，车尚未修好'), item('到了店门口', status='reviewed')):
            self.assertEqual([supported], scope_negative_claims([supported]))

    def test_title_lookup_keeps_page_progress_and_conflicting_totals_separate(self):
        from csm_bench22_title_recall import TitleRecallBench22

        system = TitleRecallBench22()
        now = '2026-12-16T18:30:00+08:00'
        sources = ('《山路》读到一百页了，全书三百页。', '我把《山路》借给朋友。', '新版《山路》全书三百五十页。')
        for turn, user in enumerate(sources, 1):
            system.ingest({'turn': turn, 'time': now, 'user': user, 'assistant': ''})
        items = [{'kind': 'CLOCK', 'now': now}, {
            'kind': 'UNKNOWN', 'status': 'source_projection', 'slot': '页数', 'text': '[UNKNOWN] 页数未提及',
            'source_turns': [2], 'citations': [{'turn': 2, 'field': 'user', 'quote': '《山路》'}],
        }]
        from wsc.csm.cem.state_extraction import render_items
        evidence = '【证据｜仅支撑】\n【聊天记录】\n\n' + system._source_block(system.turns[1])
        before = StateRetrieval(items, render_items(items), evidence, [2])
        after = system.supplement_page_totals(before, now=now, cutoff_turn=2)
        self.assertEqual('PENDING_BINDING', after.state_items[1]['kind'])
        self.assertEqual([1, 2], after.used_turns)
        self.assertIn('全书三百页', after.evidence)
        self.assertIs(before, system.supplement_page_totals(before, now=now, cutoff_turn=3))

    def test_reading_comparison_keeps_sources_units_and_visibility(self):
        from csm_bench22_reading_comparison import ReadingComparisonBench22

        system = ReadingComparisonBench22()
        now = '2026-12-16T18:30:00+08:00'
        future = '2026-12-17T18:30:00+08:00'
        sources = [
            (now, '《山路》读到一百页了，全书三百页。'),
            (now, '《晚风》读到第三章了，全书九章。'),
            (future, '睡前读《山路》，全书三百五十页。'),
        ]
        for turn, (time, user) in enumerate(sources, 1):
            system.ingest({'turn': turn, 'time': time, 'user': user, 'assistant': ''})
        query = '没读完的几本里，哪一本阅读进度最高？'
        before = system.retrieve(query, now, 0)
        bundle = system.supplement_comparison(before, query, now=now, cutoff_turn=3)
        comparison = bundle.state_items[-1]
        self.assertEqual('OBSERVATION_COMPARISON', comparison['kind'])
        self.assertFalse(comparison['scope_complete'])
        self.assertEqual([1, 2], comparison['source_turns'])
        self.assertEqual([('页', 100, 300), ('章', 3, 9)],
                         [(row['unit'], row['position'], row['total']) for row in comparison['observations']])
        self.assertIn('页与章是不同计量口径', bundle.state_text)
        self.assertIn(sources[0][1], bundle.evidence)
        self.assertNotIn('三百五十', bundle.prompt)
        self.assertEqual([], system.comparison_candidates(query, now=future, cutoff_turn=3)[1])
        system.rewind(2)
        self.assertEqual(2, len(system.comparison_candidates(query, now=future, cutoff_turn=3)[1]))

    def test_measurement_candidate_preserves_correction_and_never_confirms_it(self):
        from csm_bench22_measurement_recall import MeasurementRecallBench22

        system = MeasurementRecallBench22()
        old = '手环说每天走一万步。'
        corrected = '之前手环记的每天一万步是误记。其实每天五千多步。'
        now = '2026-12-16T18:30:00+08:00'
        for index, quote in enumerate((old, corrected), 1):
            system.ingest({'turn': index, 'time': now, 'user': quote, 'assistant': ''})
        scope = {'now': now, 'cutoff_turn': 2}
        query = '医生问我平时的活动量'
        found = system.search_measurements(query, **scope)
        self.assertEqual(corrected, found['candidates'][0]['quote'])
        self.assertFalse(system.search_measurements('我今天好累', **scope)['candidates'])
        baseline = system.retrieve(query, now, 0)
        scoped = system.supplement_measurements(baseline, query, **scope)
        self.assertEqual('PENDING_BINDING', scoped.state_items[1]['kind'])
        self.assertIn(corrected, scoped.evidence)
        system.rewind(1)
        self.assertEqual(old, system.search_measurements(query, **scope)['candidates'][0]['quote'])

    def test_reviewed_dispute_requires_both_attributions_and_the_reviewed_prefix(self):
        from csm_bench22_reported_disputes import ReportedClaim, ReportedDisputeBench22, ReviewedDispute
        from wsc.csm.cem.semantic_contract import SourceSpan

        now = '2026-12-16T18:30:00+08:00'
        system = ReportedDisputeBench22()
        quotes = ['甲说水表读数不变。', '乙说水表多了两度。']
        for turn, quote in enumerate(quotes, 1):
            system.ingest({'turn': turn, 'time': now, 'user': quote, 'assistant': ''})
        claims = tuple(ReportedClaim(speaker, SourceSpan(f'chat/{turn}', ('user',), quote))
                       for turn, (speaker, quote) in enumerate(zip(('甲', '乙'), quotes), 1))
        dispute = ReviewedDispute('水表读数', claims, 2)
        result = system.retrieve_dispute(now, 2, issue='水表读数', dispute=dispute)
        self.assertEqual([1, 2], result.used_turns)
        self.assertEqual('CONFLICT_UNRESOLVED', result.state_items[1]['kind'])
        self.assertFalse(result.state_items[1]['confirmed'])
        for quote in quotes:
            self.assertIn(quote, result.evidence)
        self.assertEqual([], system.retrieve_dispute(now, 1, issue='水表读数', dispute=dispute).used_turns)
        self.assertEqual([], system.retrieve_dispute(now, 2, issue='电表读数', dispute=dispute).used_turns)
        self.assertEqual([], system.retrieve_dispute('2026-12-15T18:30:00+08:00', 2,
                                                    issue='水表读数', dispute=dispute).used_turns)
        with self.assertRaisesRegex(ValueError, 'dispute_report_source_invalid'):
            invalid = ReviewedDispute('水表读数', (claims[0], ReportedClaim(
                '乙', SourceSpan('chat/2', ('user',), '乙说水表多了十度。'))), 2)
            system.retrieve_dispute(now, 2, issue='水表读数', dispute=invalid)

    def test_source_account_preserves_the_original_clock_and_citation(self):
        class Producer:
            def extract(self, question, evidence, now):
                value = {'kind': 'CURRENT_CONFIRMED', 'entity': '用户', 'slot': '处理状态',
                         'value': '先搁置维修', 'source_turns': [1],
                         'citations': [{'turn': 1, 'field': 'user', 'quote': '维修先搁置。'}]}
                return parse_state_items({'items': [value]}, now, sources=evidence)

        now = '2026-12-16T18:30:00+08:00'
        observed = '2026-12-10T18:30:00+08:00'
        system = CsmBench22(None, state_extractor=Producer())
        system.ingest({'turn': 1, 'time': observed, 'user': '维修先搁置。', 'assistant': ''})
        before = system.retrieve('维修的事现在怎么样？', now, 1)
        system.scope_producer_source = True
        after = system.retrieve('维修的事现在怎么样？', now, 1)
        self.assertEqual('CURRENT_CONFIRMED', before.state_items[1]['kind'])
        self.assertEqual('SOURCE_ACCOUNT', after.state_items[1]['kind'])
        self.assertEqual(observed, after.state_items[1]['source_through'])
        self.assertEqual(before.evidence, after.evidence)
        self.assertEqual(before.state_items[1]['citations'], after.state_items[1]['citations'])
        self.assertEqual(before.used_turns, after.used_turns)

    def test_same_value_reaffirmation_uses_latest_user_time_and_ignores_assistant_clock(self):
        class Producer:
            def extract(self, question, evidence, now):
                covers = [
                    [{'turn': 1, 'field': 'user', 'quote': '维修先搁置'}],
                    [{'turn': 2, 'field': 'user', 'quote': '维修先搁置'},
                     {'turn': 3, 'field': 'assistant', 'quote': '记下了'}],
                ]
                return parse_state_items({'items': [
                    {'kind': 'CURRENT_CONFIRMED', 'entity': '用户', 'slot': '处理状态',
                     'value': '先搁置维修', 'source_turns': [cite['turn'] for cite in citations],
                     'citations': citations}
                    for citations in covers
                ]}, now, sources=evidence)

        system = CsmBench22(None, state_extractor=Producer())
        for turn in (1, 2, 3):
            system.ingest({'turn': turn, 'time': f'2026-12-1{turn}T18:30:00+08:00',
                           'user': '维修先搁置。' if turn < 3 else '好。', 'assistant': '记下了'})
        args = ('维修的事现在怎么样？', '2026-12-16T18:30:00+08:00', 3)
        self.assertEqual((1,), system.retrieve(*args).state_items[1]['source_turns'])
        system.scope_producer_source = True
        result = system.retrieve(*args)
        self.assertEqual([1, 2, 3], result.used_turns)
        self.assertEqual('SOURCE_ACCOUNT', result.state_items[1]['kind'])
        self.assertEqual((2, 3), result.state_items[1]['source_turns'])
        self.assertEqual('2026-12-12T18:30:00+08:00', result.state_items[1]['source_through'])

    def test_supplemental_passage_keeps_primary_ranking_and_source_boundaries(self):
        from csm_bench22_raw_memory import RawMemoryBench22

        system = RawMemoryBench22(recall_lanes=True, sentence_passages=True)
        now = '2026-12-16T18:30:00+08:00'
        body = '设备的保修在周三结束。图书的归还在周五。楼下的店今天关门。'
        system.ingest({'turn': 1, 'time': now, 'user': body, 'assistant': ''})
        system.ingest({'turn': 2, 'time': '2026-12-17T18:30:00+08:00',
                       'user': '设备保修和图书归还另有通知。', 'assistant': ''})
        scope = {'now': now, 'cutoff_turn': 2, 'limit': 1}
        query = '设备保修和图书归还分别是哪天'
        before = system.search_candidates(query, **scope)['passages']
        after = system.search_candidates(query, **scope, distinct_passages=True)['passages']
        self.assertEqual(before, after[:1])
        self.assertEqual(2, len(after))
        self.assertTrue(all(item['turn'] == 1 for item in after))
        self.assertEqual({'设备的保修在周三结束。', '图书的归还在周五。'},
                         {body[item['start']:item['end']] for item in after})

    def test_reviewed_conditional_rules_keep_scope_and_time_boundaries(self):
        from csm_bench22_conditional_recall import ConditionalRecallBench22, ReviewedConditionalRule
        from wsc.csm.cem.semantic_contract import SourceSpan

        source_time = '2026-11-14T20:47:21+08:00'
        later = '2026-12-16T18:30:00+08:00'
        system = ConditionalRecallBench22()
        system.ingest({'turn': 1, 'time': source_time, 'user': '下班后邮件留到第二天处理。', 'assistant': '我记下了'})
        span = SourceSpan('chat/1', ('user',), '下班后邮件留到第二天处理')
        system.add_reviewed_rule(ReviewedConditionalRule('邮件处理', 'off_work', span))
        question = '刚下班到家，终于能歇会儿。'
        found = system.retrieve_condition(question, later, 1, rule_scope='邮件处理')
        self.assertEqual('CONDITIONAL_RULE', found.state_items[1]['kind'])
        self.assertEqual(span.quote, found.state_items[1]['value'])
        self.assertIn(span.quote, found.state_text)
        self.assertIn(span.quote, found.evidence)
        for text, now, cutoff, scope in ((question, later, 0, '邮件处理'), (question, later, 1, '称呼'),
                                         ('明天刚下班就回家', later, 1, '邮件处理'),
                                         (question, '2026-11-13T00:00:00+08:00', 1, '邮件处理')):
            self.assertEqual([], system.retrieve_condition(text, now, cutoff, rule_scope=scope).used_turns)
        system.ingest({'turn': 2, 'time': later, 'user': '下班后也可以处理紧急邮件。', 'assistant': ''})
        extra = SourceSpan('chat/2', ('user',), '下班后也可以处理紧急邮件')
        system.add_reviewed_rule(ReviewedConditionalRule('邮件处理', 'off_work', extra))
        unresolved = system.retrieve_condition(question, later, 2, rule_scope='邮件处理')
        self.assertEqual('PENDING_BINDING', unresolved.state_items[1]['kind'])
        self.assertNotIn('value', unresolved.state_items[1])
        self.assertEqual([1, 2], unresolved.used_turns)
        system.rewind(1)
        self.assertEqual([1], system.retrieve_condition(question, later, 2, rule_scope='邮件处理').used_turns)

    def test_reviewed_conditional_outcomes_allow_reaffirmation_without_hiding_conflict(self):
        from csm_bench22_conditional_recall import ConditionalRecallBench22, ReviewedConditionalRule
        from wsc.csm.cem.semantic_contract import SourceSpan

        now = '2026-12-16T18:30:00+08:00'
        system = ConditionalRecallBench22()
        for turn, quote, outcome in [(1, '下班后邮件留到第二天。', '次日处理'),
                                     (2, '已经下班，邮件明天再回。', '次日处理'),
                                     (3, '下班后当天就回邮件。', '当天处理')]:
            system.ingest({'turn': turn, 'time': now, 'user': quote, 'assistant': ''})
            system.add_reviewed_rule(ReviewedConditionalRule('邮件处理', 'off_work',
                                                             SourceSpan(f'chat/{turn}', ('user',), quote), outcome))
        query = '刚下班到家，想看看邮件。'
        reaffirmed = system.retrieve_condition(query, now, 2, rule_scope='邮件处理')
        self.assertEqual('次日处理', reaffirmed.state_items[1]['value'])
        self.assertEqual([1, 2], reaffirmed.used_turns)
        conflicting = system.retrieve_condition(query, now, 3, rule_scope='邮件处理')
        self.assertEqual('PENDING_BINDING', conflicting.state_items[1]['kind'])
        self.assertEqual([1, 2, 3], conflicting.used_turns)

    def test_numeric_question_premise_does_not_become_confirmed_without_matching_quote(self):
        class Producer:
            def extract(self, question, evidence, now):
                item = {'kind': 'CURRENT_CONFIRMED', 'entity': '用户', 'slot': '旧信总数', 'value': '六十封',
                        'source_turns': [1], 'citations': [{'turn': 1, 'field': 'user', 'quote': '四十三封'}]}
                return parse_state_items({'items': [item]}, now, sources=evidence)

        now = '2026-10-15T08:00:00+08:00'
        source = {'turn': 1, 'time': now, 'user': '春节那会儿她翻出来数过一回，四十三封。', 'assistant': ''}
        for scope, expected in ((False, 'CURRENT_CONFIRMED'), (True, 'PENDING_BINDING')):
            system = CsmBench22(None, state_extractor=Producer(), scope_numeric_state=scope)
            system.ingest(source)
            result = system.retrieve('一共60封信，我想挑几封抄下来', now, 1)
            self.assertEqual(expected, result.state_items[1]['kind'])
            self.assertIn('四十三封', result.evidence)
            if scope:
                self.assertNotIn('六十封', result.state_text)

    def test_relative_state_pilot_uses_source_clock(self):
        class Producer:
            def extract(self, question, evidence, now):
                item = {'kind': 'CURRENT_CONFIRMED', 'entity': '汤团', 'slot': '行为', 'value': '今天特别黏人',
                        'source_turns': [1], 'citations': [{'turn': 1, 'field': 'user', 'quote': '今天特别黏人'}]}
                return parse_state_items({'items': [item]}, now, sources=evidence)

        system = CsmBench22(None, state_extractor=Producer(), scope_relative_state=True)
        stamp = '2026-09-19T12:00:00+08:00'
        system.ingest({'turn': 1, 'time': stamp, 'user': '汤团今天特别黏人', 'assistant': ''})
        same_day = system.retrieve('汤团近况', stamp, 1)
        self.assertEqual('CURRENT_CONFIRMED', same_day.state_items[1]['kind'])
        later = system.retrieve('汤团近况', '2027-02-01T12:00:00+08:00', 1)
        self.assertEqual('PENDING_BINDING', later.state_items[1]['kind'])
        self.assertEqual('2026-09-19', later.state_items[1]['source_date'])
        self.assertIn('今天特别黏人', later.evidence)

    def test_calendar_window_candidates_follow_observation_and_rewind(self):
        from csm_bench22_window_recall import WindowRecallBench22

        system = WindowRecallBench22()
        observed = '2026-12-21T01:59:05+08:00'
        body = '周医生让我从今天起吃十五天中药。'
        system.ingest({'turn': 1, 'time': observed, 'user': body, 'assistant': '从今天起吃三十天'})
        self.assertEqual([], system.search_calendar_windows(now='2026-12-21T01:58:00+08:00', cutoff_turn=1))
        self.assertEqual([], system.search_calendar_windows(now=observed, cutoff_turn=0))
        candidate, = system.search_calendar_windows(now=observed, cutoff_turn=1)
        self.assertEqual('calendar_window_match_only', candidate['scope'])
        self.assertEqual(candidate['quote'], body[candidate['start']:candidate['end']])
        self.assertEqual([], system.search_calendar_windows(now=candidate['window_end'], cutoff_turn=1))
        self.assertNotIn('TEMPORAL_WINDOW', [item['kind'] for item in system.retrieve('药', observed, 1).state_items])
        system.rewind(0)
        self.assertEqual([], system.search_calendar_windows(now=observed, cutoff_turn=1))

    def test_literal_duration_is_not_projected_as_a_deadline_or_completion(self):
        source = {1: {'user': '周医生让我从今天起吃十五天中药，这期间先别提火锅。', 'assistant': '',
                      'time': '2026-12-21T01:59:05+08:00'}}
        anchor = {'turn': 1, 'field': 'user', 'quote': '从今天起吃十五天'}
        cite = {**anchor, 'quote': '这期间先别提火锅'}
        payload = {'items': [{'kind': 'DEADLINE', 'entity': '用户', 'slot': '药期', 'value': '十五天',
                              'source_turns': [1], 'citations': [cite], 'date_anchor': anchor}]}
        before = '2026-12-30T19:00:59+08:00'
        boundary = '2027-01-05T00:00:00+08:00'
        state, = parse_state_items(payload, before, sources=source)
        self.assertEqual('TEMPORAL_WINDOW', state['kind'])
        self.assertEqual('WITHIN_SOURCE_WINDOW', state['applicability'])
        self.assertEqual(boundary, state['due_end'])
        self.assertEqual([cite, anchor], state['citations'])
        after, = parse_state_items(payload, boundary, sources=source, retain_off_day=True)
        self.assertEqual('AFTER_SOURCE_WINDOW', after['applicability'])
        for replacement in ('不是从今天起吃十五天', '从今天起吃十五天半', '从今天起吃十五天或二十天'):
            rejected = {1: {**source[1], 'user': source[1]['user'].replace(anchor['quote'], replacement)}}
            self.assertEqual([], parse_state_items(payload, before, sources=rejected))

    def test_produced_state_keeps_citations_when_full_turns_do_not_fit(self):
        class Producer:
            def extract(self, question, evidence, now):
                self.asserted = tuple(sorted(evidence))
                return parse_state_items({'items': [{
                    'kind': 'CURRENT_CONFIRMED', 'entity': '用户', 'slot': '材料', 'value': '长材料' * 280,
                    'source_turns': [1, 2, 3, 4],
                    'citations': [{'turn': turn, 'field': 'user', 'quote': f'材料原话{turn}'}
                                  for turn in range(1, 5)],
                }]}, now, sources=evidence)

        producer = Producer()
        system = CsmBench22(None, state_extractor=producer, separate_producer_budget=True)
        now = '2026-09-05T12:00:00+08:00'
        for turn in range(1, 5):
            system.ingest({'turn': turn, 'time': now, 'user': f'材料原话{turn}' + '背景' * 735, 'assistant': ''})
        result = system.retrieve('材料', now, 4)
        self.assertEqual((1, 2, 3, 4), producer.asserted)
        self.assertEqual('CURRENT_CONFIRMED', result.state_items[1]['kind'])
        for turn in range(1, 5):
            self.assertIn(f'材料原话{turn}', result.evidence)
        self.assertEqual([1, 2, 3, 4], result.meta['evidence_turns'])
        self.assertLessEqual(len(result.prompt), 6400)

    def test_bound_commitment_publishes_exact_source_within_budget(self):
        from wsc.csm.cem.commitment_ingestion import CommitmentDraft, stage_commitment
        from wsc.csm.cem.commitment_projection import PROPERTY_KEY
        from wsc.csm.cem.entity_registry import EntityRegistry
        from wsc.csm.cem.property_journal import PropertyJournal
        from wsc.csm.cem.semantic_contract import PropertySpec, SourceSpan

        original = '工作室这一季度房租九千六，下个月10号前我得亲自去物业交。'
        time = '2026-11-25T17:27:33+08:00'
        now = '2026-12-10T07:50:26+08:00'
        for quote in (original, original + '很长的原始资料。' * 1200):
            with self.subTest(quote_chars=len(quote)):
                system = CsmBench22(None)
                system.ingest({'turn': 1, 'time': time, 'user': quote + '很长的原始资料。' * 1200, 'assistant': ''})
                span = SourceSpan('chat/1', ('user',), quote)
                registry = EntityRegistry(system.csm)
                registry.initialize()
                owner = registry.create(request_id='owner', label='用户', evidence=(span,))['ref']
                journal = PropertyJournal(system.csm)
                journal.initialize()
                journal.register(PropertySpec(PROPERTY_KEY, 'single'), evidence=(span,))
                draft = CommitmentDraft(span, owner, 'rent', '到物业交房租', 'scheduled', 'unconditional',
                                        '下个月10号前', temporal_kind='deadline')
                proposal = stage_commitment(system.csm, draft, request_id='rent', source_until=time)
                journal.review(proposal['proposal_id'], expected_digest=proposal['digest'], decision='accepted',
                               reviewer='test', reason='Exact quote.', evidence=(span,))
                binding = journal.commit(proposal['proposal_id'], expected_digest=proposal['digest'])['binding']
                result = system.retrieve('今天要办什么', now, 1, commitment_binding=binding['binding_key'])
                self.assertLessEqual(len(result.prompt), 6400)
                if quote == original:
                    self.assertEqual('DEADLINE_DATE', result.state_items[1]['kind'])
                    self.assertIn(original, result.evidence)
                    self.assertEqual([1], result.used_turns)
                else:
                    self.assertEqual('NO_CONFIRMED_STATE', result.state_items[1]['kind'])
                    self.assertEqual('state_evidence_budget', result.state_items[1]['reason'])
                    self.assertEqual([], result.used_turns)

    def test_exact_citation_read_preserves_role_and_rejects_wrong_quote(self):
        from csm_bench22_raw_memory import RawMemoryBench22

        system = RawMemoryBench22()
        now = '2026-09-05T12:00:00+08:00'
        system.ingest({'turn': 1, 'time': now, 'user': '五十元，还是五十元', 'assistant': '好的'})
        cite = {'turn': 1, 'field': 'user', 'quote': '五十元'}
        self.assertEqual(system.read_citations([cite, cite], now=now, cutoff_turn=1), [
            {**cite, 'start': None, 'end': None}])
        with self.assertRaisesRegex(ValueError, 'source_citation_mismatch'):
            system.read_citations([{**cite, 'field': 'assistant'}], now=now, cutoff_turn=1)
        with self.assertRaisesRegex(ValueError, 'source_outside_visible_history'):
            system.read_citations([cite], now=now, cutoff_turn=0)

    def test_phrase_candidates_respect_role_time_and_rewind(self):
        from csm_bench22_raw_memory import RawMemoryBench22

        system = RawMemoryBench22(phrase_recall=True)
        start, end = '2026-09-05T12:00:00+08:00', '2026-09-06T12:00:00+08:00'
        for seq, stamp, user, assistant in ((1, start, ' ', '还款120元'), (2, end, '还款120元', '')):
            system.ingest({'turn': seq, 'time': stamp, 'user': user, 'assistant': assistant})
        self.assertEqual(system.search_phrases('还款120元', now=start, cutoff_turn=2), [1])
        self.assertEqual(system.search_phrases('还款120元', now=end, cutoff_turn=2), [2, 1])
        system.rewind(1)
        self.assertEqual(system.search_phrases('还款120元', now=end, cutoff_turn=2), [1])

    def test_raw_memory_round_trips_payload_and_enforces_visibility(self):
        from csm_bench22_raw_memory import RawMemoryBench22

        system = RawMemoryBench22()
        turn = {'turn': 1, 'time': '2026-09-07T12:00:00+08:00', 'user': '', 'assistant': '',
                'media': [{'url': 'https://example.test/image', 'caption': 'A receipt'}],
                'metadata': {'source': 'original'}}
        system.ingest(turn)
        self.assertEqual(system.read_original(1, now=turn['time'], cutoff_turn=1), turn)
        future = {**turn, 'turn': 2, 'time': '2026-09-07T13:00:00+08:00', 'user': '需要交收据'}
        system.ingest(future)
        self.assertEqual(system.search_originals('收据', now=turn['time'], cutoff_turn=2)['matches'], [])
        self.assertEqual(system.search_originals('收据', now=future['time'], cutoff_turn=2)['matches'], [2])
        for now, cutoff in ((turn['time'], 0), ('2026-09-07T11:59:00+08:00', 1)):
            with self.assertRaisesRegex(ValueError, 'source_outside_visible_history'):
                system.read_original(1, now=now, cutoff_turn=cutoff)
        system.rewind(0)
        with self.assertRaisesRegex(ValueError, 'source_outside_visible_history'):
            system.read_original(1, now=turn['time'], cutoff_turn=1)

    def test_candidate_lanes_keep_offsets_and_follow_cutoff_and_rewind(self):
        from csm_bench22_raw_memory import RawMemoryBench22

        system = RawMemoryBench22(recall_lanes=True)
        body = '第一段\r\n' + '天气晴朗，' * 75 + '仪器后天到驿站。'
        system.ingest({'turn': 1, 'time': '2026-09-05T12:00:00+08:00', 'user': body, 'assistant': ''})
        system.ingest({'turn': 2, 'time': '2026-09-08T12:00:00+08:00', 'user': '仪器仪器', 'assistant': ''})
        now = '2026-09-07T12:00:00+08:00'
        found = system.search_candidates('仪器', now=now, cutoff_turn=2)
        self.assertEqual(found['date_candidates'], [1])
        passage, = found['passages']
        self.assertEqual(passage['turn'], 1)
        self.assertEqual(passage['quote'], body[passage['start']:passage['end']])
        self.assertIn('仪器', passage['quote'])
        self.assertEqual(found, system.search_candidates('仪器', now=now, cutoff_turn=1))
        system.rewind(0)
        empty = system.search_candidates('仪器', now=now, cutoff_turn=2)
        self.assertFalse(empty['passages'] or empty['date_candidates'])

    def test_off_day_state_retains_literal_date_without_inferring_completion(self):
        source = {1: {'user': '资料后天到', 'assistant': '', 'time': '2026-09-05T12:00:00+08:00'}}
        cite = {'turn': 1, 'field': 'user', 'quote': '后天'}
        payload = {'items': [{'kind': 'SCHEDULED', 'entity': '用户', 'slot': '资料', 'value': '资料到',
                              'source_turns': [1], 'citations': [cite], 'date_anchor': cite}]}
        for day, expected in ((6, 'BEFORE_NAMED_DATE'), (8, 'AFTER_NAMED_DATE')):
            now = f'2026-09-0{day}T12:00:00+08:00'
            self.assertEqual(parse_state_items(payload, now, sources=source), [])
            state, = parse_state_items(payload, now, sources=source, retain_off_day=True)
            self.assertEqual(state['kind'], 'COMMITMENT_STATE')
            self.assertEqual(state['applicability'], expected)
            self.assertEqual(state['due_start'][:10], '2026-09-07')
            self.assertIn('事项完成状态未确认', state['text'])

    def test_structured_answer_cannot_add_free_prose_or_publish_pending(self):
        from csm_bench22_state_answer import offer_state_answer, publish_state_answer

        due = {'kind': 'DUE', 'text': '[DUE] 领取资料', 'source_turns': (1,)}
        pending = {'kind': 'PENDING_BINDING', 'text': '某人的生日', 'source_turns': (2,)}
        offered, _ = offer_state_answer('今天有什么安排', [due, pending])

        def response(content):
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}

        self.assertEqual(publish_state_answer(response('{"state_refs":["s0"]}'), offered)['answer'], due['text'])
        for content in ('{"state_refs":["s1"]}', '{"state_refs":["s0"],"answer":"生日是三号"}',
                        '{"state_refs":["s0"],"state_refs":[]}'):
            self.assertEqual(publish_state_answer(response(content), offered)['status'], 'state_answer_invalid')

    def test_conflict_scope_distinguishes_user_sources_from_assistant_echo(self):
        from csm_bench22_conflict_scope import scope_producer_conflicts

        first = {'turn': 1, 'field': 'user', 'quote': '昨天店里关着门'}
        item = {'kind': 'CONFLICT_UNRESOLVED', 'status': 'source_projection', 'entity': '店',
                'slot': '营业', 'value': '营业有争议', 'source_turns': (1, 2), 'citations': [first, {
                    'turn': 2, 'field': 'assistant', 'quote': '昨天也许开门'}]}
        pending, = scope_producer_conflicts([item])
        self.assertEqual(pending['kind'], 'PENDING_BINDING')
        self.assertEqual(pending['citations'], item['citations'])
        self.assertNotIn('value', pending)
        nested = {**item, 'source_turns': (1,), 'citations': [first, {**first, 'quote': '店里关着门'}]}
        self.assertEqual(scope_producer_conflicts([nested])[0]['kind'], 'PENDING_BINDING')
        same_turn = {**nested, 'citations': [first, {**first, 'quote': '但我下午再去的时候开着门'}]}
        self.assertEqual(scope_producer_conflicts([same_turn]), [same_turn])
        supported = {**item, 'citations': [first, {'turn': 2, 'field': 'user', 'quote': '昨天我去的时候开门'}]}
        self.assertEqual(scope_producer_conflicts([supported]), [supported])

    def test_pending_conflict_cannot_promote_the_same_source_to_current(self):
        from csm_bench22_conflict_scope import scope_producer_conflicts, suppress_unresolved_current

        witness = {'turn': 1, 'field': 'user', 'quote': '昨天店里关着门'}
        conflict = {'kind': 'CONFLICT_UNRESOLVED', 'status': 'source_projection', 'entity': '店',
                    'slot': '营业', 'value': '开门时间有争议', 'source_turns': (1,), 'citations': [witness]}
        current = {**conflict, 'kind': 'CURRENT_CONFIRMED', 'value': '关门',
                   'citations': [{**witness, 'quote': '店里关着门'}]}
        independent = {**current, 'source_turns': (2,),
                       'citations': [{**witness, 'turn': 2, 'quote': '今天也关着门'}]}
        unrelated_slot = {**current, 'slot': '店门'}
        scoped = scope_producer_conflicts([conflict, current, independent, unrelated_slot])
        self.assertEqual(suppress_unresolved_current(scoped), [scoped[0], independent, unrelated_slot])
        self.assertEqual(scoped[0]['citations'], [witness])

    def test_previous_observation_requires_a_unique_visible_user_measurement(self):
        from csm_bench22_previous_observation import locate_previous_observation
        from wsc.csm.contracts import parse_instant

        texts = [('北面水槽水位十八厘米', ''), ('北面水槽水位八厘米', ''),
                 ('南面水槽水位八厘米', ''), ('北面水槽今天重新测量水位', ''),
                 ('十二厘米', '上次不是才八厘米吗？'), ('北面水槽水位八厘米', '')]
        turns = [{'user': user, 'assistant': assistant} for user, assistant in texts]
        visible = {index: parse_instant(f'2026-09-05T18:00:0{index}+08:00') for index in range(len(turns))}
        self.assertEqual(locate_previous_observation(3, 4, [0, 1, 2, 5], turns, visible), 1)
        self.assertIsNone(locate_previous_observation(3, 4, [0, 5], turns, visible))
        turns[2]['user'] = turns[1]['user']
        self.assertIsNone(locate_previous_observation(3, 4, [1, 2], turns, visible))

    def test_recurring_contact_overlap_preserves_scope_and_uncertainty(self):
        from csm_bench22_contact_windows import contact_window_state

        now = '2026-11-01T17:00:00+08:00'
        source = {'turn': 4, 'time': '2026-10-25T10:00:00+08:00',
                  'user': '每周日晚上七点到九点那两小时你不要主动联系我'}
        pending = contact_window_state('今晚八点请提醒我', now, [source])
        self.assertEqual(pending['kind'], 'PENDING_BINDING')
        self.assertEqual(pending['requested_at'], '2026-11-01T20:00:00+08:00')
        self.assertEqual(pending['citations'], [{'turn': 4, 'field': 'user', 'quote': source['user']}])
        self.assertIsNone(contact_window_state('今晚九点请提醒我', now, [source]))
        self.assertIsNone(contact_window_state('今晚八点半请提醒我', now, [source]))
        half_hour_window = {**source, 'user': source['user'].replace('九点', '九点半')}
        self.assertIsNone(contact_window_state('今晚八点请提醒我', now, [half_hour_window]))
        self.assertIsNone(contact_window_state('明晚八点请提醒我', now, [source]))
        self.assertIsNone(contact_window_state('今晚八点不用提醒我', now, [source]))
        future = {**source, 'time': '2026-11-02T18:00:00+08:00', 'assistant': source['user'], 'user': ''}
        self.assertIsNone(contact_window_state('今晚八点请提醒我', now, [future]))
        hypothetical = {**source, 'user': '假如' + source['user']}
        self.assertIsNone(contact_window_state('今晚八点请提醒我', now, [hypothetical]))

    def test_dense_passage_discovery_keeps_literal_offsets_and_visible_turns(self):
        import numpy as np
        from csm_bench22_semantic_passages import SemanticPassages

        class FakeEmbedder:
            def embed(self, texts):
                return np.array([[float('材料' in text), 0.0] for text in texts])

            query_batch = embed

        records = [{'turn': 1, 'user': '起始内容\n蓝色材料另有说明'},
                   {'turn': 2, 'user': '未来材料不能出现'}]
        index = SemanticPassages(records, FakeEmbedder())
        ranked, = index.rank(['材料'], [{0}], limit=2)
        self.assertEqual(ranked, [{'turn': 1, 'field': 'user', 'start': 5, 'end': 13, 'quote': '蓝色材料另有说明'}])

    def test_unknown_state_requires_user_provenance(self):
        now = '2026-09-07T18:10:27+08:00'
        sources = {1: {'user': '日期我记混了', 'assistant': '好的'}}
        item = {'kind': 'UNKNOWN', 'entity': '用户', 'slot': '日期',
                'value': '日期未确认', 'source_turns': [1]}
        for field, quote in sources[1].items():
            item['citations'] = [{'turn': 1, 'field': field, 'quote': quote}]
            result = parse_state_items({'items': [item]}, now, sources=sources)
            self.assertEqual(len(result), int(field == 'user'))

    def test_enabled_state_producer_requires_gateway_or_extractor(self):
        with self.assertRaisesRegex(ValueError, 'state_producer_required'):
            CsmBench22(None, produce_state=True)

    def test_retrieval_has_state_first_and_evidence_separate(self):
        system = CsmBench22(None)
        system.ingest({'turn': 1, 'time': '2026-09-05T17:45:00+08:00',
                       'user': '给汤团下单了台猫饮水机\n快递后天到驿站',
                       'assistant': '好'})
        result = system.retrieve('下班了', '2026-09-07T18:10:27+08:00', 1)
        self.assertIsInstance(result, StateRetrieval)
        self.assertTrue(result.state_items)
        self.assertEqual('CLOCK', result.state_items[0]['kind'])
        self.assertTrue(result.state_text)
        self.assertTrue(result.prompt.startswith(result.state_text))
        self.assertIn('【聊天记录】', result.evidence)
        self.assertNotIn('【聊天记录】', result.state_text)
        self.assertEqual(result.state_items, result.meta['state_items'])

    def test_state_producer_replaces_explicit_empty_state(self):
        class FakeExtractor:
            def extract(self, question, evidence, now):
                return parse_state_items({'items': [{
                    'kind': 'CURRENT_CONFIRMED', 'entity': '用户', 'slot': '生日',
                    'value': '4月17日', 'source_turns': [1],
                }]}, now)

        system = CsmBench22(None, state_extractor=FakeExtractor())
        system.ingest({'turn': 1, 'time': '2026-09-05T17:45:00+08:00',
                       'user': '我是阳历4月17', 'assistant': '记下了'})
        result = system.retrieve('我生日是哪天', '2026-09-07T18:10:27+08:00', 1)
        kinds = [item['kind'] for item in result.state_items]
        self.assertIn('CURRENT_CONFIRMED', kinds)
        self.assertNotIn('NO_CONFIRMED_STATE', kinds)
        self.assertIn('用户 / 生日 = 4月17日', result.state_text)
        self.assertTrue(result.prompt.startswith(result.state_text))

    def test_empty_history_is_explicit_state_not_silence(self):
        result = CsmBench22(None).retrieve('今天几号', '2026-09-07T18:10:27+08:00', 0)
        self.assertIsInstance(result, StateRetrieval)
        self.assertEqual(['CLOCK', 'NO_CONFIRMED_STATE'], [item['kind'] for item in result.state_items])
        self.assertEqual('', result.evidence)

    def test_future_observations_cannot_change_prefix_ranking(self):
        system = CsmBench22(None)
        now = '2026-09-07T18:10:27+08:00'
        question = '账本标签是什么材质'
        for seq in range(1, 8):
            system.ingest({'turn': seq, 'time': '2026-09-05T17:45:00+08:00',
                           'user': '账本标签是黄铜。' if seq == 1 else '今天吃了面。', 'assistant': '好'})
        prefix = system.retrieve(question, now, 7)
        self.assertIn(1, prefix.used_turns)
        for seq in range(8, 48):
            system.ingest({'turn': seq, 'time': '2026-09-08T17:45:00+08:00',
                           'user': '账本标签是什么材质？' * 4, 'assistant': '账本标签是木头。'})
        for stop in (7, 47):
            current = system.retrieve(question, now, stop)
            self.assertIn(1, current.used_turns)
            self.assertEqual(prefix.used_turns, current.used_turns)
            self.assertEqual(prefix.prompt, current.prompt)

    def test_invalid_model_payload_reuses_baseline_selection_and_keeps_transport_failure_visible(self):
        class Gateway:
            def chat(self, *args, **kwargs):
                if self.fail:
                    raise RuntimeError('gateway 429')
                return {'choices': [{'finish_reason': 'length', 'message': {'content': '{"items":[]}'}}]}

        gateway = Gateway()
        gateway.fail = False
        baseline, candidate = CsmBench22(None), CsmBench22(gateway, produce_state=True)
        turn = {'turn': 1, 'time': '2026-09-05T17:45:00+08:00',
                'user': '账本标签是黄铜。', 'assistant': '好'}
        baseline.ingest(turn)
        candidate.ingest(turn)
        query = ('账本标签是什么材质', '2026-09-07T18:10:27+08:00', 1)
        expected = baseline.retrieve(*query)
        actual = candidate.retrieve(*query)
        self.assertEqual(expected.prompt, actual.prompt)
        self.assertEqual(expected.used_turns, actual.used_turns)
        self.assertEqual('state_producer_unfinished', actual.meta['state_producer_status'])
        gateway.fail = True
        with self.assertRaisesRegex(RuntimeError, '429'):
            candidate.retrieve(*query)

    def test_producer_cannot_publish_two_current_values_for_one_slot(self):
        class FakeExtractor:
            def extract(self, question, evidence, now):
                return parse_state_items({'items': [
                    {'kind': 'CURRENT_CONFIRMED', 'entity': '用户', 'slot': '标签材质',
                     'value': value, 'source_turns': [index]}
                    for index, value in enumerate(('黄铜', '木头'), 1)
                ]}, now)

        system = CsmBench22(None, state_extractor=FakeExtractor())
        for seq, value in enumerate(('黄铜', '木头'), 1):
            system.ingest({'turn': seq, 'time': '2026-09-05T17:45:00+08:00',
                           'user': f'标签是{value}。', 'assistant': '好'})
        result = system.retrieve('标签是什么材质', '2026-09-07T18:10:27+08:00', 2)
        self.assertEqual(['CLOCK', 'CONFLICT_UNRESOLVED'], [item['kind'] for item in result.state_items])
        self.assertEqual((1, 2), result.state_items[1]['source_turns'])
        system.csm.remember([MemoryCandidate('用户', '标签材质', '黄铜', source_ids=('chat/1',))])
        reviewed = system.retrieve('标签是什么材质', '2026-09-07T18:10:27+08:00', 2)
        self.assertEqual(['CLOCK', 'CURRENT_CONFIRMED'], [item['kind'] for item in reviewed.state_items])
        self.assertEqual('黄铜', reviewed.state_items[1]['value'])

    def test_unsupported_conflict_cannot_hide_a_separate_source_observation(self):
        class Extractor:
            def extract(self, question, evidence, now):
                rows = [
                    ('CONFLICT_UNRESOLVED', '黄铜或木头', 1, '标签是黄铜'),
                    ('CURRENT_CONFIRMED', '黄铜', 2, '标签是黄铜'),
                ]
                return parse_state_items({'items': [
                    {'kind': kind, 'entity': '用户', 'slot': '标签材质', 'value': value,
                     'source_turns': [turn], 'citations': [{'turn': turn, 'field': 'user', 'quote': quote}]}
                    for kind, value, turn, quote in rows
                ]}, now, sources=evidence)

        system = CsmBench22(None, state_extractor=Extractor(), validate_conflict_sources=True,
                            scope_producer_source=True)
        now = '2026-09-05T17:45:00+08:00'
        for turn in (1, 2):
            system.ingest({'turn': turn, 'time': now, 'user': '标签是黄铜。', 'assistant': '好'})
        result = system.retrieve('标签是什么材质？', now, 2)
        self.assertEqual(['CLOCK', 'PENDING_BINDING', 'SOURCE_ACCOUNT'],
                         [item['kind'] for item in result.state_items])
        self.assertNotIn('value', result.state_items[1])
        self.assertEqual('黄铜', result.state_items[2]['value'])
        self.assertEqual([1, 2], result.used_turns)

    def test_gateway_producer_validates_citations_and_temporal_state(self):
        import json

        class Gateway:
            def chat(self, model, messages, phase, tag, **options):
                request = json.loads(messages[1]['content'])
                assert phase == 'retrieve'
                assert [row['turn'] for row in request['evidence']] == [1]
                cite = {'turn': 1, 'field': 'user', 'quote': '后天'}
                due = {'kind': 'SCHEDULED', 'entity': '用户', 'slot': '快递', 'value': '快递到驿站',
                       'source_turns': [1], 'citations': [cite], 'date_anchor': cite}
                wrong = {**due, 'source_turns': [2]}
                return {'choices': [{'finish_reason': 'stop',
                                     'message': {'content': json.dumps({'items': [wrong, due]})}}]}

        system = CsmBench22(Gateway(), produce_state=True)
        system.ingest({'turn': 1, 'time': '2026-09-05T17:45:00+08:00',
                       'user': '快递后天到驿站', 'assistant': '好'})
        result = system.retrieve('下班了', '2026-09-07T18:10:27+08:00', 1)
        self.assertEqual(['CLOCK', 'DUE'], [item['kind'] for item in result.state_items])
        self.assertEqual([1], result.used_turns)
        next_day = system.retrieve('下班了', '2026-09-08T18:10:27+08:00', 1)
        self.assertEqual('no_supported_producer_output', next_day.state_items[1]['reason'])
        system.candidate_temporal_state = True
        pending = system.retrieve('下班了', '2026-09-07T18:10:27+08:00', 1)
        self.assertEqual(['CLOCK', 'PENDING_BINDING'], [item['kind'] for item in pending.state_items])
        self.assertEqual('DUE', pending.state_items[1]['projected_kind'])
        self.assertIn('2026-09-07', pending.state_text)
        self.assertIn('用户原话：后天', pending.state_text)
        self.assertNotIn('快递到驿站', pending.state_text)
        self.assertEqual([1], pending.used_turns)

    def test_separate_producer_budget_only_publishes_supplement_supporting_state(self):
        class NoLexicalMatch(CsmBench22):
            def _rank_sources(self, question, visible):
                return []

        class Producer:
            def extract(self, question, evidence, now):
                self.turns = set(evidence)
                return self.items

        producer = Producer()
        producer.items = []
        system = NoLexicalMatch(None, state_extractor=producer, separate_producer_budget=True)
        for seq, user in enumerate(('快递后天到驿站', '晴天', '茶好了', '下班了'), 1):
            system.ingest({'turn': seq, 'time': '2026-09-05T17:45:00+08:00', 'user': user, 'assistant': '好'})
        args = ('晚上好', '2026-09-07T18:10:27+08:00', 4)
        empty = system.retrieve(*args)
        self.assertEqual(producer.turns, {1, 2, 3, 4})
        self.assertNotIn(1, empty.used_turns)
        producer.items = [{'kind': 'DUE', 'text': '[DUE] 快递到驿站', 'source_turns': (1,)}]
        result = system.retrieve(*args)
        self.assertIn('快递后天到驿站', result.evidence)
        self.assertEqual(result.meta['evidence_turns'], result.used_turns)
        self.assertLessEqual(len(result.prompt), 6400)


if __name__ == '__main__':
    unittest.main()
