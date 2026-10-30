"""Phase-bound provider admission for one persistent native process."""
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from native_provider_frames import loads
from native_provider_gate import ProviderGate


class ChainGateway:
    def __init__(self,*,model,max_calls,directory,exchange):
        if type(max_calls) is not int or not 1<=max_calls<=64:raise ValueError('chain_gateway_call_limit_invalid')
        self.model,self.max_calls,self.exchange=model,max_calls,exchange
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=False)
        self.lock=RLock();self.active=None;self.serial=0;self.calls=0;self.inflight=0;self.poisoned=False;self.trace=[]

    @contextmanager
    def stage(self,*,compact,remaining):
        if type(compact) is not bool or not callable(remaining):raise ValueError('chain_gateway_phase_invalid')
        with self.lock:
            if self.active is not None or self.poisoned or self.inflight:raise ValueError('chain_gateway_phase_not_idle')
            remaining();self.serial+=1
            scope=dict(id=self.serial,compact=compact,remaining=remaining,calls=0)
            self.active=scope
        try:yield
        finally:
            with self.lock:
                if self.inflight:self.poisoned=True
                self.active=None

    def handle(self,frame):
        with self.lock:
            if self.poisoned or self.active is None:raise ValueError('chain_gateway_no_active_phase')
            scope=self.active;limits=scope['remaining']()
            if self.calls>=self.max_calls or scope['calls']>=limits['max_responses']:
                raise ValueError('chain_gateway_response_allowance_exhausted')
            self.calls+=1;scope['calls']+=1;self.inflight+=1;ordinal=self.calls
            entry=dict(ordinal=ordinal,phase=scope['id'],compact=scope['compact']);self.trace.append(entry)
        def exchange(raw):
            value=loads(raw.decode('utf-8'))
            if not scope['compact']:
                inputs=value.get('input',[])
                metadata=value.get('client_metadata',{})
                if type(metadata) is not dict:raise ValueError('chain_gateway_metadata_invalid')
                turn=loads(metadata.get('x-codex-turn-metadata','{}'))
                if type(turn) is not dict:raise ValueError('chain_gateway_metadata_invalid')
                if turn.get('request_kind')=='compaction' or any(type(i) is dict and i.get('type')=='compaction_trigger'
                                                                for i in (inputs if type(inputs) is list else [])):
                    raise ValueError('chain_gateway_unregistered_auto_compaction')
            with self.lock:
                if self.active is not scope or self.poisoned:raise ValueError('chain_gateway_phase_ended')
                scope['remaining']()
            return self.exchange(raw)
        gate=None
        try:
            gate=ProviderGate(model=self.model,max_calls=1,seconds=min(300,limits['max_seconds']),
                directory=self.directory/('request-'+str(ordinal)),exchange=exchange,
                require_compaction_v2=scope['compact'])
            reply=gate.handle(frame);reply['ordinal']=ordinal;return reply
        finally:
            with self.lock:
                entry['gate_trace']=gate.trace if gate else []
                self.inflight-=1


class PhaseBoundSession:
    """Delegate session state; refresh the durable budget callback every stage."""
    def __init__(self,session,gateway):
        object.__setattr__(self,'session',session);object.__setattr__(self,'gateway',gateway)
        object.__setattr__(self,'remaining',None)
    def __getattr__(self,name):return getattr(self.session,name)
    def __setattr__(self,name,value):
        if name in {'session','gateway','remaining'}:object.__setattr__(self,name,value)
        else:setattr(self.session,name,value)
    def bind_phase_budget(self,remaining):
        if not callable(remaining):raise ValueError('chain_gateway_budget_callback_missing')
        self.remaining=remaining
    def execute_stage(self,*args,compact=False,**kwargs):
        remaining=self.remaining;self.remaining=None
        if remaining is None:raise ValueError('chain_gateway_budget_unbound')
        with self.gateway.stage(compact=compact,remaining=remaining):
            return self.session.execute_stage(*args,compact=compact,**kwargs)
    def close(self):return self.session.close()
