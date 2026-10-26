"""Scoped stage failure/completion checks and one actual zero-inference open."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_application_session import NativeApplicationSession
from native_evidence import read, save, manifest, file_hash

HERE = Path(__file__).parent
PROBE = Path('D:/agent-task-runs/wsc-native-history-materialization-20261025-v1')


class FakeRPC:
    def __init__(self, events=(), fail=False):
        self.events = list(events)
        self.fail = fail
        self.calls = []

    def call(self, method, params, **kwargs):
        self.calls.append(method)
        if self.fail:
            raise RuntimeError('fixture_transport_disconnect')
        return {'turn': {'id': 'current-turn'}}

    def event(self, **kwargs):
        return self.events.pop(0)

    def close(self):
        return {'empty_confirmed': True, 'fixture': True}


class StageChecks(unittest.TestCase):
    def session(self, root, rpc):
        work = root / 'workspace'
        work.mkdir()
        (work / 'README.md').write_text('fixture', encoding='utf8')
        session = NativeApplicationSession(dict(workspace=str(work), model='gpt-6-luna', effort='max'), root / 'session')
        session.server = rpc
        session.opened = deepcopy(read(PROBE / 'thread-start.json'))
        path = root / 'fixture-history.jsonl'
        path.write_bytes((PROBE / 'rollout.jsonl').read_bytes())
        session.opened['thread']['path'] = str(path)
        return session

    def test_other_turn_completion_cannot_finish_current_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tid = read(PROBE / 'thread-start.json')['thread']['id']
            events = [{'method': 'turn/completed', 'params': {'threadId': tid, 'turn': {'id': name, 'status': status}}}
                      for name, status in [('other-turn', 'failed'), ('current-turn', 'completed')]]
            rpc = FakeRPC(events)
            session = self.session(root, rpc)
            journal = []
            result = session.execute_stage('Fixture request', root / 'stage',
                dict(max_responses=3, max_seconds=5, max_total_tokens=100), journal.append)
            self.assertTrue(result['completed'])
            self.assertEqual(len(journal), 1)
            self.assertFalse(result['usage_complete'])  # Event alone is not a paid receipt.
            self.assertFalse(rpc.events)
            session.close()

    def test_start_disconnect_is_journaled_and_closes_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            session = self.session(root, FakeRPC(fail=True))
            journal = []
            result = session.execute_stage('Fixture request', root / 'stage',
                dict(max_responses=3, max_seconds=5, max_total_tokens=100), journal.append)
            self.assertEqual(len(journal), 1)
            self.assertIn('fixture_transport_disconnect', result['failure'])
            self.assertTrue(session.closed)
            self.assertFalse(result['usage_complete'])
            self.assertTrue((root / 'stage/phase-outcome.json').is_file())
            with self.assertRaisesRegex(ValueError, 'not_live'):
                session.execute_stage('Retry', root / 'retry', {}, journal.append)


result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StageChecks))
save(HERE / 'session-fixture-checks.json', dict(tests=result.testsRun, passed=result.wasSuccessful(),
    failures=[str(i) for i in result.failures + result.errors], model_calls=0,
    source_sha256=file_hash(ROOT / 'experiments/native_application_session.py'),
    scope='Synthetic event matching and disconnect journaling; no paid native stage executed'))
assert result.wasSuccessful()

AREA = Path('D:/agent-task-runs/wsc-native-application-open-20261025-v1')
AREA.mkdir()
work = AREA / 'workspace'
work.mkdir()
(work / 'README.md').write_text('Native application session preflight.\n', encoding='utf8')
exe = Path('C:/Users/48522/AppData/Local/OpenAI/Codex/bin/2993767bd1dfb009/codex.exe')
reg = dict(workspace=str(work), initial_manifest=manifest(work), executable=str(exe), executable_sha256=file_hash(exe),
           model='gpt-6-luna', effort='max', purpose='zero_inference_new_session_open', inference_calls_allowed=0)
save(AREA / 'registration.json', reg)
session = NativeApplicationSession(reg, AREA / 'session')
try:
    opened = session.open()
    outcome = dict(status='opened_without_inference', observed_model=opened['model'],
                   opened_sha256=file_hash(AREA / 'session/opened.jsonl'), model_calls=0)
finally:
    cleanup = session.close()
outcome['cleanup'] = cleanup
save(AREA / 'result.json', outcome)
print(json.dumps(outcome))
