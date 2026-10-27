"""Reuse one completed native selection after JSON-domain gate repair. No LLM."""
from pathlib import Path
from contextlib import closing
import argparse,json,sqlite3,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1')]
from native_evidence import read,save,file_hash
from native_rollout_snapshot import capture_rollout
from native_generation_binding import verify_transcript
from native_selection_wire import normalize_draft,transport_value,transport_equal,restore
from native_span_handles import expand
from native_incremental_candidate import compile_draft,POLICY
from native_incremental_compile import compile_choice
from native_indexed_checkpoint import IndexedCheckpointAdapter
from wsc import WSC,Store,Limits
from wsc.source_reference_view import MODE
from wsc.publication import check_evidence
from blackbox_recovery_case import build,tool_recovery_evidence


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    phase=read(args.source/'C2-selection/phase-outcome.json')
    if not phase.get('completed') or not phase.get('usage_complete') or phase.get('failure') or len(phase.get('finals',[]))!=1:raise ValueError('draft_not_closed')
    snapshot=capture_rollout(args.source/'C2-selection/rollout.jsonl')
    if snapshot.metadata['sha256']!=phase['rollout_sha256']:raise ValueError('draft_source_changed')
    proof,actual=verify_transcript(snapshot,phase)
    expected=read(args.source/'C2-generation/request.json')
    if not transport_equal(actual,expected):raise ValueError('actual_request_changed')
    bindings=read(args.source/'C2-generation/wire-bindings.json');manifest=read(args.source/'C2-generation/resource-manifest.json')
    restored=restore(actual['material'],manifest,bindings)
    draft=normalize_draft(json.loads(phase['finals'][0]['text']),bindings)
    draft=expand(draft,read(args.source/'C2-generation/span-handle-bindings.json'))
    path=args.out/'state.db'
    with closing(sqlite3.connect(args.source/'state.db')) as source,closing(sqlite3.connect(path)) as target:source.backup(target)
    with closing(sqlite3.connect(path)) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
    core=WSC(Store(path,session_id=binding['session_id'],workspace=binding['workspace']),access=lambda *a:True,
        resource_io=__import__('wsc.resource_io',fromlist=['ResourceIO']).ResourceIO(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')
    current=core.capture();material=core.material(current);previous=read(args.source/'C1-continuation.json')
    selection=compile_choice(material,previous,draft,compile_draft)
    view=core.prepare(current,selection,producer=POLICY['id'],limits=Limits(max_material_bytes=POLICY['max_material_bytes'],max_view_bytes=POLICY['max_view_body_bytes']),source_projection=MODE)
    op=core.stage(view,directory=args.out/'exports',archive_directory=args.out/'cold-objects',adapter=IndexedCheckpointAdapter())
    package=core.package(op);check_evidence(core,package)
    public=read(args.source.parent/'dataset.public.json');target_message=public['prefix'][5]
    target_source_id=read(args.source/'result.json')['target_source_id']
    restored_by_selection=target_source_id in selection.source_ids and target_message in package['items']
    target=json.loads(target_message['content'][0]['text'])
    source_object=next(e for e in material['events'] if e['id']==target_source_id)
    evidence=tool_recovery_evidence(snapshot.rows,manifest,source_object,target)
    save(args.out/'package.json',package);save(args.out/'selection.json',dict(source_ids=list(selection.source_ids),retained_excerpt_keys=draft.get('retained_excerpt_keys',[])))
    save(args.out/'result.json',dict(status='compiled_and_staged',new_model_calls=0,
        original_phase_sha256=file_hash(args.source/'C2-selection/phase-outcome.json'),original_source=str(args.source),
        request_binding=proof,json_transport_request_matches=True,wire_roundtrip_valid=True,
        selected_old_source_rehydrated_exactly=restored_by_selection,model_tool_recovery=evidence,
        original_usage_failures_preserved=True,view=view,operation=op,
        checkpoint_semantics='Actual previous model choice compiled through unchanged policy; old source restored from WSC store. No new selection, no fake host receipt.',
        query_quality='Not yet measured. Native import and tested-model answer still required.'))
    print(json.dumps(dict(status='compiled_and_staged',new_model_calls=0,selected_old_source_rehydrated_exactly=restored_by_selection)))


if __name__=='__main__':main()
