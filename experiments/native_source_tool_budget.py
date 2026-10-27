"""Opt-in protocol adapter: exhausted access returns a bounded tool result."""
from wsc.contracts import WSCError,encode
from native_source_tool import SourceToolHandler


class BudgetResultSourceToolHandler(SourceToolHandler):
    def __init__(self,reader):
        super().__init__(reader)
        self.refused_callbacks=0

    def handle(self,event,*,thread_id,turn_id):
        try:
            return super().handle(event,thread_id=thread_id,turn_id=turn_id)
        except WSCError as error:
            # Parent has already checked thread/turn/tool/call bindings and
            # duplicate identities. Only a pre-I/O resource refusal is adapted.
            if str(error)!='source_tool_callback_budget_exhausted':raise
            self.refused_callbacks+=1
            return {'id':event['id'],'result':{'contentItems':[{'type':'inputText',
                'text':encode({'status':'error','code':str(error)})}],'success':False}}
