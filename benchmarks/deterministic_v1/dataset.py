"""Public event streams and private, predefined answers. No model extraction."""
import hashlib
import json
import random

CATEGORIES=('critical_fact','constraint','state_update','state_override','conflict',
    'long_distance','noise','task_switch','multi_compaction','recovery','invalidation','dependency')


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def seal(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def generate(seed=1,rounds=5,noise=10):
    if type(rounds) is not int or rounds<1 or type(noise) is not int or noise<0:
        raise ValueError('dataset_size_invalid')
    rng=random.Random(seed)
    events=[];checkpoints=[];answers=[]
    def fact(key,value,tick,priority=1,until=None,dependencies=()):
        record=dict(record_type='bench.fact/1',fact_id=key,value=value,valid_from=tick,
                    valid_to=until,priority=priority,dependencies=list(dependencies),task='application')
        events.append(dict(seq=len(events),record=record))
    fact('project.path','src/application.py',0)
    fact('constraint.delete_production',False,0,priority=3)
    fact('project.identifier',f'project-{rng.randrange(1000000):06d}',0)
    identifier=events[-1]['record']['value']
    for tick in range(1,rounds+1):
        version=f'v{tick}'
        present=tick%2==1
        task_state=('pending','in_progress','completed')[(tick-1)%3]
        active=('A','B')[tick%2]
        fact('artifact.present',present,tick)
        fact('source.version',version,tick)
        fact('test.version',f'v{max(1,tick-1)}',tick,dependencies=('source.version',))
        fact('task.state',task_state,tick)
        fact('task.active',active,tick)
        fact('constraint.delete_production',True,tick,priority=1)
        fact('temporary.lease',f'lease-{tick}',tick,until=tick+1)
        for index in range(noise):
            events.append(dict(seq=len(events),record=dict(record_type='bench.noise/1',
                log=f'{tick}:{index}:{rng.randrange(1<<32):08x}',task='unrelated')))
        checkpoints.append(dict(round=tick,tick=tick,event_count=len(events)))
        expected={'project.path':'src/application.py','constraint.delete_production':False,
            'project.identifier':identifier,'artifact.present':present,'source.version':version,
            'test.version':f'v{max(1,tick-1)}','task.state':task_state,'task.active':active,
            'validation.current':tick==1,'temporary.lease':f'lease-{tick}'}
        answers.append(dict(round=tick,expected=expected,categories={
            'project.path':'critical_fact','constraint.delete_production':'constraint',
            'project.identifier':'long_distance','artifact.present':'invalidation',
            'source.version':'state_override','test.version':'recovery','task.state':'state_update',
            'task.active':'task_switch','validation.current':'dependency','temporary.lease':'multi_compaction'}))
    public=dict(schema='wsc.benchmark.public/1',seed=seed,categories=list(CATEGORIES),
                events=events,checkpoints=checkpoints)
    private=dict(schema='wsc.benchmark.oracle/1',public_sha256=seal(public),answers=answers)
    return public,private


def native_items(events):
    # Observations use the same public protocol for all adapters; no answers/queries.
    return [dict(type='message',role='assistant',content=[dict(type='output_text',
            text=canonical(event))]) for event in events]
