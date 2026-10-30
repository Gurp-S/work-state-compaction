"""No-inference native read boundary probe, using owned synthetic canaries only."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'benchmarks'))
from native_owned_process import OwnedNativeRPC
from acceptance_matrix_v1.permissions import permission_flags, PROFILE


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--policy', choices=['read-only', 'exact-deny-profile', 'campaign-deny-profile'], default='read-only')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    work = (args.out/'public-workspace').resolve()
    private = (args.out/'coordinator-private').resolve()
    peer = (args.out/'other-arm').resolve()
    for folder in (work, private, peer):
        folder.mkdir()
    for folder, value in [(work, 'public-canary'), (private, 'private-canary'), (peer, 'peer-canary')]:
        (folder/'canary.txt').write_text(value, encoding='utf-8')
    digest = sha256()
    with args.executable.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    flags = ['features.multi_agent=false']
    command_policy = dict(sandboxPolicy=dict(type='readOnly', networkAccess=False))
    if args.policy != 'read-only':
        blocked = [private, peer] if args.policy == 'exact-deny-profile' else [
            args.out.resolve().parent, Path(__file__).resolve().parents[1]]
        flags += permission_flags(work, blocked)
        command_policy = dict(permissionProfile=PROFILE)
    registration = dict(executable=str(args.executable.resolve()), executable_sha256=digest.hexdigest(),
        cwd=str(work), sandbox_policy=dict(type='readOnly', networkAccess=False),
        canaries=[str(p/'canary.txt') for p in (work, private, peer)],
        policy=args.policy, startup_flags=flags, command_policy=command_policy,
        scope='Synthetic canaries only. command/exec layer, not a model tool-inventory or thread isolation proof.')
    save(args.out/'registration.json', registration)
    server = OwnedNativeRPC(args.executable, cwd=work, stderr_path=args.out/'stderr.txt',
                            settings=flags)
    try:
        save(args.out/'initialize.json', server.call('initialize', dict(
            clientInfo=dict(name='matrix_read_boundary_probe', version='1'),
            capabilities=dict(experimentalApi=True))))
        server.send(dict(method='initialized'))
        script = """const fs=require('node:fs');const paths=JSON.parse(process.argv[1]);
const observations=paths.map(path=>{try{return {path,readable:true,bytes:fs.readFileSync(path).length}}catch(error){return {path,readable:false,code:error.code}}});
let workspace_write;try{fs.writeFileSync('workspace-write-probe.txt','owned-write-canary');workspace_write=true;}catch(error){workspace_write=false;}
console.log(JSON.stringify({observations,workspace_write}));"""
        response = server.call('command/exec', dict(command=[shutil.which('node'), '-e', script,
            json.dumps(registration['canaries'])], cwd=str(work),
            **command_policy, timeoutMs=15000), timeout=25)
        save(args.out/'command-response.json', response)
        observed = json.loads(response['stdout']) if response.get('exitCode') == 0 else None
        rows = observed['observations'] if observed else None
        result = dict(model_inference_calls=0, turn_start_calls=0, thread_start_calls=0,
            command_exit_code=response.get('exitCode'), observations=rows,
            workspace_write=observed['workspace_write'] if observed else None,
            read_only_bounds_private_canary=not rows[1]['readable'] if rows and rows[0]['readable'] else None,
            read_only_bounds_peer_canary=not rows[2]['readable'] if rows and rows[0]['readable'] else None,
            paid_dispatch_admitted=False, scope=registration['scope'])
        save(args.out/'result.json', result)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        save(args.out/'error.json', dict(error_type=type(error).__name__, error=str(error), model_inference_calls=0))
        raise
    finally:
        # Cancel the owned descendants before closing pipe handles: descendants
        # may otherwise keep stdout alive after the server itself terminated.
        owned = server.owner.close()
        save(args.out/'owned-cleanup.json', owned)
        save(args.out/'cleanup.json', server.close())


if __name__ == '__main__':
    main()
