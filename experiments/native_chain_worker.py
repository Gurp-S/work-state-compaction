"""Long-lived bounded socket bridge, with prompt owner-EOF shutdown."""
import argparse
import os
from pathlib import Path
import select
import socket
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_provider_frames import receive,send


def main(root,calls,seconds):
    if not 1<=calls<=64 or not 1<=seconds<=3600:raise ValueError('chain_worker_limits')
    if root.parent!=Path('/tmp') or not root.name.startswith('wsc-provider-'):raise ValueError('chain_worker_root')
    root.mkdir(mode=0o755,exist_ok=False);deadline=time.monotonic()+seconds
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as listener:
        listener.bind(str(root/'bridge.sock'));os.chmod(root/'bridge.sock',0o666);listener.listen(1)
        send(sys.stdout.buffer,dict(kind='ready',pid=os.getpid(),lifetime_seconds=seconds))
        for ordinal in range(1,calls+1):
            while True:
                left=deadline-time.monotonic()
                if left<=0:raise TimeoutError('chain_worker_deadline')
                if select.select([sys.stdin.buffer],[],[],0)[0]:
                    if not os.read(sys.stdin.fileno(),1):return
                    raise ValueError('chain_worker_unsolicited_owner_data')
                listener.settimeout(min(.2,left))
                try:connection,_=listener.accept();break
                except socket.timeout:pass
            with connection:
                connection.settimeout(max(.1,deadline-time.monotonic()))
                with connection.makefile('rwb',buffering=0) as wire:
                    send(sys.stdout.buffer,dict(kind='request',ordinal=ordinal,request=receive(wire)))
                    reply=receive(sys.stdin.buffer)
                    if reply.get('ordinal')!=ordinal:raise ValueError('chain_worker_reply_order')
                    send(wire,reply)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--calls',type=int,required=True);parser.add_argument('--seconds',type=int,required=True)
    args=parser.parse_args();main(args.root,args.calls,args.seconds)
