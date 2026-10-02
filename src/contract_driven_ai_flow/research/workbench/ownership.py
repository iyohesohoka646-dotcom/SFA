"""Read-only process identity for durable task ownership."""
import os
from pathlib import Path
import subprocess

from ...storage import process_alive


def birth(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            created, exited, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if kernel.GetProcessTimes(handle, *(ctypes.byref(v) for v in (created, exited, kernel_time, user_time))):
                return str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    else:
        try:
            stat = Path(f'/proc/{pid}/stat').read_text()
            return stat[stat.rfind(')') + 2:].split()[19]
        except (OSError, IndexError):
            try:
                return subprocess.check_output(['ps', '-p', str(pid), '-o', 'lstart='], timeout=2, text=True).strip() or None
            except (OSError, subprocess.SubprocessError):
                return None


def current_owner():
    return {'pid': os.getpid(), 'birth': birth(os.getpid())}


def owner_alive(owner):
    if not isinstance(owner, dict) or type(owner.get('pid')) is not int or owner['pid'] <= 0:
        return False
    if not process_alive(owner['pid']):
        return False
    actual = birth(owner['pid'])
    return actual is None or owner.get('birth') is None or actual == owner['birth']
