"""New S2->S3 development admission, preserving source events and model choices."""
from dataclasses import fields
import json
from pathlib import Path
import shutil
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, file_hash, manifest
from native_fixture_transport import attach
from native_incremental_candidate import frontier, compile_draft, POLICY, admit_rendered
from native_indexed_checkpoint import IndexedCheckpointAdapter
from wsc import WSC, Store
from wsc.contracts import Event, Limits, encode
from wsc import events
from wsc.source_reference_view import MODE
from wsc.publication import check_evidence

COMMON = Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1')
OUT = Path('D:/agent-task-runs/wsc-a3-dev-C-20261026-v1')


def prepare(*, OUT=OUT, runtime_workspace=None):
    OUT = Path(OUT)
    OUT.mkdir(exist_ok=False)
    template = COMMON / 'staged/frozen-workspace'
    capsule = read(COMMON / 'staged/capsule.json')
    assert manifest(template) == capsule['source_manifest']
    for path in ('wsc-a3-c-continuation-20261026-v1', 'wsc-a3-closeout-20261026-v1', 'wsc-a3-capsule-review-20261026-v1'):
        result = read(Path('D:/agent-task-runs') / path / 'result.json')
        assert result['cleanup']['empty_confirmed'] and not result['ledger']['inflight']
    payload = read(COMMON / 'staged/payload-C.json')
    oldwork = Path(runtime_workspace or payload['registration']['workspace']).resolve()
    work = (OUT / 'workspace').resolve()
    shutil.copytree(template, work)
    assert manifest(work) == capsule['source_manifest']
    # Closed private dependency/runtime directories move once; source and prior
    # evidence stay at their old paths. No dependency duplication or deletion.
    moves = []
    for relative in ('gui/node_modules', '.wsc-runtime/browsers'):
        source = (oldwork / relative).resolve(); target = (work / relative).resolve()
        assert oldwork in {Path('D:/agent-task-runs/wsc-a3-common-prefix-20261025-v1/arms/C/workspace').resolve(),
            Path('D:/agent-task-runs/wsc-a3-dev-C-20261026-v1/workspace').resolve()}
        assert work.is_relative_to(OUT.resolve()) and source.is_relative_to(oldwork) and target.is_relative_to(work)
        assert source.is_dir() and not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        moves.append(dict(source=str(source), target=str(target)))
    save(OUT / 'runtime-move-plan.json', moves)
    for value in moves: Path(value['source']).rename(value['target'])
    save(OUT / 'runtime-move-completed.json', moves)
    shutil.copyfile(oldwork / '.wsc-runtime/browser-capability.mjs', work / '.wsc-runtime/browser-capability.mjs')
    reg = {**payload['registration'], 'workspace': str(work), 'initial_manifest': capsule['source_manifest'],
        'browser_cache': str(work / '.wsc-runtime/browsers'), 'browser_probe': str(work / '.wsc-runtime/browser-capability.mjs'),
        'parent_thread_id': payload['common_prefix']['reset_parent_thread_id'],
        'before_turn_id': payload['common_prefix']['reset_before_turn_id']}
    frozen = read(read(COMMON / 'registration.json')['tasks']['a3']['binding'])['workspace']
    reg = attach(reg, frozen)
    source = sqlite3.connect('file:' + str(COMMON / 'arms/C/output/wsc.db') + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    original_events = events.rows(source)
    presentations = [(row['id'], json.loads(row['data'])) for row in source.execute('SELECT id,data FROM presentations')]
    source.close()
    core = WSC(Store(OUT / 'state.db', session_id='a3/dev-C-v1/C', workspace=str(work)), access=lambda *args: True)
    keys = {field.name for field in fields(Event)}
    core.ingest([Event(**{key: row[key] for key in keys}) for row in original_events])
    for request_id, value in presentations:
        core.presented(request_id, tuple(value['source_ids']), receiver=value['receiver'])
    snapshot = core.capture()
    assert list(snapshot.events) == original_events
    old_package = read(COMMON / 'indexed-view-replay-v2/package.json')
    assert snapshot.source_digest == old_package['binding']['source_digest']
    material, offered = frontier(core, snapshot, None, OUT / 'cold-public')
    draft_path = COMMON / 'arms/C/output/S2-generation/compiled-draft.json'
    draft = read(draft_path); assert not draft.pop('retained_excerpt_keys', [])
    selection = compile_draft(material, draft)
    view = core.prepare(snapshot, selection, producer=POLICY['id'], source_projection=MODE,
        limits=Limits(max_view_bytes=POLICY['max_view_body_bytes']))
    operation = core.stage(view, directory=OUT / 'exports', archive_directory=OUT / 'cold-objects', adapter=IndexedCheckpointAdapter())
    package = admit_rendered(core.package(operation)); check_evidence(core, package)
    assert package['binding']['workspace'] == str(work)
    old_selection = read(COMMON / 'indexed-view-replay-v2/package.json')
    assert set(package['excerpt_evidence']) == set(old_selection['excerpt_evidence'])
    save(OUT / 'package.json', package)
    core.discard(operation)
    save(OUT / 'prepared.json', dict(registration=reg, request=payload['stages'][2]['request'],
        source_digest_unchanged=True, original_events_unchanged=True,
        original_draft=str(draft_path), original_draft_sha256=file_hash(draft_path),
        package=str(OUT / 'package.json'), package_sha256=file_hash(OUT / 'package.json'),
        rendered_bytes=len(encode(package['items']).encode()), selected_sources=len(selection.source_ids),
        excerpts=len(selection.excerpts), source_template=str(template), template_sha256=capsule['source_manifest'],
        model_calls=0, scope='Independent S2->S3 development admission from exact archived choices; not formal B/C'))
    print(dict(prepared=True, model_calls=0, source_digest_unchanged=True, sources=len(selection.source_ids), excerpts=len(selection.excerpts)), flush=True)


if __name__ == '__main__': prepare()
