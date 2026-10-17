#!/usr/bin/env python3
"""One CPU attribution capture, never a throughput run."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from variants import environment, enabled_for_mask

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('label')
p.add_argument('mask', type=int, choices=range(8))
p.add_argument('--reps', type=int, default=2)
p.add_argument('--api-audit', action='store_true', help='Trace every CUDA API without CPU sampling')
a = p.parse_args()
root = Path('/w/e4/phase2')
(root / 'profiles').mkdir(parents=True, exist_ok=True)
prefix = root / 'profiles' / a.label
exe = root / 'release/gjxl_transfer_gate'
command = ['/w/g3/nsys/opt/nvidia/nsight-systems/2025.6.3/bin/nsys', 'profile',
           '--trace=cuda,nvtx', '--sample=process-tree', '--backtrace=dwarf',
           '--samples-per-backtrace=1', '--capture-range=cudaProfilerApi',
           '--capture-range-end=stop', '--force-overwrite=true', '--export=sqlite',
           '-o', str(prefix), str(exe), 'trace', '12', str(a.reps), '/w/corpus/dev']
if a.api_audit:
    command[command.index('--sample=process-tree')] = '--sample=none'
    command.insert(2, '--cpuctxsw=none')
    command.insert(2, '--cuda-trace-all-apis=true')
# Write directly to files. A failed Nsight agent can leave its target alive
# with inherited pipes; communicate() would then wait until the full timeout.
with prefix.with_suffix('.stdout').open('w') as out, prefix.with_suffix('.stderr').open('w') as err:
    run = subprocess.run(command, env=environment(enabled_for_mask(a.mask)),
                         stdout=out, stderr=err, timeout=120)
run.check_returncode()
stdout = prefix.with_suffix('.stdout').read_text()
stderr = prefix.with_suffix('.stderr').read_text()
rows = [json.loads(line) for line in stdout.splitlines() if line.startswith('{')]
profile = next(r for r in rows if r.get('profile_tiles') == 400 * a.reps)
assert prefix.with_suffix('.sqlite').exists()
result = dict(command=command, mask=a.mask, profile=profile,
              sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
              stderr=stderr, trace=str(prefix))
print(json.dumps(result), flush=True)
