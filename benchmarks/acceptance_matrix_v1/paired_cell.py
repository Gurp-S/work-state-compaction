"""One registered cell; existing native transport and WSC generation/publication."""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'experiments'),str(ROOT/'benchmarks/deterministic_v1')]
from wsc import WSC,Store,HostReceipt
from wsc.adapters.codex import CodexCheckpointAdapter
from wsc.evidence import write_once
from wsc.resource_io import ResourceIO
from wsc.source_access import SnapshotSourceAccess,SourceAccessLimits
from wsc.source_reference_view import MODE
from wsc.contracts import encode
from native_incremental_candidate import prepare,admit_rendered
from native_incremental_generation import generate
from native_indexed_checkpoint import IndexedCheckpointAdapter
from native_snapshot_aliases import validate_recovery_aliases
from native_task_recovery import open_task_receiver
from native_blackbox_sessions import fresh,import_fresh
from native_rollout_snapshot import capture_rollout
from native_evidence import state
from blackbox import compression_evidence
from .permissions import permission_flags,PROFILE,runtime_startup_flags
from .evidence import seal
from .acceptors import accept_t1,load_candidate


def save(path,value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)


class NativeCheckpointHost:
    """Explicit native acceptance and durable receipt; never inferred from export."""
    def __init__(self,port,bootstrap,folder):
        self.port,self.bootstrap,self.folder=port,bootstrap,Path(folder)
    def install(self,package):
        policy=package.get('adapter',{}).get('actor_projection_policy')
        if policy is not None:
            from native_hot_checkpoint import POLICY,validate_hot_recovery_aliases
            if policy!=POLICY:raise ValueError('actor_projection_policy_unknown')
            validate_hot_recovery_aliases(package,self.port.handler.reader)
        else:validate_recovery_aliases(package,self.port.handler.reader)
        proof=import_fresh(self.port.session,package['items'],self.bootstrap,self.folder)
        self.port._require_live()
        receipt=HostReceipt(operation_id=package['operation_id'],package_digest=package['package_digest'],
            session_id=package['binding']['session_id'],workspace=package['binding']['workspace'],generation=package['next_generation'],
            control_epoch=package['binding']['control_epoch'],installed_through=package['through'],
            receiver=self.port.owner,evidence_accessible=True)
        write_once(self.folder/'host-receipt.json',encode(asdict(receipt)).encode('utf-8'))
        save(self.folder/'host-import-proof.json',proof)
        return receipt
    def lookup(self,key):
        p=self.folder/'host-receipt.json'
        if not p.exists():return None
        value=json.loads(p.read_text(encoding='utf-8'))
        return HostReceipt(**value) if value['operation_id']==key else None


