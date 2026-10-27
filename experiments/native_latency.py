"""Host-only opt-in timing. No prompts, tool schemas or model inputs change."""
from contextlib import contextmanager
from threading import Lock,local
from time import perf_counter_ns,time_ns
import json


class LatencyRecorder:
    def __init__(self,path,*,clock=perf_counter_ns):
        self.path=path;self.clock=clock;self.lock=Lock();self.stack=local();self.sequence=0
        self.stream=path.open('x',encoding='utf-8')
        self._write(dict(type='header',format='wsc.host_latency/1',monotonic_ns=clock(),wall_ns=time_ns()))
    def _write(self,value):
        with self.lock:self.stream.write(json.dumps(value,separators=(',',':'))+'\n')
    @contextmanager
    def span(self,label,**metadata):
        with self.lock:identity=self.sequence;self.sequence+=1
        stack=getattr(self.stack,'ids',[]);self.stack.ids=stack
        parent=stack[-1] if stack else None;start=self.clock();stack.append(identity);status='ok';error=None
        try:yield
        except BaseException as exc:status='error';error=type(exc).__name__;raise
        finally:
            end=self.clock();stack.pop()
            self._write(dict(type='span',id=identity,parent=parent,label=label,start_ns=start,end_ns=end,
                status=status,error_type=error,metadata=metadata))
    def call(self,label,function,*args,**kwargs):
        with self.span(label):return function(*args,**kwargs)
    def event(self,component,value):
        params=value.get('params',{})
        self._write(dict(type='received_event',component=component,received_monotonic_ns=self.clock(),
            received_wall_ns=time_ns(),method=value.get('method'),server_emitted_ms=value.get('emittedAtMs'),
            request_id=value.get('id'),
            thread_id=params.get('threadId'),turn_id=params.get('turnId',params.get('turn',{}).get('id')),call_id=params.get('callId'),
            item_type=params.get('item',{}).get('type'),item_id=params.get('item',{}).get('id')))
    def close(self):self.stream.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class TimedRPC:
    def __init__(self,rpc,recorder,component,*,deny_inference=False):
        self.rpc,self.recorder,self.component,self.deny_inference=rpc,recorder,component,deny_inference
    def __getattr__(self,name):return getattr(self.rpc,name)
    def call(self,method,*args,**kwargs):
        if self.deny_inference and method in ('turn/start','thread/compact/start'):raise ValueError('zero_model_timing_inference_denied')
        with self.recorder.span('rpc.'+method,component=self.component):return self.rpc.call(method,*args,**kwargs)
    def send(self,message):
        if self.deny_inference and message.get('method') in ('turn/start','thread/compact/start'):raise ValueError('zero_model_timing_inference_denied')
        with self.recorder.span('rpc.send',component=self.component,response_id=message.get('id')):return self.rpc.send(message)
    def event(self,*args,**kwargs):
        value=self.rpc.event(*args,**kwargs);self.recorder.event(self.component,value);return value
    def close(self):
        with self.recorder.span('rpc.close',component=self.component):return self.rpc.close()


def attach(session,recorder,component,*,deny_inference=False):
    if hasattr(session,'_latency_recorder'):raise ValueError('session_latency_already_attached')
    session.server=TimedRPC(session.server,recorder,component,deny_inference=deny_inference)
    if hasattr(session,'execute_stage'):
        stage=session.execute_stage
        def timed_stage(*args,**kwargs):
            with recorder.span('stage.execute_and_account',component=component):return stage(*args,**kwargs)
        session.execute_stage=timed_stage
    session._latency_recorder=recorder
    return session


def summarize(path):
    records=[json.loads(line) for line in path.read_text().splitlines()]
    spans=[r for r in records if r['type']=='span'];results=[]
    for span in spans:
        intervals=sorted((max(span['start_ns'],x['start_ns']),min(span['end_ns'],x['end_ns'])) for x in spans if x['parent']==span['id'])
        covered=0;cursor=span['start_ns']
        for start,end in intervals:
            if end>max(start,cursor):covered+=end-max(start,cursor)
            cursor=max(cursor,end)
        results.append(dict(label=span['label'],id=span['id'],parent=span['parent'],
            inclusive_seconds=(span['end_ns']-span['start_ns'])/1e9,
            exclusive_seconds=(span['end_ns']-span['start_ns']-covered)/1e9,status=span['status']))
    return dict(spans=results,scope='Local monotonic wall intervals. Nested intervals are not additive; parallel branches may overlap. Server event timestamps use a separate clock domain.')
