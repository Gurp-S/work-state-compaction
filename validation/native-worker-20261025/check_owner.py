"""Real Windows parent/child lifecycle check, not a paid model experiment."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
from native_owned_process import ProcessOwner
from native_evidence import save, file_hash

OUT = Path(__file__).parent
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel.OpenProcess.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel.CloseHandle.argtypes = [wintypes.HANDLE]

fixture = '''import subprocess,sys
sys.stdin.readline()
child = subprocess.Popen([sys.executable,'-B','-c','import time; time.sleep(120)'],
 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(child.pid,flush=True)
sys.stdin.read()
'''


def run(owned):
    parent = subprocess.Popen([sys.executable, '-B', '-c', fixture], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    owner = ProcessOwner() if owned else None
    child_handle = None
    try:
        if owner:
            owner.attach(parent)
        parent.stdin.write('spawn\n')
        parent.stdin.flush()
        child_pid = int(parent.stdout.readline())
        child_handle = kernel.OpenProcess(0x100001, False, child_pid)  # SYNCHRONIZE | TERMINATE
        assert child_handle, 'fixture_child_handle_missing'
        members = owner.members() if owner else None
        if owner:
            assert parent.pid in members and child_pid in members
        parent.stdin.close()
        parent.wait(timeout=5)
        before = kernel.WaitForSingleObject(child_handle, 0) == 258
        assert before, 'fixture_did_not_reproduce_orphan_pattern'
        receipt = owner.close() if owner else None
        if owner:
            assert receipt['empty_confirmed'] and kernel.WaitForSingleObject(child_handle, 5000) == 0
        else:
            assert kernel.TerminateProcess(child_handle, 137)
            assert kernel.WaitForSingleObject(child_handle, 5000) == 0
        return dict(owned=owned, parent_pid=parent.pid, child_pid=child_pid,
                    child_alive_after_parent_exit=before, membership=members, cleanup=receipt,
                    fixture_child_cleanup_confirmed=True)
    finally:
        if owner:
            owner.close()
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if child_handle:
            if kernel.WaitForSingleObject(child_handle, 0) == 258:
                kernel.TerminateProcess(child_handle, 137)
                kernel.WaitForSingleObject(child_handle, 5000)
            kernel.CloseHandle(child_handle)
        parent.stdout.close()
        parent.stderr.close()


before, after = run(False), run(True)
save(OUT / 'owner-check.json', dict(baseline=before, candidate=after, model_calls=0,
    source_sha256=file_hash(ROOT / 'experiments/native_owned_process.py'),
    scope='Real synthetic child: baseline is parent-only supervision pattern, not a replay of a past model tool leak'))
print(json.dumps(dict(parent_only_child_survived=True, private_job_child_terminated=True, model_calls=0)))
