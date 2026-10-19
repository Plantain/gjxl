"""Supervise a G5 command without allocating CUDA memory."""
import ctypes as C
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


class Memory(C.Structure):
    _fields_ = [('total', C.c_ulonglong), ('free', C.c_ulonglong),
                ('used', C.c_ulonglong)]


nv = C.CDLL('libnvidia-ml.so.1')
assert nv.nvmlInit_v2() == 0
device = C.c_void_p()
assert nv.nvmlDeviceGetHandleByIndex_v2(0, C.byref(device)) == 0


def free():
    value = Memory()
    assert nv.nvmlDeviceGetMemoryInfo(device, C.byref(value)) == 0
    return value.free


floor = 12 * 1024**3
minimum = free()
if minimum < floor + int(os.environ.get('G5_EXPECTED_PEAK_MIB', '2048')) * 1024**2:
    print('G5 preflight deferred:', minimum, flush=True)
    sys.exit(75)
began = time.monotonic()
child = subprocess.Popen(sys.argv[2:], start_new_session=True)
samples = 0
reason = None
try:
    while child.poll() is None:
        minimum = min(minimum, free())
        samples += 1
        if minimum < floor or time.monotonic() - began > int(os.environ.get('G5_LIMIT_SECONDS', '250')):
            reason = 'physical-free floor' if minimum < floor else 'time limit'
            os.killpg(child.pid, signal.SIGKILL)
            break
        time.sleep(.02)
    status = child.wait()
finally:
    if child.poll() is None:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()
    Path(sys.argv[1]).write_text(json.dumps(dict(
        command=sys.argv[2:], minimum_free_bytes=minimum, floor_bytes=floor,
        samples=samples, seconds=time.monotonic()-began,
        stopped=reason, returncode=child.returncode), indent=2)+'\n')
    nv.nvmlShutdown()
sys.exit(76 if reason else status)
