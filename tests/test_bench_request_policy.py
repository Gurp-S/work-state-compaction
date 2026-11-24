"""Request preservation and no paid retries on rejected response envelopes."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'benchmarks'))
import bench_llm
from bench_request_policy import configure, TextEnvelopeError


def response(finish='stop', content='answer', **extra):
    return {'choices': [{'finish_reason': finish, 'message': {'content': content, **extra}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 3}}


class RequestPolicyTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'CSM_BENCH_API_KEY': 'test-only-credential',
            'CSM_BENCH_TRANSPORT_POLICY': 'text-only'})
        self.env.start(); self.addCleanup(self.env.stop)

    def ask(self, data):
        chat = bench_llm.Chat(max_tokens=800)
        http = SimpleNamespace(status_code=200, raise_for_status=Mock(), json=lambda: data)
        with patch.object(bench_llm.requests, 'post', return_value=http) as post:
            try:
                return chat.ask('system', 'question'), chat, post
            finally:
                self.assertEqual(post.call_count, 1)
                self.assertEqual(chat.calls, 1)
                self.assertEqual(chat.completion_tokens, 3)

    def test_request_policy_preserves_messages_and_budget(self):
        original = {'messages': [{'role': 'user', 'content': 'original'}], 'max_tokens': 800}
        self.assertIs(configure(original, 'legacy'), original)
        selected = configure(original, 'text-only')
        self.assertEqual(selected['messages'], original['messages'])
        self.assertEqual(selected['max_tokens'], 800)
        self.assertEqual(selected['thinking'], {'type': 'disabled'})
        self.assertEqual(selected['tool_choice'], 'none')
        self.assertNotIn('thinking', original)

    def test_length_empty_and_tool_results_fail_without_retry(self):
        for data in (response('length', 'partial'), response(content=''),
                     response('tool_calls', 'checking'),
                     response(tool_calls=[{'function': {'name': 'pwsh'}}]),
                     response(reasoning_content='unexpected reasoning')):
            with self.subTest(data=data), self.assertRaises(TextEnvelopeError):
                self.ask(data)

    def test_valid_answer_and_explicit_parameters_reach_http(self):
        answer, chat, post = self.ask(response())
        self.assertEqual(answer, 'answer')
        payload = post.call_args.kwargs['json']
        self.assertEqual(payload['thinking'], {'type': 'disabled'})
        self.assertEqual(payload['tool_choice'], 'none')
        self.assertEqual(payload['max_tokens'], 800)

    def test_legacy_client_does_not_inject_the_new_policy(self):
        data = response(content='old response')
        data['choices'][0].pop('finish_reason')
        with patch.dict(os.environ, {'CSM_BENCH_TRANSPORT_POLICY': 'legacy'}):
            answer, _, post = self.ask(data)
        self.assertEqual(answer, 'old response')
        self.assertNotIn('thinking', post.call_args.kwargs['json'])
        self.assertNotIn('tool_choice', post.call_args.kwargs['json'])

    def test_unknown_policy_fails_before_credentials_or_network(self):
        with patch.dict(os.environ, {'CSM_BENCH_TRANSPORT_POLICY': 'unknown'}), \
             patch.object(bench_llm, '_key') as key:
            with self.assertRaises(ValueError):
                bench_llm.Chat()
        key.assert_not_called()

    def test_semantic_purposes_keep_low_thinking_and_format_disables_it(self):
        payload = {'messages': [], 'max_tokens': 800}
        for purpose in ('answer', 'handoff', 'select', 'extract', 'resolve', 'judge'):
            configured = configure(payload, 'purpose-routed', purpose)
            self.assertEqual(configured['thinking'], {'type': 'enabled'})
            self.assertEqual(configured['reasoning_effort'], 'low')
            self.assertEqual(configured['max_tokens'], 800)
        configured = configure(payload, 'purpose-routed', 'format')
        self.assertEqual(configured['thinking'], {'type': 'disabled'})
        self.assertNotIn('reasoning_effort', configured)
        with self.assertRaises(ValueError):
            configure(payload, 'purpose-routed', 'unknown')

    def test_purpose_routed_client_accepts_reasoning_with_complete_answer(self):
        data = response(reasoning_content='test reasoning')
        data['usage']['completion_tokens_details'] = {'reasoning_tokens': 2}
        with patch.dict(os.environ, {'CSM_BENCH_TRANSPORT_POLICY': 'purpose-routed'}):
            answer, _, post = self.ask(data)
        self.assertEqual(answer, 'answer')
        self.assertEqual(post.call_args.kwargs['json']['reasoning_effort'], 'low')

    def test_new_policy_does_not_retry_timeout_with_unknown_server_outcome(self):
        chat = bench_llm.Chat()
        with patch.object(bench_llm.requests, 'post', side_effect=bench_llm.requests.Timeout('test timeout')) as post:
            with self.assertRaises(bench_llm.requests.Timeout):
                chat.ask('system', 'question')
        self.assertEqual(post.call_count, 1)


if __name__ == '__main__':
    unittest.main()
