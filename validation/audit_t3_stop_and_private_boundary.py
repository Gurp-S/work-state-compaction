"""Retained stop evidence plus optional zero-inference native denial admission."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'benchmarks'), str(ROOT/'benchmarks/deterministic_v1'), str(ROOT/'experiments')]
from acceptance_matrix_v1.private_material import inventory, verify, within
from acceptance_matrix_v1.permissions import permission_flags, PROFILE
from acceptance_matrix_v1.workspace_runtime import verify_runtime, digest
from native_blackbox_sessions import fresh

CONTROLS = Path('D:/wsc-public-workspaces/wsc-t3-runtime-admission-20261029-v7')
AUDIT = Path('D:/agent-task-runs/wsc-t3-evaluator-v2-audit-20261029-v1')


def read(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def main(out, native):
    out.mkdir(parents=True, exist_ok=False)
    private = out/'coordinator-private'; private.mkdir()
    work = out/'public'; work.mkdir()
    plan = read(CONTROLS/'registration.json')
    replay = read(AUDIT/'results.json')
    sources = dict(replay['retained_file_hashes'], **replay['evaluator_hashes'])
    for path, expected in sources.items():
        if digest(path) != expected: raise ValueError('retained_material_changed:' + path)
    area = CONTROLS/'coordinator-private/last-state-only/continuation'
    phase = read(area/'phase-outcome.json')
    events = [json.loads(line) for line in (area/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    terminals = [{'index': i, 'status': r['params']['turn']['status']}
                 for i, r in enumerate(events) if r.get('method') == 'turn/completed'
                 and r.get('params', {}).get('turn', {}).get('id') == phase['usage_completion_evidence']['turn_id']]
    raw = [json.loads(line) for line in (area/'rollout.jsonl').read_text(encoding='utf-8').splitlines()]
    endings = [r['payload']['type'] for r in raw if r['type'] == 'event_msg'
               and r['payload'].get('type') in ('task_complete', 'task_completed', 'turn_aborted')]
    stop = dict(phase_failure=phase['failure'], cap=phase['budget_observation']['token_limit'],
                known_tokens=phase['receipts']['all_usage']['total_tokens'],
                event_terminals=terminals, rollout_terminal_types=endings,
                usage_complete=phase['usage_complete'], accounting_reasons=phase['usage_completion_evidence']['reasons'],
                phase_sha256=digest(area/'phase-outcome.json'), events_sha256=digest(area/'events.jsonl'),
                rollout_sha256=digest(area/'rollout.jsonl'), no_completion_reclassification=True)
    if len(terminals) != 1 or terminals[0]['status'] != 'interrupted' or endings != ['turn_aborted']:
        raise ValueError('retained_terminal_evidence_unexpected')
    save(private/'stop-audit.json', stop)
    canary = private/'canary.txt'; canary.write_text('private-boundary-admission', encoding='utf-8')
    files = [Path(p) for p in sources] + [area/'events.jsonl', AUDIT/'targeted-checks.json',
        ROOT/'reviews/t3-evaluator-v2-offline-audit.md', ROOT/'validation/replay_t3_evaluator_v2.py',
        ROOT/'validation/run_t3_baseline_controls.py', Path(__file__), canary]
    domains = [Path(p) for p in plan['blocked']] + [ROOT/'reviews', ROOT/'validation', AUDIT, CONTROLS, private]
    # Every retained study has an explicit top-level artifact domain; no full-drive scan.
    history = Path('D:/agent-task-runs')
    for path in files:
        if path.is_relative_to(history): domains.append(history/path.relative_to(history).parts[0])
    manifest = inventory(files, domains, workspace=work)
    gaps = [str(p) for p in files if not any(within(p.resolve(), Path(q).resolve()) for q in plan['blocked'])]
    save(private/'material-inventory.json', manifest)
    save(private/'prior-profile-coverage.json', dict(uncovered_declared_files=gaps,
         scope='Lexical coverage audit; does not prove a historical successful read or leakage'))
    result = dict(model_calls=0, native_probe_requested=native, prior_profile_uncovered_files=len(gaps),
                  inventory_files=len(manifest['files']), denied_domains=len(manifest['blocked']),
                  terminal='interrupted', history_dependency_qualified=False,
                  new_paid_dispatch_admitted=False, old_results_unchanged=True)
    if native:
        source_runtime = CONTROLS/'A/.runtime'
        verify_runtime(source_runtime)
        shutil.copytree(source_runtime, work/'.runtime')
        if verify_runtime(work/'.runtime') != verify_runtime(source_runtime): raise ValueError('probe_runtime_changed')
        verify(manifest, workspace=work)
        reg = dict(workspace=str(work), executable=plan['executable'], executable_sha256=plan['executable_sha256'], **plan['model'])
        probes = list(manifest['files'])
        code = ('import json,sys;from pathlib import Path;out=[]\n'
                'for p in sys.argv[1:]:\n'
                ' try:Path(p).read_bytes();out.append({"path":p,"denied":False})\n'
                ' except PermissionError:out.append({"path":p,"denied":True})\n'
                'print(json.dumps(out))')
        # Retired actor files may retain explicit Windows ACL grants. A denied
        # enclosing directory alone was experimentally insufficient for one file.
        # Keep explicit file denials and still require actual reads to fail.
        flags = permission_flags(work, [*manifest['blocked'], *probes])
        save(private/'native-registration.json', dict(**reg, permission_flags=flags,
             inventory_sha256=digest(private/'material-inventory.json'), probes=probes, model_calls=0))
        session = None
        try:
            session = fresh(reg, private/'native-session', host_permissions=dict(profile=PROFILE, startup_flags=flags), startup_timeout=60)
            response = session.server.call('command/exec', dict(command=[str(work/'.runtime/python.exe'), '-B', '-c', code, *probes],
                cwd=str(work), permissionProfile=PROFILE, timeoutMs=15000), timeout=25)
            save(private/'native-command.json', response)
            observed = json.loads(response['stdout']) if response.get('exitCode') == 0 else []
            if len(observed) != len(probes) or any(r != dict(path=p, denied=True) for r,p in zip(observed,probes)):
                raise ValueError('private_material_native_denial_failed')
            verify(manifest, workspace=work)
            # No turn/start or compact is issued. Verify the actual rollout as well.
            rollout = Path(session.opened['thread']['path'])
            rows = [json.loads(line) for line in rollout.read_text(encoding='utf-8').splitlines()] if rollout.exists() else []
            if any(r['type'] == 'token_usage_record' for r in rows): raise ValueError('unexpected_model_usage')
            result.update(native_probe_passed=True, denied_files=len(observed), observed_model_receipts=0,
                          physical_history_exists=rollout.exists(),
                          scope='One actual native command/exec profile; no universal MCP or model behavior claim')
        except BaseException as error:
            save(private/'native-error.json', dict(type=type(error).__name__, error=str(error), model_calls=0))
            raise
        finally:
            if session:
                session.server.owner.close()
                save(private/'native-cleanup.json', session.close())
    for path, expected in sources.items():
        if digest(path) != expected: raise ValueError('retained_material_changed_after_probe')
    save(out/'results.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--native', action='store_true')
    args = parser.parse_args(); main(args.out.resolve(), args.native)
