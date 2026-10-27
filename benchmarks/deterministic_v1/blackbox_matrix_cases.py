"""Authored black-box histories; answers remain outside compressor inputs.

These fixtures exercise explicit public state rules, not free-text semantics.
Planning is model-free and does not assert any real compression has occurred.
"""
import argparse,json,random
from pathlib import Path
from dataset import canonical,seal,native_items
from blackbox import questions

CASES=('authority','version-relations','task-switch','long-distance','expiry-recovery')
PROTOCOL=dict(record_type='bench.protocol/1',
    state_resolution='At tick T, eligible records satisfy valid_from <= T and (valid_to is null or T < valid_to). Highest priority wins; ties use the greatest sequence number. No eligible record means null.',
    version_validation='A validation is current exactly when its tested_version equals the current source_version and its artifact_id equals the current artifact_id.',
    noise_records='bench.noise/1 records are observations outside application state.',
    history_query='A query for an earlier tick uses the same eligibility and priority rules at that tick.')


def build(case,seed=1,rounds=5,noise=40):
    if case not in CASES:raise ValueError('unknown_case')
    if type(rounds) is not int or rounds<1 or type(noise) is not int or noise<0:raise ValueError('invalid_size')
    if type(seed) is not int:raise ValueError('invalid_seed')
    rng=random.Random(seed);events=[];checkpoints=[];private=[]
    secret=f'{rng.getrandbits(96):024x}'
    def fact(task,key,value,tick,priority=1,until=None,dependencies=()):
        seq=len(events)
        events.append(dict(seq=seq,record=dict(record_type='bench.fact/1',fact_id=f'f{seq}',task=task,key=key,
            value=value,valid_from=tick,valid_to=until,priority=priority,dependencies=list(dependencies))))
    def query(key,text,expected,category):
        return dict(question_id=key,question=text,answer_type=('null' if expected is None else 'boolean' if type(expected) is bool else 'integer' if type(expected) is int else 'object' if isinstance(expected,dict) else 'string'),expected=expected,category=category)
    if case=='authority':fact('release','production_delete_allowed',False,0,priority=3)
    if case=='long-distance':
        fact('application','recovery_key',secret,0);fact('application','config_path',f'config/{secret[:8]}/live.json',0)
    for tick in range(1,rounds+1):
        expected=[]
        if case=='authority':
            fact('release','production_delete_allowed',True,tick,priority=1)
            fact('release','environment','staging',tick,priority=2)
            fact('release','environment','production' if tick%2 else 'development',tick,priority=2)
            expected=[query('delete',f'At tick {tick}, what is release.production_delete_allowed?',False,'constraint'),
                query('environment',f'At tick {tick}, what is release.environment?','production' if tick%2 else 'development','conflict')]
        elif case=='version-relations':
            artifact=f'artifact-{tick}';version=f'v{tick}'
            validated=dict(tested_version=f'v{max(1,tick-1)}',artifact_id=f'artifact-{max(1,tick-1)}')
            fact('application','source_version',version,tick)
            fact('application','artifact_id',artifact,tick)
            fact('application','validation',validated,tick,dependencies=('application.source_version','application.artifact_id'))
            expected=[query('source',f'At tick {tick}, what is application.source_version?',version,'state_override'),
                query('validation',f'At tick {tick}, what is the complete application.validation record?',validated,'critical_fact'),
                query('current',f'At tick {tick}, is application.validation current?',tick==1,'dependency')]
        elif case=='task-switch':
            active='editor' if tick%2 else 'sync';editor='completed' if tick>=3 else 'paused';sync='paused' if tick%2 else 'in_progress'
            fact('workspace','active_task',active,tick);fact('editor','status',editor,tick);fact('sync','status',sync,tick)
            expected=[query('active',f'At tick {tick}, what is workspace.active_task?',active,'task_switch'),
                query('editor',f'At tick {tick}, what is editor.status?',editor,'state_update'),
                query('sync',f'At tick {tick}, what is sync.status?',sync,'state_update')]
        elif case=='long-distance':
            fact('other-application','recovery_key',f'{rng.getrandbits(96):024x}',tick)
            fact('application','source_version',f'v{tick}',tick)
            expected=[query('key',f'At tick {tick}, what is application.recovery_key?',secret,'long_distance'),
                query('path',f'At tick {tick}, what is application.config_path?',f'config/{secret[:8]}/live.json','recovery')]
        elif case=='expiry-recovery':
            # Explicit gaps are necessary: continuously renewed leases cannot test expiry.
            if tick%2:
                fact('worker','lease',f'lease-{tick}',tick,until=tick+1)
            present=tick%2==1;fact('artifact','present',present,tick)
            expected=[query('lease',f'At tick {tick}, what is worker.lease?',f'lease-{tick}' if tick%2 else None,'invalidation'),
                query('present',f'At tick {tick}, what is artifact.present?',present,'invalidation'),
                query('historical-lease','At tick 1, what was worker.lease?','lease-1','recovery')]
        for index in range(noise):
            events.append(dict(seq=len(events),record=dict(record_type='bench.noise/1',task='unrelated',
                log=f'{tick}:{index}:{rng.getrandbits(128):032x}',similar_field='source_version',similar_value=f'v{rng.randrange(100)}')))
        checkpoints.append(dict(round=tick,tick=tick,event_count=len(events)))
        private.append(dict(round=tick,questions=expected))
    public=dict(schema='wsc.blackbox.public/1',case=case,seed=seed,protocol=PROTOCOL,events=events,checkpoints=checkpoints)
    oracle=dict(schema='wsc.blackbox.oracle/1',public_sha256=seal(public),checkpoints=private)
    return public,oracle


