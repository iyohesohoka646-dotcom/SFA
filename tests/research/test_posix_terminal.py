"""Real POSIX job control, output decoding and owned-session cleanup."""

import os
import select
import signal
import sys
import time

import pytest

from contract_driven_ai_flow.research.workbench.terminal import _PosixPTY

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX controlling terminal")


def open_terminal(tmp_path, source):
    return _PosixPTY(
        [sys.executable, "-u", "-c", source],
        tmp_path,
        dict(os.environ, PYTHONUTF8="1"),
        24,
        80,
    )


def read_until(terminal, wanted, timeout=5):
    data = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if select.select([terminal.fd], [], [], 0.1)[0]:
            try:
                data += terminal.read()
            except (EOFError, OSError):
                break
            if wanted in data:
                return data
    raise AssertionError(f"Terminal did not output {wanted!r}: {data!r}")


def test_posix_controlling_terminal_delivers_interrupt(tmp_path):
    terminal = open_terminal(
        tmp_path,
        "import os,time\ntry:\n print('FOREGROUND',os.tcgetpgrp(0)==os.getpgrp(),flush=True)\n time.sleep(30)\nexcept KeyboardInterrupt:\n print('INTERRUPTED',flush=True)\n",
    )
    try:
        assert "FOREGROUND True" in read_until(terminal, "FOREGROUND True")
        terminal.write("\x03")
        read_until(terminal, "INTERRUPTED")
    finally:
        terminal.close()


def test_split_utf8_output_is_not_eof(tmp_path):
    terminal = open_terminal(
        tmp_path,
        "import os,time\nb='中'.encode('utf-8')\nos.write(1,b[:1]); time.sleep(.25); os.write(1,b[1:]); time.sleep(5)\n",
    )
    try:
        assert select.select([terminal.fd], [], [], 5)[0]
        first = terminal.read()
        assert first == "中"
        assert terminal.poll() is None
    finally:
        terminal.close()


def test_close_targets_owned_pids_without_a_redundant_group_signal(
    tmp_path, monkeypatch
):
    terminal = open_terminal(
        tmp_path, "import time; print('READY',flush=True); time.sleep(30)"
    )
    read_until(terminal, "READY")

    def redundant_group_signal():
        raise PermissionError("A previously terminated group cannot be signaled")

    monkeypatch.setattr(terminal.tree, "terminate", redundant_group_signal)
    try:
        terminal.close()
        assert terminal.poll() is not None
        assert terminal.fd == -1
    finally:
        if terminal.fd >= 0:
            terminal.process.kill()
            terminal.process.wait(timeout=2)
            os.close(terminal.fd)
            terminal.fd = -1


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # Killed orphan zombies await the OS reaper and cannot execute further code.
    import subprocess

    status = subprocess.run(
        ["ps", "-p", str(pid), "-o", "stat="], capture_output=True, text=True
    ).stdout.strip()
    return bool(status) and not status.startswith("Z")


@pytest.mark.parametrize("separate_group", [False, True])
@pytest.mark.parametrize("leader_exits_first", [False, True])
def test_closing_terminal_cleans_stubborn_children_after_leader_exit(
    tmp_path, separate_group, leader_exits_first
):
    marker = tmp_path / "child.pid"
    child_code = f"import os,signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\nsignal.signal(signal.SIGHUP,signal.SIG_IGN)\nopen({str(marker)!r},'w').write(str(os.getpid()))\ntime.sleep(30)"
    parent = (
        f"import subprocess,sys,time,pathlib\nsubprocess.Popen([sys.executable,'-c',{child_code!r}],process_group={'0' if separate_group else 'None'})\nwhile not pathlib.Path({str(marker)!r}).exists(): time.sleep(.01)\nprint('STARTED',flush=True)\n"
        + ("" if leader_exits_first else "time.sleep(30)")
    )
    terminal = open_terminal(tmp_path, parent)
    child = None
    closed = False
    try:
        read_until(terminal, "STARTED")
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        child = int(marker.read_text())
        terminal.close()
        closed = True
        assert not alive(child), "An owned terminal child survived session close"
    finally:
        if not closed:
            terminal.close()
        if child and alive(child):
            os.kill(child, signal.SIGKILL)


def test_interactive_shell_foreground_job_interrupt_and_resume(tmp_path):
    import shlex

    terminal = _PosixPTY(
        ["/bin/bash", "--noprofile", "--norc", "-i"], tmp_path, dict(os.environ), 24, 80
    )
    try:
        job = "import time; print('JOB-'+str(6*7), flush=True); time.sleep(30)"
        terminal.write(
            shlex.quote(sys.executable) + " -u -c " + shlex.quote(job) + "\r"
        )
        read_until(terminal, "JOB-42")
        terminal.write("\x03")
        read_until(terminal, "KeyboardInterrupt")
        terminal.write("printf 'RESUME-%s\\n' $((6*7))\r")
        read_until(terminal, "RESUME-42")
        assert terminal.poll() is None
    finally:
        terminal.close()
