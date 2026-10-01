"""Create user-requested launchers using the installed interpreter, never PATH guesses."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys

from .paths import FlowError
from .storage import atomic_write
from .workspace import user_home


def desktop() -> Path:
    if os.name == "nt":
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "[Environment]::GetFolderPath('Desktop')"],
                                capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
        if result.returncode != 0 or not result.stdout.strip():
            raise FlowError("Cannot locate Desktop; provide --directory explicitly")
        return Path(result.stdout.strip())
    return Path.home() / "Desktop"


def create_shortcuts(directory: Path | None = None, *, workspace: Path | None = None, project: Path | None = None):
    directory = (directory or desktop()).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    workspace = (workspace or user_home()).resolve()
    scope = ["--project", str(project.resolve())] if project else ["--home", str(workspace)]
    files = []
    for action, title in (("start", "Scientific Dataflow Inspector"),):
        arguments = ["-X", "utf8", "-m", "contract_driven_ai_flow.launcher", "--action", action, *scope]
        if os.name == "nt":
            # COM resolves the actual Desktop, including redirected/non-ASCII paths.
            executable = Path(sys.executable).with_name("pythonw.exe")
            if not executable.is_file():
                executable = Path(sys.executable)
            path = directory / (title + ".lnk")
            def quote(value):
                return "'" + str(value).replace("'", "''") + "'"
            script = "$taskLink = (New-Object -ComObject WScript.Shell).CreateShortcut(" + quote(path) + "); "
            script += "$taskLink.TargetPath=" + quote(executable) + "; $taskLink.Arguments=" + quote(subprocess.list2cmdline(arguments)) + "; "
            script += "$taskLink.WorkingDirectory=" + quote(directory) + "; $taskLink.WindowStyle=7; $taskLink.Save()"
            result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True,
                                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
            if result.returncode:
                raise FlowError("Windows shortcut creation failed; use cdaf studio or a writable --directory")
        elif sys.platform == "darwin":
            path = directory / (title + ".command")
            atomic_write(path, "#!/bin/sh\nexec " + shlex.join([sys.executable, *arguments]) + "\n")
            path.chmod(0o755)
        else:
            path = directory / (title + ".desktop")
            def desktop_quote(value):
                return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('`', '\\`') + '"'
            command = " ".join(desktop_quote(value) for value in [sys.executable, *arguments])
            atomic_write(path, f"[Desktop Entry]\nType=Application\nName={title}\nExec={command}\nTerminal=false\nCategories=Development;\n")
            path.chmod(0o755)
        files.append(str(path))
    if os.name=='nt':
        # Remove only the two launchers previously created by this package.
        def quote(value):return "'"+str(value).replace("'","''")+"'"
        script="$taskShell=New-Object -ComObject WScript.Shell; "
        for title in ('Contract Flow Studio','Stop Contract Flow Studio'):
            old=directory/(title+'.lnk')
            script+="if(Test-Path -LiteralPath "+quote(old)+"){ $taskOld=$taskShell.CreateShortcut("+quote(old)+"); if($taskOld.Arguments.Contains('contract_driven_ai_flow.launcher')){Remove-Item -LiteralPath "+quote(old)+"} }; "
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15,check=True)
    return {"files": files, "python": sys.executable, "workspace": str(workspace), "project": str(project.resolve()) if project else None,
            "note": "Recreate shortcuts after moving or removing the Python environment"}
