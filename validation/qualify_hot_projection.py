"""Reuse three real drafts; optional native install, all without inference."""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks'),str(ROOT/'benchmarks/deterministic_v1'),str(ROOT/'validation')]
from wsc import WSC,Store,Event,Selection
from wsc.contracts import encode
from wsc.source_access import SnapshotSourceAccess,SourceAccessLimits
from wsc.source_reference_view import MODE
from wsc.resource_io import ResourceIO
from native_hot_checkpoint import POLICY,HotCheckpointAdapter,project_text,engine_items,load_projection,validate_hot_recovery_aliases
from native_task_recovery import open_task_receiver
from acceptance_matrix_v1.paired_cell import Cell,NativeCheckpointHost,save
from run_matrix_first_slice import file_hash

BASE=Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1')
REPEATS=Path('D:/agent-task-runs/wsc-matrix-two-repetitions-20261029-v1')


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def replay(folder,out):
    package=read(folder/'coordinator-private/C/publication.json')['package']
    reference=package['adapter']['projection_evidence'];metadata=load_projection(reference)
    candidates=[index for index,item in enumerate(package['items']) if any(block.get('text','').startswith('{"archive":') for block in item.get('content',[]))]
    if len(candidates)!=1:raise ValueError('indexed_actor_state_not_unique')
    index=candidates[0];text=package['items'][index]['content'][0]['text']
    hot=deepcopy(package)
    hot['items'][index]['content'][0]['text']=project_text(text,metadata,reference)
    hot['adapter'].update(actor_projection_policy=POLICY,hot_working_state_index=index)
    if engine_items(hot)!=package['items']:raise ValueError('replayed_native_items_changed')
    database=folder/'coordinator-private/C/state.db';before=file_hash(database)
    shutil.copyfile(database,out/'state-copy.db')
    core=WSC(Store(out/'state-copy.db',session_id=package['binding']['session_id'],workspace=package['binding']['workspace']),
        access=lambda *a:True,resource_io=ResourceIO())
    snapshot=core.capture()
    if snapshot.cut!=package['binding']['cut']:raise ValueError('recorded_source_cut_changed')
    reader=SnapshotSourceAccess(core.store,snapshot,access=core.access,limits=SourceAccessLimits(max_calls=64))
    validate_hot_recovery_aliases(hot,reader)
    aliases=metadata['header']['source_aliases']
    for alias,value in aliases.items():
        if reader.read(alias)['original_source_id']!=value['source_id']:raise ValueError('replayed_source_changed')
    if file_hash(database)!=before:raise ValueError('original_database_changed')
    save(out/'diagnostic-items.json',dict(original_items=package['items'],hot_items=hot['items'],
        projection_reference=reference,scope='Offline diagnostic, not a resealed or installed publication.'))
    return dict(all_items_roundtrip_equal=True,verified_aliases=len(aliases),original_database_unchanged=True,
        original_text_bytes=len(text.encode('utf-8')),hot_text_bytes=len(hot['items'][index]['content'][0]['text'].encode('utf-8')),
        original_items_sha256=sha256(encode(package['items']).encode('utf-8')).hexdigest(),
        scope='Same recorded model choices and every literal section. Cloned DB independently verifies aliases; no model or original DB writes.')


def native(out,executable):
    root=out/'native';root.mkdir();(root/'coordinator-private').mkdir()
    for name in ('C','Bprime','C-selector'):(root/name).mkdir()
    plan=dict(executable=str(executable.resolve()),executable_sha256=file_hash(executable),model=dict(model='gpt-6.1-sol',effort='max'),
        actor_projection_policy=POLICY,blocked=[str(root/'coordinator-private')])
    save(root/'registration.json',dict(**plan,model_calls=0,scope='Native import/receipt only; no model task or compaction.'))
    cell=Cell('C',plan,root,None,{})
    core=WSC(Store(cell.folder/'state.db',session_id='hot-native-fixture',workspace=str(cell.work)),access=lambda *a:True,resource_io=ResourceIO())
    core.ingest([Event('user','message',dict(type='message',role='user',content=[dict(type='input_text',text='状态样本')]),role='user',text='状态样本'),
        Event('source','observation',{'value':2},text='{"value":2}',observed_at='t1')])
    snapshot=core.capture();view=core.prepare(snapshot,Selection(source_ids=('source',)),producer='deterministic-fixture',source_projection=MODE)
    reader=SnapshotSourceAccess(core.store,snapshot,access=core.access);holder={}
    def factory(**kwargs):
        session,bootstrap=cell.open('receiver',**kwargs);holder['bootstrap']=bootstrap;return session
    port=None
    try:
        port=open_task_receiver(factory,reader)
        operation=core.stage(view,directory=cell.folder/'export',adapter=HotCheckpointAdapter())
        receipt=core.install(operation,NativeCheckpointHost(port,holder['bootstrap'],cell.folder/'receiver-session'))
        return dict(installed=True,receipt=receipt,model_calls=0,scope='Actual native fresh import and engine confirmation, not task-quality proof.')
    finally:
        cleanups=[cell.close_session(session) for session in cell.sessions]
        save(root/'cleanup.json',cleanups)


def main(out,executable=None):
    out.mkdir(parents=True,exist_ok=False)
    results={}
    for label,folder in [('r1',BASE),('r2',REPEATS/'r2'),('r3',REPEATS/'r3')]:
        target=out/label;target.mkdir();results[label]=replay(folder,target)
    result=dict(policy=POLICY,model_calls=0,replays=results,default_adapter_changed=False)
    result['source_sha256']={str(path):file_hash(path) for path in [Path(__file__).resolve(),
        ROOT/'experiments/native_hot_checkpoint.py',ROOT/'experiments/native_indexed_checkpoint.py',
        ROOT/'experiments/native_snapshot_aliases.py',ROOT/'benchmarks/acceptance_matrix_v1/paired_cell.py']}
    save(out/'replay-results.json',result)
    if executable:
        try:result['native_admission']=native(out,executable)
        except BaseException as error:
            save(out/'qualification-error.json',dict(type=type(error).__name__,error=str(error),model_calls=0))
            raise
    save(out/'results.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--executable',type=Path)
    args=parser.parse_args();main(args.out.resolve(),args.executable)
