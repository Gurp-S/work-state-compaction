"""Register the complete 5x3 matrix; execute the first predeclared two pairs.

No automatic wave continuation or replacement. Subsequent waves need a reviewed
ledger continuation; task failures are preserved and never retried for success.
"""
import ast
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,digest,file_hash,manifest
from native_incremental_candidate import POLICY
from native_task_matrix import paired_plan,settle_matrix
from native_repeated_pairs import run_workers,schedule
from native_application_budget import StudyBudget
from native_paired_admission import PairedAdmission
from native_application_adapters import FrozenApplicationAdapters
from native_application_worker import ApplicationStudyWorker
from native_host_controls import FEATURE_OVERRIDES, settings

AREA=Path('D:/agent-task-runs/wsc-application-matrix-20261025-v3')
PREVIOUS=Path('D:/agent-task-runs/wsc-application-matrix-20261025-v2')
TASK_IDS=['a3','collaboration','files','imports','booking']


def register():
    AREA.mkdir(exist_ok=False)
    conditions=deepcopy(read(ROOT/'validation/application-freeze-20261025/study-conditions-v1.json'))
    conditions['candidate'].update(POLICY)
    conditions['candidate']['implementation']['sha256']=file_hash(ROOT/'experiments/native_incremental_candidate.py')
    conditions['candidate']['reference_contract']='Each source field accepts an exact offered source identity or its unambiguous short alias; record references name an offered revision.'
    conditions['candidate']['previous_selection_contract']='Stored prior view binds selected records, source handles, clues and excerpts; all are visible to the next selector without automatic semantic carry.'
    conditions['host_feature_overrides']=FEATURE_OVERRIDES
    conditions['bootstrap_identity_policy']='Ignore native message/additional_tools envelope IDs only; tool names, descriptions and schemas remain exact.'
    previous_ledger=read(PREVIOUS/'wave-0-ledger.json')['snapshot']['study']
    assert previous_ledger['responses']==0 and previous_ledger['tokens']==0 and not previous_ledger['uncertain']
    conditions['boundaries']['process_policy']='Both arms close the prior owned process tree before opening the next native fork; filesystem state stays in the private workspace.'
    conditions['budgets']['peer_wait_scope']='Explicit paired lazy-host admission wait is recorded separately and excluded from the arm execution deadline; study wall clock includes it.'
    conditions['launch_qualified']='bootstrap_and_runtime_gated_before_each_model_call'
    conditions['launch_gaps']=[]
    conditions['qualification_evidence']={
        'nested':str(HERE/'recursive-checks.json'),
        'identity_fix':str(HERE/'selection-identity-replay.json'),
        'live_compaction_and_generation':str(Path('D:/agent-task-runs/wsc-live-boundary-qualification-20261025-v1/result.json')),
        'live_continuation':str(Path('D:/agent-task-runs/wsc-live-boundary-completion-20261025-v2/result.json')),
        'grader_adapter':str(Path('D:/agent-task-runs/wsc-matrix-grade-adapter-20261025-v1/review.json'))}
    conditions['qualification_limits']=['One small live boundary; no full application or three actual compactions yet',
        'V1 selector request/output reused by exact-identity v2 compiler; no semantic generation retry',
        'Observed host controls only, not provider wire identity; external-author filesystem read denial not proven']
    tasks={}
    for task in TASK_IDS:
        path=Path('D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1/input-binding.json') if task=='a3' else Path(
            f'D:/agent-task-runs/wsc-four-app-inputs-20261025-v1/{task}/input-binding.json')
        tasks[task]=dict(binding=str(path),binding_sha256=file_hash(path))
    reuse={}
    for task in ('a3','collaboration'):
        for arm in ('B','C'):
            oldroot=PREVIOUS/'trajectories'/task/'r1'/arm
            prepared=oldroot/'output/prepared-input.json'
            result=oldroot/'output/worker-result.json'
            entry=read(result)
            assert entry['state']=='infrastructure_error' and not entry['phases'] and entry['admission_matched'] is False
            assert all(v['empty_confirmed'] for v in entry['cleanup'])
            reuse[task+'/r1/'+arm]=dict(workspace=str(oldroot/'workspace'),prepared=str(prepared),
                prepared_sha256=file_hash(prepared),result=str(result),result_sha256=file_hash(result),
                binding_sha256=tasks[task]['binding_sha256'])
    conditions['private_input_reuse']=reuse
    expected={}
    frozen_a3=Path(read(tasks['a3']['binding'])['workspace'])
    script="const m=await import(process.argv[1]);console.log(JSON.stringify(Object.fromEntries(Array.from({length:8},(_,i)=>[String(i+1),m.cases.filter(c=>c.stage<=i+1).map(c=>c.id)]))));"
    process=subprocess.run(['E:/nodejs/node.exe','--input-type=module','-e',script,
        (frozen_a3/'task-contract/a3-ui-long-v1/harness/acceptance-cases.mjs').as_uri()],capture_output=True,text=True,encoding='utf8',check=True)
    expected['a3']=json.loads(process.stdout)
    for task in TASK_IDS[1:]:
        frozen=Path(read(tasks[task]['binding'])['workspace'])
        entries=[('startup_and_page',1)]
        for name in ('cases.py','extended_cases.py'):
            tree=ast.parse((frozen/'task-contract/acceptance'/name).read_text(encoding='utf8'))
            for node in tree.body:
                if isinstance(node,ast.FunctionDef):
                    for decorator in node.decorator_list:
                        if isinstance(decorator,ast.Call) and isinstance(decorator.func,ast.Name) and decorator.func.id=='case':
                            args=[ast.literal_eval(v) for v in decorator.args]
                            if args[0]==task: entries.append((args[1],args[2]))
        expected[task]={str(i):[name for name,stage in entries if stage<=i] for i in range(1,9)}
    runtime=read(Path('D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1/runtime.json'))
    tools=digest(dict(executable=conditions['executable'],python=file_hash(sys.executable),node=runtime['node'],
        browser=runtime['chromium'],settings=settings(dict(effort=conditions['effort'],host_feature_overrides=FEATURE_OVERRIDES))))
    matrix=dict(kind='native_wsc_task_matrix_v1',parallel_pairs=2,tasks=[])
    ordinal=0
    for task in TASK_IDS:
        binding=read(tasks[task]['binding'])
        code=binding['source_manifest']
        task_spec=dict(id=task,conditions=dict(source_manifest_sha256=digest(code),
            task_contract_sha256=digest({k:v for k,v in code.items() if k.startswith('task-contract/')}),
            model=conditions['model'],effort=conditions['effort'],tools_sha256=tools,budget=conditions['budgets']),pairs=[])
        for repeat in range(1,4):
            arms={}
            for arm in ('B','C'):
                root=AREA/'trajectories'/task/f'r{repeat}'/arm
                arms[arm]=dict(strategy='native_control' if arm=='B' else 'registered_wsc',
                    workspace=reuse.get(f'{task}/r{repeat}/{arm}',{}).get('workspace',str(root/'workspace')),
                    output=str(root/'output'),browser_profile=str(root/'browser-profile'),
                    ports=[27400+ordinal*3+i for i in range(3)])
                ordinal+=1
            task_spec['pairs'].append(dict(id=f'r{repeat}',arms=arms))
        matrix['tasks'].append(task_spec)
    plan=paired_plan(matrix)
    first=[j for j in schedule(plan) if j['wave']==0]
    assert len(first)==4 and {j['pair_id'] for j in first}=={'a3/r1','collaboration/r1'}
    for job in first:
        for port in job['resources']['ports']:
            with socket.socket() as sock: sock.bind(('127.0.0.1',port))
    pins={str(p):file_hash(p) for folder in ('src','experiments') for p in sorted((ROOT/folder).rglob('*.py'))}
    pins[str(Path(__file__).resolve())]=file_hash(__file__)
    registration=dict(conditions=conditions,matrix=matrix,tasks=tasks,expected_checks=expected,
        node_executable=runtime['node']['executable'],pins=pins,
        execution=dict(selected_waves=[0],registered_pairs=15,registered_trajectories=30,selected_pairs=2,
            selected_trajectories=4,automatic_retries=0,infrastructure_replacements=0,
            next_wave_gate='Review first-wave artifacts/ledger and preserve the cumulative budget before further waves'),
        read_boundary='Private writable roots and input allowlist; external-author read denial is not proven',
        prepared_known_protocol_usage=dict(responses=4,total_tokens=95406,cash=None),
        supersedes_zero_inference_attempt=dict(registration=str(PREVIOUS/'registration.json'),
            ledger=str(PREVIOUS/'wave-0-ledger.json'),reason='Native optional tool definition drift plus unnormalized transport envelope IDs',
            host_repair_evidence='D:/agent-task-runs/wsc-host-controls-20261025-v2/result.json'),
        parent_authoring_usage='unknown_not_zero')
    save(AREA/'registration.json',registration)
    print(json.dumps(dict(registered_pairs=15,selected_pairs=2,selected_trajectories=4,
        first_wave=['a3/r1','collaboration/r1'],model_calls=0)),flush=True)


