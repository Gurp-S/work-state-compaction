"""Replay actual bound callbacks, before/after, without model dispatch."""
from pathlib import Path
from contextlib import closing
import argparse,sys,json,sqlite3
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments')]
from wsc import WSC,Store,WSCError
from wsc.source_access import SnapshotSourceAccess
from native_source_tool import SourceToolHandler
from native_source_tool_budget import BudgetResultSourceToolHandler
from native_evidence import read,save,file_hash


def main():
    parser=argparse.ArgumentParser()
    for name in ('source','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
    events=[json.loads(line) for line in (args.source/'selection/events.jsonl').read_text().splitlines()]
    events=[value for value in events if value.get('method')=='item/tool/call']
    trace=read(args.source/'source-tool-trace.json');source_db=args.source/'state.db';before_hash=file_hash(source_db)
    path=args.out/'clone.db'
    with closing(sqlite3.connect(source_db)) as before,closing(sqlite3.connect(path)) as after:before.backup(after)
    with closing(sqlite3.connect(path)) as db:binding=json.loads(db.execute("SELECT value FROM meta WHERE key='binding'").fetchone()[0])
    core=WSC(Store(path,session_id=binding['session_id'],workspace=binding['workspace']),access=lambda *a:True)
    snapshot=core.capture();old=SourceToolHandler(SnapshotSourceAccess(core.store,snapshot,access=core.access))
    new=BudgetResultSourceToolHandler(SnapshotSourceAccess(core.store,snapshot,access=core.access))
    failure=None;replies=[]
    for index,event in enumerate(events):
        kwargs=dict(thread_id=event['params']['threadId'],turn_id=event['params']['turnId'])
        try:previous=old.handle(event,**kwargs)
        except WSCError as error:failure=str(error);previous=None
        reply=new.handle(event,**kwargs);replies.append(reply)
        if index<len(trace):
            assert json.loads(reply['result']['contentItems'][0]['text'])==trace[index]['output']
            assert previous==reply
        else:
            assert failure=='source_tool_callback_budget_exhausted'
            assert reply['result']['success'] is False
    assert len(events)>len(trace)==8 and new.reader.calls==old.reader.calls==8
    assert len(new.seen)==len(new.trace)==8 and file_hash(source_db)==before_hash
    result=dict(passed=True,model_calls=0,callbacks_replayed=len(events),unchanged_successful_results=len(trace),
        old_failure=failure,new_refused_callbacks=new.refused_callbacks,old_reads=old.reader.calls,new_reads=new.reader.calls,
        source_database_unchanged=True,scope='Protocol and fixed access cap only; no claim the model subsequently completes selection or QA.',
        evidence_sha256={key:file_hash(args.source/key) for key in ['selection/events.jsonl','source-tool-trace.json','state.db']})
    save(args.out/'replies.json',replies);save(args.out/'result.json',result);print(json.dumps(result))


if __name__=='__main__':main()
