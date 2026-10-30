"""No inference: current answer inventory, named native thread, exact history import."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'experiments'), str(ROOT/'benchmarks'), str(ROOT/'benchmarks/deterministic_v1')]
from acceptance_matrix_v1.permissions import permission_flags, PROFILE
from acceptance_matrix_v1.inventory import private_inventory
from native_blackbox_sessions import fresh, import_fresh
from native_evidence import state
from native_rollout_snapshot import capture_rollout


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--selector-runtime')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    readiness = json.loads((ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json').read_text(encoding='utf-8'))
    registration = json.loads((ROOT/'reviews/acceptance-matrix-admission-20261028/registration.draft.json').read_text(encoding='utf-8'))
    fixture = Path(registration['tasks']['T1']['fixture_root'])
    work, private, peer = [args.out.resolve()/name for name in ('public-workspace', 'coordinator-private', 'other-arm')]
    shutil.copytree(fixture/'public-starter', work)
    private.mkdir()
    peer.mkdir()
    (work/'canary.txt').write_text('public-canary', encoding='utf-8')
    (private/'canary.txt').write_text('private-canary', encoding='utf-8')
    (peer/'canary.txt').write_text('peer-canary', encoding='utf-8')
    fixture_roots = {Path(p).parent.resolve() for p in readiness['task_fixture_roots'].values()}
    fixture_roots.add(Path(readiness['task_fixture_superseded']).resolve())
    prior_t4 = Path('D:/agent-task-runs/wsc-matrix-t4-admission-20261028-v1')
    if prior_t4.exists():
        fixture_roots.add(prior_t4)
    inventory, fixture_roots = private_inventory(ROOT, readiness)
    blocked = sorted(set(inventory) | {private, peer})
    probes = [work/'canary.txt', private/'canary.txt', peer/'canary.txt',
              ROOT/'benchmarks/acceptance_matrix_v1/task_specs.py',
              ROOT/'benchmarks/acceptance_matrix_v1/calibration/retry_reference.py',
              ROOT/'tests/test_matrix_t2_t5_acceptors.py', ROOT/'versions/matrix-five-task-calibration-v1.46-delta.zip']
    for root in sorted(fixture_roots):
        candidates = sorted(root.rglob('oracle.json')) or sorted(root.rglob('reference-acceptance.json'))
        if not candidates:
            raise ValueError('private_inventory_file_missing:'+str(root))
        probes.append(candidates[0])
    hasher = sha256()
    with args.executable.open('rb') as stream:
        for part in iter(lambda: stream.read(1024*1024), b''):
            hasher.update(part)
    reg = dict(workspace=str(work), executable=str(args.executable), executable_sha256=hasher.hexdigest(),
               **registration['models']['strong'])
    permissions = dict(profile=PROFILE, startup_flags=permission_flags(work, blocked))
    save(args.out/'registration.json', dict(native=reg, permissions=permissions, blocked=[str(p) for p in blocked],
                                           probe_paths=[str(p) for p in probes], model_inference_calls=0))
    session = fresh(reg, private/'native', host_permissions=permissions, selector_runtime=args.selector_runtime)
    try:
        # Native bootstrap materializes on first injection. Reuse the existing
        # benchmark anchor protocol, then seal the observed wire before import.
        session.server.call('thread/inject_items', dict(threadId=session.opened['thread']['id'], items=[
            dict(type='message', role='assistant', content=[dict(type='output_text',
                text='{"record_type":"bench.bootstrap/1","id":"matrix-native-boundary"}')])]))
        snap = capture_rollout(session.opened['thread']['path'], archive=private/'native/bootstrap.jsonl')
        bootstrap = state(snap.rows)
        public = json.loads((fixture/'history.public.json').read_text(encoding='utf-8'))
        import_proof = import_fresh(session, public['prefix'], bootstrap, private/'native')
        probes.append(Path(session.opened['thread']['path']))
        script = """const fs=require('node:fs');const paths=JSON.parse(process.argv[1]);
const reads=paths.map(path=>{try{return {path,readable:true,bytes:fs.readFileSync(path).length}}catch(e){return {path,readable:false,code:e.code}}});
let write;try{fs.writeFileSync('write-probe.txt','owned-write');write=true}catch(e){write=false}
console.log(JSON.stringify({reads,write}));"""
        raw = session.server.call('command/exec', dict(command=[shutil.which('node'), '-e', script, json.dumps([str(p) for p in probes])],
            cwd=str(work), permissionProfile=PROFILE, timeoutMs=15000), timeout=25)
        save(args.out/'command-response.json', raw)
        observed = json.loads(raw['stdout']) if raw.get('exitCode') == 0 else None
        result = dict(thread_profile=session.opened.get('activePermissionProfile'), import_proof=import_proof,
            observed=observed, known_inventory_blocked=bool(observed and observed['write']
                and observed['reads'][0]['readable'] and all(not r['readable'] and r.get('code') in ('EPERM','EACCES')
                for r in observed['reads'][1:])), model_inference_calls=0, turn_start_calls=0,
            full_model_tool_boundary_verified=False, paid_dispatch_admitted=False,
            scope='Actual native named thread, exact history import and command-layer known-path probes only.')
        save(args.out/'result.json', result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('import_proof','observed')}, ensure_ascii=False))
    except Exception as error:
        save(args.out/'error.json', dict(error=str(error), error_type=type(error).__name__, model_inference_calls=0))
        raise
    finally:
        save(args.out/'owned-cleanup.json', session.server.owner.close())
        save(args.out/'cleanup.json', session.close())


if __name__ == '__main__':
    main()
