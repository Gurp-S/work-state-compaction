"""One native transport rehearsal with inference RPCs disabled at the caller."""
from pathlib import Path
import json
import sys

from audit import ROOT, source_boundary, project, require
from native_evidence import read, save, file_hash, digest, manifest, import_evidence, usage
from native_rollout_snapshot import capture_rollout
from native_pair_admission import observe
from native_rpc import NativeRPC
from native_thread_archive import archive_threads
from run_control_continuation import open_thread
from run_native_pair import initialize, import_items, SETTINGS


class TransportOnly:
    def __init__(self, server):
        self.server, self.methods = server, []

    def call(self, method, params, **kwargs):
        require(method in {'initialize', 'thread/start', 'thread/inject_items'}, 'inference_or_unregistered_rpc_disabled')
        self.methods.append(method)
        return self.server.call(method, params, **kwargs)

    def send(self, value):
        require(value == {'method': 'initialized'}, 'unregistered_notification_disabled')
        self.methods.append('initialized')
        return self.server.send(value)


def main(source, prior, area, sandbox='read-only'):
    require(sandbox in {'read-only', 'workspace-write'}, 'transport_sandbox_invalid')
    require(not area.exists(), 'transport_probe_already_exists')
    area.mkdir(parents=True)
    old = read(prior / 'registration.json')
    reg = {'workspace': old['workspace'], 'executable': old['executable'],
           'purpose': 'native_transport_only_no_turn_or_compaction', 'new_inference_limit': 0,
           'sandbox': sandbox}
    inputs = [source / 'source_task/admission.json', source / 'source_task/registration.json',
              source / 'source_task/phase-outcome.json', source / 'native-rollout-archive/source.jsonl',
              prior / 'checkpoint/package.json', Path(reg['executable']),
              Path(__file__).resolve(), Path(__file__).with_name('audit.py')]
    config = Path.home() / '.codex/config.toml'
    if config.exists():
        inputs.append(config)
    reg['pins'] = {str(p.resolve()): file_hash(p) for p in inputs}
    reg['workspace_manifest'] = manifest(reg['workspace'])
    save(area / 'registration.json', reg)
    phase, admission, source_reg = read(inputs[2]), read(inputs[0]), read(inputs[1])
    snap = capture_rollout(inputs[3])
    require(snap.metadata['parse_complete'] and snap.metadata['sha256'] == phase['rollout_sha256'], 'source_changed')
    prefix = source_boundary([r['payload'] for r in snap.rows if r['type'] == 'response_item'], admission, source_reg, phase)
    keys = [f"native:{phase['thread_id']}:{i}:{digest(p)}" for i,p in enumerate(prefix)]
    package = read(inputs[4])
    opened, result = {}, {'status': 'started', 'inference_calls': 0}
    try:
        with NativeRPC(reg['executable'], cwd=reg['workspace'], stderr_path=area / 'stderr.txt', settings=SETTINGS) as raw:
            server = TransportOnly(raw)
            initialize(server)
            value = open_thread(server, reg, area, read_only=sandbox == 'read-only')
            opened['transport'] = value
            initial = area / 'initial'
            initial.mkdir()
            marker = [{'type': 'message', 'role': 'assistant', 'phase': 'commentary',
                       'content': [{'type': 'output_text', 'text': json.dumps({
                           'kind': 'transport_observation', 'registration': file_hash(area / 'registration.json'),
                           'task_execution': 'not_requested'})}]}]
            import_items(server, value, marker, initial)
            current = observe(value, marker)
            require(current['response_count'] == 0, 'unexpected_inference')
            save(area / 'actual-host.json', current)
            candidate, _ = project(package['items'], prefix, keys, package['evidence'], current)
            cell = area / 'candidate'
            cell.mkdir()
            import_items(server, value, candidate, cell)
            observed = capture_rollout(value['thread']['path'])
            evidence = import_evidence([r['payload'] for r in observed.rows if r['type'] == 'response_item'], candidate)
            require(evidence['matched'] and usage(observed.rows, value['thread']['id'])['response_count'] == 0,
                    'transport_evidence_missing_or_inference_observed')
            save(area / 'import-evidence.json', evidence)
            result.update(status='native_import_verified_no_inference', rpc_methods=server.methods,
                          user_bootstrap_coverage_verified=True, original_package_sha256=file_hash(inputs[4]),
                          candidate_sha256=digest(candidate))
    except Exception as exc:
        result.update(status='failed_preserved', error=type(exc).__name__ + ':' + str(exc))
    finally:
        result['archives'] = archive_threads(area, opened)
        result['workspace_unchanged'] = manifest(reg['workspace']) == reg['workspace_manifest']
        result['pins_unchanged'] = all(file_hash(p) == h for p,h in reg['pins'].items())
        result['scope'] = 'Transport RPCs only; no inference or command execution. Not semantic qualification, atomic installation or token benefit.'
        save(area / 'result.json', result)
    print(json.dumps({k:v for k,v in result.items() if k != 'archives'}, ensure_ascii=False))


if __name__ == '__main__':
    main(*(Path(value).resolve() for value in sys.argv[1:4]),
         sandbox=sys.argv[4] if len(sys.argv) > 4 else 'read-only')
