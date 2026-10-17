#!/usr/bin/env python3
"""Summarize Claude's ABBA JSONL; never launch encoders or change defaults."""
import collections
import json
from pathlib import Path
import sys


groups = collections.defaultdict(list)
binaries = {}
for path in map(Path, sys.argv[1:]):
    plan, rows_in_run = None, []
    def complete_run():
        if plan is None:
            return
        counts = collections.Counter((r['contexts'], r['abba_position']) for r in rows_in_run)
        expected = {(c, pos): plan['reps'] for c in plan['contexts'] for pos in range(4)}
        assert dict(counts) == expected, f'Incomplete invocation in {path}: {counts}'
    for line in path.read_text().splitlines():
        row = json.loads(line)
        if 'expected_seconds' in row and 'contexts' in row:
            complete_run()
            plan, rows_in_run = row, []
        if 'binaries' in row:
            for executable, digest in row['binaries'].items():
                assert binaries.setdefault(executable, digest) == digest, 'Mixed binary builds'
        if row.get('path') == 'device':
            assert plan is not None and plan.get('phase') == 'E4-phase4', 'Supply phase-4 logs with invocation metadata'
            assert row['corpus'] == plan['corpus'] and row['comparison'] == plan['comparison']
            assert row['base'] == plan['base'] and row.get('phase') == plan['phase']
            assert row['seconds'] > 0 and row['cpu_seconds'] > 0 and row['tiles'] > 0
            assert row['encoder_vram_bytes'] <= 2048 << 20
            rows_in_run.append(row)
            groups[(row['corpus'], row['comparison'], tuple(row['base']), row['contexts'], row['variant'])].append(row)
    complete_run()
assert groups, 'Supply one or more completed ABBA JSONL files'
rows = []
for (corpus, comparison, base, contexts, variant), samples in sorted(groups.items()):
    positions = {r['abba_position'] for r in samples}
    assert positions == ({0, 3} if variant == 'baseline' else {1, 2}), 'Incomplete ABBA'
    seconds = sum(r['seconds'] for r in samples)
    rows.append(dict(corpus=corpus, comparison=comparison, base=base, contexts=contexts, variant=variant,
                     tiles_per_second=sum(r['tiles'] for r in samples) / seconds,
                     busy_cpu_cores=sum(r['cpu_seconds'] for r in samples) / seconds,
                     cpu_ms_per_tile=1000 * sum(r['cpu_seconds'] for r in samples) / sum(r['tiles'] for r in samples),
                     peak_encoder_vram_bytes=max(r['encoder_vram_bytes'] for r in samples),
                     samples=len(samples)))
for row in rows:
    if row['variant'] != 'baseline':
        baseline = next(b for b in rows if b['variant'] == 'baseline' and
                        all(b[k] == row[k] for k in ('corpus', 'comparison', 'base', 'contexts')))
        row['paired_ratio'] = row['tiles_per_second'] / baseline['tiles_per_second']
        row['paired_cpu_reduction'] = baseline['cpu_ms_per_tile'] / row['cpu_ms_per_tile']
best = []
for corpus, comparison, base in sorted({(r['corpus'], r['comparison'], r['base']) for r in rows}):
    subset = [r for r in rows if r['corpus'] == corpus and r['comparison'] == comparison and r['base'] == base]
    baseline = next((r for r in subset if r['variant'] == 'baseline' and r['contexts'] == 12), None)
    candidates = [r for r in subset if r['variant'] != 'baseline']
    if baseline is None:
        best.append(dict(corpus=corpus, comparison=comparison, base=base,
                         reason='Need baseline at 12 contexts for this comparison'))
        continue
    for row in candidates:
        row['ratio_to_baseline_12'] = row['tiles_per_second'] / baseline['tiles_per_second']
        row['cpu_reduction_to_baseline_12'] = baseline['cpu_ms_per_tile'] / row['cpu_ms_per_tile']
    best.append(dict(corpus=corpus, comparison=comparison, base=base,
                     baseline_12=baseline, candidates=candidates))
print(json.dumps(dict(rows=rows, best=best, binaries=binaries, defaults_changed=False,
                      global_goal_evaluated=False,
                      note='Incremental comparison against current defaults plus --base; '
                           'not the original frozen-satellite performance gate.'), indent=2))
