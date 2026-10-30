"""Local WebSocket sink for unchanged built-in OpenAI transport; no upstream."""
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Lock,Thread

sys.path.insert(0,str(Path(__file__).parent/'fixture-vendor'))
from websockets.sync.server import serve
from websockets.exceptions import ConnectionClosed


def main(child):
    if not child or child[0]!='/opt/codex/bin/codex':raise ValueError('fixture_child_invalid')
    root=Path('/work/protocol-fixture');root.mkdir();lock=Lock();count=0;generated=0
    def handshake(connection,request):
        if request.path!='/v1/responses':return connection.respond(404,'local fixture route unavailable')
    def handler(connection):
        nonlocal count,generated
        try:
            while True:
                raw=connection.recv(timeout=40)
                if type(raw) is not str:raise ValueError('fixture_websocket_text_required')
                with lock:count+=1;number=count
                if number>8:connection.close(1008,'local frame limit');return
                request=json.loads(raw);phase=Path('/work/probe-phase.txt').read_text().strip()
                prewarm=request.get('generate') is False
                if not prewarm:
                    with lock:generated+=1;generation=generated
                    if generation>4:connection.close(1008,'local generation limit');return
                (root/f'{number:03}-request.json').write_bytes(raw.encode())
                (root/f'{number:03}-metadata.json').write_text(json.dumps(dict(path=connection.request.path,
                    phase=phase,bytes=len(raw.encode()),transport='websocket',prewarm=prewarm)))
                if phase=='compaction_route' and not prewarm:
                    event=dict(type='error',status=501,error=dict(type='server_error',code='local_route_probe_no_compaction_result',
                        message='Local fixture has no compaction result'))
                    connection.send(json.dumps(event));connection.close();return
                item=dict(type='message',id='msg_ws_probe',role='assistant',status='completed',
                    content=[dict(type='output_text',text='LOCAL_WEBSOCKET_FIXTURE',annotations=[])])
                if not prewarm and generation==1:item=dict(type='custom_tool_call',id='ctc_ws_probe',call_id='local_call',name='exec',
                    input='text(await tools.WSCContext({operation:"describe",reference:"source:s45"}));')
                response=dict(id='resp_ws_'+str(number),object='response',status='completed',model='scripted-no-llm',
                    output=[item],usage=dict(input_tokens=0,output_tokens=0,total_tokens=0))
                events=[dict(type='response.created',response={**response,'status':'in_progress','output':[]}),
                    dict(type='response.output_item.added',output_index=0,item=item),
                    dict(type='response.output_item.done',output_index=0,item=item),
                    dict(type='response.completed',response=response)]
                if prewarm:
                    response['output']=[]
                    events=[dict(type='response.created',response={**response,'status':'in_progress'}),
                            dict(type='response.completed',response=response)]
                (root/f'{number:03}-response.bin').write_bytes(json.dumps(events).encode())
                for event in events:connection.send(json.dumps(event))
        except ConnectionClosed:pass
    with serve(handler,'127.0.0.1',0,process_request=handshake,compression=None,max_size=8*1024*1024,
               max_queue=4,close_timeout=2) as server:
        Thread(target=server.serve_forever,daemon=True).start()
        env=dict(os.environ,OPENAI_API_KEY='local_protocol_fixture_no_privilege')
        args=[child[0],'-c','model_provider="openai"','-c',
            'openai_base_url="http://127.0.0.1:'+str(server.socket.getsockname()[1])+'/v1"',*child[1:]]
        try:return subprocess.call(args,env=env)
        finally:server.shutdown()


if __name__=='__main__':sys.exit(main(sys.argv[1:]))
