"""Reset inherited signal disposition before attaching an interactive child to a PTY."""
import os
import signal
import subprocess
import sys

def main():
    argv=sys.argv[1:]
    if not argv: raise SystemExit('A terminal command is required')
    if os.name!='nt':
        signal.signal(signal.SIGINT,signal.SIG_DFL)
        signal.signal(signal.SIGQUIT,signal.SIG_DFL)
        os.execvpe(argv[0],argv,os.environ)
    # Windows inherits the console's Ctrl+C ignore flag even when a new
    # pseudoconsole is attached. Git Bash and noninteractive launchers set it.
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.SetConsoleCtrlHandler.argtypes=[ctypes.c_void_p,wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype=wintypes.BOOL
    if not kernel.SetConsoleCtrlHandler(None,False): raise ctypes.WinError(ctypes.get_last_error())
    # Keep the supervisor alive while its interactive child handles Ctrl+C.
    signal.signal(signal.SIGINT,lambda *_:None)
    child=subprocess.Popen(argv)
    raise SystemExit(child.wait())

if __name__=='__main__': main()
