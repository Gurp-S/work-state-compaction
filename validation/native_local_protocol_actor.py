"""Local scripted HTTP sink inside the actor. No forwarding or auth support."""
from http.server import BaseHTTPRequestHandler,HTTPServer
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading


def main(child,*,builtin=False,remote_v2=False):
    if not child or child[0]!='/opt/codex/bin/codex':raise ValueError('fixture_child_invalid')
    root=Path('/work/protocol-fixture');root.mkdir()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            number=self.server.calls+1;self.server.calls=number
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=8*1024*1024 or number>4:self.send_error(413);return
            body=self.rfile.read(size);phase=Path('/work/probe-phase.txt').read_text().strip()
            (root/f'{number:03}-request.json').write_bytes(body)
            (root/f'{number:03}-metadata.json').write_text(json.dumps(dict(path=self.path,phase=phase,bytes=len(body))))
            if phase=='resumed_tools' and self.path=='/v1/responses':
                item=dict(type='message',id='msg_local_probe',role='assistant',status='completed',
                    content=[dict(type='output_text',text='LOCAL_PROTOCOL_FIXTURE',annotations=[])])
                if number==1:item=dict(type='custom_tool_call',id='ctc_local_probe',call_id='local_call',name='exec',
                    input='text(await tools.WSCContext({operation:"describe",reference:"source:s45"}));')
                response=dict(id='resp_local_protocol',object='response',status='completed',model='scripted-no-llm',
                    output=[item],usage=dict(input_tokens=0,output_tokens=0,total_tokens=0))
                events=[dict(type='response.created',response={**response,'status':'in_progress','output':[]}),
                    dict(type='response.output_item.added',output_index=0,item=item),
                    dict(type='response.output_item.done',output_index=0,item=item),
                    dict(type='response.completed',response=response)]
                data=''.join('event: '+v['type']+'\ndata: '+json.dumps(v)+'\n\n' for v in events).encode()
                code,kind=200,'text/event-stream'
            else:
                # Observe the real route; never fabricate opaque compaction.
                code,kind,data=501,'application/json',b'{"error":{"code":"local_route_probe_no_compaction_result"}}'
            (root/f'{number:03}-response.bin').write_bytes(data)
            self.send_response(code);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    server=HTTPServer(('127.0.0.1',0),Handler);server.calls=0
    threading.Thread(target=server.serve_forever,daemon=True).start()
    settings=['model_provider="wsc_fixture"','model_providers.wsc_fixture.name="Local protocol fixture"',
        'model_providers.wsc_fixture.base_url="http://127.0.0.1:'+str(server.server_port)+'/v1"',
        'model_providers.wsc_fixture.wire_api="responses"','model_providers.wsc_fixture.requires_openai_auth=false',
        'model_providers.wsc_fixture.supports_websockets=false','model_providers.wsc_fixture.request_max_retries=0',
        'model_providers.wsc_fixture.stream_max_retries=0']
    if remote_v2:settings.append('model_providers.wsc_fixture.capabilities.remote_compaction="v2"')
    if builtin:
        settings=['model_provider="openai"',
            'openai_base_url="http://127.0.0.1:'+str(server.server_port)+'/v1"']
        # No real credential is loaded or persisted. This value is useful only
        # against the local sink in the isolated network namespace.
        os.environ['OPENAI_API_KEY']='local_protocol_fixture_no_privilege'
    args=[child[0]]
    for value in settings:args.extend(['-c',value])
    args.extend(child[1:])
    try:return subprocess.call(args)
    finally:server.shutdown();server.server_close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--builtin-openai',action='store_true')
    p.add_argument('--remote-v2',action='store_true')
    p.add_argument('child',nargs=argparse.REMAINDER);a=p.parse_args()
    if a.builtin_openai and a.remote_v2:p.error('fixture provider modes conflict')
    sys.exit(main(a.child,builtin=a.builtin_openai,remote_v2=a.remote_v2))
