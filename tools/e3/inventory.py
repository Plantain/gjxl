#!/usr/bin/env python3
"""Attribute nsys copies/syncs using CUDA backtraces (including PIE exports).

nsys in a --pid=host container can export unresolved executable addresses.
Supply the executable and its load base to resolve them with addr2line. Copies
without their own stack inherit the next completion's stack on the same thread;
the synchronous copy helpers make that association exact within each batch.
"""
import argparse
import bisect
import collections
import json
import sqlite3
import subprocess

p = argparse.ArgumentParser()
p.add_argument('sqlite')
p.add_argument('--binary', required=True)
p.add_argument('--base', type=lambda x: int(x, 0), required=True)
p.add_argument('--tiles', type=int, required=True)
a = p.parse_args()
db = sqlite3.connect(a.sqlite)
strings = dict(db.execute('select id,value from StringIds'))
stacks = collections.defaultdict(list)
ips = sorted({ip for (ip,) in db.execute('select originalIP from CUDA_CALLCHAINS')
              if a.base <= ip < a.base + 0x2000000})
lines = subprocess.check_output(['addr2line', '-f', '-C', '-e', a.binary,
                                *[hex(ip - a.base - 1) for ip in ips]], text=True).splitlines()
resolved = {ip: lines[2*i:2*i+2] for i, ip in enumerate(ips)}
for chain, depth, ip in db.execute('select id,stackDepth,originalIP from CUDA_CALLCHAINS order by id,stackDepth'):
    if ip in resolved:
        stacks[chain].append(resolved[ip])

# With CUDA backtraces enabled, nsys emits a wrapper and a versioned runtime
# record with the same thread/correlation ID. Count the call once, preferring
# the wrapper that carries the stack.
unique_runtime = {}
for row in db.execute('select start,end,globalTid,correlationId,nameId,callchainId from CUPTI_ACTIVITY_KIND_RUNTIME order by start'):
    key = row[2:4]
    if key not in unique_runtime or row[5] is not None:
        unique_runtime[key] = row
runtime = sorted(unique_runtime.values())
by_tid = collections.defaultdict(list)
for start, end, tid, corr, name, chain in runtime:
    if chain is not None:
        by_tid[tid].append((start, chain))
times = {tid: [r[0] for r in rows] for tid, rows in by_tid.items()}
calls = {r[3]: r for r in runtime}
copies = collections.defaultdict(lambda: [0, 0])
for corr, kind, size in db.execute('select correlationId,copyKind,bytes from CUPTI_ACTIVITY_KIND_MEMCPY'):
    start, end, tid, _, name, chain = calls[corr]
    if chain is None:
        i = bisect.bisect_left(times.get(tid, []), start)
        chain = by_tid[tid][i][1] if i < len(by_tid[tid]) else -1
    # Keep two application callers after the backend helper / call_once.
    stack = stacks[chain]
    site = ' > '.join(f'{fn} ({loc})' for fn, loc in stack[:5])
    row = copies[(kind, site)]
    row[0] += 1
    row[1] += size
syncs = collections.Counter()
for start, end, tid, corr, name, chain in runtime:
    if 'Synchronize' in strings[name]:
        syncs[(strings[name], ' > '.join(f'{fn} ({loc})' for fn, loc in stacks[chain][:5]))] += 1
result = {'tiles': a.tiles,
          'copies': [{'direction': {1: 'H2D', 2: 'D2H', 8: 'D2D'}.get(k, str(k)),
                      'site': site, 'calls': n, 'bytes': size,
                      'bytes_per_tile': size/a.tiles} for (k, site), (n, size) in copies.items()],
          'syncs': [{'api': api, 'site': site, 'calls': n, 'per_tile': n/a.tiles}
                    for (api, site), n in syncs.items()],
          'stacks': [list(stack) for stack in sorted({
              tuple(tuple(frame) for frame in stack) for stack in stacks.values()})]}
print(json.dumps(result, indent=2))
