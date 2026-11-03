"""Disposable live scientific fixture and external RSS measurements; no production hooks."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

from contract_driven_ai_flow.studio import start,read_state,stop

root=Path(sys.argv[1]);duration=int(sys.argv[2]);root.mkdir(parents=True,exist_ok=True)
script=root/'live.py'
script.write_text('import time\nimport numpy as np\nX = np.zeros((64, 64))\ndeadline = time.monotonic() + '+str(duration)+'\nwhile time.monotonic() < deadline:\n    X = X + .001\n    time.sleep(.1)\n',encoding='utf-8')
handle=start(root,owned=True)
print(json.dumps({**handle,'script':str(script)}),flush=True)
class Memory(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD),*((key,ctypes.c_size_t) for key in ('peak','rss','paged_peak','paged','nonpaged_peak','nonpaged','pagefile','pagefile_peak'))]
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.OpenProcess.argtypes,kernel.OpenProcess.restype=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD],wintypes.HANDLE
kernel.CloseHandle.argtypes=[wintypes.HANDLE]
memory_fn=ctypes.WinDLL('psapi').GetProcessMemoryInfo
memory_fn.argtypes,memory_fn.restype=[wintypes.HANDLE,ctypes.POINTER(Memory),wintypes.DWORD],wintypes.BOOL
process=kernel.OpenProcess(0x0410,False,handle['pid']);samples=[];started=time.monotonic()
try:
    while time.monotonic()-started<duration+60 and read_state(root):
        sample=Memory();sample.cb=ctypes.sizeof(sample)
        if memory_fn(process,ctypes.byref(sample),sample.cb):samples.append({'seconds':time.monotonic()-started,'backend_rss_bytes':sample.rss})
        (root/'rss.json').write_text(json.dumps(samples),encoding='utf-8')
        time.sleep(1)
finally:
    kernel.CloseHandle(process);stop(root)
