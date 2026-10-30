"""Inside the closed network: loopback Responses front end and native child.

Only the dedicated Unix socket is reachable outside the actor. No provider
credentials, arbitrary URL forwarding, CONNECT, or task filesystem RPC exists.
"""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_provider_frames import receive, send

MAX_REQUEST = 8*1024*1024
MAX_RESPONSE = 16*1024*1024


def main(calls, child, *, compaction_v2=False):
    if not 1 <= calls <= 64 or not child or child[0] != '/opt/codex/bin/codex':
        raise ValueError('provider_actor_registration')
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'
        def log_message(self,*args): pass
        def do_POST(self):
            if self.path != '/v1/responses': self.send_error(404); return
            lengths=self.headers.get_all('Content-Length',[])
            if (len(lengths)!=1 or self.headers.get('Transfer-Encoding') is not None
                    or not lengths[0].isascii() or not lengths[0].isdecimal()):
                self.send_error(400); return
            size=int(lengths[0])
            if not 0 < size <= MAX_REQUEST: self.send_error(413); return
            self.connection.settimeout(30)
            body=self.rfile.read(size)
            if len(body)!=size: self.send_error(400); return
            if self.server.remaining<=0: self.send_error(429); return
            # Reserve before connecting; failed attempts do not restore capacity.
            self.server.remaining-=1
            try:
                with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
                    connection.settimeout(120); connection.connect('/run/wsc-provider/bridge.sock')
                    with connection.makefile('rwb',buffering=0) as wire:
                        send(wire,dict(method='POST',path='/v1/responses',body=base64.b64encode(body).decode()))
                        reply=receive(wire)
                status=reply['status']; data=base64.b64decode(reply['body'],validate=True)
                if type(status) is not int or not 100<=status<=599 or len(data)>MAX_RESPONSE:
                    raise ValueError('provider_bridge_response_invalid')
                content_type=reply.get('content_type','application/json')
                if content_type not in ('application/json','text/event-stream'): raise ValueError('provider_bridge_content_type')
                self.send_response(status); self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
            except (OSError,ValueError,EOFError,KeyError):
                self.send_error(502)
    server=HTTPServer(('127.0.0.1',0),Handler); server.remaining=calls
    with Path('/work/provider-transport.json').open('x',encoding='utf-8') as stream:
        json.dump(dict(base_url='http://127.0.0.1:'+str(server.server_port)+'/v1',max_calls=calls),stream)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    # Local transport only; the owner chooses and records the actual model.
    settings=[
        'model_provider="wsc_bridge"',
        'model_providers.wsc_bridge.name="WSC controlled transport"',
        'model_providers.wsc_bridge.base_url="http://127.0.0.1:'+str(server.server_port)+'/v1"',
        'model_providers.wsc_bridge.wire_api="responses"',
        'model_providers.wsc_bridge.requires_openai_auth=false',
        'model_providers.wsc_bridge.supports_websockets=false',
        'model_providers.wsc_bridge.request_max_retries=0',
        'model_providers.wsc_bridge.stream_max_retries=0']
    if compaction_v2:
        from native_compaction_profile import PROFILE,settings as profile_settings
        settings.extend(profile_settings(PROFILE))
    args=[child[0]]
    for setting in settings: args.extend(['-c',setting])
    args.extend(child[1:])
    try: return subprocess.call(args)
    finally: server.shutdown(); server.server_close()


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--calls',type=int,required=True)
    p.add_argument('--compaction-v2',action='store_true')
    p.add_argument('child',nargs=argparse.REMAINDER); a=p.parse_args()
    sys.exit(main(a.calls,a.child,compaction_v2=a.compaction_v2))
