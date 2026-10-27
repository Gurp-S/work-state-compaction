"""Predeclared release-receipt continuation and exact tool-output evidence."""
import json,random
from hashlib import sha256
from dataset import canonical,seal


def message(role,value):
    return dict(type='message',role=role,content=[dict(type='input_text' if role=='user' else 'output_text',text=canonical(value))])


def build(seed=20261027,count=64):
    if type(count) is not int or count<4:raise ValueError('receipt_count_invalid')
    rng=random.Random(seed);receipts=[];prefix=[message('user',dict(record_type='release.tracking/1',
        application='release-console',current_build_rule='The receipt with the greatest build_number is the current build.',
        historical_receipts='Historical build receipts remain distinct observations.'))]
    for number in range(1,count+1):
        receipt=dict(record_type='release.receipt/1',receipt_id=f'build-{number:03d}',build_number=number,
            artifact=f'artifacts/release-{number:03d}.zip',nonce=f'{rng.getrandbits(128):032x}',
            source_version=f'commit-{rng.getrandbits(64):016x}',test_status='passed')
        receipts.append(receipt);prefix.append(message('assistant',receipt))
        prefix.append(message('assistant',dict(record_type='release.log/1',build_number=number,
            trace=f'{rng.getrandbits(128):032x}',status='upload_complete')))
    target=receipts[2]
    followup=dict(record_type='release.receipt/1',receipt_id=f'build-{count+1:03d}',build_number=count+1,
        artifact=f'artifacts/release-{count+1:03d}.zip',nonce=f'{rng.getrandbits(128):032x}',
        source_version=f'commit-{rng.getrandbits(64):016x}',test_status='passed')
    delta=[message('assistant',followup),message('user',dict(record_type='release.audit_request/1',
        pending_task='Prepare the release audit using the original nonce of build-003 and the current build number.',
        copied_nonce=None))]
    public=dict(schema='wsc.blackbox.recovery-case/1',seed=seed,receipt_count=count,prefix=prefix,delta=delta,
        target_receipt_id=target['receipt_id'],checkpoints=[len(prefix),len(prefix)+len(delta)])
    oracle=dict(public_sha256=seal(public),questions=[dict(question_id='nonce',
        question='What is the exact original nonce of receipt build-003?',answer_type='string',expected=target['nonce']),
        dict(question_id='current',question='What is the current build number?',answer_type='integer',expected=count+1)])
    return public,oracle,target


def decoded_objects(value,seen=None,depth=0):
    """Decode structured tool payloads, not prose entailment or answer scoring."""
    if depth>8:return
    seen=set() if seen is None else seen
    if isinstance(value,dict):
        yield value
        for nested in value.values():yield from decoded_objects(nested,seen,depth+1)
    elif isinstance(value,list):
        for nested in value:yield from decoded_objects(nested,seen,depth+1)
    elif isinstance(value,str) and len(value)<=2*1024*1024:
        identity=sha256(value.encode()).digest()
        if identity in seen:return
        seen.add(identity);decoder=json.JSONDecoder();start=0;attempts=0
        while start<len(value) and attempts<10000:
            brace=value.find('{',start);bracket=value.find('[',start)
            positions=[i for i in (brace,bracket) if i>=0]
            if not positions:break
            position=min(positions);attempts+=1
            try:
                parsed,end=decoder.raw_decode(value,position);start=end
                yield from decoded_objects(parsed,seen,depth+1)
            except ValueError:start=position+1


def tool_recovery_evidence(rows,manifest,source_object,target):
    expected={key:seal(value) for key,value in [('manifest',manifest),('source_object',source_object),('receipt',target)]}
    hits={key:[] for key in expected}
    for index,row in enumerate(rows,1):
        payload=row.get('payload',{})
        if row.get('type')!='response_item' or payload.get('type') not in ('function_call_output','custom_tool_call_output'):continue
        for value in decoded_objects(payload.get('output')):
            checksum=seal(value)
            for kind,match in expected.items():
                if checksum==match:hits[kind].append(index)
    return dict(exact_objects_in_model_tool_outputs={k:sorted(set(v)) for k,v in hits.items()},
        full_source_object_observed=bool(hits['source_object']),target_receipt_observed=bool(hits['receipt']),
        scope='Exact JSON object equality in native model tool results only; not keyword scoring or proof that every correct answer required recovery.')
