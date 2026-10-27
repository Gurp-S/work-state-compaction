"""Zero-inference live fork/config admission for black-box behavior probes."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments'))
from native_owned_process import OwnedNativeRPC
from native_host_controls import settings
from native_recursive_fork import seal,observe
from dataset import canonical


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--registration',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    spec=json.loads(args.registration.read_text(encoding='utf-8'))
    reg=spec['sessions']['B'] if 'sessions' in spec else spec
    if sha256(Path(reg['executable']).read_bytes()).hexdigest()!=reg['executable_sha256']:
        raise ValueError('registered_cli_changed')
    work=args.out/'public-workspace';work.mkdir()
    result=dict(model_calls=0,turn_start_sent=False,compact_start_sent=False,passed=False,
        executable_sha256=reg['executable_sha256'],requested_model=reg['model'],requested_effort=reg['effort'])
    server=None
    def save(name,value):(args.out/name).write_text(canonical(value),encoding='utf-8')
    def raw(path):
        path=Path(path);deadline=time.monotonic()+3
        while not path.exists() and time.monotonic()<deadline:time.sleep(.05)
        return path.read_bytes()
    try:
        server=OwnedNativeRPC(reg['executable'],cwd=work,stderr_path=args.out/'stderr.txt',settings=settings({
            'effort':reg['effort'],'host_feature_overrides':reg.get('host_feature_overrides',{})}))
        save('initialized.json',server.call('initialize',dict(clientInfo=dict(name='blackbox_admission',version='1'),capabilities=dict(experimentalApi=True))));server.send(dict(method='initialized'))
        params=dict(cwd=str(work),model=reg['model'],approvalPolicy='never',sandbox='read-only',
                    runtimeWorkspaceRoots=[str(work)],ephemeral=False)
        parent=server.call('thread/start',{**params,'allowProviderModelFallback':False,'dynamicTools':[]})
        save('parent.json',parent)
        if parent['model']!=reg['model'] or parent['reasoningEffort']!=reg['effort']:
            raise ValueError('native_model_or_effort_mismatch')
        items=[dict(type='message',role='assistant',content=[dict(type='output_text',text=canonical(dict(
            record_type='blackbox_capability_fixture',fixture_id='same-history-1',value=41)))])]
        save('inject.json',server.call('thread/inject_items',dict(threadId=parent['thread']['id'],items=items)))
        parent_path=Path(parent['thread']['path']);before=raw(parent_path)
        histories=[]
        for name in ('uncompressed-sibling','compression-sibling'):
            opened=server.call('thread/fork',dict(**params,threadId=parent['thread']['id'],
                excludeTurns=True,deferGoalContinuation=True),timeout=35)
            save(name+'.json',opened)
            data=raw(opened['thread']['path'])
            binding=seal(data,{parent['thread']['id']:str(parent_path)},args.out/(name+'-ancestry'))
            observed=observe(data,binding)
            if any(r['type']=='token_usage_record' for r in observed['local_rows']+observed['inherited_rows']):
                raise ValueError('unregistered_inference_observed')
            histories.append(observed['evidence']['effective_items_sha256'])
            if opened['model']!=parent['model'] or opened['reasoningEffort']!=parent['reasoningEffort']:
                raise ValueError('fork_model_or_effort_changed')
        if len(set(histories))!=1 or parent_path.read_bytes()!=before:
            raise ValueError('sibling_history_or_parent_changed')
        result.update(passed=True,sibling_effective_history_sha256=histories[0],
            parent_sha256=sha256(before).hexdigest(),same_history_verified=True,
            limitations=['No model response or new compression was executed.',
                'Internal summarizer model/temperature/seed are not verified.',
                'This confirms live branch setup, not post-compaction behavior quality.'])
    except Exception as error:result['error']=type(error).__name__+':'+str(error)
    finally:
        result['cleanup']=server.close() if server else dict(empty_confirmed=True,process_started=False)
        save('result.json',result)
    print(canonical({k:result[k] for k in ('model_calls','passed','cleanup','error') if k in result}))


if __name__=='__main__':main()
