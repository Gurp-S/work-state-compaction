"""Black-box behavior contracts: never inspect/decrypt compaction semantics."""
from hashlib import sha256
import json
import math
from dataset import canonical


def strict_json(text):
    def pairs(values):
        result={}
        for key,value in values:
            if key in result:raise ValueError('duplicate_json_key')
            result[key]=value
        return result
    def number(value):
        parsed=float(value)
        if not math.isfinite(parsed):raise ValueError('nonfinite_json_number')
        return parsed
    def reject(value):raise ValueError('nonfinite_json_number')
    return json.loads(text,object_pairs_hook=pairs,parse_float=number,parse_constant=reject)


def questions(oracle):
    return dict(questions=[{key:item[key] for key in ('question_id','question','answer_type')}
                          for item in oracle['questions']],
        response_contract=dict(answers=[dict(question_id='question identity',value='JSON value of requested type')]))


def score_answer(text,oracle):
    errors=[];by_id={};duplicate=set()
    try:
        value=strict_json(text)
        if not isinstance(value,dict) or set(value)!= {'answers'} or not isinstance(value['answers'],list):
            raise ValueError('answer_envelope_invalid')
        for item in value['answers']:
            if not isinstance(item,dict) or set(item)!= {'question_id','value'} or not isinstance(item['question_id'],str):
                raise ValueError('answer_item_invalid')
            key=item['question_id']
            if key in by_id:duplicate.add(key)
            by_id[key]=item['value']
    except (ValueError,TypeError) as error:errors.append(type(error).__name__+':'+str(error))
    allowed={item['question_id'] for item in oracle['questions']}
    extras=sorted(set(by_id)-allowed)
    if extras:errors.append('unexpected_question_ids:'+canonical(extras))
    details=[]
    for question in oracle['questions']:
        key=question['question_id']
        if question.get('verification')=='unscorable':verdict='unscorable'
        elif errors or key in duplicate:verdict='invalid'
        elif key not in by_id:verdict='missing'
        else:verdict='correct' if canonical(by_id[key])==canonical(question['expected']) else 'incorrect'
        details.append(dict(question_id=key,verdict=verdict,actual_present=key in by_id,
            actual=by_id.get(key),expected=question.get('expected')))
    return dict(details=details,protocol_errors=errors,duplicate_question_ids=sorted(duplicate),
        counts={name:sum(item['verdict']==name for item in details) for name in (
            'correct','incorrect','missing','invalid','unscorable')},
        scope='Observed system answers only; no claim about encrypted summary content.')


def compression_evidence(before,after,phase,events):
    """Confirm operation from durable boundaries + bound receipt + terminal event."""
    reasons=[]
    def check(ok,reason):
        if not ok:reasons.append(reason)
    check(after.startswith(before),'source_prefix_changed')
    rows=[strict_json(line) for line in after.decode('utf-8').splitlines() if line.strip()]
    prior=[strict_json(line) for line in before.decode('utf-8').splitlines() if line.strip()]
    local=rows[len(prior):] if after.startswith(before) else []
    tid=phase.get('thread_id');turn=phase.get('usage_completion_evidence',{}).get('turn_id')
    check(bool(tid) and bool(turn),'identity_missing')
    baseline=phase.get('turn_accounting',{}).get('before',{})
    check(baseline.get('sha256')==sha256(before).hexdigest() and baseline.get('byte_length')==len(before),'baseline_binding_changed')
    check(phase.get('compaction') is True,'explicit_compaction_not_registered')
    check(sha256(after).hexdigest()==phase.get('rollout_sha256'),'source_digest_changed')
    check(phase.get('completed') is True and not phase.get('failure'),'phase_not_successful')
    check(phase.get('usage_complete') is True,'phase_usage_unknown')
    receipts={r['payload'].get('response_id'):r['payload'] for r in local if r.get('type')=='token_usage_record'}
    compacted=[(i,r['payload']) for i,r in enumerate(local) if r.get('type')=='compacted']
    check(len(compacted)==1,'compaction_count_not_one')
    for index,item in compacted:
        receipt=receipts.get(item.get('compaction_response_id'))
        check(receipt is not None and item.get('latest_token_usage_record')==receipt,'compaction_receipt_unbound')
        if receipt:
            check(receipt.get('thread_id')==tid and receipt.get('turn_id')==turn,'compaction_receipt_identity_changed')
            check(any(r.get('type')=='token_usage_record' and r['payload']==receipt for r in local[:index]),'compaction_receipt_order_changed')
    check(sum(r.get('type')=='event_msg' and r.get('payload',{}).get('type')=='task_complete'
        and r['payload'].get('turn_id')==turn for r in local)==1,'durable_completion_missing')
    terminal=[e.get('params',{}).get('turn',{}) for e in events if e.get('method')=='turn/completed'
        and e.get('params',{}).get('threadId')==tid and e.get('params',{}).get('turn',{}).get('id')==turn]
    check(len(terminal)==1 and terminal[0].get('status')=='completed','native_terminal_missing')
    return dict(confirmed=not reasons,reasons=reasons,thread_id=tid,turn_id=turn,
        before_sha256=sha256(before).hexdigest(),after_sha256=sha256(after).hexdigest(),
        summary_content_inspected=False,scope='Exactly one explicit idle native compaction; phase accounting is independently required.')
