"""Owned process-tree lifetime on Windows and POSIX."""
import ctypes
import os
import signal


class ProcessTree:
    def __init__(self, process):
        self.process = process
        self.handle = None
        self.extra_handles=[]
        if os.name == "nt":
            from ctypes import wintypes
            class BasicLimits(ctypes.Structure):
                _fields_ = [("ProcessUserTime", ctypes.c_longlong), ("JobUserTime", ctypes.c_longlong),
                    ("Flags", wintypes.DWORD), ("MinWorkingSet", ctypes.c_size_t), ("MaxWorkingSet", ctypes.c_size_t),
                    ("ActiveProcesses", wintypes.DWORD), ("Affinity", ctypes.c_size_t),
                    ("Priority", wintypes.DWORD), ("Scheduling", wintypes.DWORD)]
            class IoCounters(ctypes.Structure):
                _fields_ = [(name, ctypes.c_ulonglong) for name in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]
            class ExtendedLimits(ctypes.Structure):
                _fields_ = [("Basic", BasicLimits), ("Io", IoCounters),
                    *((name, ctypes.c_size_t) for name in ("ProcessMemory", "JobMemory", "PeakProcessMemory", "PeakJobMemory"))]
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            create = kernel.CreateJobObjectW
            create.argtypes, create.restype = [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE
            configure = kernel.SetInformationJobObject
            configure.argtypes, configure.restype = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL
            assign = kernel.AssignProcessToJobObject
            assign.argtypes, assign.restype = [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL
            close = kernel.CloseHandle
            close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
            handle = create(None, None)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = ExtendedLimits()
            limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not configure(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not assign(handle, int(process._handle)):
                error = ctypes.get_last_error()
                close(handle)
                process.kill()
                raise ctypes.WinError(error)
            self.handle, self._kernel = handle, kernel

    def terminate(self):
        if self.extra_handles:
            from ctypes import wintypes
            code=wintypes.DWORD()
            get_code=self._kernel.GetExitCodeProcess
            get_code.argtypes,get_code.restype=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)],wintypes.BOOL
            terminate=self._kernel.TerminateProcess
            terminate.argtypes,terminate.restype=[wintypes.HANDLE,wintypes.UINT],wintypes.BOOL
            for handle in self.extra_handles:
                if get_code(handle,ctypes.byref(code)) and code.value==259:
                    if not terminate(handle,130):raise ctypes.WinError(ctypes.get_last_error())
        if self.handle:
            terminate = self._kernel.TerminateJobObject
            terminate.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            terminate(self.handle, 130)
        elif os.name != "nt":
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        elif self.process.poll() is None:
            self.process.kill()

    def include(self,pid):
        """Include an authenticated owned service behind a Windows venv launcher."""
        if not self.handle or pid==self.process.pid:return
        from ctypes import wintypes
        kernel=self._kernel
        open_process=kernel.OpenProcess
        open_process.argtypes,open_process.restype=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD],wintypes.HANDLE
        process=open_process(0x1101,False,pid)  # QUERY_LIMITED_INFORMATION | SET_QUOTA | TERMINATE.
        if not process:raise ctypes.WinError(ctypes.get_last_error())
        keep=False
        try:
            inside=wintypes.BOOL()
            contains=kernel.IsProcessInJob
            contains.argtypes,contains.restype=[wintypes.HANDLE,wintypes.HANDLE,ctypes.POINTER(wintypes.BOOL)],wintypes.BOOL
            if not contains(process,self.handle,ctypes.byref(inside)):raise ctypes.WinError(ctypes.get_last_error())
            if inside.value:return
            assign=kernel.AssignProcessToJobObject
            assign.argtypes,assign.restype=[wintypes.HANDLE,wintypes.HANDLE],wintypes.BOOL
            if not assign(self.handle,process):
                error=ctypes.get_last_error()
                if error!=5:raise ctypes.WinError(error)
                # Some Store Python/system jobs reject nested Job assignment.
                # Hold this authenticated service's handle, so force-stop never
                # reopens a PID that could have been recycled by an unrelated app.
                self.extra_handles.append(process);keep=True
        finally:
            if not keep:kernel.CloseHandle(process)

    def close(self):
        if self.extra_handles:
            for handle in self.extra_handles:self._kernel.CloseHandle(handle)
            self.extra_handles=[]
        if self.handle:
            close = self._kernel.CloseHandle
            close.argtypes = [ctypes.c_void_p]
            close(self.handle)
            self.handle = None
