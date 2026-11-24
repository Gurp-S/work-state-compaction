"""Real version/store boundaries plus a local model-protocol fixture."""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'benchmarks')]
from wsc.csm import CSM, Event, MemoryCandidate
from wsc.csm.cem.source_tools import SourceToolSession
from test_csm_source_inspection import MemoryStore
import source_tool_loop as loop
import bench_llm


def final(text='The source says the person was hurt.'):
    return {'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': text}}],
            'usage': {'completion_tokens': 20}}


def call(handle='r1', call_id='read-1', name='csm_read_source'):
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': '',
        'reasoning_content': 'fixture trace kept across the tool exchange',
        'tool_calls': [{'id': call_id, 'type': 'function', 'function': {'name': name,
            'arguments': json.dumps({'handle': handle})}}]}}], 'usage': {'completion_tokens': 30}}


class FakeChat:
    def __init__(self, replies): self.replies, self.requests = replies, []
    def exchange(self, messages, **kwargs):
        self.requests.append(copy.deepcopy({'messages': messages, **kwargs}))
        return copy.deepcopy(self.replies[len(self.requests) - 1])


class SourceToolTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore(); self.addCleanup(self.store.db.close)
        self.core = CSM(self.store, clock=lambda: '2026-01-10T00:00:00Z')
        self.value = 'Person had a setback recently.'
        self.core.ingest([Event('source', 'chat', {'turns': [{'speaker': 'Person', 'dia_id': '1',
            'text': 'Recently I had a setback. I got hurt last month.', 'img_url': ['original']} ]},
            observed_at='2026-01-01T00:00:00Z')])
        result = self.core.remember([MemoryCandidate('Person', 'setback', self.value, source_ids=('source',))])[0]
        row = self.store.db.execute('SELECT data FROM revisions WHERE memory_id=? AND revision=1',
                                    (result['memory_id'],)).fetchone()
        self.primary = [{**json.loads(row['data']), 'entity': 'Person', 'slot': 'setback'}]
        self.rendered = json.dumps([{'entity': 'Person', 'slot': 'setback', 'value': self.value, 'status': 'current'}])

    def run_loop(self, chat):
        return loop.answer(chat, self.core, 'What happened?', self.primary, self.rendered, 'existing benchmark prompt')

    def test_optional_tool_is_model_selected_and_history_preserves_trace(self):
        chat = FakeChat([call(), final()]); before = self.store.db.total_changes
        result = self.run_loop(chat)
        self.assertIn('hurt', result['answer'])
        self.assertEqual(result['source_tool']['source_reads'], 1)
        self.assertLessEqual(result['source_tool']['source_chars'], 4000)
        self.assertEqual(chat.requests[0]['tool_choice'], 'auto')
        self.assertEqual(chat.requests[1]['messages'][2]['reasoning_content'], 'fixture trace kept across the tool exchange')
        tool = chat.requests[1]['messages'][3]
        self.assertEqual(tool['role'], 'tool'); self.assertEqual(tool['tool_call_id'], 'read-1')
        self.assertIn('got hurt', tool['content'])
        self.assertEqual(self.store.db.total_changes, before)

    def test_model_can_answer_without_reading(self):
        chat = FakeChat([final()]); result = self.run_loop(chat)
        self.assertEqual(len(chat.requests), 1)
        self.assertEqual(result['source_tool']['source_reads'], 0)

    def test_rendered_identity_or_value_cannot_redirect_a_handle(self):
        session = SourceToolSession(self.core, self.primary)
        changed = json.loads(self.rendered)
        changed[0]['entity'] = 'Someone else'
        with self.assertRaisesRegex(ValueError, 'alignment'):
            session.catalogue(json.dumps(changed))
        changed[0]['entity'] = 'Person'
        changed[0]['value'] += ' (on a rendered date)'
        packet = session.catalogue(json.dumps(changed))
        self.assertFalse(session.handles)
        self.assertNotIn('source_handle', packet['items'][0])

    def test_unknown_handle_and_json_fields_cannot_probe_other_memories(self):
        session = SourceToolSession(self.core, self.primary)
        for args in ('{"handle":"unoffered"}', '{"handle":"r1","revision":2}'):
            result = json.loads(session.execute('csm_read_source', args))
            self.assertIn('error', result)
        self.assertEqual(session.reads, 2)
        with self.assertRaises(ValueError): session.execute('csm_read_source', '{"handle":"r1"}')

    def test_ambiguous_or_mismatched_version_gets_no_handle(self):
        wrong = [{**self.primary[0], 'revision': 99}]
        self.assertFalse(SourceToolSession(self.core, wrong).handles)
        with self.store.transaction() as db:
            record = dict(self.primary[0]); record['revision'] = 2
            db.execute('INSERT INTO revisions(memory_id,revision,data) VALUES(?,?,?)',
                (record['memory_id'], 2, json.dumps(record)))
        without_revision = [{k: v for k, v in self.primary[0].items() if k != 'revision'}]
        self.assertFalse(SourceToolSession(self.core, without_revision).handles)

    def test_pending_does_not_become_a_revision_or_current_world_fact(self):
        pending = [{**self.primary[0], 'pending_id': 'proposal'}]
        session = SourceToolSession(self.core, pending)
        row = session.catalogue(self.rendered)['items'][0]
        self.assertFalse(session.handles)
        self.assertEqual(row['classification'], 'PENDING_BINDING')
        self.assertFalse(row['confirmed'])

    def test_two_reads_then_final_request_has_no_tools(self):
        chat = FakeChat([call(), call(call_id='read-2'), final()])
        result = self.run_loop(chat)
        self.assertEqual(len(chat.requests), 3)
        self.assertEqual(chat.requests[-1]['tool_choice'], 'none')
        self.assertEqual(chat.requests[-1]['tools'], [])
        self.assertEqual(result['source_tool']['reads'][1]['result']['error'], 'source_tool_source_already_returned')

    def test_unknown_tool_or_oversized_batch_never_executes(self):
        with patch.object(self.core, 'source_evidence') as read:
            with self.assertRaises(loop.SourceToolRunError):
                self.run_loop(FakeChat([call(name='pwsh')]))
            oversized = call(); oversized['choices'][0]['message']['tool_calls'] *= 3
            with self.assertRaises(loop.SourceToolRunError): self.run_loop(FakeChat([oversized]))
        read.assert_not_called()

    def test_length_is_not_an_executable_tool_call(self):
        data = call(); data['choices'][0]['finish_reason'] = 'length'
        with patch.object(self.core, 'source_evidence') as read, self.assertRaises(loop.SourceToolRunError):
            self.run_loop(FakeChat([data]))
        read.assert_not_called()

    def test_large_input_fails_before_any_model_call(self):
        chat = FakeChat([])
        with self.assertRaisesRegex(loop.SourceToolRunError, 'catalogue_budget'):
            loop.answer(chat, self.core, 'q', self.primary,
                        json.dumps([{'entity': 'Person', 'slot': 'setback', 'value': 'x' * 25000}]), 'system')
        self.assertFalse(chat.requests)

    def test_digest_failure_after_offering_is_not_hidden_by_a_fallback(self):
        session = SourceToolSession(self.core, self.primary)
        with self.store.transaction() as db:
            db.execute('UPDATE events SET data=? WHERE id=?', ('{"text":"changed"}', 'source'))
        result = json.loads(session.execute('csm_read_source', '{"handle":"r1"}'))
        self.assertIn('digest_mismatch', result['error'])
        self.assertNotIn('result', result)