class Cell:
    def __init__(self,name,plan,out,ledger,inputs,*,ledger_id=None,prepared_folder=False):
        self.name,self.plan,self.out,self.ledger,self.inputs=name,plan,Path(out),ledger,inputs
        self.run_id=ledger_id or name
        self.folder=self.out/'coordinator-private'/name
        self.folder.mkdir(exist_ok=prepared_folder)
        self.work=self.out/name
        self.sessions=[]
        self.phases=[]
    def close_session(self,session):
        session.server.owner.close()
        return session.close()
    def open(self,label,*,selector=False,dynamic_tools=(),selector_runtime=None):
        work=self.out/'C-selector' if selector else self.work
        blocked=self.plan['blocked']+[str(self.out/p) for p in self.plan.get('workspace_names',('Bprime','C','C-selector')) if self.out/p!=work]
        reg=dict(workspace=str(work),executable=self.plan['executable'],executable_sha256=self.plan['executable_sha256'],
                 **self.plan['model'])
        session=fresh(reg,self.folder/(label+'-session'),dynamic_tools=dynamic_tools,selector_runtime=selector_runtime,
            host_permissions=dict(profile=PROFILE,startup_flags=permission_flags(work,blocked)+runtime_startup_flags(self.plan)),
            startup_timeout=self.plan.get('startup_timeout_seconds',20))
        original=session.close
        def close():
            session.server.owner.close()
            return original()
        session.close=close
        self.sessions.append(session)
        session.server.call('thread/inject_items',dict(threadId=session.opened['thread']['id'],items=[dict(type='message',role='assistant',
            content=[dict(type='output_text',text='{"record_type":"bench.bootstrap/1","id":"matrix-paired-cell"}')])]))
        bootstrap=state(capture_rollout(session.opened['thread']['path']).rows)
        return session,bootstrap
    def start(self,label):
        return self.ledger.reserve(self.run_id,label,self.plan['run_limits'][self.name])['ticket']
    def call(self,ticket,session,request,label,*,schema=None,compact=False,port=None):
        limits=self.ledger.remaining(ticket)
        self.ledger.bind_input(ticket,dict(request_sha256=sha256(request.encode('utf-8')).hexdigest(),schema_sha256=seal(schema),
            operation='native_compact' if compact else 'model_turn',thread_id=session.opened['thread']['id'],
            input_history_sha256=self.ledger.runs[self.run_id]['spec']['binding']['history_sha256']))
        frames=[]
        if port is None:
            phase=session.execute_stage(request,self.folder/label,limits,frames.append,compact=compact,output_schema=schema)
        else:
            def admission(actual,text,output_schema):
                self.ledger.remaining(ticket)
                return dict(comparison='system_blackbox',capacity_status='unobserved',request_input_tokens=None,
                    budget_ticket=ticket,limits=limits,thread_id=port.owner,workspace=port.workspace,
                    request_sha256=sha256(text.encode('utf-8')).hexdigest(),source_digest=port.handler.reader.snapshot_binding['source_digest'])
            phase=port.execute_stage(request,self.folder/label,limits,frames.append,output_schema=schema,system_admission=admission)
        if len(frames)!=1 or frames[0]!=phase:raise ValueError('paired_phase_receipt_not_unique')
        self.phases.append(phase)
        return phase
    def settle(self,ticket,phase,error=None):
        value=dict(phase) if phase else dict(receipts=dict(response_receipts=[]),usage_complete=False)
        if error:value['failure']=str(error)
        return self.ledger.settle(ticket,value)
    def evaluate_artifact(self):
        return accept_t1(load_candidate(self.work/'retry_client.py'))
    def run(self):
        ticket,phase=None,None
        result=None
        try:
            ticket=self.start('compression')
            if self.name=='Bprime':
                session,bootstrap=self.open('native')
                import_fresh(session,self.inputs['prefix'],bootstrap,self.folder/'native-session')
                before=Path(session.opened['thread']['path']).read_bytes()
                phase=self.call(ticket,session,'explicit idle native compression','compression',compact=True)
                events=[json.loads(line) for line in (self.folder/'compression/events.jsonl').read_text(encoding='utf-8').splitlines()]
                proof=compression_evidence(before,(self.folder/'compression/rollout.jsonl').read_bytes(),phase,events)
                save(self.folder/'compression-proof.json',proof)
                if not proof['confirmed']:raise ValueError('native_compression_unconfirmed')
                self.settle(ticket,phase);ticket,phase=None,None
                port=None
            else:
                core=WSC(Store(self.folder/'state.db',session_id=self.out.name,workspace=str(self.work)),access=lambda *a:True,
                    resource_io=ResourceIO(),query_policy='prefix_index_v1',publication_policy='bounded_catalog_v1')
                source=self.plan['source_presentation']
                batch=CodexCheckpointAdapter().import_items(self.inputs['prefix'],thread_id=source['thread_id'],
                                                            start_ordinal=source['bootstrap_items'])
                core.ingest(batch)
                core.presented('qualified-import:'+source['sha256'],tuple(event.id for event in batch if event.kind=='result'),
                               receiver=source['thread_id'])
                snapshot=core.capture()
                selector,_=self.open('selector',selector=True,selector_runtime='source_selector_minimal_v1')
                def choose(offered):
                    def execute(request,schema):
                        nonlocal phase
                        text=json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':'))
                        phase=self.call(ticket,selector,text,'selection',schema=schema)
                        return phase,self.folder/'selection/rollout.jsonl'
                    return generate(offered,execute,self.out/'C-selector/generation',short_span_handles=True,compact_wire=True)
                prepared=prepare(core,snapshot,None,self.out/'C-selector/cold-public',choose,source_projection=MODE)
                self.close_session(selector)
                reader=SnapshotSourceAccess(core.store,snapshot,access=core.access,limits=SourceAccessLimits(**self.plan['recovery_limits']))
                holder={}
                def factory(**kwargs):
                    session,bootstrap=self.open('receiver',**kwargs)
                    holder['bootstrap']=bootstrap
                    return session
                port=open_task_receiver(factory,reader)
                session=port.session
                adapter=IndexedCheckpointAdapter()
                if self.plan.get('actor_projection_policy') is not None:
                    from native_hot_checkpoint import POLICY,HotCheckpointAdapter
                    if self.plan['actor_projection_policy']!=POLICY:raise ValueError('actor_projection_policy_unknown')
                    adapter=HotCheckpointAdapter()
                operation=core.stage(prepared['view'],directory=self.folder/'exports',archive_directory=self.folder/'cold-objects',adapter=adapter)
                package=admit_rendered(core.package(operation))
                receipt=core.install(operation,NativeCheckpointHost(port,holder['bootstrap'],self.folder/'receiver-session'))
                save(self.folder/'publication.json',dict(operation=operation,receipt=receipt,package=package,
                    continuation=prepared['continuation'],native_receipt_scope='Explicit fresh receiver import plus durable host receipt; not provider transaction atomicity.'))
                self.settle(ticket,phase);ticket,phase=None,None
            ticket=self.start('continuation')
            phase=self.call(ticket,session,self.inputs['request'],'continuation',port=port)
            for item in self.sessions:self.close_session(item)
            self.settle(ticket,phase);ticket,phase=None,None
            result=self.evaluate_artifact()
            result['task_success']=result['success']
            budget=self.ledger.snapshot()['budget']
            result['success']=bool(result['success'] and phase is None and all(p.get('completed') and not p.get('failure') for p in self.phases)
                and not budget['arms'][self.run_id]['stopped'] and not budget['study']['uncertain'])
            result['run_success']=result['success']
            if self.name=='C':
                save(self.folder/'recovery.json',dict(calls=reader.calls,trace=port.handler.trace,refused_callbacks=port.handler.refused_callbacks,
                    rows_verified=reader.rows_verified,text_bytes_examined=reader.text_bytes_examined,limits=vars(reader.limits),
                    system_admission=port.last_system_admission))
        except BaseException as error:
            if ticket is not None:
                self.settle(ticket,phase,error)
                ticket=None
            result=dict(success=False,run_success=False,task_success=None,error_type=type(error).__name__,error=str(error),failure_class='unclassified',checks=[])
        finally:
            cleanup=[]
            for session in self.sessions:
                cleanup.append(self.close_session(session))
            if result is not None:
                self.ledger.finish(self.run_id,result)
                save(self.folder/'result.json',dict(**result,cleanup=cleanup))
        return result
