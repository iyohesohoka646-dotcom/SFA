"""Cancelable child processes owned by the workbench, with bounded diagnostics."""
import os
import subprocess
import threading
import time

from ..processes import ProcessTree


def run_process(command, *, timeout=30, cancel=None, input=None, cwd=None, env=None):
    process = subprocess.Popen(command, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
        start_new_session=os.name != 'nt')
    tree, threads = None, []
    buffers = [bytearray(), bytearray()]
    overflow = threading.Event()
    limit = 1024 * 1024

    def drain(stream, data):
        try:
            while block := stream.read1(8192):
                remaining = limit - len(data)
                data.extend(block[:remaining])
                if len(block) > remaining:
                    overflow.set()
                    return
        except (OSError, ValueError):
            pass

    def write():
        try:
            process.stdin.write(input)
            process.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            process.stdin.close()

    try:
        tree = ProcessTree(process)
        for stream, data in zip((process.stdout, process.stderr), buffers):
            thread = threading.Thread(target=drain, args=(stream, data), daemon=True, name='cdaf-worker-output')
            threads.append(thread); thread.start()
        if input is not None:
            thread = threading.Thread(target=write, daemon=True, name='cdaf-worker-input')
            threads.append(thread); thread.start()
        started = time.monotonic()
        while True:
            if overflow.is_set():
                raise ValueError('Worker diagnostics exceed byte budget')
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Task cancelled')
            if process.poll() is not None and not any(t.is_alive() for t in threads):
                return process.returncode, *(bytes(data) for data in buffers)
            if time.monotonic() - started > timeout:
                raise TimeoutError('Worker exceeded time budget')
            overflow.wait(.02)
    finally:
        try:
            if tree is not None:
                if process.poll() is None or any(t.is_alive() for t in threads):
                    tree.terminate()
                tree.close()
            elif process.poll() is None:
                process.kill()
            process.wait(timeout=3)
        finally:
            for thread in threads:
                thread.join(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
