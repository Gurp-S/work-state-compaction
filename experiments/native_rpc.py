"""Small stdio transport for experiments; uses native authentication unchanged."""
import json
from pathlib import Path
import queue
import subprocess
import threading
import time


class NativeRPC:
    def __init__(self, executable, *, cwd, stderr_path, settings=()):
        self.stderr = Path(stderr_path).open("x", encoding="utf-8")
        command = [str(executable), "app-server", "--stdio"]
        for setting in settings:
            command.extend(["-c", setting])
        self.proc = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self.stderr, text=True, encoding="utf-8", bufsize=1,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.queue, self.pending, self.counter = queue.Queue(), [], 0
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self.queue.put(json.loads(line))
        except Exception as exc:
            self.queue.put({"transport_error": type(exc).__name__})
        finally:
            self.queue.put({"eof": True})

    def send(self, value):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", **value}, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params, timeout=20):
        self.counter += 1
        key = self.counter
        self.send({"id": key, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                item = self.queue.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise TimeoutError(method) from exc
            if item.get("eof"):
                raise RuntimeError("app_server_eof")
            if item.get("id") == key and "method" not in item:
                if "error" in item:
                    raise RuntimeError(method + ": " + json.dumps(item["error"], ensure_ascii=False))
                return item["result"]
            self.pending.append(item)
        raise TimeoutError(method)

    def event(self, timeout=5):
        item = self.pending.pop(0) if self.pending else self.queue.get(timeout=timeout)
        if item.get("eof"):
            raise RuntimeError("app_server_eof")
        return item

    def close(self):
        if self.proc.stdin:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        self.proc.stdout.close()
        self.stderr.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
