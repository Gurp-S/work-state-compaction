"""Outside the actor: Unix socket <-> owner stdio. No network/provider code."""
import argparse
import os
from pathlib import Path
import socket
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from native_provider_frames import receive, send


def main(root, calls, seconds):
    if not 1 <= calls <= 64 or not 1 <= seconds <= 300: raise ValueError('provider_bridge_limits')
    if root.parent != Path('/tmp') or not root.name.startswith('wsc-provider-'):
        raise ValueError('provider_bridge_socket_root')
    root.mkdir(mode=0o755, exist_ok=False)
    deadline = time.monotonic()+seconds
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(root/'bridge.sock')); os.chmod(root/'bridge.sock', 0o666); listener.listen(1)
        send(sys.stdout.buffer, dict(kind='ready'))
        for ordinal in range(1, calls+1):
            remaining = deadline-time.monotonic()
            if remaining <= 0: raise TimeoutError('provider_bridge_deadline')
            listener.settimeout(remaining)
            with listener.accept()[0] as connection:
                connection.settimeout(max(.1, deadline-time.monotonic()))
                with connection.makefile('rwb', buffering=0) as wire:
                    request = receive(wire)
                    send(sys.stdout.buffer, dict(kind='request', ordinal=ordinal, request=request))
                    reply = receive(sys.stdin.buffer)
                    if reply.get('ordinal') != ordinal: raise ValueError('provider_bridge_reply_order')
                    send(wire, reply)


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('--root',type=Path,required=True)
    p.add_argument('--calls',type=int,required=True); p.add_argument('--seconds',type=int,required=True)
    a=p.parse_args(); main(a.root,a.calls,a.seconds)
