"""Zero-inference source-tool registration and snapshot read admission."""
from pathlib import Path
from contextlib import closing
import argparse,json,sqlite3,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1')]
from wsc import WSC,Store
from wsc.source_access import SnapshotSourceAccess
from native_source_tool import SOURCE_TOOL,SourceToolHandler
from native_evidence import read,save,file_hash,manifest
from native_blackbox_sessions import fresh
from native_rollout_snapshot import capture_rollout


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','registration','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False);begin=time.monotonic()
    path=args.out/'state.db'
    with closing(sqlite3.connect(args.source/'state.db')) as source,closing(sqlite3.connect(path)) as target:source.backup(target)
    with closing(sqlite3.connect(path)) as db:bound=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
    core=WSC(Store(path,session_id=bound['session_id'],workspace=bound['workspace']),access=lambda *a:True,query_policy='prefix_index_v1')
    reader=SnapshotSourceAccess(core.store,core.capture(),access=core.access);handler=SourceToolHandler(reader)
    found=reader.find('build-003');assert found['complete'] and any(m['source']=='s6' for m in found['matches'])
    restored=reader.read('s6');target=read(args.source.parent/'dataset.public.json')['prefix'][5]['content'][0]['text']
    assert restored['text']==target
    save(args.out/'mechanical-read.json',dict(found=found,restored=restored))
    base=read(args.registration)['sessions']['B'];reg={**base,'workspace':bound['workspace'],'sandbox':'read-only','initial_manifest':manifest(bound['workspace'])}
    for key in ('browser_cache','native_c_auto_compaction','parent_thread_id','parent_paths','before_turn_id'):reg.pop(key,None)
    session=None;result=dict(model_calls=0,passed=False)
    try:
        session=fresh(reg,args.out/'tool-session',dynamic_tools=[SOURCE_TOOL])
        session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=[dict(type='message',role='assistant',content=[dict(type='output_text',text='{"record_type":"source_access_admission/1"}')])]))
        snap=capture_rollout(session.opened['thread']['path'],archive=args.out/'tool-registration.jsonl')
        if not snap.metadata['parse_complete'] or any(r['type']=='token_usage_record' for r in snap.rows):raise ValueError('unexpected_inference_or_bad_source')
        meta=next(r['payload'] for r in snap.rows if r['type']=='session_meta')
        tools=meta.get('dynamic_tools')
        if not tools or not any(t.get('name')=='WSCSource' for t in tools):raise ValueError('dynamic_source_tool_registration_unobserved')
        result.update(passed=True,source_tool_registered=True,mechanical_target_read_equal=True,
            source_scope=reader.describe(),provider_callback_executed=False,scope='Tool registration and engine source reads only; no tested-model recovery or benefit claim.')
    except Exception as error:result['error']=type(error).__name__+':'+str(error)
    finally:
        result['cleanup']=session.close() if session else None;result['seconds']=time.monotonic()-begin
        save(args.out/'result.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
