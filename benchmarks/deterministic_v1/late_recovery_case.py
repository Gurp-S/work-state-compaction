"""Predeclared late absolute position and delayed recovery request."""
from copy import deepcopy
import json
from blackbox_recovery_case import build as original,message
from dataset import seal


def build(seed=20261028,count=320,target_number=270):
    if type(target_number) is not int or not 256<target_number<count-16:raise ValueError('late_target_not_late_or_distant')
    public,_,_=original(seed,count);public=deepcopy(public)
    receipts=[json.loads(item['content'][0]['text']) for item in public['prefix'] if item['role']=='assistant']
    target=next(value for value in receipts if value.get('record_type')=='release.receipt/1' and value['build_number']==target_number)
    identity=target['receipt_id']
    public.update(schema='wsc.blackbox.late-recovery-case/1',target_receipt_id=identity,target_build_number=target_number)
    public['delta'][-1]=message('user',dict(record_type='release.audit_request/1',pending_task=f'Prepare the release audit using the original nonce of {identity} and the current build number.',copied_nonce=None))
    oracle=dict(public_sha256=seal(public),questions=[dict(question_id='nonce',question=f'What is the exact original nonce of receipt {identity}?',answer_type='string',expected=target['nonce']),
        dict(question_id='current',question='What is the current build number?',answer_type='integer',expected=count+1)])
    return public,oracle,target
