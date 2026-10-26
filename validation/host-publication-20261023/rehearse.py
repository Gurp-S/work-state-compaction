"""Exercise the runtime publication/import hook with inference RPCs unavailable."""
from pathlib import Path
import json
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'experiments'), str(ROOT / 'src')]
from native_evidence import read, save, digest, file_hash, manifest, usage, import_evidence
from native_host_checkpoint import PendingHostCheckpoint
from native_rollout_snapshot import capture_rollout
from native_thread_archive import archive_threads
from native_rpc import NativeRPC
from run_native_pair import initialize, SETTINGS
from run_control_continuation import open_thread
from wsc import Store, WSC
from wsc.adapters.recorded_codex import RecordedCodexCheckpointAdapter
from wsc.contracts import encode


class TransportOnly:
    def __init__(self, raw):
        self.raw, self.methods = raw, []

    def call(self, method, params, **kwargs):
        if method not in {'initialize', 'thread/start', 'thread/inject_items'}:
            raise ValueError('inference_or_command_rpc_disabled')
        self.methods.append(method)
        return self.raw.call(method, params, **kwargs)

    def send(self, value):
        if value != {'method': 'initialized'}:
            raise ValueError('unregistered_notification')
        self.methods.append('initialized')
        return self.raw.send(value)


def main(area):
    area.mkdir(exist_ok=False)
    source = Path('D:/agent-task-runs/wsc-control-continuation-20261023-v1')
    old = read(source / 'registration.json')
    source_cell = source / 'source_task'
    rollout = source / 'native-rollout-archive/source.jsonl'
    phase = read(source_cell / 'phase-outcome.json')
    receipt_path = source / 'interrupted-offline-acceptance/receipt.json'
    source_paths = [rollout, receipt_path, source_cell / 'phase-outcome.json',
                    source_cell / 'registration.json', source_cell / 'admission.json']
    source_paths += [p for f in ('src', 'tests', 'experiments') for p in (ROOT / f).rglob('*.py')]
    source_paths += [Path(__file__), Path(old['executable']), Path.home() / '.codex/config.toml']
    reg = {'purpose': 'host_bound_publication_transport_only', 'workspace': old['workspace'],
           'executable': old['executable'], 'inference_limit': 0, 'retries': 0,
           'workspace_manifest': manifest(old['workspace']),
           'pins': {str(p.resolve()): file_hash(p) for p in source_paths}}
    save(area / 'registration.json', reg)
    pending = PendingHostCheckpoint(area / 'checkpoint', reg['workspace'], rollout, phase,
                                    read(receipt_path), receipt_path, source_cell)
    opened, result = {}, {'status': 'started', 'model_calls': 0}
    try:
        with NativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=area / 'stderr.txt', settings=SETTINGS) as raw:
            server = TransportOnly(raw)
            initialize(server)
            cell = area / 'target'
            cell.mkdir()
            target = open_thread(server, reg, cell)
            opened['transport'] = target
            fact = {'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': encode({
                'kind': 'transport_observation', 'task_execution': 'not_requested',
                'current_workspace': reg['workspace'], 'current_file_manifest_sha256': digest(reg['workspace_manifest'])})}]}
            supplied = pending.import_into(server, target, cell, fact)
            package = read(area / 'checkpoint/package.json')
            summary = read(area / 'checkpoint/result.json')
            core = WSC(Store(area / 'checkpoint/state.db', session_id='checkpoint', workspace=reg['workspace']),
                       access=lambda *args: True)
            assert core.package(summary['operation']) == package
            with sqlite3.connect(area / 'checkpoint/state.db') as db:
                body = json.loads(db.execute('SELECT data FROM views WHERE id=?', (summary['view'],)).fetchone()[0])['body']
            baseline = RecordedCodexCheckpointAdapter().render(body, core.capture().events, package['binding']['cut'],
                package['evidence'], source_index=package['source_index'], understanding_index=package['understanding_index'])
            save(area / 'baseline-items.json', baseline)
            n = len(package['adapter']['host_context_binding']['source_ids'])
            tail = baseline[n:]
            candidate = package['items']
            assert candidate[:-1] == tail[:-1]
            facts = json.loads(candidate[-1]['content'][0]['text'])
            host = facts.pop('historical_host_context')
            assert facts == json.loads(tail[-1]['content'][0]['text'])
            for entry, original in zip(host['sources'], baseline[:n]):
                assert file_hash(entry['path']) == entry['sha256'] and read(entry['path']) == original
            snapshot = capture_rollout(target['thread']['path'], archive=area / 'imported-rollout.jsonl')
            proof = import_evidence([r['payload'] for r in snapshot.rows if r['type']=='response_item'], supplied)
            assert proof['matched'] and usage(snapshot.rows, target['thread']['id'])['response_count'] == 0
            save(area / 'import-evidence.json', proof)
            result.update(status='published_and_imported_without_inference', methods=server.methods,
                          before_item_bytes=len(encode(baseline).encode()), after_item_bytes=len(encode(candidate).encode()),
                          task_tail_unchanged=True, cold_host_values_verified=True,
                          package_digest=package['package_digest'], publication_state='ready', cursor=core.status()['cursor'])
    except Exception as exc:
        result.update(status='failed_preserved', error=type(exc).__name__ + ':' + str(exc))
    finally:
        result['archives'] = archive_threads(area, opened)
        result['workspace_unchanged'] = manifest(reg['workspace']) == reg['workspace_manifest']
        result['pins_unchanged'] = all(file_hash(p)==h for p,h in reg['pins'].items())
        result['scope'] = 'Same published view rendered by old/new adapters; real native import; no task execution or token-benefit claim.'
        save(area / 'result.json', result)
    print(json.dumps({k:v for k,v in result.items() if k!='archives'},ensure_ascii=False))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
