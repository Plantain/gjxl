#!/usr/bin/env python3
"""Reduce Nsight CPU samples/backtraces and correlate lane CUDA API intervals.

CPU samples describe on-CPU work, not wall time. API wall spans can overlap
across lanes. Unscheduled time includes both blocking and preemption; OSRT
wait primitives give evidence of blocking but not exclusive off-CPU totals.
"""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import json
import re
import sqlite3


def category(api, stack):
    if 'Synchronize' in api:
        return 'cuda_wait'
    if 'Launch' in api or 'Graph' in api:
        return 'cuda_launch'
    if api:
        return 'cuda_copy_other'
    # Most specific frames first, so allocator/mutex samples inside entropy
    # remain overhead, rather than being charged to arithmetic/serialization.
    for symbol, module in stack:
        if any(x in symbol.lower() for x in ('mutex', 'rwlock', 'futex', 'cond_wait', 'semaphore')):
            return 'mutex_other'
        if any(x in symbol for x in ('malloc', 'calloc', 'realloc', 'free', 'Allocator',
                                      'Allocation', 'ResourceBudget', 'operator new', 'operator delete')):
            return 'allocation_budget'
        if 'libToolsInjection' in module or 'NSYS_' in symbol:
            return 'profiler'
        if 'gjxl' not in symbol:
            continue
        if any(x in symbol for x in ('Entropy', 'Ans', 'Histogram', 'BitWriter', 'Tokeniz',
                                      'HybridUint', 'WriteBits', 'WriteVarDct', 'WriteFrame')):
            return 'entropy_serialization'
        if any(x in symbol for x in ('AcStrategy', 'MakeCandidates', 'Division', 'Quant',
                                      'Dct', 'Aq', 'Prepared', 'Resident', 'Frame')):
            return 'host_preparation_decisions'
    return 'other_unresolved'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('sqlite')
    p.add_argument('--tiles', type=int, required=True)
    a = p.parse_args()
    db = sqlite3.connect(a.sqlite)
    strings = dict(db.execute('select id,value from StringIds'))
    apis = defaultdict(list)
    api_wall, api_count = Counter(), Counter()
    for tid, start, end, name in db.execute(
            'select globalTid,start,end,nameId from CUPTI_ACTIVITY_KIND_RUNTIME order by start'):
        name = strings[name].split('_v')[0]
        if name == 'cuProfilerStart':
            continue
        apis[tid].append((start, end, name))
        api_wall[name] += end-start
        api_count[name] += 1
    tids = set(apis)
    lo = min(v[0][0] for v in apis.values())
    hi = max(v[-1][1] for v in apis.values())
    starts = {tid: [x[0] for x in rows] for tid, rows in apis.items()}
    stacks = defaultdict(list)
    for sid, symbol, module in db.execute('select id,symbol,module from SAMPLING_CALLCHAINS order by id,stackDepth'):
        stacks[sid].append((strings[symbol], strings[module]))
    counts, other_threads, leaves = Counter(), Counter(), Counter()
    categories_by_tid = defaultdict(Counter)
    broken = 0
    for sid, t, tid in db.execute('select id,start,globalTid from COMPOSITE_EVENTS where threadState=1'):
        if not lo <= t <= hi:
            continue
        if tid not in tids:
            other_threads[tid] += 1
            continue
        index = bisect_right(starts[tid], t)-1
        api = apis[tid][index][2] if index >= 0 and t < apis[tid][index][1] else ''
        stack = stacks[sid]
        cat = category(api, stack)
        counts[cat] += 1
        categories_by_tid[tid][cat] += 1
        if stack:
            leaves[(cat, stack[0][0], stack[0][1])] += 1
        broken += any('[Broken' in s for s, _ in stack)
    # Sched events can include unrelated host threads: restrict to lane TIDs.
    sched = defaultdict(list)
    for t, tid, on in db.execute('select start,globalTid,isSchedIn from SCHED_EVENTS order by start'):
        if tid in tids:
            sched[tid].append((t, on))
    on_cpu, api_on = 0, Counter()
    for tid, events in sched.items():
        intervals = []
        active = lo if events and not events[0][1] else None
        for t, on in events:
            if on:
                active = max(lo, t)
            elif active is not None:
                if min(hi, t) > active:
                    intervals.append((active, min(hi, t)))
                active = None
        if active is not None and active < hi:
            intervals.append((active, hi))
        on_cpu += sum(e-s for s,e in intervals)
        index = 0
        for s,e,name in apis[tid]:
            while index < len(intervals) and intervals[index][1] <= s:
                index += 1
            j = index
            while j < len(intervals) and intervals[j][0] < e:
                b,z = intervals[j]
                api_on[name] += max(0, min(e,z)-max(s,b))
                j += 1
    osrt = Counter()
    if db.execute("select 1 from sqlite_master where name='OSRT_API'").fetchone():
        for tid,s,e,name in db.execute('select globalTid,start,end,nameId from OSRT_API'):
            if tid in tids and lo <= s <= hi:
                osrt[strings[name]] += max(0, min(hi,e)-s)
    total = sum(counts.values())
    print(json.dumps(dict(source=a.sqlite, tiles=a.tiles, lane_threads=len(tids),
        lane_samples=total, broken_backtrace_samples=broken,
        non_lane_samples=dict(other_threads), lane_scheduled_cpu_ms_per_tile=on_cpu/1e6/a.tiles,
        categories=[dict(category=k,samples=v,percent=100*v/total,
                         estimated_cpu_ms_per_tile=on_cpu/1e6/a.tiles*v/total)
                    for k,v in counts.most_common()],
        by_thread=categories_by_tid,
        cuda_api=[dict(api=k,count=api_count[k],count_per_tile=api_count[k]/a.tiles,
                      wall_ms_per_tile=v/1e6/a.tiles,
                      scheduled_cpu_ms_per_tile=api_on[k]/1e6/a.tiles,
                      off_cpu_ms_per_tile=(v-api_on[k])/1e6/a.tiles)
                  for k,v in api_wall.most_common()],
        osrt_wall_ms_per_tile={k:v/1e6/a.tiles for k,v in osrt.most_common(15)},
        leaves=[dict(category=k,symbol=s,module=m,samples=v)
                for (k,s,m),v in leaves.most_common(60)],
        caveats=['Loaded/instrumented attribution; no throughput decision.',
                 'Sample proportions estimate CPU attribution; CUDA API scheduled CPU is interval intersection.',
                 'Scheduling export does not distinguish preemption from blocked time.',
                 'Broken backtraces retained; runtime correlation still classifies CUDA samples.']), indent=2))


if __name__ == '__main__':
    main()