def material(public,round_number):
    point=next(p for p in public['checkpoints'] if p['round']==round_number)
    protocol=dict(type='message',role='user',content=[dict(type='input_text',text=canonical(public['protocol']))])
    return [protocol]+native_items(public['events'][:point['event_count']])


def plan(seed=1,rounds=5,noise=40,repeats=3):
    if type(repeats) is not int or repeats<3:raise ValueError('formal_repeats_below_three')
    entries=[];payloads={}
    for case in CASES:
        public,oracle=build(case,seed,rounds,noise);payloads[case]=(public,oracle)
        for repetition in range(1,repeats+1):
            for point,answers in zip(public['checkpoints'],oracle['checkpoints']):
                items=material(public,point['round']);query=questions(answers)
                entries.append(dict(case=case,repetition=repetition,checkpoint=point['round'],
                    public_sha256=seal(public),items_sha256=seal(items),query_sha256=seal(query),
                    public_bytes=len(canonical(items).encode()),
                    arms=['uncompressed','native','wsc'],
                    trunk_query_injection_allowed=False,probe_fork_required=True,
                    native_compaction_receipt_required=True,
                    wsc_selection_questions_visible=False))
    return dict(schema='wsc.blackbox.matrix-plan/1',status='prepared_not_executed',model_calls=0,
        comparison='system_blackbox',seed=seed,rounds=rounds,noise=noise,repeats=repeats,cells=entries,
        model_workspace_must_exclude_private=True,
        unknown_cost_fields=['internal_context_tokens','internal_summarizer_parameters','internal_recovery_cost'],
        limitation='Prepared histories only; no native compression, WSC selection, answers, repetitions or gains executed.'),payloads


def write_plan(out,**kwargs):
    matrix,payloads=plan(**kwargs);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    for case,(public,oracle) in payloads.items():
        for folder,value in [('public',public),('private',oracle)]:
            target=out/folder/(case+'.json');target.parent.mkdir(exist_ok=True)
            target.write_text(canonical(value),encoding='utf-8')
    (out/'matrix.json').write_text(canonical(matrix),encoding='utf-8')
    return matrix


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    for key,default in [('seed',1),('rounds',5),('noise',40),('repeats',3)]:parser.add_argument('--'+key,type=int,default=default)
    args=parser.parse_args();matrix=write_plan(**vars(args))
    print(canonical(dict(status=matrix['status'],cells=len(matrix['cells']),model_calls=0)))


if __name__=='__main__':main()
