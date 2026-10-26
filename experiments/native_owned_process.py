"""Opt-in Windows process ownership for an experimental native server.

Attach before initialize/turn/command dispatch. One private OS Job per worker;
closing it kills remaining descendants, without enumerating or killing external
processes by executable name. Earlier NativeRPC callers remain unchanged.
"""
import ctypes
from ctypes import wintypes
import os
import time


class _BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
        ('flags', wintypes.DWORD), ('min_working_set', ctypes.c_size_t), ('max_working_set', ctypes.c_size_t),
        ('active_process_limit', wintypes.DWORD), ('affinity', ctypes.c_size_t),
        ('priority', wintypes.DWORD), ('scheduling_class', wintypes.DWORD)]


class _IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops',
                                                       'read_bytes', 'write_bytes', 'other_bytes')]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', _BasicLimits), ('io', _IOCounters), ('process_memory', ctypes.c_size_t),
               ('job_memory', ctypes.c_size_t), ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]


def _kernel():
    if os.name != 'nt':
        raise RuntimeError('owned_native_process_requires_windows')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
    kernel.QueryInformationJobObject.restype = wintypes.BOOL
    kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel.TerminateJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _checked(ok, operation):
    if not ok:
        raise OSError(ctypes.get_last_error(), operation)


class ProcessOwner:
    def __init__(self):
        self.kernel = _kernel()
        self.handle = self.kernel.CreateJobObjectW(None, None)
        _checked(self.handle, 'CreateJobObjectW')
        self.attached = []
        self.receipt = None
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; breakaway disabled.
        try:
            _checked(self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)),
                     'SetInformationJobObject')
        except BaseException:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise

    def attach(self, process):
        if self.handle is None or self.attached:
            raise ValueError('owner_requires_one_live_root')
        if process.poll() is not None:
            raise ValueError('native_root_already_exited')
        _checked(self.kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle))),
                 'AssignProcessToJobObject')
        self.attached.append(process.pid)
        if process.pid not in self.members():
            raise RuntimeError('native_root_membership_not_observed')

    def members(self):
        if self.handle is None:
            raise RuntimeError('owner_already_closed')
        capacity = 64
        while capacity <= 65536:
            class ProcessList(ctypes.Structure):
                _fields_ = [('assigned', wintypes.DWORD), ('count', wintypes.DWORD), ('pids', ctypes.c_size_t * capacity)]
            result = ProcessList()
            if self.kernel.QueryInformationJobObject(self.handle, 3, ctypes.byref(result), ctypes.sizeof(result), None):
                return [int(result.pids[i]) for i in range(result.count)]
            if ctypes.get_last_error() != 234:  # ERROR_MORE_DATA
                _checked(False, 'QueryInformationJobObject')
            capacity *= 2
        raise RuntimeError('native_process_tree_too_large')

    def close(self):
        if self.handle is None:
            return self.receipt
        before, after = None, None
        try:
            before = self.members()
            _checked(self.kernel.TerminateJobObject(self.handle, 137), 'TerminateJobObject')
            deadline = time.monotonic() + 5
            while True:
                after = self.members()
                if not after or time.monotonic() >= deadline:
                    break
                time.sleep(.02)
            self.receipt = dict(root_pids=self.attached[:], members_before_close=before,
                                members_after_termination=after, empty_confirmed=not after)
            if after:
                raise RuntimeError('owned_processes_still_present')
            return self.receipt
        finally:
            _checked(self.kernel.CloseHandle(self.handle), 'CloseHandle')
            self.handle = None


class OwnedNativeRPC:
    """NativeRPC delegation with a private descendant cleanup boundary."""
    def __init__(self, *args, **kwargs):
        from native_rpc import NativeRPC
        self.owner = ProcessOwner()
        self.rpc = None
        self.closed = False
        try:
            self.rpc = NativeRPC(*args, **kwargs)
            self.owner.attach(self.rpc.proc)
        except BaseException:
            try:
                self.owner.close()
            finally:
                if self.rpc is not None:
                    self.rpc.close()
            raise

    def __getattr__(self, name):
        return getattr(self.rpc, name)

    def close(self):
        if self.closed:
            return self.owner.receipt
        try:
            # First normal native shutdown; the job then removes remaining tools.
            self.rpc.close()
        finally:
            self.closed = True
            return_value = self.owner.close()
        return return_value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
