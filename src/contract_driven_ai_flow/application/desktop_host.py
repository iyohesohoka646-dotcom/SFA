"""Private desktop IPC: stdout contains availability, stdin closure ends ownership."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import threading

from .lifecycle import BackendOwner


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--project',type=Path,required=True)
    args=parser.parse_args();owner=BackendOwner(args.project)
    def start():
        try:
            handle=owner.start()
            if handle:print(json.dumps({'state':'ready',**asdict(handle)}),flush=True)
        except Exception as error:
            print(json.dumps({'state':'error','message':type(error).__name__+': backend startup failed; inspect the project .cdaf/studio.log'}),flush=True)
    worker=threading.Thread(target=start);worker.start()
    try:
        for line in sys.stdin:
            if line.strip()=='stop':break
    finally:owner.stop();worker.join(10)


if __name__=='__main__':main()
