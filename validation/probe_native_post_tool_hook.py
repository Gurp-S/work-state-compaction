"""Zero-LLM native transport probe using an explicit local scripted Responses fixture.

Not a model-quality test or a native compression comparator. No production settings changed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--executable', required=True)
    parser.add_argument('--code-mode', action='store_true')
    parser.add_argument('--failed-command', action='store_true')
    args = parser.parse_args()
    folder = Path(args.output).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    home, work = folder / 'private-home', folder / 'workspace'
    home.mkdir(); work.mkdir()
    (home / 'config.toml').write_text('[features]\nhooks = true\n', encoding='utf-8')
    hook = folder / 'fixture_hook.py'
    hook.write_text('''import json,sys,os
from pathlib import Path
p=Path(sys.argv[1])
raw=sys.stdin.buffer.read()
with p.open('xb') as f:
 f.write(raw);f.flush();os.fsync(f.fileno())
assert p.read_bytes()==raw
json.loads(raw)
print(json.dumps({} if len(sys.argv)>2 else {"continue":False,"stopReason":"WSC_HOOK_REPLACEMENT_FIXTURE"}))
''', encoding='utf-8')
    hook_command = f'"{sys.executable}" "{hook}" "{folder / "hook-input.json"}"'
    session_command = f'"{sys.executable}" "{hook}" "{folder / "session-input.json"}" session'
    (home / 'hooks.json').write_text(json.dumps({'hooks': {'SessionStart': [
        {'hooks': [{'type':'command', 'command':session_command, 'commandWindows':'& '+session_command, 'timeout':10}]}
    ], 'PostToolUse': [
        {'hooks': [{'type': 'command', 'command': hook_command, 'commandWindows':'& '+hook_command, 'timeout': 10}]}
    ]}}, indent=2), encoding='utf-8')
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers['Content-Length']))
            request = json.loads(raw)
            requests.append(request)
            number = len(requests)
            (folder / f'request-{number}.json').write_bytes(raw)
            if number > 2:
                self.send_error(429, 'fixture_request_limit'); return
            if number == 1:
                shell = "Write-Output 'WSC_RAW_RESULT_FIXTURE'" + ('; exit 1' if args.failed_command else '')
                item = {'type': 'custom_tool_call', 'id': 'ctc_fixture', 'call_id': 'call_fixture',
                        'name': 'exec', 'input': 'const r = await tools.exec_command('+json.dumps({'cmd':shell,'max_output_tokens':1000})+'); text({promise_resolved:true,result:r});'}
                if not args.code_mode:
                    item = {'type':'function_call', 'id':'fc_fixture', 'call_id':'call_fixture',
                            'name':'exec_command', 'arguments':json.dumps({'cmd':shell, 'max_output_tokens':1000})}
            else:
                item = {'type': 'message', 'id': 'msg_fixture', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': 'FIXTURE_COMPLETE', 'annotations': []}]}
            response = {'id': f'resp_fixture_{number}', 'object': 'response', 'status': 'completed',
                        'model': 'fixture-no-llm', 'output': [item],
                        'usage': {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}}
            events = [
                {'type':'response.created', 'response':{**response, 'status':'in_progress', 'output':[]}},
                {'type':'response.output_item.added', 'output_index':0, 'item':item},
                {'type':'response.output_item.done', 'output_index':0, 'item':item},
                {'type':'response.completed', 'response':response},
            ]
            body = ''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = dict(os.environ, CODEX_HOME=str(home))
    settings = [
        'model_provider="wsc_local_fixture"', 'model="fixture-no-llm"',
        'model_providers.wsc_local_fixture.name="WSC local contract fixture"',
        f'model_providers.wsc_local_fixture.base_url="http://127.0.0.1:{server.server_port}/v1"',
        'model_providers.wsc_local_fixture.wire_api="responses"',
        'model_providers.wsc_local_fixture.requires_openai_auth=false',
        'model_providers.wsc_local_fixture.request_max_retries=0',
        'model_providers.wsc_local_fixture.stream_max_retries=0',
        'model_providers.wsc_local_fixture.supports_websockets=false',
        'features.plugins=false', 'features.multi_agent=false',
        'features.code_mode=' + str(args.code_mode).lower(),
    ]
    command = [args.executable, '--dangerously-bypass-hook-trust']
    for setting in settings: command += ['-c', setting]
    command += ['--ask-for-approval', 'never', 'exec', '--skip-git-repo-check', '--json', '--sandbox', 'danger-full-access',
                'Local scripted transport qualification.']
    (folder / 'registration.json').write_text(json.dumps(dict(
        kind='scripted_local_protocol_fixture_not_model_experiment', model_calls=0,
        local_provider_only=True, global_config_changed=False, command=command), indent=2), encoding='utf-8')
    try:
        run = subprocess.run(command, cwd=work, env=env, capture_output=True, timeout=45,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (folder / 'stdout.jsonl').write_bytes(run.stdout)
        (folder / 'stderr.txt').write_bytes(run.stderr)
        result = dict(exit_code=run.returncode, requests=len(requests),
                      hook_ran=(folder / 'hook-input.json').exists(), model_calls=0,
                      session_hook_ran=(folder / 'session-input.json').exists(),
                      native_next_request_captured=len(requests)==2)
    except subprocess.TimeoutExpired as exc:
        (folder / 'stdout.jsonl').write_bytes(exc.stdout or b'')
        (folder / 'stderr.txt').write_bytes(exc.stderr or b'')
        result = dict(timeout=True, requests=len(requests), model_calls=0,
                      hook_ran=(folder / 'hook-input.json').exists())
    finally:
        server.shutdown(); server.server_close()
    (folder / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
