"""Public HTTP acceptance runtime. Outputs are outside the submitted workspace."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler


def manifest(root):
    return {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()
            and not any(part in ('__pycache__', 'node_modules', '.git') for part in p.relative_to(root).parts)}


def save(path, body):
    with path.open('x', encoding='utf8') as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2)


class App:
    def __init__(self, workspace, output):
        self.workspace = workspace
        self.output = output
        self.data = output / 'data'
        self.data.mkdir()
        self.process = None
        self.events = []
        self.opener = build_opener(ProxyHandler({}))

    def start(self):
        log_index = len(list(self.output.glob('stderr-*.txt')))
        self.err = (self.output / f'stderr-{log_index}.txt').open('x', encoding='utf8')
        self.process = subprocess.Popen(
            [sys.executable, '-B', '-X', 'utf8', '-m', 'backend.server',
             '--data', str(self.data), '--port', '0'], cwd=self.workspace,
            stdout=subprocess.PIPE, stderr=self.err, text=True, encoding='utf8')
        self.stdout = []
        ready = queue.Queue()

        def drain():
            for line in self.process.stdout:
                self.stdout.append(line)
                try:
                    item = json.loads(line)
                    if isinstance(item, dict) and item.get('ready') is True:
                        ready.put(item)
                except ValueError:
                    pass
            ready.put(None)

        self.reader = threading.Thread(target=drain, daemon=True)
        self.reader.start()
        try:
            result = ready.get(timeout=15)
            assert result and type(result.get('port')) is int and 0 < result['port'] < 65536, 'ready_receipt_missing'
            self.base = 'http://127.0.0.1:' + str(result['port'])
            self.events.append({'event': 'started', 'pid': self.process.pid, 'port': result['port']})
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.reader.join(timeout=2)
        self.events.append({'event': 'stopped', 'pid': self.process.pid, 'exit_code': self.process.returncode,
                            'stdout': ''.join(self.stdout)})
        self.process.stdout.close()
        self.err.close()
        self.process = None

    def restart(self):
        self.stop()
        self.start()

    def call(self, method, path, payload=None, *, token='admin-a', status=200, raw=False):
        headers = {'Content-Type': 'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer ' + token
        request = Request(self.base + path, method=method, headers=headers,
                          data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf8'))
        try:
            response = self.opener.open(request, timeout=10)
        except HTTPError as error:
            response = error
        with response:
            code = response.code
            body = response.read(4_000_001)
        assert len(body) <= 4_000_000, 'response_too_large'
        decoded = body.decode('utf8', errors='strict')
        result = decoded if raw else json.loads(decoded)
        self.events.append({'event': 'http', 'method': method, 'path': path, 'token': token,
                            'request': payload, 'status': code, 'response': result})
        assert code == status, f'{method} {path}: expected {status}, got {code}: {decoded[:300]}'
        if code >= 400:
            assert isinstance(result, dict) and isinstance(result.get('error'), str), 'error_contract_invalid'
        return result

    def race(self, method, path, payloads):
        gate = threading.Barrier(len(payloads))

        def request(payload):
            gate.wait(timeout=5)
            # Read statuses without predeclaring which thread wins.
            request = Request(self.base + path, method=method,
                              headers={'Content-Type': 'application/json', 'Authorization': 'Bearer admin-a'},
                              data=json.dumps(payload).encode('utf8'))
            try:
                response = build_opener(ProxyHandler({})).open(request, timeout=10)
            except HTTPError as error:
                response = error
            with response:
                body = json.loads(response.read(4_000_000).decode('utf8', errors='strict'))
                return {'status': response.code, 'body': body, 'request': payload}

        with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
            results = list(executor.map(request, payloads))
        self.events.append({'event': 'race', 'method': method, 'path': path, 'results': results})
        return results
