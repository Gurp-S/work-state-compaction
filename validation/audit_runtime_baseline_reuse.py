"""Read-only compatibility and exposure audit; no models/candidate execution."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks')]
from wsc.tool_results import ResultPolicy
from native_rollout_snapshot import parse_rollout
from acceptance_matrix_v1.evidence import seal


def read(path):return json.loads(Path(path).read_bytes())
def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def outputs(items):
    names={};rows=[]
    for ordinal,item in enumerate(items):
        kind=item.get('type');call=item.get('call_id')
        if kind in ('function_call','custom_tool_call'):names[call]=item.get('name')
        if kind not in ('function_call_output','custom_tool_call_output'):continue
        body=item.get('output');parts=[body] if type(body) is str else None
        if type(body) is list and all(type(v) is dict and v.get('type') in ('input_text','output_text')
                and type(v.get('text')) is str for v in body):parts=[v['text'] for v in body]
        rows.append(dict(ordinal=ordinal,call_id=call,tool=names.get(call),text_bytes=sum(len(v.encode()) for v in parts) if parts is not None else None,
            max_text_block_bytes=max((len(v.encode()) for v in parts),default=0) if parts is not None else None,
            output_shape='text' if type(body) is str else 'text_blocks' if parts is not None else type(body).__name__,
            recovery_identity_known=names.get(call) in ('WSCSource','WSCContext','WSCResult'),
            nested_code_tool_identity_unobserved=names.get(call) in ('exec','functions.exec')))
    return rows


def exposure(rows,threshold):
    sizes=[r['text_bytes'] for r in rows if r['text_bytes'] is not None]
    over=[r for r in rows if r['text_bytes'] is not None and r['text_bytes']>threshold]
    return dict(outputs=len(rows),text_outputs=len(sizes),text_bytes=sum(sizes),max_text_bytes=max(sizes,default=0),
        above_default_threshold=len(over),above_threshold_rows=over,
        scope='Observed text or sum of explicit text blocks only; no invented separators. Upstream stdout/nested roles may be unobserved; text-block replacement is not assumed supported')


def main(out):
    out.mkdir(parents=True,exist_ok=False)
    first=Path('D:/agent-task-runs/wsc-matrix-runtime-followup-20261029-v1')
    repeats=Path('D:/agent-task-runs/wsc-matrix-two-repetitions-20261029-v1')
    original=read(first/'registration.json');repeat=read(repeats/'registration.json');inputs=read(first/'coordinator-private/inputs.json')
    threshold=ResultPolicy().externalize_bytes
    tasks={};pins={}
    readiness=read(ROOT/'reviews/acceptance-matrix-admission-20261028/readiness.json')
    for task,location in readiness['task_fixture_roots'].items():
        root=Path(location);history=root/'history.public.json';data=read(history);pins[str(history)]=digest(history)
        tasks[task]=dict(history_sha256=seal(data['prefix']),prefix_items=len(data['prefix']),
            exposure=exposure(outputs(data['prefix']),threshold),starter_files={str(p.relative_to(root/'public-starter')):digest(p)
                for p in sorted((root/'public-starter').rglob('*')) if p.is_file()},
            request_declares_windows_runtime='.runtime/python.exe' in data['request'])
    continuations={};drafts={}
    for identity,base in [('r1',first),('r2',repeats/'r2'),('r3',repeats/'r3')]:
        for arm in ('Bprime','C'):
            path=base/'coordinator-private'/arm/'continuation/rollout.jsonl'
            raw=path.read_bytes();snapshot=parse_rollout(raw)
            if not snapshot.metadata['parse_complete']:raise ValueError('reuse_audit_incomplete_rollout')
            items=[r['payload'] for r in snapshot.rows if r['type']=='response_item']
            rows=outputs(items);pins[str(path)]=sha256(raw).hexdigest()
            continuations[identity+':'+arm]=exposure(rows,threshold)
            if arm=='C':
                selected=base/'coordinator-private/C/selection/phase-outcome.json'
                publication=base/'coordinator-private/C/publication.json'
                final=read(selected);package=read(publication)
                pins[str(selected)]=digest(selected);pins[str(publication)]=digest(publication)
                drafts[identity]=dict(selection= str(selected),selection_completed=final['completed'],
                    original_selection_total_tokens=final['receipts']['all_usage']['total_tokens'],
                    original_workspace=package['receipt']['workspace'],source_projection=package['package']['adapter']['source_projection'],
                    selected_sources=json.loads(final['finals'][-1]['text'])['source_ids'],
                    portable_installation_qualified=False)
    for path in (first/'registration.json',repeats/'registration.json',first/'coordinator-private/inputs.json'):
        pins[str(path)]=digest(path)
    oracle=Path(readiness['task_fixture_roots']['T1'])/'coordinator-private/oracle.json';pins[str(oracle)]=digest(oracle)
    result=dict(model_calls=0,threshold_bytes=threshold,history_integrity=dict(
        first_prefix_matches=seal(inputs['prefix'])==original['history_sha256'],
        repeat_prefix_matches=original['history_sha256']==repeat['history_sha256'],
        complete_inputs_match=digest(first/'coordinator-private/inputs.json')==original['input_sha256']==repeat['input_sha256'],
        public_task_matches=read(oracle)['public_sha256']==original['task_public_sha256'],
        repeat_registration_baseline_pin_matches=digest(first/'registration.json')==repeat['baseline_sha256']),
        fixtures=tasks,continuations=continuations,selection_drafts=drafts,
        reuse=dict(raw_history='Reusable as frozen historical data with exact hashes',
            starters_and_oracles='Reusable data; current acceptor behavior and environment must be qualified separately',
            selection_drafts='Reusable for offline representation checks; old workspace/source/scope bindings do not authorize new installation',
            model_cost_baselines='Not admitted for direct comparison with new Linux/controlled-provider host',
            opaque_native_summaries='Not inspected, decrypted, or declared portable'),
        incompatibilities=['Windows executable versus Linux executable','Python 3.11.9 Windows versus 3.11.18 Linux',
            'Request explicitly declares .runtime/python.exe','Old filesystem deny profile had known answer-file reachability gap',
            'Native default transport versus owner-buffered first-party gateway; headers/cache/timing not equivalent',
            'Old Windows workspace-bound publications versus new mapped host/guest workspace',
            'Actual native checkpoint installation on the mapped host remains unqualified'],
        semantic_correctness_or_token_savings_evaluated=False,source_sha256=pins)
    (out/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(history_integrity=result['history_integrity'],fixture_exposure={k:v['exposure'] for k,v in tasks.items()},
        continuation_exposure={k:{x:v[x] for x in ('outputs','max_text_bytes','above_default_threshold')} for k,v in continuations.items()},
        selection_drafts=drafts,model_calls=0),ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);main(p.parse_args().out.resolve())
