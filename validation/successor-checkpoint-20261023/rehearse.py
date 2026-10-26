"""Second WSC boundary from a real two-turn C archive, without inference."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'experiments'),str(ROOT/'src')]
from native_evidence import read,save,manifest,digest,file_hash
from native_rpc import NativeRPC
from native_thread_archive import archive_threads
from native_successor_checkpoint import host_origin,PendingSuccessorCheckpoint,SuccessorHostAdapter
from native_rollout_snapshot import capture_rollout
from run_native_pair import initialize,SETTINGS
from run_control_continuation import open_thread
from wsc.contracts import encode

BASE = Path('D:/agent-task-runs/wsc-bounded-command-20261023-v2')
AREA = Path('D:/agent-task-runs/wsc-successor-host-publication-20261023-v1')


def main():
    AREA.mkdir()
    reg = read(BASE/'registration.json')
    before = manifest(reg['workspace'])
    source_cell = BASE/'expanded_task/host-observation'
    origin = host_origin(source_cell/'rollout.jsonl',read(source_cell/'admission.json'),read(source_cell/'imported-items.json'))
    source_phase = read(BASE/'handoff/phase-outcome.json')
    source_path = BASE/'handoff/rollout.jsonl'
    parent_path = BASE/'checkpoint/package.json'
    parent_digest = read(BASE/'expanded_task/host-publication.json')['package_digest']
    pins = {str(p):file_hash(p) for p in [source_path,parent_path,Path(source_phase['rollout_path']),Path(__file__),
        *[p for f in ('src','tests','experiments') for p in (ROOT/f).rglob('*.py')]]}
    save(AREA/'registration.json', {'model_limit':0,'retries':0,'origin':origin,
         'source_phase':source_phase,'parent_digest':parent_digest,'pins':pins,'workspace_manifest':before})
    opened = {}
    result = {'status':'started','model_calls':0,'methods':[]}
    class Zero:
        def __init__(self,raw): self.raw=raw
        def call(self,method,params,**kwargs):
            if method not in {'initialize','plugin/list','skills/list','thread/start','thread/inject_items'}:
                raise ValueError('inference_or_commands_disabled')
            result['methods'].append(method)
            return self.raw.call(method,params,**kwargs)
        def send(self,value):
            if value != {'method':'initialized'}: raise ValueError('unregistered_notification')
            return self.raw.send(value)
    try:
        with NativeRPC(reg['executable'],cwd=reg['workspace'],stderr_path=AREA/'stderr.txt',settings=SETTINGS) as raw:
            server=Zero(raw);initialize(server)
            plugins=server.call('plugin/list',{'cwds':[reg['workspace']],'forceRefetch':False},timeout=45)
            skills=server.call('skills/list',{'cwds':[reg['workspace']],'forceReload':False},timeout=45)
            save(AREA/'discovery.json',{'plugins':plugins,'skills':skills})
            if plugins.get('marketplaceLoadErrors'): raise ValueError('plugin_discovery_failed')
            cell=AREA/'successor';cell.mkdir()
            target=open_thread(server,reg,cell);opened['successor']=target
            pending=PendingSuccessorCheckpoint(AREA/'checkpoint',reg['workspace'],source_path,source_phase,
                read(BASE/'expanded_task/acceptance/receipt.json'),BASE/'expanded_task/acceptance/receipt.json',
                origin=origin,parent_path=parent_path,parent_digest=parent_digest)
            fact={'type':'message','role':'developer','content':[{'type':'input_text','text':encode({
                'kind':'successor_transport_observation','current_workspace':reg['workspace'],
                'current_file_manifest_sha256':digest(before),'task_execution':'not_started'})}]}
            items=pending.import_into(server,target,cell,fact)
            package=read(AREA/'checkpoint/package.json')
            host_cell=cell/'host-observation'
            adapter=pending.adapter_for(capture_rollout(host_cell/'rollout.jsonl'),read(host_cell/'admission.json'),read(host_cell/'imported-items.json'))
            adapter.validate_dependencies()
            original=[r['payload'] for r in capture_rollout(source_path).rows
                      if r['type']=='response_item' and r['payload']['type']=='message']
            assert original[:len(adapter.prefix)]==adapter.prefix
            assert package['items'][:-1]==original[len(adapter.prefix):]
            result.update(status='second_boundary_published_and_imported',imported_items=len(items),
                unchanged_task_messages=len(package['items'])-1,cold_dependency_files=len(adapter.dependencies),
                ancestor_packages=adapter.ancestors,package_digest=package['package_digest'],
                rendered_bytes=len(encode(package['items']).encode('utf-8')),
                source_turn_id=source_phase['usage_completion_evidence']['turn_id'],
                source_accounting_scope=read(BASE/'handoff/registration.json')['accounting_scope'],
                scope='Second boundary transport from actual C history, not new task execution or semantic benefit.')
    except Exception as exc:
        result.update(status='stopped',error=type(exc).__name__+':'+str(exc))
    finally:
        result['archives']=archive_threads(AREA,opened)
        counts=[v.get('receipts',{}).get('response_count') for v in result['archives'].values()]
        result['actual_responses']=sum(counts) if len(counts)==1 and all(type(v) is int for v in counts) else None
        result['workspace_unchanged']=manifest(reg['workspace'])==before
        result['pins_unchanged']=all(file_hash(p)==h for p,h in pins.items())
        save(AREA/'result.json',result)
        print(json.dumps({k:v for k,v in result.items() if k not in {'archives','ancestor_packages'}},ensure_ascii=False))


if __name__=='__main__': main()
