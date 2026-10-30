"""Six scheduled history updates; private oracles never enter compression input."""
from copy import deepcopy
import json
import random

from .evidence import seal
from .task_specs import SPECS, build_task, message

CHECKPOINTS=(2,4,6)
EXTRA_RETRIES=((408,),(502,),(425,502),(409,425),(408,),())
TITLE_LIMITS=(48,16,32,12,24,64)
STATES=('active','paused','active','complete','active','complete')


def build_chain(task, *, seed=0, noise_per_round=2, public_failure_log='',initial_history=None):
    if task not in ('T1','T3') or type(seed) is not int or type(noise_per_round) is not int or not 0<=noise_per_round<=100:
        raise ValueError('chain_dataset_arguments_invalid')
    initial,oracle=build_task(task,public_failure_log=public_failure_log,noise=20)
    if initial_history is not None:
        if type(initial_history) is not list:raise ValueError('chain_initial_history_invalid')
        initial['prefix']=deepcopy(initial_history);restored={}
        for item in initial_history:
            if item.get('type')!='function_call_output':continue
            value=json.loads(item['output'])
            identity=value.get('source_id')
            if type(identity) is not str or not identity.startswith(task+'/') or identity in restored:
                raise ValueError('chain_initial_source_identity_invalid')
            restored[identity]=dict(data=value,sha256=seal(value))
        current=[v['data']['policy'] for v in restored.values()
                 if v['data'].get('record_type')=='contract.registry/1']
        if not current or max(current,key=lambda p:p['revision'])!=SPECS[task]['latest']:
            raise ValueError('chain_initial_policy_mismatch')
        oracle['sources']=restored
    rng=random.Random(seed);sources=deepcopy(oracle['sources']);rounds=[];oracles={}
    policies=[];state_sources=[]
    for number in range(1,7):
        items=[]
        def observe(identity,data):
            record=dict(source_id=identity,**deepcopy(data))
            sources[identity]=dict(data=record,sha256=seal(record))
            call=identity.replace('/','_')
            items.extend([dict(type='function_call',call_id=call,name='fixture_observe',
                               arguments=json.dumps(dict(fixture_source=identity))),
                          dict(type='function_call_output',call_id=call,
                               output=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')))])
        policy=deepcopy(SPECS[task]['latest']);policy['revision']=number+2
        if task=='T1':
            policy['retry_statuses']=[429,503,*EXTRA_RETRIES[number-1]]
        else:
            policy.update(max_title_codepoints=TITLE_LIMITS[number-1],
                title_limit_scope='all_rows_in_v1_v2_and_v3_including_archived',
                title_limit_failure='ValueError_before_any_mutation_caller_transaction_unchanged',
                title_measure='Python_len_unicode_codepoints_not_utf8_bytes',
                valid_v3_replay='reject_over_limit_rows_otherwise_no_change')
        identity=task+f'/policy/r{number+2}'
        observe(identity,dict(record_type='contract.registry/1',policy=policy))
        state_id=task+f'/work-item/{number}'
        observe(state_id,dict(record_type='fixture.work_item_state/1',work_item=task+'/release-gate',
            revision=number,status=STATES[number-1],basis_policy=identity,
            scope='Authored application work-item state, not an assertion that candidate code has passed tests'))
        for i in range(noise_per_round):
            observe(task+f'/chain-log/{number}/{i}',dict(record_type='fixture.background_observation/1',
                worker='maintenance',sequence=rng.randrange(1_000_000),message='Unrelated worker heartbeat'))
        opposite=deepcopy(SPECS[task]['latest'] if not policies else policies[-1])
        items.append(message('assistant',dict(record_type='fixture.assistant_hypothesis/1',
            proposed_policy=opposite,proposed_state='complete' if STATES[number-1]!='complete' else 'active',
            status='unverified_hypothesis_not_registry_update')))
        policies.append(policy);state_sources.append(state_id)
        field='retry_statuses' if task=='T1' else 'max_title_codepoints'
        expected=dict(current_revision=number+2,current_policy=policy[field],
            round1_policy=policies[0][field],current_state=STATES[number-1],round1_state=STATES[0])
        bindings=dict(current_revision=dict(source_id=identity,field_path=['policy','revision']),
            current_policy=dict(source_id=identity,field_path=['policy',field]),
            round1_policy=dict(source_id=task+'/policy/r3',field_path=['policy',field]),
            current_state=dict(source_id=state_id,field_path=['status']),
            round1_state=dict(source_id=state_sources[0],field_path=['status']))
        request=(SPECS[task]['request']+'\n当前工作项状态另写 work_state.json，字段 work_item、revision、status、basis_policy。'
            '\n最高注册表 revision 定义本轮行为。Assertions: '+', '.join(expected)+
            '。current_* 对应本轮最新有效记录；round1_* 对应本链第一轮当时记录。'
            '每项含 assertion_id、value、source_id、field_path（JSON路径数组）。')
        rounds.append(dict(round=number,history_items=items,checkpoint=number in CHECKPOINTS,
                           checkpoint_request=request if number in CHECKPOINTS else None))
        facts=[dict(fact_id=key,value=deepcopy(value),**deepcopy(bindings[key]),
                    current_valid_rounds=[1,1] if key.startswith('round1_') else [number,number],
                    query_as_of_round=1 if key.startswith('round1_') else number,
                    priority='authoritative_registry' if 'policy' in key or key=='current_revision' else 'authoritative_work_item',
                    dependencies=[identity] if key=='current_state' else []) for key,value in expected.items()]
        oracles[str(number)]=dict(task=task,round=number,policy=deepcopy(policy),facts=facts,
            sources=deepcopy(sources),expected_assertions=expected,expected_bindings=bindings,
            expected_work_state=dict(work_item=task+'/release-gate',revision=number,
                                     status=STATES[number-1],basis_policy=identity))
    scheduled=dict(schema='wsc.acceptance.six_round_schedule/1',task=task,seed=seed,
        initial_history=initial['prefix'],rounds=rounds,checkpoints=list(CHECKPOINTS),
        artifact_paths=[SPECS[task]['entry'],'work_state.json'],history_dependency_qualified=False,
        initial_history_sha256=seal(initial['prefix']),initial_history_reused=initial_history is not None,
        input_scope='Coordinator-held schedule; only initial_history and released round history enter the actor. Future rounds are not actor files.')
    private=dict(schedule_sha256=seal(scheduled),rounds=oracles,
                 scope='Private evaluator material. Never adapter input or actor workspace content.')
    return scheduled,private


def release_round(schedule,number):
    if schedule.get('schema')!='wsc.acceptance.six_round_schedule/1' or type(number) is not int or not 1<=number<=6:
        raise ValueError('chain_release_invalid')
    return deepcopy(schedule['rounds'][number-1]['history_items'])
