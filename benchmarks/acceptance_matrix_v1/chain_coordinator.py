"""Receipt-bound six-round orchestration; adapters own actual native/WSC I/O.

The adapter receives released events and requests only, never an oracle or the
future schedule. Qualification runs are explicitly not experimental results.
"""
from copy import deepcopy
from .chain_dataset import release_round
from .evidence import seal


def aggregate(phases, *, failure=None):
    entries=[];seen={};complete=bool(phases) and failure is None
    for phase in phases:
        complete &= phase.get('usage_complete') is True
        if phase.get('failure') or phase.get('completed') is not True:
            failure=failure or phase.get('failure') or 'chain_model_phase_not_completed'
        for receipt in phase.get('receipts',{}).get('response_receipts',[]):
            identity=receipt.get('response_id')
            if not identity or identity in seen:
                complete=False
                if identity in seen and seen[identity]!=receipt.get('usage'):
                    failure=failure or 'chain_conflicting_response_receipt'
                continue
            seen[identity]=receipt.get('usage');entries.append(deepcopy(receipt))
    return dict(usage_complete=complete,completed=failure is None,failure=failure,
                receipts=dict(response_receipts=entries))


class ChainCoordinator:
    """One logical task arm. The caller owns ledger creation and root admission."""
    def __init__(self,schedule,oracle,registration,ledger,run_id,timing,*,qualification_only=False):
        if (schedule.get('checkpoints')!=[2,4,6] or len(schedule.get('rounds',[]))!=6
                or [r.get('round') for r in schedule['rounds']]!=list(range(1,7))):
            raise ValueError('chain_schedule_shape_invalid')
        digest=seal(schedule)
        if oracle.get('schedule_sha256')!=digest or registration.get('schedule_sha256')!=digest:
            raise ValueError('chain_schedule_binding_changed')
        if registration.get('oracle_sha256')!=seal(oracle):raise ValueError('chain_oracle_binding_changed')
        if registration.get('arm') not in ('Bprime','C'):raise ValueError('chain_arm_invalid')
        if registration.get('session_semantics') not in ('logical_task','same_native_thread'):
            raise ValueError('chain_session_semantics_unregistered')
        if not qualification_only and registration.get('paid_dispatch_authorized') is not True:
            raise ValueError('chain_dispatch_not_authorized')
        expected={*(f'compress-{n}' for n in range(1,7)),*(f'task-{n}' for n in (2,4,6))}
        if set(registration.get('phase_limits',{}))!=expected:raise ValueError('chain_phase_limits_incomplete')
        binding=ledger.runs[run_id]['spec']['binding']
        if binding.get('schedule_sha256')!=digest or binding.get('oracle_sha256')!=seal(oracle):
            raise ValueError('chain_ledger_binding_changed')
        self.schedule,self.oracle,self.registration=deepcopy(schedule),deepcopy(oracle),deepcopy(registration)
        self.ledger,self.run_id,self.timing=ledger,run_id,timing
        self.qualification_only=qualification_only
        self.rows=[];self.started=False

    def run(self,adapter,evaluator):
        if self.started:raise ValueError('chain_already_started_no_replay')
        if (self.registration['session_semantics']=='same_native_thread'
                and adapter.supports_native_thread_continuity is not True):
            raise ValueError('chain_adapter_cannot_preserve_native_thread')
        if not self.qualification_only and adapter.real_dispatch_qualified is not True:
            raise ValueError('chain_adapter_not_qualified_for_real_dispatch')
        self.started=True;opened=False;closed=False;error=None;cleanup_outside_reservation=False

        def stage(identity,operation,*,final=False):
            nonlocal opened,closed
            grant=self.ledger.reserve(self.run_id,identity,self.registration['phase_limits'][identity])
            ticket=grant['ticket'];phases=[];failure=None;value=None
            def record(phase):phases.append(deepcopy(phase))
            try:
                self.ledger.bind_input(ticket,dict(operation=identity,
                    schedule_sha256=self.registration['schedule_sha256']))
                with self.timing.measure(identity):
                    # Setup is inside the first reserved interval. No implicit
                    # zero-cost inference is inferred from a missing record.
                    if not opened:
                        opened=True
                        self.timing.call('host.chain_open',adapter.open,
                            deepcopy(self.schedule['initial_history']),
                            lambda:self.ledger.remaining(ticket),record)
                    value=operation(lambda:self.ledger.remaining(ticket),record)
            except BaseException as exc:
                failure=type(exc).__name__+':'+str(exc)
                raise
            finally:
                if final or failure:
                    for attempt in range(2):
                        try:
                            self.timing.call('host.chain_close',adapter.close);closed=True;break
                        except BaseException as exc:
                            failure=failure or 'chain_close_failed:'+type(exc).__name__
                phase=aggregate(phases,failure=failure)
                row=dict(stage=identity,phase=phase,settlement=None);self.rows.append(row)
                try:
                    settlement=self.ledger.settle(ticket,phase);row['settlement']=settlement
                except BaseException as exc:
                    row['settlement_error']=type(exc).__name__;raise
            if not phase['usage_complete'] or phase['failure'] or settlement['arm_stopped']:
                raise ValueError('chain_stage_incomplete_or_stopped')
            return value

        checkpoints=[]
        full_chain=self.timing.measure('full_chain');full_chain.__enter__()
        try:
            with self.timing.measure('chain.rounds'):
                for number in range(1,7):
                    def compress(remaining,record,number=number):
                        self.timing.call('history.release',adapter.append_events,
                            release_round(self.schedule,number),number,remaining,record)
                        proof=self.timing.call('compression.boundary',adapter.compress,number,remaining,record)
                        if type(proof) is not dict or proof.get('confirmed') is not True:
                            raise ValueError('chain_compression_not_confirmed')
                        return proof
                    proof=stage('compress-'+str(number),compress)
                    self.rows[-1]['compression_evidence']=deepcopy(proof)
                    if number not in (2,4,6):continue
                    def checkpoint(remaining,record,number=number):
                        snapshot=self.timing.call('task.continue',adapter.continue_task,
                            self.schedule['rounds'][number-1]['checkpoint_request'],number,remaining,record)
                        # Private expected values enter only the coordinator's
                        # evaluator after the actor turn has ended.
                        result=self.timing.call('task.evaluate',evaluator,snapshot,
                            deepcopy(self.oracle['rounds'][str(number)]))
                        if (type(result) is not dict or 'task_success' not in result
                                or not (type(result['task_success']) is bool or result['task_success'] is None)):
                            raise ValueError('chain_evaluator_result_invalid')
                        return dict(round=number,result=result)
                    checkpoints.append(stage('task-'+str(number),checkpoint,final=number==6))
        except BaseException as exc:
            error=dict(type=type(exc).__name__,code=str(exc))
        finally:
            if opened and not closed:
                # A failed cleanup is not a reason to replay a task or model call.
                cleanup_outside_reservation=True
                try:self.timing.call('host.cleanup_retry',adapter.close);closed=True
                except BaseException as exc:
                    error=error or dict(type=type(exc).__name__,code='chain_cleanup_unconfirmed')
            full_chain.__exit__(None,None,None)
        all_passed=len(checkpoints)==3 and all(c['result']['task_success'] is True for c in checkpoints)
        result=dict(success=all_passed and error is None,qualification_only=self.qualification_only,
            experimental_result=not self.qualification_only,checkpoints=checkpoints,stages=self.rows,
            failure=error,cleanup_confirmed=closed,timing=self.timing.snapshot(),
            cleanup_outside_reservation=cleanup_outside_reservation,
            scope='One arm, one chain. Not a paired result, repetition statistic or native-default performance claim.')
        if self.ledger.runs[self.run_id]['status']=='running':self.ledger.finish(self.run_id,result)
        return result