class TransportTests(unittest.TestCase):
    def test_failed_http_retains_usage_and_is_never_retried(self):
        data = {'error': 'incomplete', 'usage': {'prompt_tokens': 23, 'completion_tokens': 15}}
        response = Mock(status_code=502, text=json.dumps(data))
        response.json.return_value = data
        response.raise_for_status.side_effect = RuntimeError('HTTP 502')
        with patch.dict(os.environ, {'CSM_BENCH_API_KEY': 'test-only-credential'}): chat = bench_llm.Chat()
        with patch('bench_tool_transport.requests.post', return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError, '502'):
                chat.exchange([], tools=[], tool_choice='none')
        self.assertEqual(post.call_count, 1)
        self.assertEqual((chat.calls, chat.prompt_tokens, chat.completion_tokens), (1, 23, 15))
        self.assertEqual(chat.tool_exchanges[0]['status'], 'failed')

    def test_native_tool_reply_keeps_reasoning_and_has_no_retry(self):
        data = call(); data.update(model=bench_llm.MODEL, _wb_contract={'saw_done': True, 'saw_explicit_finish': True})
        response = Mock(status_code=200, text=json.dumps(data)); response.json.return_value = data
        with patch.dict(os.environ, {'CSM_BENCH_API_KEY': 'test-only-credential'}): chat = bench_llm.Chat()
        with patch('bench_tool_transport.requests.post', return_value=response) as post:
            result = chat.exchange([{'role': 'user', 'content': 'question'}],
                tools=[{'type': 'function', 'function': {'name': 'csm_read_source'}}], tool_choice='auto')
        self.assertEqual(post.call_count, 1)
        self.assertIn('reasoning_content', result['choices'][0]['message'])
        payload = json.loads(post.call_args.kwargs['data'])
        self.assertTrue(payload['_wb_strict_chat_contract'])
        self.assertFalse(payload['parallel_tool_calls'])
