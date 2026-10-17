#!/usr/bin/env python3
"""Attribute transfer deltas from existing E3 traces; no GPU work or timing."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3

from variants import DEFAULT_ENABLED


def baseline_totals(path, tiles):
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    copies = dict(db.execute('''select copyKind, sum(bytes)
                               from CUPTI_ACTIVITY_KIND_MEMCPY group by copyKind'''))
    syncs = db.execute('''select count(*) from (
        select distinct r.globalTid, r.correlationId
        from CUPTI_ACTIVITY_KIND_RUNTIME r join StringIds s on s.id=r.nameId
        where s.value like '%Synchronize%')''').fetchone()[0]
    kernels = db.execute('select count(*) from CUPTI_ACTIVITY_KIND_KERNEL').fetchone()[0]
    return dict(h2d_bytes=copies[1]/tiles, d2h_bytes=copies[2]/tiles,
                d2d_bytes=copies[8]/tiles, pcie_bytes=(copies[1]+copies[2])/tiles,
                host_syncs=syncs/tiles, kernels=kernels/tiles, rgb_h2d_bytes=0)


def read(path, compact):
    db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    starts = defaultdict(list)
    for stream, start in db.execute('''select k.streamId, k.start
            from CUPTI_ACTIVITY_KIND_KERNEL k join StringIds s on s.id=k.demangledName
            where s.value like '%LinearRgbToOpsinKernel<(bool)1>%' order by k.start'''):
        starts[stream].append(start)
    sums, widths = Counter(), Counter()
    for stream, bounds in starts.items():
        for start, end in zip(bounds, bounds[1:] + [2**63-1]):
            copies = list(db.execute('''select bytes from CUPTI_ACTIVITY_KIND_MEMCPY
                where streamId=? and start>=? and start<? and copyKind=2 order by start''',
                                    (stream, start, end)))
            sizes = [row[0] for row in copies]
            values, contexts, histogram = sizes[-3:]
            count_reads = sizes[-6:-3] if compact else sizes[-5:-3]
            if compact:
                assert count_reads[-1] == 8 and histogram % 8 == 0
            else:
                assert values == contexts * 2 and histogram == 760320
            tokens = contexts // 2
            assert values in (tokens, 2*tokens, 4*tokens)
            widths[values // tokens] += 1
            sums.update(tiles=1, values=values, contexts=contexts, histogram=histogram,
                        token_control=sum(count_reads), total_d2h=sum(sizes),
                        frame_and_decisions=sum(sizes)-sum(count_reads)-sum(sizes[-3:]))
    assert sums['tiles'] == 120
    return dict(totals=dict(sums), per_tile={k:v/sums['tiles'] for k,v in sums.items()
                                           if k != 'tiles'}, widths=dict(widths))


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('profiles', type=Path)
a = p.parse_args()
baseline = read(a.profiles / 'baseline-poc120.sqlite', False)
compact = read(a.profiles / 'candidate2.sqlite', True)
b, c = baseline['per_tile'], compact['per_tile']
saved = dict(
    resident_tables_h2d=396288+62976+47616+292,
    resident_tables_stream_syncs=20,
    compact_histograms_d2h=b['histogram']-c['histogram']-8,
    narrow_tokens_d2h=b['values']-c['values']-8,
    narrow_coefficients_d2h=b['frame_and_decisions']-c['frame_and_decisions'],
    batched_readbacks_stream_syncs=8,
    sync_removal_event_syncs=6+119/120,
    cpu_tokens_h2d=53826.8,
    cpu_tokens_d2h=b['values']+b['contexts']+b['histogram']+b['token_control'],
    cpu_tokens_d2d=3145728,
    cpu_tokens_syncs=5)
totals = baseline_totals(a.profiles / 'baseline-poc120.sqlite', baseline['totals']['tiles'])
assert totals['d2h_bytes'] == b['total_d2h']
defaults = totals.copy()
defaults['d2h_bytes'] -= saved['compact_histograms_d2h'] + saved['narrow_coefficients_d2h']
defaults['pcie_bytes'] = defaults['h2d_bytes'] + defaults['d2h_bytes']
defaults['kernels'] += 2  # One coefficient pack and one histogram compaction per tile.
print(json.dumps(dict(baseline=baseline, prior_gpu_candidate=compact,
                     standalone_savings_per_tile=saved,
                     baseline_device_input_per_tile=totals,
                     selected_defaults=dict(enabled=DEFAULT_ENABLED, per_tile=defaults,
                                            inventory_derived=True, newly_profiled=False),
                     notes=['Existing traces only; no new profile or timing run.',
                            'Each single token compaction flag adds an 8-byte header; both share it.',
                            'CPU tokens makes histogram and token-width flags inactive.',
                            'CPU tokens and sync removal overlap by two event waits.',
                            'Coefficient narrowing includes its 4-byte width readback.']), indent=2))
