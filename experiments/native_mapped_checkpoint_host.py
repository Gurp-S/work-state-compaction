"""Opt-in durable host journal for a mapped native receiver.

An intent is written before injection. Unknown outcomes are observed from the
append-only native log, never replayed. This does not claim a cross-store atomic
transaction or remove the caller's requirement to serialize receiver mutation.
"""
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock

from wsc.contracts import HostReceipt,digest,encode,require
from wsc.evidence import write_once,link_like
from wsc.publication import operation,check_binding,check_evidence
from native_evidence import state,import_evidence
from native_host_controls import bootstrap_items
from native_rollout_snapshot import parse_rollout


class MappedCheckpointHost:
    def __init__(self,port,directory,*,bootstrap=None,after_import=None,max_history_bytes=32*1024*1024):
        self.port=port;self.context=port.context;self.directory=Path(directory).absolute()
        for p in (self.directory,*self.directory.parents):require(not link_like(p),'checkpoint_journal_link')
        self.directory.mkdir(parents=True,exist_ok=True)
        self.after_import=after_import;self.max_history_bytes=max_history_bytes;self.lock=RLock()
        self.bootstrap=bootstrap
        require(type(max_history_bytes) is int and max_history_bytes>0,'checkpoint_history_limit_invalid')
        port._require_live()
        self.history_path=str(port.session.rollout_path())
        self.guest_history=port.session.opened['thread']['path']

    def _path(self,key,name):
        require(type(key) is str and len(key)==32 and all(c in '0123456789abcdef' for c in key),'checkpoint_operation_invalid')
        path=self.directory/(key+'-'+name+'.json')
        for p in (path,*path.parents):require(not link_like(p),'checkpoint_journal_link')
        return path

    def _save(self,key,name,value):
        write_once(self._path(key,name),encode(dict(value=value,seal=digest(value))).encode())

    def _load(self,key,name):
        p=self._path(key,name)
        if not p.exists():return None
        with p.open('rb') as f:raw=f.read(4*1024*1024+1)
        require(len(raw)<=4*1024*1024,'checkpoint_journal_limit')
        value=json.loads(raw.decode('utf-8'))
        require(value.get('seal')==digest(value.get('value')),'checkpoint_journal_corrupt')
        return value['value']

    def _identity(self,*,live=True):
        if live:self.port._require_live()
        require(self.port.session.opened['thread']['path']==self.guest_history,'checkpoint_history_binding_changed')
        return dict(receiver=self.port.owner,session_id=self.context.core.store.session_id,
            workspace=self.context.core.store.workspace,guest_workspace=self.port.workspace,
            history=str(self.port.session.rollout_path()) if live else self.history_path)

    def _history(self):
        path=self.port.session.rollout_path()
        with path.open('rb') as stream:raw=stream.read(self.max_history_bytes+1)
        require(len(raw)<=self.max_history_bytes,'checkpoint_history_limit')
        snapshot=parse_rollout(raw)
        require(snapshot.metadata['parse_complete'],'checkpoint_history_incomplete')
        return raw,snapshot

    def _proof(self,intent):
        require(intent['identity']==self._identity(),'checkpoint_receiver_binding_changed')
        raw,snapshot=self._history();length=intent['before_length']
        require(len(raw)>=length and sha256(raw[:length]).hexdigest()==intent['before_sha256'],
            'checkpoint_history_prefix_changed')
        actual=state(snapshot.rows);before=intent['bootstrap'];boundary=len(before)
        require(bootstrap_items(actual[:boundary],self.port.workspace)==bootstrap_items(before,self.port.workspace),
            'checkpoint_bootstrap_changed')
        proof=import_evidence(actual[boundary:boundary+len(intent['items'])],intent['items'])
        if not proof['matched'] or proof['start_ordinal']!=0:return None
        return dict(import_proof=proof,native_history_sha256=sha256(raw).hexdigest(),
            later_items_preserved=max(0,len(actual)-boundary-len(intent['items'])))

    def _receipt(self,key,intent,proof):
        receipt=HostReceipt(**intent['receipt'])
        self._save(key,'receipt',dict(identity=intent['identity'],receipt=asdict(receipt),proof=proof))
        return receipt

    def install(self,package):
        with self.lock,self.context.lock:
            key=package['operation_id'];existing=self._load(key,'receipt')
            if existing:
                require(existing['identity']==self._identity(live=False) and existing['receipt']['package_digest']==package['package_digest'],
                    'checkpoint_receipt_binding_changed')
                return HostReceipt(**existing['receipt'])
            # An intent may already have escaped to native. Even a currently
            # empty receiver is not permission to replay an unknown operation.
            require(self._load(key,'intent') is None,'checkpoint_outcome_requires_lookup')
            with self.context.core.store.transaction() as db:
                current=operation(db,key)
                require(current['package']==package and current['state']=='installing','checkpoint_operation_binding_changed')
                check_binding(db,self.context.core,current)
                check_evidence(self.context.core,package);self.context.validate_package(package)
                reader=self.port.handler.reader.snapshot_binding
                require(reader['source_digest']==package['binding']['source_digest'] and reader['cut']==package['binding']['cut'],
                    'checkpoint_recovery_prefix_changed')
                raw,snapshot=self._history()
                require(not any(r['type']=='token_usage_record' for r in snapshot.rows),'checkpoint_receiver_not_fresh')
                before=state(snapshot.rows)
                require(type(self.bootstrap) is list and len(before)==len(self.bootstrap)
                        and bootstrap_items(before,self.port.workspace)==bootstrap_items(self.bootstrap,self.port.workspace),
                        'checkpoint_receiver_not_fresh')
                # Factory-owned fresh receiver bootstrap only. The exact
                # bootstrap is retained, and no native history is overwritten.
                receipt=HostReceipt(operation_id=key,package_digest=package['package_digest'],
                    session_id=package['binding']['session_id'],workspace=package['binding']['workspace'],
                    generation=package['next_generation'],control_epoch=package['binding']['control_epoch'],
                    installed_through=package['through'],receiver=self.port.owner,evidence_accessible=True)
                intent=dict(identity=self._identity(),before_length=len(raw),before_sha256=sha256(raw).hexdigest(),
                    bootstrap=before,items=package['items'],receipt=asdict(receipt))
                self._save(key,'intent',intent)
                self.port.server.call('thread/inject_items',dict(threadId=self.port.owner,items=package['items']),timeout=15)
                proof=self._proof(intent)
                require(proof is not None,'checkpoint_native_install_unobserved')
                if self.after_import:self.after_import()
                return self._receipt(key,intent,proof)

    def lookup(self,key):
        with self.lock,self.context.lock:
            old=self._load(key,'receipt')
            if old:
                require(old['identity']==self._identity(live=False),'checkpoint_receipt_binding_changed')
                return HostReceipt(**old['receipt'])
            intent=self._load(key,'intent')
            if intent is None:return None
            # A historical commit is observed without re-authorizing a new
            # export. Later source revocation still applies to future queries.
            proof=self._proof(intent)
            return self._receipt(key,intent,proof) if proof is not None else None
