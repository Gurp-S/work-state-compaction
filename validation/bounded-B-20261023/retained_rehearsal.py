"""Zero-inference retained-pair publication rehearsal using existing mechanisms."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'experiments'), str(ROOT/'src')]
from native_evidence import read, save, manifest, digest, file_hash
from native_group_admission import NativeGroupAdmission
from native_host_checkpoint import PendingHostCheckpoint
from native_pair_admission import observe
from native_thread_archive import archive_threads
from native_rpc import NativeRPC
from native_runtime_probe import verify_runtime
from run_control_continuation import open_thread
from run_native_pair import initialize, import_items, SETTINGS
from wsc.contracts import encode

BASE = Path('D:/agent-task-runs/wsc-bounded-command-20261023-v2')
AREA = Path('D:/agent-task-runs/wsc-retained-host-publication-20261023-v1')


def main():
    AREA.mkdir()
    reg = read(BASE/'registration.json')
    before = manifest(reg['workspace'])
    source = read(BASE/'source_task/phase-outcome.json')
    source_hash = file_hash(source['rollout_path'])
    result = {'status':'started', 'model_calls':0, 'methods':[]}
    opened = {}

    class ZeroInference:
        def __init__(self, raw): self.raw = raw
        def call(self, method, params, **kwargs):
            allowed = {'initialize','plugin/list','skills/list','command/exec','thread/start','thread/inject_items'}
            if method not in allowed:
                raise ValueError('inference_or_resume_disabled')
            result['methods'].append(method)
            return self.raw.call(method, params, **kwargs)
        def send(self, value):
            if value != {'method':'initialized'}: raise ValueError('unregistered_notification')
            return self.raw.send(value)

    save(AREA/'registration.json', {'purpose':'retained_pair_transport_only', 'model_limit':0,
         'retries':0, 'workspace':reg['workspace'], 'initial_manifest':before,
         'source_rollout_sha256':source_hash, 'driver_sha256':file_hash(__file__)})
    try:
        with NativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=AREA/'stderr.txt', settings=SETTINGS) as raw:
            server = ZeroInference(raw)
            initialize(server)
            verify_runtime(server, reg['workspace'], reg['runtime_command'], AREA/'runtime-preflight')
            plugins = server.call('plugin/list', {'cwds':[reg['workspace']], 'forceRefetch':False}, timeout=45)
            skills = server.call('skills/list', {'cwds':[reg['workspace']], 'forceReload':False}, timeout=45)
            save(AREA/'discovery.json', {'plugins':plugins,'skills':skills})
            if plugins.get('marketplaceLoadErrors'): raise ValueError('plugin_discovery_failed')
            controls = [{'type':'message', 'role':'developer', 'content':[{'type':'input_text', 'text':encode({
                'kind':'retained_thread_transport_observation', 'current_workspace':reg['workspace'],
                'current_file_manifest_sha256':digest(before), 'task_execution':'not_started'})}]}]
            admissions = {}
            for name in ('B','C'):
                cell = AREA/name; cell.mkdir()
                opened[name] = open_thread(server, reg, cell)
                import_items(server, opened[name], controls, cell)
                admissions[name] = observe(opened[name], controls)
                save(cell/'admission.json', admissions[name])
            gate = NativeGroupAdmission(admissions, members={'B','C'})
            save(AREA/'paired-admission.json', {'host_sha256':digest(admissions['B']['host']),
                 'thread_ids':{k:v['thread_id'] for k,v in admissions.items()}, 'model_calls':0})
            pending = PendingHostCheckpoint(AREA/'checkpoint', reg['workspace'], BASE/'source_task/rollout.jsonl',
                source, read(BASE/'source_task/acceptance/receipt.json'),
                BASE/'source_task/acceptance/receipt.json', BASE/'source_task')
            current = {name:observe(opened[name], controls) for name in opened}
            destination = AREA/'retained-C-import'; destination.mkdir()
            items = gate.execute('C', current,
                lambda:pending.import_into(server, opened['C'], destination, controls[0]))
            result.update(status='retained_pair_publication_verified', imported_item_count=len(items),
                publication=read(destination/'host-publication.json'),
                scope='Retained target import only. No task inference, native compaction, semantic or long-horizon claim.')
    except Exception as exc:
        result.update(status='stopped', error=type(exc).__name__+':'+str(exc))
    finally:
        result['archives'] = archive_threads(AREA, opened)
        result['workspace_unchanged'] = manifest(reg['workspace']) == before
        result['source_thread_unchanged'] = file_hash(source['rollout_path']) == source_hash
        result['actual_responses'] = sum(v.get('receipts',{}).get('response_count',0) for v in result['archives'].values())
        save(AREA/'result.json',result)
        print(json.dumps({k:v for k,v in result.items() if k not in {'archives','publication'}},ensure_ascii=False))


if __name__ == '__main__': main()
