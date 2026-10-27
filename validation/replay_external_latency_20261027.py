"""One actual local publication/import replay, with all inference forbidden."""
from pathlib import Path
from contextlib import closing
from types import SimpleNamespace
import argparse,sqlite3,json,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1')]
from native_latency import LatencyRecorder,attach,summarize
from native_evidence import read,save,file_hash,manifest
from native_blackbox_sessions import fresh
from native_study_fork_session import NativeForkSession
from native_rollout_snapshot import capture_rollout
from native_selector_runtime import PROFILE
from native_source_tool import SOURCE_TOOL,SourceToolHandler,checked_description
from native_incremental_candidate import frontier,compile_draft,POLICY
from native_incremental_compile import compile_choice
from native_incremental_generation import output_schema
from native_selection_wire import project as project_wire
from native_span_handles import project as project_spans
from native_event_table import project as project_table
from native_indexed_checkpoint import IndexedCheckpointAdapter
from blackbox_group_runner import fork_registration,effective,import_receiver,cold_entries
from blackbox_resource_probe import verify_paths
from wsc import WSC,Store,Limits
from wsc.resource_io import ResourceIO
from wsc.snapshot_literal_access import SnapshotLiteralAccess
from wsc.source_reference_view import MODE
from wsc.publication import check_evidence


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','candidate','registration','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();source=args.source/'R01';candidate=args.candidate/'candidate'
    if not read(args.candidate/'table-run-audit.json')['passed']:raise ValueError('completed_candidate_not_audited')
    before=file_hash(source/'state.db');args.out.mkdir(parents=True,exist_ok=False)
    timer=LatencyRecorder(args.out/'timing.jsonl');sessions={};result=dict(status='started',model_calls=0);begin=time.monotonic()
    try:
        with timer.span('replay.total'):
            with timer.span('wsc.clone_state'):
                path=args.out/'state.db'
                with closing(sqlite3.connect(source/'state.db')) as a,closing(sqlite3.connect(path)) as b:a.backup(b)
                with closing(sqlite3.connect(path)) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
                core=WSC(Store(path,session_id=binding['session_id'],workspace=binding['workspace']),access=lambda *a:True,
                    resource_io=ResourceIO(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')
            snapshot=timer.call('wsc.capture',core.capture);previous=read(source/'C1-continuation.json')
            material,offered=timer.call('wsc.frontier_and_cold_publication',frontier,core,snapshot,previous,args.out/'cold-public')
            reader=timer.call('wsc.source_reader_construction',SnapshotLiteralAccess,core.store,snapshot,access=core.access)
            with timer.span('wsc.input_projection'):
                offered={**offered,'source_access':checked_description(offered,SourceToolHandler(reader).describe())}
                short,handles=project_spans(offered);schema=output_schema(short,source_aliases_only=True)
                wire,resources,aliases=project_wire(short,args.out/'resources.json');wire,table=project_table(wire)
                save(args.out/'projection.json',dict(schema_bytes=len(json.dumps(schema).encode()),event_table_applied=table['applied']))
            base=read(args.registration)['sessions']['B'];reg={**base,'workspace':binding['workspace'],'sandbox':'read-only','initial_manifest':manifest(binding['workspace'])}
            for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):reg.pop(key,None)
            with timer.span('integration.selector_start'):
                selector=fresh(reg,args.out/'selector-session',dynamic_tools=[SOURCE_TOOL],selector_runtime=PROFILE)
                sessions['selector']=attach(selector,timer,'selector',deny_inference=True)
                selector.server.call('thread/inject_items',dict(threadId=selector.opened['thread']['id'],items=[dict(type='message',role='assistant',content=[dict(type='output_text',text='{"record_type":"source_selection_runtime/1"}')])]))
            with timer.span('qualification.selector_manifest_check'):
                loc=wire['cold_source_manifest'];verify_paths(selector,[dict(path=loc['path'],sha256=loc['sha256'])],args.out/'manifest-access.json')
            with timer.span('wsc.compile_prepare'):
                draft=read(candidate/'generation/compiled-draft.json');selection=compile_choice(material,previous,draft,compile_draft)
                view=core.prepare(snapshot,selection,producer=read(candidate/'registration.json')['policy'],limits=Limits(max_material_bytes=POLICY['max_material_bytes'],max_view_bytes=POLICY['max_view_body_bytes']),source_projection=MODE)
            with timer.span('wsc.stage_and_evidence_validation'):
                op=core.stage(view,directory=args.out/'exports',archive_directory=args.out/'cold-objects',adapter=IndexedCheckpointAdapter())
                package=core.package(op);check_evidence(core,package)
            boot=SimpleNamespace(opened=read(args.source/'bootstrap-session/opened.json'),registration={})
            parent=SimpleNamespace(opened=read(source/'parent-session/thread-fork.json'),fork_binding=read(source/'parent-session/ancestry/binding.json'))
            public=read(args.source/'dataset.public.json')
            bootstrap=effective(parent,Path(parent.opened['thread']['path']).read_bytes())[:-(len(public['prefix'])+len(public['delta']))]
            with timer.span('integration.receiver_start'):
                receiver=NativeForkSession(fork_registration(reg,boot),args.out/'receiver-session');sessions['receiver']=receiver
                receiver.open();attach(receiver,timer,'receiver',deny_inference=True)
            with timer.span('integration.receiver_import'):
                import_receiver(receiver,package['items'],bootstrap,args.out/'receiver-session')
            with timer.span('qualification.receiver_cold_access_check'):
                verify_paths(receiver,cold_entries(package),args.out/'receiver-access.json')
            timer.call('wsc.discard_staged_operation',core.discard,op)
            with timer.span('qualification.probe_fork'):
                probe=NativeForkSession(fork_registration(reg,receiver),args.out/'probe-session');sessions['probe']=probe
                probe.open();attach(probe,timer,'probe',deny_inference=True)
            result['status']='completed'
    except Exception as error:result.update(status='failed_preserved',error=type(error).__name__+':'+str(error))
    finally:
        with timer.span('integration.cleanup'):
            result['cleanup']={name:session.close() for name,session in sessions.items()}
        timer.close();result['seconds']=time.monotonic()-begin
        for session in sessions.values():
            if session.opened:
                rows=capture_rollout(session.opened['thread']['path']).rows
                if any(r['type']=='token_usage_record' for r in rows):raise ValueError('zero_model_replay_inference_observed')
        result['source_database_unchanged']=file_hash(source/'state.db')==before
        if not result['source_database_unchanged'] or any(not x['empty_confirmed'] for x in result['cleanup'].values()):result['status']='failed_preserved'
        result['timing']=summarize(args.out/'timing.jsonl');save(args.out/'result.json',result)
    print(json.dumps(dict(status=result['status'],model_calls=0,seconds=result['seconds'],error=result.get('error'))))


if __name__=='__main__':main()
