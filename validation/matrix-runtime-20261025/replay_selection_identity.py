"""Before/after on the exact model draft. No model retry and no success rewrite."""
from pathlib import Path
import json
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0, str(ROOT / 'experiments'))
sys.path.insert(0, str(ROOT / 'src'))
from native_incremental_candidate import prepare
from native_evidence import read, save, file_hash, digest
from wsc import WSC, Store
from wsc.contracts import Event, Usage
from wsc.quote_selection import SelectionDraft

OLD = Path('D:/agent-task-runs/wsc-live-boundary-qualification-20261025-v1')
draft = read(OLD / 'selection/model-draft.json')
offered = read(OLD / 'selection/request.json')['material']
old_version = ROOT / 'versions/20261025-incremental-candidate-study-freeze-v1-delta.zip'
with zipfile.ZipFile(old_version) as archive:
    source = archive.read('experiments/native_incremental_candidate.py').decode()
namespace = {'__name__': 'old_incremental_policy', '__file__': str(ROOT / 'experiments/native_incremental_candidate.py')}
exec(compile(source, 'archived-v1-candidate', 'exec'), namespace)


def replay(prepare_function):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        original = WSC(Store(OLD / 'state.db', session_id='qualification-C', workspace=read(OLD / 'registration.json')['workspace']), access=lambda *a: True)
        events = original.capture().events
        core = WSC(Store(root / 'state.db', session_id='qualification-C', workspace=original.store.workspace), access=lambda *a: True)
        core.ingest([Event(**{k: v for k, v in row.items() if k != 'seq'}) for row in events])
        try:
            result = prepare_function(core, core.capture(), None, root / 'cold',
                lambda actual: SelectionDraft(draft, Usage()))
            with core.store.connect() as db:
                body = json.loads(db.execute('SELECT data FROM views WHERE id=?', (result['view'],)).fetchone()[0])['body']
            return dict(passed=True, selected_sources=[row['id'] for row in body['sources']],
                        clues=body['clues'], excerpts=body.get('excerpts', []))
        except ValueError as error:
            return dict(passed=False, error=str(error))


before = replay(namespace['prepare'])
after = replay(prepare)
assert not before['passed'] and before['error'] == 'quote_source_missing'
assert after['passed']
assert set(draft['source_ids']) <= set(after['selected_sources'])
assert [c['text'] for c in draft['clues']] == [c['text'] for c in after['clues']]
assert len(after['excerpts']) == len(draft['span_refs'])
save(HERE / 'selection-identity-replay.json', dict(before=before, after=after,
    original_draft_path=str(OLD / 'selection/model-draft.json'), original_draft_sha256=file_hash(OLD / 'selection/model-draft.json'),
    current_source_sha256=file_hash(ROOT / 'experiments/native_incremental_candidate.py'),
    old_attempt_remains_failed=True, model_calls=0,
    scope='Exact displayed IDs compiled without changing selections, clues or quoted spans; no semantic model retry'))
print(dict(before=before['error'], after=after['passed'], model_calls=0))
