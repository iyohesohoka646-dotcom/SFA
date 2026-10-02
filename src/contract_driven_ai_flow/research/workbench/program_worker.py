"""Standard-library protocol for an explicitly enabled user probe program."""
import hashlib
import importlib
import inspect
import asyncio
import json
from pathlib import Path
import sys

def main():
    request=json.load(sys.stdin)
    root=Path(request['root']).resolve();sys.path.insert(0,str(root))
    module,symbol=request['entrypoint'].split(':')
    origin=root.joinpath(*module.split('.')).with_suffix('.py')
    expected=request.get('implementation_digest')
    if expected and (not origin.is_file() or hashlib.sha256(origin.read_bytes()).hexdigest()!=expected):
        raise ValueError('Program changed after review; import and enable a new resource version')
    imported=importlib.import_module(module)
    fn=imported
    for component in symbol.split('.'):fn=getattr(fn,component)
    if not callable(fn):raise TypeError('Program entry is not callable')
    if not origin.is_file() and getattr(imported,'__file__',None):origin=Path(imported.__file__)
    digest=hashlib.sha256(origin.read_bytes()).hexdigest() if origin.is_file() else None
    result=fn(request['context'],request['parameters'])
    if inspect.isawaitable(result):result=asyncio.run(result)
    if not isinstance(result,dict):raise ValueError('Program result must be an object')
    if result.get('status') not in ('ready','pass','fail','error','unknown','skipped'):
        raise ValueError('Program result requires an explicit result status')
    print(json.dumps({'result':result,'program_digest':digest},ensure_ascii=False,allow_nan=False))

if __name__=='__main__':main()