def run():
    reg=read(AREA/'registration.json')
    assert all(file_hash(path)==value for path,value in reg['pins'].items()),'study_code_changed_after_registration'
    assert file_hash(reg['conditions']['executable']['path'])==reg['conditions']['executable']['sha256']
    plan=paired_plan(reg['matrix'])
    jobs=schedule(plan)
    limits={j['pair_id']+'/'+j['arm']:reg['conditions']['budgets']['per_arm'] for j in jobs}
    budget=StudyBudget(limits,reg['conditions']['budgets']['study'])
    admission=PairedAdmission(AREA/'admission')
    adapters=FrozenApplicationAdapters(reg['conditions'],reg['tasks'],reg['expected_checks'],node_executable=reg['node_executable'])
    worker=ApplicationStudyWorker(reg['conditions'],budget,adapters.prepare,admission,adapters.grade)
    result=run_workers(plan,worker,AREA/'wave-0',waves=[0])
    save(AREA/'wave-0-ledger.json',dict(snapshot=budget.snapshot(),study_started_monotonic=budget.started))
    settlement=settle_matrix(reg['matrix'],result['worker_observations'])
    save(AREA/'wave-0-settlement.json',settlement)
    print(json.dumps(dict(status='first_wave_finished_review_pending',workers={key:dict(state=value['result']['state'],
        quality=value['result'].get('quality'),error=value['result'].get('error')) for key,value in result['worker_observations'].items()},
        ledger=budget.snapshot()['study'],complete_study=False),ensure_ascii=False),flush=True)


if __name__=='__main__':
    {'register':register,'run':run}[sys.argv[1]]()
