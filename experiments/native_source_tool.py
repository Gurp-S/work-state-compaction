"""Explicit optional dynamic-tool port for deterministic WSC source access."""
from copy import deepcopy
from wsc.contracts import require,WSCError,encode,digest

SOURCE_TOOL={'type':'function','name':'WSCSource',
    'description':'Bound WSC source observations. read returns original public text by source alias. find returns exact literal matches in source order without relevance ranking. Results include ranges, hashes, provenance and coverage; old text remains readable when not inline.',
    'inputSchema':{'type':'object','properties':{
        'operation':{'type':'string','enum':['read','find']},'source':{'type':['string','null']},
        'literal':{'type':['string','null']},'offset':{'type':'integer','minimum':0},
        'cursor':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':8192,
            'description':'read: character count, maximum 8192; find: matched source count, maximum 8.'}},
        'required':['operation'],'additionalProperties':False}}


def checked_description(offered,description):
    expected={'session_id':offered['session_id'],'cut':offered['frontier_boundary']['current_cut'],
        'source_digest':offered['frontier_boundary']['source_digest']}
    require(isinstance(description,dict) and encode(description.get('engine_binding'))==encode(expected),'source_tool_snapshot_binding_mismatch')
    return {k:deepcopy(v) for k,v in description.items() if k!='engine_binding'}


class SourceToolHandler:
    def __init__(self,reader):self.reader=reader;self.seen={};self.trace=[]
    def describe(self):return {'tool':SOURCE_TOOL['name'],**self.reader.describe(),'engine_binding':deepcopy(self.reader.snapshot_binding)}
    def execute_arguments(self,args):
        require(isinstance(args,dict) and set(args)<={'operation','source','literal','offset','cursor','limit'},'source_tool_arguments_invalid')
        operation=args.get('operation')
        if operation=='read':
            require(args.get('literal') is None and args.get('cursor',0)==0,'source_tool_arguments_invalid')
            return self.reader.read(args.get('source'),offset=args.get('offset',0),limit=args.get('limit',2048))
        if operation=='find':
            require(args.get('source') is None and args.get('offset',0)==0,'source_tool_arguments_invalid')
            return self.reader.find(args.get('literal'),cursor=args.get('cursor',0),limit=args.get('limit',8))
        raise WSCError('source_tool_operation_invalid')
    def handle(self,event,*,thread_id,turn_id):
        params=event.get('params',{});call=params.get('callId')
        require(event.get('method')=='item/tool/call' and type(event.get('id')) in (str,int)
            and params.get('threadId')==thread_id and params.get('turnId')==turn_id
            and params.get('tool')==SOURCE_TOOL['name'] and params.get('namespace') is None
            and type(call) is str and bool(call),'source_tool_callback_binding_invalid')
        fingerprint=digest({'id':event['id'],'params':params})
        if call in self.seen:
            previous,reply=self.seen[call];require(previous==fingerprint,'source_tool_call_identity_conflict')
            return deepcopy(reply)
        require(len(self.seen)<self.reader.limits.max_calls,'source_tool_callback_budget_exhausted')
        args=params.get('arguments')
        try:
            value=self.execute_arguments(args)
            ok=True
        except WSCError as error:value={'status':'error','code':str(error)};ok=False
        reply={'id':event['id'],'result':{'contentItems':[{'type':'inputText','text':encode(value)}],'success':ok}}
        self.seen[call]=(fingerprint,deepcopy(reply))
        self.trace.append({'thread_id':thread_id,'turn_id':turn_id,'call_id':call,'arguments':deepcopy(args),'output':value})
        return reply
