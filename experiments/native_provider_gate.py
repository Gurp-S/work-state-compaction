"""Host-only bounded provider dispatch. Callback owns actual auth and accounting.

No LLM, URL, credential loading, retries or token-budget admission is built in.
Bytes are buffered; streaming latency is not qualified by this transport.
"""
import base64
from hashlib import sha256
from pathlib import Path
from threading import Lock
import time

from native_provider_frames import loads


def dispatch(gate,request,ordinal):
    """Every accepted transport request gets a reply, including owner failure."""
    try:return gate.handle(request),None
    except Exception as error:
        code=str(error) if type(error) is ValueError else 'provider_owner_exchange_failed'
        payload=base64.b64encode(b'{"error":{"code":"provider_owner_exchange_failed"}}').decode()
        return dict(ordinal=ordinal,status=502,content_type='application/json',body=payload),dict(type=type(error).__name__,code=code)


class ProviderGate:
    def __init__(self, *, model, max_calls, seconds, directory, exchange,require_compaction_v2=False):
        if (type(model) is not str or not model or type(max_calls) is not int
                or not 1<=max_calls<=64 or type(seconds) is not int or not 1<=seconds<=300
                or not callable(exchange)):
            raise ValueError('provider_gate_registration')
        self.model,self.max_calls,self.exchange=model,max_calls,exchange
        self.deadline=time.monotonic()+seconds
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=False)
        self.calls=0;self.trace=[];self.lock=Lock()
        if type(require_compaction_v2) is not bool:raise ValueError('provider_gate_compaction_policy_invalid')
        self.require_compaction_v2=require_compaction_v2

    def handle(self, frame):
        with self.lock:
            if time.monotonic()>=self.deadline: raise TimeoutError('provider_gate_deadline')
            if self.calls>=self.max_calls: raise ValueError('provider_gate_call_limit')
            self.calls+=1; ordinal=self.calls; begin=time.monotonic()
            if (type(frame) is not dict or set(frame)!={'method','path','body'}
                    or frame['method']!='POST' or frame['path']!='/v1/responses'
                    or type(frame['body']) is not str or len(frame['body'])>12*1024*1024):
                raise ValueError('provider_gate_route')
            raw=base64.b64decode(frame['body'],validate=True)
            if not 0<len(raw)<=8*1024*1024: raise ValueError('provider_gate_request_size')
            value=loads(raw.decode('utf-8'))
            if type(value) is not dict or value.get('model')!=self.model:
                raise ValueError('provider_gate_model')
            (self.directory/f'{ordinal:03}-request.json').write_bytes(raw)
            evidence=dict(ordinal=ordinal,request_bytes=len(raw),request_sha256=sha256(raw).hexdigest())
            self.trace.append(evidence)
            try:
                if self.require_compaction_v2:
                    from native_compaction_profile import admit_request
                    evidence['compaction_admission']=admit_request(value)
                status,content_type,body=self.exchange(raw)
                if (type(status) is not int or not 100<=status<=599
                        or content_type not in ('application/json','text/event-stream')
                        or type(body) is not bytes or len(body)>16*1024*1024):
                    raise ValueError('provider_gate_response')
                (self.directory/f'{ordinal:03}-response.bin').write_bytes(body)
                evidence.update(status=status,response_bytes=len(body),response_sha256=sha256(body).hexdigest())
                return dict(ordinal=ordinal,status=status,content_type=content_type,body=base64.b64encode(body).decode())
            except BaseException as error:
                evidence['error_type']=type(error).__name__;raise
            finally:
                evidence['owner_exchange_seconds']=time.monotonic()-begin
