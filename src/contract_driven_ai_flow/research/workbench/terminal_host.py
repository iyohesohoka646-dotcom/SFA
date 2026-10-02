"""Reset inherited signal disposition before attaching an interactive child to a PTY."""

import os
import signal
import subprocess
import sys


def main():
    argv = sys.argv[1:]
    if not argv:
        raise SystemExit("A terminal command is required")
    if os.name != "nt":
        import fcntl
        import termios

        # This wrapper is already a new session leader; inheriting an open
        # slave alone does not acquire a controlling terminal. No preexec_fn
        # runs in the multithreaded service process.
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        os.tcsetpgrp(0, os.getpgrp())
        for name in ("SIGINT", "SIGQUIT", "SIGTSTP", "SIGTTIN", "SIGTTOU"):
            signal.signal(getattr(signal, name), signal.SIG_DFL)
        os.execvpe(argv[0], argv, os.environ)
    # Windows inherits the console's Ctrl+C ignore flag even when a new
    # pseudoconsole is attached. Git Bash and noninteractive launchers set it.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetConsoleCtrlHandler.argtypes = [ctypes.c_void_p, wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL
    if not kernel.SetConsoleCtrlHandler(None, False):
        raise ctypes.WinError(ctypes.get_last_error())
    # Keep the supervisor alive while its interactive child handles Ctrl+C.
    signal.signal(signal.SIGINT, lambda *_: None)
    child = subprocess.Popen(argv)
    raise SystemExit(child.wait())


if __name__ == "__main__":
    main()
