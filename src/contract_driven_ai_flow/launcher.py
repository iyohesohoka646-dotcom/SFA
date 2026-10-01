"""Windowless local Web launcher; browser connections own default service lifetime."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import webbrowser

from .storage import atomic_write
from .studio import start, stop
from .workspace import user_home


def main():
    parser = argparse.ArgumentParser(description="Open Scientific Dataflow Inspector")
    parser.add_argument("--action", choices=["start", "stop"], default="start")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    root = (args.project or args.home or user_home()).resolve()
    try:
        result = stop(root) if args.action == "stop" else start(root, workspace=args.project is None, owned=True)
        atomic_write(root / ".cdaf/launcher.json", json.dumps(result))
        if args.action == "start" and not args.no_open:
            webbrowser.open(result["url"])
    except Exception as exc:
        # pythonw has no console. Preserve the concrete startup diagnosis locally.
        message = f"Studio could not start: {exc}\nRun cdaf doctor or inspect {root / '.cdaf/studio.log'}"
        atomic_write(root / ".cdaf/launcher-error.txt", message)
        if not args.no_open:
            webbrowser.open((root / ".cdaf/launcher-error.txt").as_uri())
        raise SystemExit(1)


if __name__ == "__main__":
    main()
