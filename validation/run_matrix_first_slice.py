"""Frozen first slice: one tool probe, then independent T1 A/control.

--prepare never infers; --execute claims one parent-bound allocation and never
reopens a ledger. No B/C or chain runs are silently launched by this program.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'experiments'), str(ROOT/'benchmarks'), str(ROOT/'benchmarks/deterministic_v1')]
from acceptance_matrix_v1.evidence import seal
from acceptance_matrix_v1.inventory import private_inventory
from acceptance_matrix_v1.permissions import permission_flags, PROFILE
from acceptance_matrix_v1.dispatch_budget import DispatchBudget, inspect_ledger
from acceptance_matrix_v1.native_dispatch import execute_bound_stage
from acceptance_matrix_v1.acceptors import accept_t1, load_candidate
from native_blackbox_sessions import fresh, import_fresh
from native_evidence import state
from native_rollout_snapshot import capture_rollout


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def file_hash(path):
    h = sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024*1024), b''):
            h.update(part)
    return h.hexdigest()


def workspace_manifest(path):
    return {p.relative_to(path).as_posix():file_hash(p) for p in sorted(path.rglob('*')) if p.is_file()}


def prepare(out, executable, previous=None):
    out.mkdir(parents=True, exist_ok=False)
    private = out/'coordinator-private'
    private.mkdir()
    registration = json.loads((ROOT/'reviews/acceptance-matrix-admission-20261028/registration.draft.json').read_text(encoding='utf-8'))
    readiness = json.loads((ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json').read_text(encoding='utf-8'))
    if not registration['all_five_acceptors_calibrated']:
        raise ValueError('five_acceptors_not_calibrated')
    fixture = Path(registration['tasks']['T1']['fixture_root'])
    public = json.loads((fixture/'history.public.json').read_text(encoding='utf-8'))
    if seal(public) != registration['tasks']['T1']['public_sha256']:
        raise ValueError('registered_fixture_changed')
    for name in ('tool-probe', 'A', 'last-state-only'):
        work = out/name
        if name == 'tool-probe':
            work.mkdir()
        else:
            shutil.copytree(fixture/'public-starter', work)
        (work/'canary.txt').write_text('owned-public-canary', encoding='utf-8')
    (private/'canary.txt').write_text('owned-private-canary', encoding='utf-8')
    paths = [str(out/'tool-probe/canary.txt'), str(private/'canary.txt'), str(out/'A/canary.txt')]
    script = ('const fs=require("node:fs");const paths='+json.dumps(paths)+';'
        'const reads=paths.map(path=>{try{return {path,readable:true,bytes:fs.readFileSync(path).length}}'
        'catch(e){return {path,readable:false,code:e.code}}});'
        'fs.writeFileSync("write-probe.txt","owned-write");'
        'console.log(JSON.stringify({schema:"matrix.tool_boundary/1",reads,workspace_write:true}));')
    command = "& '"+shutil.which('node').replace("'", "''")+"' -e '"+script.replace("'", "''")+"'"
    probe_request = '执行下列PowerShell命令一次，返回实际工具stdout，不使用其他代理或读取其他文件。\n'+command
    requests = {'tool-probe': probe_request, 'A': public['request'], 'last-state-only': public['request']}
    prefixes = {'tool-probe': [], 'A': public['prefix'], 'last-state-only': []}
    limits = registration['first_batch']['limits']
    run_limits = registration['first_batch']['task_run_limits']
    runs = {}
    for name in requests:
        runs[name] = dict(arm=name, limits=dict(run_limits if name != 'tool-probe' else
            dict(max_total_tokens=100000, max_responses=4, max_seconds=180)), binding=dict(
                workspace=str(out/name), **registration['models']['strong'], history_sha256=seal(prefixes[name]),
                request_sha256=sha256(requests[name].encode('utf-8')).hexdigest(), task='T1' if name != 'tool-probe' else 'admission',
                repetition=1, input_public_sha256=seal(public)))
    blocked, _ = private_inventory(ROOT, readiness)
    parent = Path(readiness['previous_envelope'])
    if file_hash(parent) != readiness['previous_envelope_sha256']:
        raise ValueError('parent_envelope_changed')
    remaining = json.loads(parent.read_text(encoding='utf-8'))['remaining_limits']
    if any(limits[k] > remaining[k] for k in limits):
        raise ValueError('child_allocation_exceeds_parent_reference')
    inputs = dict(requests=requests, prefixes=prefixes)
    save(private/'inputs.json', inputs)
    sources = [Path(__file__).resolve(), ROOT/'benchmarks/acceptance_matrix_v1/native_dispatch.py',
        ROOT/'benchmarks/acceptance_matrix_v1/dispatch_budget.py', ROOT/'benchmarks/acceptance_matrix_v1/inventory.py',
        ROOT/'benchmarks/acceptance_matrix_v1/permissions.py', ROOT/'benchmarks/deterministic_v1/native_blackbox_sessions.py',
        ROOT/'experiments/native_evidence.py', ROOT/'experiments/native_application_session.py',
        ROOT/'benchmarks/acceptance_matrix_v1/acceptors.py']
    plan = dict(status='frozen_first_slice_not_full_matrix', executable=str(executable.resolve()),
        executable_sha256=file_hash(executable), parent=str(parent), parent_sha256=file_hash(parent),
        parent_claim=str(parent.parent/'matrix-first-batch-20261028.claim.json'), runs=runs, limits=limits,
        blocked=[str(p) for p in blocked]+[str(private),str(parent.parent)], inputs_sha256=file_hash(private/'inputs.json'),
        source_sha256={str(p): file_hash(p) for p in sources}, probe_paths=paths,
        workspace_manifests={name:workspace_manifest(out/name) for name in requests},
        trigger='uncompressed_controls_only', comparison='system_blackbox', parallelism=2,
        scope='Tool probe then A/control only; Bprime/C repetitions still pending; all spend belongs to first batch.',
        no_automatic_retries=True, old_failures_and_unknowns_preserved=True)
    if previous is not None:
        closure_path=previous/'closure.json'
        closure=json.loads(closure_path.read_text(encoding='utf-8'))
        audited=inspect_ledger(previous/'coordinator-private/ledger.db')['state']
        if audited['status']!='closed' or audited['budget']['study']['uncertain']:
            raise ValueError('previous_slice_not_closed_or_usage_unknown')
        if any(audited['runs'][name]['status']!='planned' for name in ('A','last-state-only')):
            raise ValueError('controls_already_started')
        if closure['budget']['budget']['study']!=audited['budget']['study']:
            raise ValueError('previous_closure_ledger_mismatch')
        remaining=closure['remaining_first_batch_limits']
        if remaining['max_total_tokens']+audited['budget']['study']['tokens']!=audited['budget']['study']['limits']['max_total_tokens'] \
                or remaining['max_responses']+audited['budget']['study']['responses']!=audited['budget']['study']['limits']['max_responses']:
            raise ValueError('previous_remaining_allocation_invalid')
        amendment=ROOT/'reviews/2026-10-28-acceptance-matrix-execution-v1.2.md'
        plan.update(parent=str(closure_path),parent_sha256=file_hash(closure_path),
            parent_claim=str(previous/'controls-continuation.claim.json'),limits=remaining,
            blocked=plan['blocked']+[str(previous)],skip_tool_probe=True,
            previous_probe_retained_as_failed=True,execution_amendment=str(amendment),
            execution_amendment_sha256=file_hash(amendment),
            scope='Only previously unstarted A/control. Original probe failure/cost preserved; no probe retry or budget reset.')
    save(out/'registration.json', plan)
    return plan


def tool_evidence(out):
    expected = json.loads((out/'registration.json').read_text(encoding='utf-8'))['probe_paths']
    rows = capture_rollout(out/'coordinator-private/tool-probe-phase/rollout.jsonl').rows
    outputs = [row['payload'].get('output') for row in rows if row.get('type') == 'response_item'
               and row['payload'].get('type') in ('function_call_output','custom_tool_call_output')]
    def values(value):
        if isinstance(value, dict):
            yield value
            for v in value.values():
                yield from values(v)
        elif isinstance(value, list):
            for v in value:
                yield from values(v)
        elif isinstance(value, str):
            for line in value.splitlines():
                try:
                    parsed = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(parsed, str):
                    yield from values(parsed)
    for value in values(outputs):
        if value.get('schema') != 'matrix.tool_boundary/1':
            continue
        rows = value.get('reads', [])
        if len(rows) == 3 and [row.get('path') for row in rows] == expected \
                and rows[0].get('readable') is True and rows[0].get('bytes') == len(b'owned-public-canary') \
                and value.get('workspace_write') is True and (out/'tool-probe/write-probe.txt').is_file() \
                and (out/'tool-probe/write-probe.txt').read_bytes() == b'owned-write' \
                and all(row.get('readable') is False and row.get('code') in ('EPERM','EACCES') for row in rows[1:]):
            return dict(success=True, observed_tool_output=value, scope='Typed actual tool output, not model final self-report.')
    return dict(success=False, reason='matching_actual_tool_output_not_observed')


def execute(out):
    plan = json.loads((out/'registration.json').read_text(encoding='utf-8'))
    sealed={**plan['source_sha256'], plan['executable']:plan['executable_sha256'],
            plan['parent']:plan['parent_sha256'], str(out/'coordinator-private/inputs.json'):plan['inputs_sha256']}
    if plan.get('execution_amendment'):
        sealed[plan['execution_amendment']]=plan['execution_amendment_sha256']
    for path,digest in sealed.items():
        if file_hash(path) != digest:
            raise ValueError('frozen_input_changed:'+path)
    # Exclusive parent-side reservation prevents a second child from resetting this allocation.
    save(plan['parent_claim'], dict(child=str(out), limits=plan['limits'], registration_sha256=file_hash(out/'registration.json'),
                                   parent_sha256=plan['parent_sha256'], allocation_is_not_spend=True))
    private = out/'coordinator-private'
    ledger = DispatchBudget(private/'ledger.db', plan['runs'], plan['limits'])
    inputs = json.loads((private/'inputs.json').read_text(encoding='utf-8'))
    def run(name, phase_limits):
        work = out/name
        def opener():
            if workspace_manifest(work) != plan['workspace_manifests'][name]:
                raise ValueError('registered_initial_workspace_changed')
            blocked = plan['blocked']+[str(out/peer) for peer in plan['runs'] if peer != name]
            reg = dict(workspace=str(work), executable=plan['executable'], executable_sha256=plan['executable_sha256'],
                       model=plan['runs'][name]['binding']['model'], effort=plan['runs'][name]['binding']['effort'])
            session = fresh(reg, private/(name+'-session'), host_permissions=dict(profile=PROFILE,
                            startup_flags=permission_flags(work, blocked)))
            original_close = session.close
            def owned_close():
                session.server.owner.close()
                return original_close()
            session.close = owned_close
            try:
                session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=[
                    dict(type='message',role='assistant',content=[dict(type='output_text',text='{"record_type":"bench.bootstrap/1","id":"matrix-first-slice"}')])]))
                snap = capture_rollout(session.opened['thread']['path'])
                prefix = inputs['prefixes'][name]
                session.matrix_import_proof = import_fresh(session,prefix,state(snap.rows),private/(name+'-session')) if prefix else dict(imported_items_sha256=seal([]))
                return session
            except BaseException:
                session.server.owner.close()
                session.close()
                raise
        result = execute_bound_stage(ledger,name,'continuation',phase_limits,opener,inputs['requests'][name],private/(name+'-phase'))
        if name == 'tool-probe':
            accepted = tool_evidence(out)
        else:
            accepted = accept_t1(load_candidate(work/'retry_client.py'))
        accepted['success'] = bool(accepted['success'] and result['outcome']['completed'] and result['outcome']['failure'] is None)
        ledger.finish(name, accepted)
        save(private/(name+'-acceptance.json'), accepted)
        return accepted
    results = {}
    try:
        if not plan.get('skip_tool_probe'):
            results['tool-probe'] = run('tool-probe', plan['runs']['tool-probe']['limits'])
        if plan.get('skip_tool_probe') or results['tool-probe']['success']:
            snap = ledger.snapshot()['budget']['study']
            paired = dict(max_total_tokens=(plan['limits']['max_total_tokens']-snap['tokens'])//2,
                          max_responses=(plan['limits']['max_responses']-snap['responses'])//2,max_seconds=1800)
            with ThreadPoolExecutor(max_workers=2) as pool:
                jobs = {name:pool.submit(run,name,paired) for name in ('A','last-state-only')}
                for name,job in jobs.items():
                    results[name] = job.result()
    except BaseException as error:
        save(out/'execution-error.json',dict(type=type(error).__name__,error=str(error)))
        raise
    finally:
        snapshot = ledger.snapshot()
        save(out/'closure.json',dict(results=results,budget=snapshot,history_dependency_qualified=bool(
            results.get('A',{}).get('success') and not results.get('last-state-only',{}).get('success',True)),
            remaining_first_batch_limits=dict(max_total_tokens=max(0,plan['limits']['max_total_tokens']-snapshot['budget']['study']['tokens']),
                max_responses=max(0,plan['limits']['max_responses']-snapshot['budget']['study']['responses']),
                max_seconds=max(0,int(plan['limits']['max_seconds']-snapshot['active_seconds']))),
            old_unknowns_preserved=True,whole_campaign_usage_complete=False,
            scope='First slice only; remaining allocation is not account quota or complete historical usage.'))
        ledger.close()
    print(json.dumps({name:value['success'] for name,value in results.items()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--executable',type=Path)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--continue-controls-from',type=Path)
    args = parser.parse_args()
    if args.execute:
        execute(args.out.resolve())
    else:
        print(json.dumps(prepare(args.out.resolve(),args.executable,args.continue_controls_from),ensure_ascii=False)[:180])
