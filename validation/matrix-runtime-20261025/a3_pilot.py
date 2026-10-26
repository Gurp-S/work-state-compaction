"""Prepare and qualify one A3 B/C pair; never launch the remaining matrix."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
from pathlib import Path
import socket
import sys

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
sys.path.insert(0,str(ROOT/'experiments'))
from native_evidence import read,save,file_hash,digest
from native_application_adapters import FrozenApplicationAdapters
from native_application_budget_policy import shared_arm_allocation
from native_application_budget import StudyBudget
from native_campaign_envelope import qualification_envelope
from native_paired_admission import PairedAdmission
from native_application_worker import ApplicationStudyWorker

AREA=Path('D:/agent-task-runs/wsc-a3-qualification-20261025-v1')
PRIOR=Path('D:/agent-task-runs/wsc-application-matrix-20261025-v3')


def history():
    ledger=read(PRIOR/'wave-0-ledger.json')['snapshot']
    phases=[]
    paths=[Path('D:/agent-task-runs')/name/'result.json' for name in (
        'wsc-native-application-phase-20261025-v1','wsc-live-boundary-qualification-20261025-v1',
        'wsc-live-boundary-completion-20261025-v2')]
    for path in paths:
        result=read(path)
        phases.extend(result['phases'] if 'phases' in result else [result['phase']])
    zero=Path('D:/agent-task-runs/wsc-application-matrix-20261025-v2')
    zero_ledger=read(zero/'wave-0-ledger.json')['snapshot']['study']
    assert zero_ledger['tokens']==zero_ledger['responses']==0 and not zero_ledger['uncertain']
    wall=(read(PRIOR/'wave-0/worker-result.json')['wall_seconds']
          +read(zero/'wave-0/worker-result.json')['wall_seconds']+sum(phase['seconds'] for phase in phases))
    files=[PRIOR/'wave-0-ledger.json',PRIOR/'wave-0/worker-result.json',
           zero/'wave-0-ledger.json',zero/'wave-0/worker-result.json',*paths]
    for task in ('a3','collaboration'):
        for arm in ('B','C'):
            output=PRIOR/'trajectories'/task/'r1'/arm/'output'
            result=read(output/'worker-result.json')
            assert all(item['empty_confirmed'] for item in result['cleanup'])
            native=Path(read(output/'initial/thread-start.json')['thread']['path'])
            closed=output/'final-threads/000.jsonl'
            assert native.read_bytes()==closed.read_bytes(),'historical_native_history_changed'
            files.extend([output/'worker-result.json',native,closed])
    return qualification_envelope(ledger,phases,wall),{str(path):file_hash(path) for path in files}


def prepare():
    AREA.mkdir(exist_ok=False)
    prior=read(PRIOR/'registration.json')
    conditions=deepcopy(prior['conditions'])
    conditions['budgets']=shared_arm_allocation(conditions['budgets'])
    conditions.pop('private_input_reuse',None)
    conditions['qualification_scope']='One A3 pair; actual three boundaries and final acceptance; not formal replication'
    envelope,history_files=history()
    tasks={'a3':prior['tasks']['a3']}
    jobs=[]
    for index,arm in enumerate(('B','C')):
        root=AREA/'arms'/arm
        jobs.append(dict(pair_id='a3/qualification1',arm=arm,conditions_sha256=digest(conditions),
            resources=dict(workspace=str(root/'workspace'),output=str(root/'output'),
                browser_profile=str(root/'browser-profile'),ports=[28900+3*index+i for i in range(3)])))
    adapters=FrozenApplicationAdapters(conditions,tasks,prior['expected_checks'],node_executable=prior['node_executable'])
    def materialize(job):
        staged=deepcopy(job)
        staged['resources']['output']=str(AREA/'preparation'/job['arm'])
        payload=adapters.prepare(staged)
        save(AREA/'prepared'/('payload-'+job['arm']+'.json'),payload)
        return job['arm']
    with ThreadPoolExecutor(max_workers=2) as pool:
        for arm in pool.map(materialize,jobs):
            print('prepared '+arm,flush=True)
    prepared=dict(conditions=conditions,jobs=jobs,tasks=tasks,expected_checks=prior['expected_checks'],
        node_executable=prior['node_executable'],envelope=envelope,history_files=history_files,
        payload_files={str(AREA/'prepared'/('payload-'+arm+'.json')):file_hash(AREA/'prepared'/('payload-'+arm+'.json')) for arm in ('B','C')},
        formal_matrix_started=False,new_model_calls=0)
    save(AREA/'prepared.json',prepared)
    print(json.dumps(dict(status='inputs_prepared_no_models',envelope=envelope)),flush=True)


def register():
    prepared=read(AREA/'prepared.json')
    assert all(file_hash(path)==value for path,value in prepared['payload_files'].items())
    assert all(file_hash(path)==value for path,value in prepared['history_files'].items())
    executable=prepared['conditions']['executable']
    assert file_hash(executable['path'])==executable['sha256']
    prepared['envelope'],prepared['history_files']=history()
    runtime=read(Path('D:/agent-task-runs/wsc-a3-frozen-inputs-20261025-v1/runtime.json'))
    for name in ('node','chromium'):
        assert file_hash(runtime[name]['executable'])==runtime[name]['sha256']
    prepared['runtime_files']={runtime[name]['executable']:runtime[name]['sha256'] for name in ('node','chromium')}
    prepared['runtime_files'][sys.executable]=file_hash(sys.executable)
    for job in prepared['jobs']:
        for port in job['resources']['ports']:
            with socket.socket() as sock:
                sock.bind(('127.0.0.1',port))
    pins={str(path):file_hash(path) for folder in ('src','experiments') for path in sorted((ROOT/folder).rglob('*.py'))}
    pins[str(Path(__file__).resolve())]=file_hash(__file__)
    save(AREA/'registration.json',dict(**prepared,pins=pins,automatic_retries=0,
        usage_policy='New unknown usage freezes this qualification; historical ledger remains frozen and reserved',
        launch_scope='Exactly one pair; no full matrix continuation'))
    print('registered one A3 pair',flush=True)


def run():
    reg=read(AREA/'registration.json')
    assert all(file_hash(path)==value for path,value in reg['pins'].items())
    assert all(file_hash(path)==value for path,value in {**reg['payload_files'],**reg['history_files']}.items())
    assert all(file_hash(path)==value for path,value in reg['runtime_files'].items())
    budget=StudyBudget({job['pair_id']+'/'+job['arm']:reg['conditions']['budgets']['per_arm'] for job in reg['jobs']},
        reg['envelope']['remaining_limits'])
    admission=PairedAdmission(AREA/'admission')
    adapters=FrozenApplicationAdapters(reg['conditions'],reg['tasks'],reg['expected_checks'],node_executable=reg['node_executable'])
    def prepared(job):
        path=AREA/'prepared'/('payload-'+job['arm']+'.json')
        assert file_hash(path)==reg['payload_files'][str(path)]
        payload=read(path)
        save(Path(job['resources']['output'])/'prepared-input.json',dict(payload_path=str(path),payload_sha256=file_hash(path)))
        return payload
    worker=ApplicationStudyWorker(reg['conditions'],budget,prepared,admission,adapters.grade)
    def invoke(job):
        def record(phase):
            root=AREA/'phase-journal'/job['arm']
            ordinal=len(list(root.glob('*.json'))) if root.exists() else 0
            save(root/f'{ordinal:03d}.json',phase)
        return worker(job,record)
    outcomes={}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(invoke,job):job for job in reg['jobs']}
        for future in as_completed(futures):
            job=futures[future]
            try:
                outcomes[job['arm']]=future.result()
            except Exception as error:
                phases=[read(path) for path in sorted((AREA/'phase-journal'/job['arm']).glob('*.json'))]
                receipts=[receipt for phase in phases for receipt in phase.get('receipts',{}).get('response_receipts',[])]
                budget.mark_unknown(job['pair_id']+'/'+job['arm'],receipts)
                outcomes[job['arm']]=dict(state='infrastructure_error',phases=phases,
                    error=type(error).__name__+':'+str(error),quality=dict(status='unknown'))
            print(json.dumps(dict(arm=job['arm'],state=outcomes[job['arm']]['state'],
                error=outcomes[job['arm']].get('error'),reason=outcomes[job['arm']].get('reason')),ensure_ascii=False),flush=True)
    save(AREA/'result.json',dict(outcomes=outcomes,ledger=budget.snapshot(),historical_envelope=reg['envelope'],
        whole_campaign_usage_complete=False,formal_matrix_started=False))
    print(json.dumps(dict(status='qualification_finished_review_pending',ledger=budget.snapshot()['study'])),flush=True)


if __name__=='__main__':
    {'prepare':prepare,'register':register,'run':run}[sys.argv[1]]()
