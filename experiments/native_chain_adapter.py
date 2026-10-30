"""Bprime adapter: one native thread, real V2 stage, bounded closed-turn copies.

The factory owns the closed-mount runtime, gateway admission and cleanup. This
adapter never loads authentication, an oracle, reference code or a future round.
"""
from hashlib import sha256
from pathlib import Path
import time

from wsc.evidence import link_like
from wsc.resource_io import ResourceIO
from native_chain_compaction import compact, bounded
from native_compaction_profile import PROFILE
from native_evidence import state, import_evidence, save
from native_rollout_snapshot import parse_rollout


class NativeChainAdapter:
    supports_native_thread_continuity=True
    real_dispatch_qualified=False

    def __init__(self,factory,directory,*,model,effort,entry,public_test_sha256,max_evidence_bytes=32*1024*1024):
        if entry not in ('retry_client.py','migrate.py'):raise ValueError('chain_entry_invalid')
        if type(max_evidence_bytes) is not int or max_evidence_bytes<=0:raise ValueError('chain_native_evidence_limit_invalid')
        self.factory,self.directory=factory,Path(directory)
        self.directory.mkdir(parents=True,exist_ok=False)
        self.model,self.effort,self.entry=model,effort,entry
        self.public_test_sha256=public_test_sha256
        self.limit=max_evidence_bytes;self.session=None;self.identity=None;self.last_round=0
        self.io=ResourceIO()

    def _identity(self):
        session=self.session
        if session is None or session.closed:raise ValueError('chain_native_session_not_live')
        actual=dict(thread=session.opened['thread']['id'],model=session.registration['model'],
            effort=session.registration['effort'],guest_workspace=session.registration['workspace'],
            workspace=str(session.workspace_path()),history=str(session.rollout_path()),server=id(session.server))
        if (actual['model']!=self.model or actual['effort']!=self.effort
                or actual['guest_workspace']!='/work/actor' or session.opened.get('cwd')!='/work/actor'
                or session.registration.get('native_compaction_profile')!=PROFILE):
            raise ValueError('chain_native_configuration_changed')
        if self.identity is not None and actual!=self.identity:raise ValueError('chain_native_identity_changed')
        return actual

    def _inject(self,items,directory,remaining):
        self._identity();remaining()
        directory.mkdir()
        history=self.session.rollout_path();before=bounded(history,self.limit);parsed=parse_rollout(before)
        if not parsed.metadata['parse_complete']:raise ValueError('chain_native_history_incomplete')
        old=state(parsed.rows)
        self.session.server.call('thread/inject_items',dict(threadId=self.identity['thread'],items=items),
                                 timeout=min(15,remaining()['max_seconds']))
        deadline=time.monotonic()+min(3,remaining()['max_seconds'])
        while True:
            after=bounded(history,self.limit)
            if not after.startswith(before):raise ValueError('chain_native_injection_prefix_changed')
            observed=parse_rollout(after)
            if observed.metadata['parse_complete']:
                current=state(observed.rows)
                if len(current)>=len(old)+len(items):break
            if time.monotonic()>=deadline:raise ValueError('chain_native_injection_unobserved')
            time.sleep(.02)
        if current[:len(old)]!=old or len(current)!=len(old)+len(items):
            raise ValueError('chain_native_injection_history_changed')
        proof=import_evidence(current[len(old):],items)
        if proof.get('matched') is not True or proof['start_ordinal']!=0:
            raise ValueError('chain_native_injection_items_changed')
        (directory/'appended.jsonl').write_bytes(after[len(before):])
        save(directory/'proof.json',dict(before_sha256=sha256(before).hexdigest(),after_sha256=sha256(after).hexdigest(),
            before_bytes=len(before),after_bytes=len(after),native_import=proof,thread_id=self.identity['thread']))

    def open(self,initial_history,remaining,record):
        if self.session is not None:raise ValueError('chain_native_open_replay')
        if hasattr(self.factory,'open_with_history'):
            self.session=self.factory.open_with_history(initial_history,remaining)
        else:self.session=self.factory(remaining)
        self.identity=self._identity()
        if hasattr(self.session,'chain_initial_import'):
            from native_evidence import digest
            proof=self.session.chain_initial_import
            if proof.get('items_sha256')!=digest(initial_history) or not proof.get('import_evidence',{}).get('matched'):
                raise ValueError('chain_native_initial_import_changed')
        else:self._inject(initial_history,self.directory/'initial-import',remaining)
        # Non-inference setup is explicit. The following real compaction still
        # has to provide nonempty complete usage to the coordinator ledger.
        record(dict(completed=True,usage_complete=True,failure=None,receipts=dict(response_receipts=[])))

    def append_events(self,items,number,remaining,record):
        if type(number) is not int or number!=self.last_round+1:raise ValueError('chain_native_round_order_invalid')
        self._inject(items,self.directory/('round-'+str(number)+'-import'),remaining)
        self.last_round=number

    def compress(self,number,remaining,record):
        self._identity()
        if number!=self.last_round:raise ValueError('chain_native_round_binding_changed')
        if hasattr(self.session,'bind_phase_budget'):self.session.bind_phase_budget(remaining)
        return compact(self.session,self.directory/('round-'+str(number)+'-compression'),remaining(),record,
                       max_evidence_bytes=self.limit)

    def _snapshot(self,number,phase):
        self._identity();work=Path(self.identity['workspace'])
        folder=self.directory/('round-'+str(number)+'-artifact');folder.mkdir()
        files={};errors=[]
        for name,limit in ((self.entry,1048576),('work_state.json',8192),('test_smoke.py',1048576)):
            source=work/name
            try:
                for part in (source,*source.parents):
                    if link_like(part):raise ValueError('chain_artifact_path_link')
                raw=self.io.read_bounded(source,limit+1)
                if len(raw)>limit:raise ValueError('chain_artifact_size_exceeded')
                (folder/name).write_bytes(raw)
                files[name]=dict(path=str(folder/name),sha256=sha256(raw).hexdigest(),bytes=len(raw))
            except (OSError,ValueError) as error:errors.append(dict(file=name,error=type(error).__name__))
        # A second read detects visible mutation during the multi-file copy.
        # It is not a filesystem transaction or a background-process barrier.
        for name,value in files.items():
            try:
                if self.io.digest(work/name,max_bytes=value['bytes'])!=value['sha256']:
                    errors.append(dict(file=name,error='artifact_changed'))
            except (OSError,ValueError) as error:errors.append(dict(file=name,error=type(error).__name__))
        result=dict(round=number,task_phase=phase,files=files,errors=errors,
            public_test_preserved=files.get('test_smoke.py',{}).get('sha256')==self.public_test_sha256,
            scope='Closed-turn bounded regular-file copy with two-pass stability; not atomic or proof of no background writer.')
        save(folder/'snapshot.json',result)
        return result

    def continue_task(self,request,number,remaining,record):
        self._identity()
        if number!=self.last_round or number not in (2,4,6):raise ValueError('chain_native_checkpoint_invalid')
        if hasattr(self.session,'bind_phase_budget'):self.session.bind_phase_budget(remaining)
        phase=self.session.execute_stage(request,self.directory/('round-'+str(number)+'-task'),remaining(),record)
        return self._snapshot(number,phase)

    def close(self):
        if self.session is not None and not self.session.closed:return self.session.close()
