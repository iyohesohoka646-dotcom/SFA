"""Cancelable child processes owned by the workbench, with bounded diagnostics."""
import os
import subprocess
import time

from ..processes import ProcessTree


def run_process(command, *, timeout=30, cancel=None, input=None, cwd=None, env=None):
    process = subprocess.Popen(command, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        start_new_session=os.name != 'nt')
    tree = ProcessTree(process)
    started = time.monotonic()
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Task cancelled')
            if time.monotonic() - started > timeout:
                raise TimeoutError('Worker exceeded time budget')
            try:
                stdout, stderr = process.communicate(input=input, timeout=.05)
                if len(stdout) > 1024 * 1024 or len(stderr) > 1024 * 1024:
                    raise ValueError('Worker diagnostics exceed byte budget')
                return process.returncode, stdout, stderr
            except subprocess.TimeoutExpired:
                input = None
    finally:
        if process.poll() is None:
            tree.terminate()
            process.communicate(timeout=3)
        tree.close()
