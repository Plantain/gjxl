#!/usr/bin/env python3
"""Reduce remote Nsight evidence without copying large traces to the Mac."""
import argparse
import collections
import csv
import io
import json
import re
import sqlite3
import statistics
from pathlib import Path


def occupancy(path):
    if not path:
        return {}
    lines = Path(path).read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('"ID","Process ID"'))
    groups = collections.defaultdict(list)
    for row in csv.DictReader(io.StringIO('\n'.join(lines[start:]))):
        if row.get('Metric Name') != 'sm__warps_active.avg.pct_of_peak_sustained_active':
            continue
        # Nsight Compute writes namespace-qualified names, Nsight Systems
        # shortName retains only the function and any template parameters.
        name = row['Kernel Name'].split('(')[0].rsplit('::', 1)[-1]
        name = re.sub(r'<.*', '', name).strip()
        groups[name].append(float(row['Metric Value'].replace(',', '')))
    return {name: dict(samples=len(values), mean_pct=statistics.mean(values),
                       min_pct=min(values), max_pct=max(values))
            for name, values in groups.items()}


def union_ns(intervals):
    end = 0
    total = 0
    for start, stop in sorted(intervals):
        total += max(0, stop - max(end, start))
        end = max(end, stop)
    return total


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('sqlite', type=Path)
    p.add_argument('--tiles', type=int, default=120)
    p.add_argument('--occupancy')
    a = p.parse_args()
    db = sqlite3.connect(a.sqlite)
    db.row_factory = sqlite3.Row
    kernels = [dict(r) for r in db.execute('''
        select k.*, s.value as name from CUPTI_ACTIVITY_KIND_KERNEL k
        join StringIds s on s.id=k.shortName order by k.start''')]
    counters = occupancy(a.occupancy)
    groups = collections.defaultdict(list)
    for k in kernels:
        groups[k['name']].append(k)
    stages = []
    for name, group in groups.items():
        bare = re.sub(r'<.*', '', name)
        shapes = collections.Counter((r['gridX'], r['gridY'], r['gridZ'],
                                      r['blockX'], r['blockY'], r['blockZ']) for r in group)
        stages.append(dict(kernel=name, count=len(group), per_tile=len(group) / a.tiles,
                           ms_per_tile=sum(r['end'] - r['start'] for r in group) / 1e6 / a.tiles,
                           grids=[dict(grid=list(s[:3]), block=list(s[3:]), count=n)
                                  for s, n in sorted(shapes.items())],
                           registers_per_thread=sorted({r['registersPerThread'] for r in group}),
                           shared_bytes=sorted({r['staticSharedMemory'] + r['dynamicSharedMemory'] for r in group}),
                           isolated_achieved_occupancy=counters.get(bare)))
    stages.sort(key=lambda r: r['ms_per_tile'], reverse=True)
    runtime = [dict(r) for r in db.execute('''select r.*, s.value as name
        from CUPTI_ACTIVITY_KIND_RUNTIME r join StringIds s on s.id=r.nameId''')]
    apis = collections.defaultdict(list)
    correlation = {}
    for r in runtime:
        apis[r['name']].append(r)
        correlation[r['correlationId']] = r
    api_summary = {name: dict(count=len(rows), per_tile=len(rows) / a.tiles,
                              ms_per_tile=sum(r['end'] - r['start'] for r in rows) / 1e6 / a.tiles)
                   for name, rows in apis.items()}
    copies = [dict(r) for r in db.execute('select * from CUPTI_ACTIVITY_KIND_MEMCPY')]
    memsets = [dict(r) for r in db.execute('select * from CUPTI_ACTIVITY_KIND_MEMSET')]
    streams = collections.defaultdict(list)
    for op in kernels + copies + memsets:
        streams[op['streamId']].append(op)
    chains = []
    # In the resident encoder each worker owns one stream and submits one tile
    # at a time. The RGB8 input kernel starts the GPU part of each tile. A chain
    # ends at that tile's last stream operation, excluding CPU entropy/tail.
    for stream, ops in streams.items():
        ops.sort(key=lambda r: r['start'])
        starts = [i for i, r in enumerate(ops) if 'LinearRgbToOpsinKernel' in r.get('name', '')]
        for ordinal, begin in enumerate(starts):
            end = starts[ordinal + 1] if ordinal + 1 < len(starts) else len(ops)
            tile = ops[begin:end]
            gaps, unsubmitted, queued = 0, 0, 0
            for prev, nxt in zip(tile, tile[1:]):
                gap = max(0, nxt['start'] - prev['end'])
                api = correlation.get(nxt['correlationId'])
                # Split at host API completion. This is observational, not a
                # proof of scheduler causality or a cross-stream dependency.
                host_gap = min(gap, max(0, api['end'] - prev['end'])) if api else 0
                gaps += gap
                unsubmitted += host_gap
                queued += gap - host_gap
            sequence = []
            for op in tile:
                name = op.get('name', 'copy' if 'copyKind' in op else 'memset')
                if sequence and sequence[-1]['name'] == name:
                    sequence[-1]['count'] += 1
                    sequence[-1]['ms'] += (op['end'] - op['start']) / 1e6
                else:
                    sequence.append(dict(name=name, count=1, ms=(op['end'] - op['start']) / 1e6))
            chains.append(dict(stream=stream, ordinal=ordinal,
                               gpu_span_ms=(tile[-1]['end'] - tile[0]['start']) / 1e6,
                               device_work_ms=sum(r['end'] - r['start'] for r in tile) / 1e6,
                               gap_ms=gaps / 1e6, before_api_completion_ms=unsubmitted / 1e6,
                               after_api_completion_ms=queued / 1e6, sequence=sequence))
    assert len(chains) == a.tiles, len(chains)
    longest = max(chains, key=lambda r: r['gpu_span_ms'])
    spans = [r['gpu_span_ms'] for r in chains]
    first, last = min(r['start'] for r in kernels), max(r['end'] for r in kernels)
    result = dict(source=str(a.sqlite), tiles=a.tiles,
                  kernel_streams=len({r['streamId'] for r in kernels}),
                  kernel_count=len(kernels), kernels_per_tile=len(kernels) / a.tiles,
                  summed_kernel_ms_per_tile=sum(r['end'] - r['start'] for r in kernels) / 1e6 / a.tiles,
                  kernel_interval_union_fraction=union_ns((r['start'], r['end']) for r in kernels) / (last - first),
                  occupancy_note='NCU single-tile kernel replay; achieved active warps on active SM cycles. '
                                 'Not whole-device occupancy or simultaneous twelve-lane occupancy.',
                  stages=stages, runtime=api_summary,
                  copies={str(kind): dict(bytes=sum(r['bytes'] for r in copies if r['copyKind'] == kind),
                                           count=sum(r['copyKind'] == kind for r in copies))
                          for kind in sorted({r['copyKind'] for r in copies})},
                  chains=dict(count=len(chains), mean_span_ms=statistics.mean(spans),
                              median_span_ms=statistics.median(spans), max_span_ms=max(spans),
                              mean_work_ms=statistics.mean(r['device_work_ms'] for r in chains),
                              mean_gap_ms=statistics.mean(r['gap_ms'] for r in chains),
                              mean_before_api_completion_ms=statistics.mean(r['before_api_completion_ms'] for r in chains),
                              mean_after_api_completion_ms=statistics.mean(r['after_api_completion_ms'] for r in chains),
                              longest=longest))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
