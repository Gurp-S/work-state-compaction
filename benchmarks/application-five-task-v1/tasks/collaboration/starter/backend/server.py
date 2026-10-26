"""Local HTTP entry point; no third-party Python dependencies."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path

from .service import Service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    service = Service(Path(args.data))
    web = Path(__file__).resolve().parents[1] / 'web'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            try:
                if not self.path.startswith('/api/'):
                    target = (web / ('index.html' if self.path == '/' else self.path.lstrip('/'))).resolve()
                    if not target.is_relative_to(web.resolve()) or not target.is_file():
                        self.send_error(404)
                        return
                    raw = target.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css'}.get(target.suffix, 'application/octet-stream'))
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                size = int(self.headers.get('Content-Length', '0'))
                if size < 0 or size > 2_000_000:
                    status, body = 413, {'error': 'body_too_large'}
                else:
                    body = json.loads(self.rfile.read(size)) if size else {}
                    token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                    status, body = service.request(self.command, self.path, body, token)
            except (ValueError, TypeError, KeyError):
                status, body = 400, {'error': 'invalid_request'}
            except Exception:
                status, body = 500, {'error': 'internal_error'}
            raw = json.dumps(body, ensure_ascii=False).encode('utf8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST = do_PATCH = do_DELETE = handle_request

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(json.dumps({'ready': True, 'port': server.server_port}), flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
