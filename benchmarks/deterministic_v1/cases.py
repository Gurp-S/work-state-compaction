"""Named, auditable lifecycle fixtures. Never infer encrypted summary semantics."""
from dataset import seal


def lifecycle(name):
    events=[];checkpoints=[];answers=[]
    def add(key,value,tick,deps=()):
        events.append(dict(seq=len(events),record=dict(record_type='bench.fact/1',
            fact_id=key,value=value,task='application',priority=1,valid_from=tick,
            valid_to=None,dependencies=list(deps))))
    def end(tick,expected,categories):
        checkpoints.append(dict(round=tick,tick=tick,event_count=len(events)))
        answers.append(dict(round=tick,task='application',expected=expected,categories=categories))
    if name=='artifact-lifecycle':
        # Public protocol translation is explicitly authored, not an LLM extractor.
        add('artifact.present',True,1)
        end(1,{'artifact.present':True},{'artifact.present':'invalidation'})
        add('artifact.present',False,2)
        end(2,{'artifact.present':False},{'artifact.present':'invalidation'})
        basis=dict(kind='real_failure_motivated_structured_counterfactual',
            actual_missing_artifact='.codex-vitest-preload.mjs',
            actual_source='execution-v3/R02/C/S3-phase/rollout.jsonl',
            actual_source_sha256='16df40dbf50dabd731089aba818d1c2ea75ba096b372ed8a244aa266912c7f2f',
            absence_output_line=680,compaction_line=698,failed_invocation_line=709,
            missing_module_output_line=712,recreation_line=716,successful_output_line=719,
            limitation='Two-stage fixture is an authored protocol translation, not raw-trace semantic extraction or a claim of summary loss.')
    elif name=='version-validation':
        add('source.version','v1',1);add('test.version','v1',1,('source.version',))
        end(1,{'source.version':'v1','test.version':'v1','validation.current':True},
            {'source.version':'state_override','test.version':'critical_fact','validation.current':'dependency'})
        add('source.version','v2',2)
        end(2,{'source.version':'v2','test.version':'v1','validation.current':False},
            {'source.version':'state_override','test.version':'critical_fact','validation.current':'dependency'})
        basis=dict(kind='goal_derived_synthetic_counterfactual',
            limitation='V1 passed/V2 untested is an explicit target-document risk, not an observed failure claimed from the C trace.')
    else:raise ValueError('unknown_lifecycle_case')
    public=dict(schema='wsc.benchmark.public/1',case=name,events=events,checkpoints=checkpoints,basis=basis)
    return public,dict(schema='wsc.benchmark.oracle/1',public_sha256=seal(public),answers=answers)
