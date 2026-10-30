"""One preregistered real recovery admission; not a compression comparison."""
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'benchmarks'))
from acceptance_matrix_v1.campaign_allocation import remaining
from acceptance_matrix_v1.dispatch_budget import DispatchBudget
from native_provider_chatgpt import ChatGPTProvider

PARENT=Path('D:/agent-task-runs/wsc-deferred-catalog-qualification-20261027-v1')
PARENT_SHA='cbf8bc5592dd873ab2394ea2b9f2e2f322c77b4d55c9c1498cd6f0749dab41af'
LIMITS=dict(max_total_tokens=100000,max_responses=4,max_seconds=180)
TARGET_INDEX=3500


def save(path,value):
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)


class LiveContextTrial:
    def __init__(self,*,revision=1):
        if revision not in (1,2):raise ValueError('trial_revision_unregistered')
        self.revision=revision
        self.nonce=uuid4().hex+uuid4().hex
        records=[dict(index=i,token=sha256(('fixture-'+str(i)).encode()).hexdigest()) for i in range(7000)]
        records[TARGET_INDEX]['token']=self.nonce
        self.text=json.dumps(dict(records=records),separators=(',',':'))
        self.target=dict(coordinates='RFC6901_zero_based_array_index',index=TARGET_INDEX,pointer=f'/records/{TARGET_INDEX}/token')
        self.request=f'返回历史工具结果中 JSON Pointer {self.target["pointer"]} 指定的原文值（数组索引从0计数）。JSON 字段 answer 为该值，reference 为该结果的 result:rN 引用。'
        self.schema=dict(type='object',properties=dict(answer=dict(type='string'),reference=dict(type='string')),
            required=['answer','reference'],additionalProperties=False)
        self.receipts=[];self.messages=[];self.ledger=None;self.ticket=None;self.settled=False;self.network_attempts=0
        home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
        self.provider=ChatGPTProvider(home/'auth.json',timeout=45)

    def prepare(self,out,registration,view):
        self.private=out/'coordinator-private';self.reference='result:'+view['result_id']
        self.provider.capture=self.private/'provider-responses'
        self.provider.capture.mkdir(exist_ok=False)
        if self.nonce in json.dumps(view):raise ValueError('trial_answer_leaked_into_view')
        envelope=PARENT/'next-admission-envelope.json'
        if sha256(envelope.read_bytes()).hexdigest()!=PARENT_SHA:raise ValueError('trial_parent_envelope_changed')
        claims=list(PARENT.glob('matrix-*.claim.json'))
        before=remaining(json.loads(envelope.read_bytes())['remaining_limits'],[json.loads(p.read_bytes())['limits'] for p in claims])
        after=remaining(before,[LIMITS]);claim=PARENT/('matrix-context-recovery-20261030.claim.json' if self.revision==1 else 'matrix-context-recovery-20261030-r2.claim.json')
        repair={}
        if self.revision==2:
            previous=Path('D:/agent-task-runs/wsc-live-context-recovery-20261030-v1/coordinator-private/live-outcome.json')
            error_check=Path('D:/agent-task-runs/wsc-native-owner-error-20261030-v1/results.json')
            old=json.loads(previous.read_bytes());check=json.loads(error_check.read_bytes())
            if old['success'] or old['usage_complete'] or check.get('owner_error_return_verified') is not True or check['real_model_calls']!=0:
                raise ValueError('trial_revision_repair_evidence_missing')
            repair=dict(previous_failure_retained=str(previous),previous_failure_sha256=sha256(previous.read_bytes()).hexdigest(),
                owner_error_check_sha256=sha256(error_check.read_bytes()).hexdigest(),
                reason='Capture raw/partial response before media checks; bounded protocol classification and immediate owner errors',
                same_admission_family_attempt=2,previous_allocation_frozen=True)
        self.registration=dict(kind='actual_model_context_recovery_admission_not_BC',model='gpt-6.1-sol',effort='max',
            limits=LIMITS,revision=self.revision,repair_evidence=repair,max_parallel=1,no_automatic_retry=True,temperature=None,seed=None,
            parent_sha256=PARENT_SHA,allocation_before=before,allocation_after=after,
            existing_claims_sha256={str(p):sha256(p.read_bytes()).hexdigest() for p in claims},
            source_registration_sha256=sha256(registration.read_bytes()).hexdigest(),
            target=self.target,user_request=self.request,user_request_sha256=sha256(self.request.encode()).hexdigest(),
            original_sha256=sha256(self.text.encode()).hexdigest(),oracle_sha256=sha256(self.nonce.encode()).hexdigest(),
            qualification='Completed turn, actual query, exact final nonce and reference, complete response receipts',
            input_capacity='unobserved; system blackbox',token_cap='Response-boundary admission; overshoot retained, not provider-side hard cap',
            credentials='Host only; never archived',old_unknowns_preserved=True)
        save(self.private/'live-registration.json',self.registration)
        save(self.private/'oracle.json',dict(answer=self.nonce,reference=self.reference))
        save(claim,dict(child=str(out),limits=LIMITS,parent_sha256=PARENT_SHA,
            registration_sha256=sha256((self.private/'live-registration.json').read_bytes()).hexdigest(),
            allocation_is_not_spend=True,old_unknowns_preserved=True))
        self.ledger=DispatchBudget(self.private/'live-ledger.db',{'context':dict(arm='context',limits=LIMITS,
            binding=dict(registration_sha256=sha256((self.private/'live-registration.json').read_bytes()).hexdigest()))},LIMITS)
        self.ticket=self.ledger.reserve('context','one-turn',LIMITS)

    def exchange(self,raw):
        self.ledger.remaining(self.ticket['ticket'])
        if self.network_attempts>=4 or len(self.receipts)!=self.network_attempts:
            raise ValueError('trial_prior_response_unknown_or_limit')
        if sum(v['usage']['total_tokens'] for v in self.receipts)>=LIMITS['max_total_tokens']:
            raise ValueError('trial_token_cap')
        self.network_attempts+=1
        status,kind,body=self.provider(raw)
        completed=[]
        if kind=='text/event-stream':
            for line in body.decode('utf-8').splitlines():
                if not line.startswith('data: '):continue
                try:event=json.loads(line[6:])
                except ValueError:continue
                if event.get('type')=='response.completed':completed.append(event['response'])
        if status==200 and len(completed)==1:
            response=completed[0];usage=response.get('usage',{})
            if all(type(usage.get(k)) is int and usage[k]>=0 for k in ('input_tokens','output_tokens','total_tokens')):
                self.receipts.append(dict(response_id=response['id'],usage=usage))
            self.messages.extend(i for i in response.get('output',[]) if i.get('type')=='message' and i.get('role')=='assistant')
        return status,kind,body

    def finish(self,callbacks,*,failure=None):
        answer=None
        if self.messages:
            text=''.join(c.get('text','') for c in self.messages[-1].get('content',[]) if c.get('type')=='output_text')
            try:answer=json.loads(text)
            except ValueError:pass
        complete=len(self.receipts)==self.network_attempts and self.network_attempts>0
        correct=answer==dict(answer=self.nonce,reference=self.reference)
        outcome=dict(real_model_calls_attempted=self.network_attempts,known_response_receipts=len(self.receipts),
            usage_complete=complete,exact_answer_and_reference=correct,actual_callbacks=len(callbacks),
            success=failure is None and correct and len(callbacks)>0 and complete,
            failure=failure,receipts=dict(response_receipts=self.receipts),provider_trace=self.provider.trace,
            scope='One actual-model external-result recovery admission; no compression, quality superiority or BC conclusion')
        outcome['settlement']=self.ledger.settle(self.ticket['ticket'],outcome);self.settled=True
        self.ledger.finish('context',outcome)
        save(self.private/'live-outcome.json',outcome)
        return outcome

    def close(self):
        if self.ledger:self.ledger.close()
