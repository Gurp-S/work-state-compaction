"""Targeted before/after: cleanup errors cannot suppress known phase evidence."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
from native_evidence import read, save, file_hash
from native_application_session import NativeApplicationSession

PROBE = Path('D:/agent-task-runs/wsc-native-history-materialization-20261025-v1')


class BrokenCleanup:
    def call(self, *args, **kwargs):
        raise RuntimeError('fixture_disconnect')

    def close(self):
        raise RuntimeError('fixture_cleanup_failure')


def observe(cls):
    with tempfile.TemporaryDirectory() as folder:
        area = Path(folder)
        work = area / 'workspace'
        work.mkdir()
        session = cls(dict(workspace=str(work), model='gpt-6-luna', effort='max'), area / 'session')
        session.server = BrokenCleanup()
        opened = read(PROBE / 'thread-start.json')
        path = area / 'history.jsonl'
        path.write_bytes((PROBE / 'rollout.jsonl').read_bytes())
        opened['thread']['path'] = str(path)
        session.opened = opened
        journal, error = [], None
        try:
            session.execute_stage('Fixture', area / 'stage',
                dict(max_responses=1, max_seconds=5, max_total_tokens=100), journal.append)
        except RuntimeError as exc:
            error = str(exc)
        return dict(error=error, journal_entries=len(journal), receipt_persisted=(area / 'stage/phase-outcome.json').exists(),
                    termination_error=journal[0].get('termination_error') if journal else None)


before_source = HERE / 'before-cleanup-guard.py.txt'
namespace = {'__name__': 'before_cleanup_guard'}
exec(compile(before_source.read_text(encoding='utf8'), str(before_source), 'exec'), namespace)
before = observe(namespace['NativeApplicationSession'])
after = observe(NativeApplicationSession)
assert before['journal_entries'] == 0 and not before['receipt_persisted']
assert after['journal_entries'] == 1 and after['receipt_persisted'] and after['termination_error']
save(HERE / 'cleanup-guard-check.json', dict(before=before, after=after, model_calls=0,
    before_sha256=file_hash(before_source), current_sha256=file_hash(ROOT / 'experiments/native_application_session.py'),
    scope='Synthetic simultaneous disconnect and cleanup failure; no paid-stage replay'))
print(after)
