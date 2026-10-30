"""Code behavior, state artifacts and exact source applicability scored separately."""
from contextlib import closing
from copy import deepcopy
import json

from .acceptors import accept_t1, collect, database, raises, require
from .acceptor_t3_v2 import accept_t3_v2, snapshot
from .evidence import canonical, evaluate


def evaluate_claims(assertions,oracle):
    result=evaluate(assertions,oracle['expected_assertions'],oracle['sources'])
    submitted={a['assertion_id']:a for a in assertions}
    rows=[]
    for identity,binding in oracle['expected_bindings'].items():
        claim=submitted.get(identity,{})
        correct=(claim.get('source_id')==binding['source_id']
                 and canonical(claim.get('field_path'))==canonical(binding['field_path']))
        rows.append(dict(assertion_id=identity,applicability_binding_correct=correct))
    return dict(exact_fields=result,applicability=rows,
        applicability_accuracy=sum(r['applicability_binding_correct'] for r in rows)/len(rows),
        success=result['exact_answer_correct']==len(rows) and result['citation_byte_matches']==len(rows)
            and all(r['applicability_binding_correct'] for r in rows),
        free_text_semantics='unassessed')


def retry_cases(module,policy):
    retries=set(policy['retry_statuses'])
    def extra_and_revoked():
        for code in (408,409,425,429,500,502,503,504):
            calls=[];original=dict(id='case',tenant='scope',method='GET',payload={'nested':[1]})
            before=deepcopy(original)
            def send(value,attempt):
                calls.append((deepcopy(value),attempt));value['payload']['nested'].append(99)
                return dict(status=code if attempt==1 else 200,value='result')
            rows=module.run_batch([original],send,max_attempts=2)
            expected_attempts=2 if code in retries else 1
            expected_status=200 if code in retries else code
            require(original==before,'chain_retry_mutated_caller')
            require(calls==[(before,n) for n in range(1,expected_attempts+1)],'chain_retry_uses_stale_policy')
            require(rows==[dict(tenant='scope',id='case',state='ok' if code in retries else 'failed',
                status=expected_status,value='result',attempts=expected_attempts)],'chain_retry_result_mismatch')
    return collect('T1',[('chain-current-and-revoked-statuses','current-policy',extra_and_revoked)])


def migration_cases(module,policy):
    limit=policy['max_title_codepoints']
    def fixture(version,title,archived=0):
        db=database(version=version if version<3 else 2,rows=[('p1','a',title,archived)])
        if version==3:
            # Build input schema with SQL; never execute a reference migration here.
            db.execute('ALTER TABLE projects ADD COLUMN row_version INTEGER NOT NULL DEFAULT 1')
            db.execute('UPDATE schema_version SET version=3')
        return db
    def boundaries():
        for version in (1,2,3):
            with closing(fixture(version,'🙂'*limit)) as db:
                module.migrate(db)
                require(db.execute('SELECT title FROM projects').fetchall()==[('🙂'*limit,)],'chain_title_boundary_changed')
                require(db.execute('SELECT version FROM schema_version').fetchall()==[(3,)],'chain_valid_title_not_migrated')
    def failures():
        for version in (1,2,3):
            for archived in (0,1):
                with closing(fixture(version,'🙂'*(limit+1),archived)) as db:
                    db.execute("INSERT INTO notes VALUES ('caller-pending')");before=snapshot(db)
                    raises(ValueError,lambda:module.migrate(db))
                    require(snapshot(db)==before,'chain_rejection_changed_caller_state')
    return collect('T3',[('chain-unicode-title-boundary','current-policy',boundaries),
        ('chain-over-limit-atomic-rejection','transaction-atomicity',failures)])


def evaluate_code(module,oracle):
    task=oracle['task']
    if task=='T1':base=accept_t1(module);extra=retry_cases(module,oracle['policy'])
    elif task=='T3':base=accept_t3_v2(module);extra=migration_cases(module,oracle['policy'])
    else:raise ValueError('chain_task_invalid')
    rows=base['checks']+extra['checks']
    success=False if any(r['passed'] is False for r in rows) else None if any(r['passed'] is None for r in rows) else True
    return dict(task=task,round=oracle['round'],success=success,checks=rows,
        constraint_violations=sorted({r['constraint_id'] for r in rows if r['passed'] is False and r['constraint_id']}),
        scope='Deterministic candidate execution; isolated evaluator process required by coordinator.')


def evaluate_work_state(raw,oracle):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('chain_state_duplicate_key')
            result[key]=value
        return result
    try:
        value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite')))
        return dict(success=canonical(value)==canonical(oracle['expected_work_state']),parse_error=None)
    except (ValueError,TypeError,RecursionError) as error:
        return dict(success=False,parse_error=type(error).__name__)
