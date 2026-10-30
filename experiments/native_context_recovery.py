"""Single context recovery tool in an ordinary native receiver; opt-in only."""
from copy import deepcopy
from pathlib import Path

from wsc.contracts import require,digest,encode
from native_task_recovery import TaskReceiver
from native_context_workspace import ContextWorkspace


class ContextHandler:
    def __init__(self,receiver):self.receiver=receiver;self.seen={};self.trace=[];self.refused_callbacks=0

    @property
    def reader(self):return self.receiver.query.reader

    def handle(self,event,*,thread_id,turn_id):
        receiver=self.receiver
        with receiver.context.lock:
            receiver._require_live()
            params=event.get('params',{});call=params.get('callId')
            require(thread_id==receiver.owner and event.get('method')=='item/tool/call'
                and type(event.get('id')) in (str,int) and params.get('threadId')==thread_id
                and params.get('turnId')==turn_id and params.get('tool')=='WSCContext'
                and params.get('namespace') is None and type(call) is str and bool(call),'context_tool_callback_binding_invalid')
            key=(thread_id,turn_id,call);fingerprint=digest(event)
            if key in self.seen:
                old,reply=self.seen[key];require(old==fingerprint,'context_tool_callback_identity_conflict')
                return deepcopy(reply)
            if len(self.seen)>=receiver.context.max_queries:
                value={'status':'error','code':'context_query_call_limit'};success=False
                self.refused_callbacks+=1
            else:
                outcome=receiver.query.call(params.get('arguments'));value=outcome.text;success=outcome.status=='success'
            reply={'id':event['id'],'result':{'contentItems':[{'type':'inputText','text':value if type(value) is str else encode(value)}],
                                             'success':success}}
            if len(self.seen)<receiver.context.max_queries:self.seen[key]=(fingerprint,deepcopy(reply))
            if len(self.trace)<receiver.context.max_queries:
                self.trace.append(dict(call_id=call,thread_id=thread_id,turn_id=turn_id,success=success))
            return reply


class ContextReceiver(TaskReceiver):
    def __init__(self,session,context,snapshot,*,workspace_binding=None,query=None):
        self.session,self.context,self.binding=session,context,workspace_binding
        self.owner=session.opened['thread']['id'];self.server=session.server
        self.workspace=session.registration['workspace'] if workspace_binding else str(Path(session.registration['workspace']).resolve())
        if not workspace_binding:require(self.workspace==context.core.store.workspace,'context_host_workspace_mismatch')
        self.query=query or context.query_tool(snapshot);self._require_live();self.handler=ContextHandler(self)

    def _require_live(self):
        require(self.session.server is self.server and self.server is not None and not self.session.closed
                and self.session.opened is not None,'task_source_session_not_live')
        require(self.session.opened['thread']['id']==self.owner,'task_source_owner_changed')
        if self.binding:self.binding.validate(self.session,self.context.core)
        else:
            require(str(Path(self.session.registration['workspace']).resolve())==self.workspace
                and str(Path(self.session.opened['cwd']).resolve())==self.workspace,'task_source_owner_changed')
        proc=getattr(self.server,'proc',None)
        require(proc is None or proc.poll() is None,'task_source_session_not_live')

    def advance(self,snapshot):
        with self.context.lock:
            self._require_live();self.query=self.context.query_tool(snapshot,
                infer_json_pointer_units=self.query.infer_json_pointer_units)


def open_context_receiver(open_session,context,snapshot,*,actor_root=None,infer_json_pointer_units=False):
    query=context.query_tool(snapshot,infer_json_pointer_units=infer_json_pointer_units);definition=query.definition()
    session=open_session(dynamic_tools=[definition],selector_runtime=None)
    try:
        binding=ContextWorkspace.prove(session,context.core,actor_root) if actor_root is not None else None
        return ContextReceiver(session,context,snapshot,workspace_binding=binding,query=query)
    except BaseException:
        session.close();raise
