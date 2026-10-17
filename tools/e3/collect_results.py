#!/usr/bin/env python3
"""Check E3 evidence and emit the aggregate gate. Raw captures stay remote."""
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])


def read(name):
    return json.loads((root / name).read_text())


def rows(name):
    return [json.loads(line) for line in (root / f'{name}.jsonl').read_text().splitlines()
            if line.strip()]


labels = ['baseline-identity', 'baseline-edges', 'final-identity', 'final-edges',
          'conformance-corpus', 'conformance-edges', 'regression', 'asan-final',
          'endurance', 'bracket-poc120', 'bracket-dev',
          'trace-baseline-poc120', 'trace-final-poc120',
          'memcheck-provider', 'memcheck-resident',
          'initcheck-provider', 'initcheck-resident']
labels += [f'bracket-confirm-{corpus}-{block}'
           for corpus in ('poc120', 'dev') for block in range(3)]
labels += ['endurance-heap', 'asan-endurance']
exit_codes = {label: int((root / f'{label}.exitcode').read_text()) for label in labels}
identity = [read(f'final-{name}-identity.json') for name in ('byte', 'edge')]
decoded = [read(f'conformance-{name}.jsonl') for name in ('corpus', 'edges')]
profiles = {variant: read(f'profile-{variant}-poc120.json')
            for variant in ('baseline', 'final')}
before, after = profiles['baseline'], profiles['final']
pci_bytes = {name: sum(p['copies'][direction]['bytes_per_tile']
                       for direction in ('h2d', 'd2h'))
             for name, p in profiles.items()}
reductions = {'pcie_bytes': pci_bytes['baseline'] / pci_bytes['final'],
              'synchronizations': before['syncs_per_tile'] / after['syncs_per_tile']}

timing = {}
memory_samples = []
contexts = []
for corpus in ('poc120', 'dev'):
    run_labels = [f'bracket-{corpus}'] + [f'bracket-confirm-{corpus}-{b}' for b in range(3)]
    samples = [dict(r, run_label=label) for label in run_labels for r in rows(label)]
    contexts.extend(r['contexts'] for r in samples if 'contexts' in r)
    measured = [r for r in samples if 'tiles' in r]
    memory_samples.extend(measured)
    variants = {}
    for variant in ('baseline', 'candidate'):
        subset = [r for r in measured if r['variant'] == variant]
        tiles = sum(r['tiles'] for r in subset)
        seconds = sum(r['seconds'] for r in subset)
        for label in run_labels:
            expected = 48 if label == run_labels[0] else (80 if corpus == 'poc120' else 24)
            assert sum(r['run_label'] == label for r in subset) == expected
        assert len({r['bytes'] for r in subset}) == 1
        variants[variant] = {
            'tiles': tiles, 'seconds': seconds, 'tiles_per_second': tiles / seconds,
            'cpu_busy_cores': sum(r['cpu_seconds'] for r in subset) / seconds,
            'encoder_peak_vram_bytes': max(r['encoder_vram_bytes'] for r in subset),
            'bytes_per_batch': subset[0]['bytes'],
            'runs': {label: {
                'tiles': sum(r['tiles'] for r in subset if r['run_label'] == label),
                'seconds': sum(r['seconds'] for r in subset if r['run_label'] == label),
            } for label in run_labels},
        }
    assert variants['baseline']['bytes_per_batch'] == variants['candidate']['bytes_per_batch']
    variants['speedup'] = (variants['candidate']['tiles_per_second'] /
                           variants['baseline']['tiles_per_second'])
    timing[corpus] = variants

endurance_rows = rows('endurance')
contexts.extend(r['contexts'] for r in endurance_rows if 'contexts' in r)
endurance = [r for r in endurance_rows if 'encodes' in r]
memory_samples.extend(endurance)
tail = endurance[len(endurance) // 2:]
diagnostic_rows = rows('endurance-heap')
diagnostic = [r for r in diagnostic_rows if 'path' in r]
heap = [r for r in diagnostic_rows if r.get('heap_sample')]
heap_tail = heap[len(heap) // 2:]
asan_endurance = [r for r in rows('asan-endurance') if 'path' in r]
memory_samples.extend(diagnostic + asan_endurance)
peak_vram = max(r['encoder_vram_bytes'] for r in memory_samples)
cuda_sanitizers = {}
for label in labels:
    if label.startswith(('memcheck-', 'initcheck-')):
        log = (root / f'{label}.stderr').read_text() + (root / f'{label}.jsonl').read_text()
        counts = [int(n) for n in re.findall(r'ERROR SUMMARY: (\d+) errors', log)]
        cuda_sanitizers[label] = bool(counts) and all(n == 0 for n in counts)
        if label.startswith('memcheck-'):
            leaks = re.findall(r'LEAK SUMMARY: (\d+) bytes leaked in (\d+) allocations', log)
            cuda_sanitizers[label] &= bool(leaks) and all(
                int(size) == 0 and int(count) == 0 for size, count in leaks)

gates = {
    'commands_succeeded': all(code == 0 for code in exit_codes.values()),
    'byte_identity': [r['files'] for r in identity] == [1560, 21]
                     and all(r['mismatches'] == 0 for r in identity),
    'stock_decode': [r['decoded'] for r in decoded] == [1560, 21]
                    and all(r['failed'] == 0 for r in decoded),
    'fourfold_transfer_reduction': reductions['pcie_bytes'] >= 4,
    'fourfold_sync_reduction': reductions['synchronizations'] >= 4,
    'zero_rgb_h2d': after['rgb_h2d_bytes'] == 0,
    'no_steady_device_allocations': not after['steady_state_allocation_or_creation_apis'],
    'throughput_at_least_e1': all(r['speedup'] >= 1 for r in timing.values()),
    'worker_cap': bool(contexts) and max(contexts) <= 16,
    'vram_cap': peak_vram <= 2048 * 1024 * 1024,
    'asan_ubsan': exit_codes['asan-final'] == 0
                  and not (root / 'asan-final.stderr').read_text()
                  and exit_codes['asan-endurance'] == 0
                  and not (root / 'asan-endurance.stderr').read_text(),
    'cuda_sanitizers': all(cuda_sanitizers.values()),
    'endurance': endurance[-1]['encodes'] == 10000
                 and len({r['bytes'] for r in endurance}) == 1
                 and len({r['vram_bytes'] for r in endurance}) == 1
                 and diagnostic[-1]['encodes'] == 20000
                 and len({r['bytes'] for r in diagnostic}) == 1
                 and len({r['vram_bytes'] for r in diagnostic}) == 1
                 and len(heap) == 50
                 and len({r['managed_live_bytes'] for r in heap}) == 1
                 and len({r['managed_idle_bytes'] for r in heap}) == 1
                 and asan_endurance[-1]['encodes'] == 10000
                 and len({r['bytes'] for r in asan_endurance}) == 1,
}
for comparison, decode in zip(identity, decoded):
    assert {r['file']: r['candidate_sha256'] for r in comparison['codestreams']} == {
        r['file']: r['sha256'] for r in decode['files']}

result = {
    'work_package': 'E3', 'passed': all(gates.values()), 'gates': gates,
    'baseline_commit': 'c3c82fbb71adff6e3565c4d98f1e44fee5f6b15b',
    'identity_codestreams': sum(r['files'] for r in identity),
    'decoded_codestreams': sum(r['decoded'] for r in decoded),
    'profile': profiles, 'reductions': reductions,
    'timing': timing,
    'timing_note': 'Matched Release encoder code, 12 contexts. Includes every sample from '
                   'the initial three short ABBA blocks plus three longer confirmation blocks; '
                   'each confirmation block holds the lock separately. No E3 builds active. '
                   'This worker issued no operational service controls. '
                   'Claude confirms absolute rates in a clean window.',
    'encoder_peak_vram_bytes': peak_vram,
    'max_encoder_workers': max(contexts),
    'endurance_encodes': endurance[-1]['encodes'],
    'endurance_warmup_encodes': 800,
    'endurance_final_rss_bytes': tail[-1]['rss_bytes'],
    'endurance_tail_rss_growth_bytes': max(r['rss_bytes'] for r in tail) - min(r['rss_bytes'] for r in tail),
    'endurance_vram_bytes': sorted({r['vram_bytes'] for r in endurance}),
    'endurance_memory_diagnostic': {
        'encodes': diagnostic[-1]['encodes'],
        'managed_live_bytes': sorted({r['managed_live_bytes'] for r in heap}),
        'managed_idle_bytes': sorted({r['managed_idle_bytes'] for r in heap}),
        'malloc_live_tail_range_bytes': [min(r['malloc_live_bytes'] for r in heap_tail),
                                        max(r['malloc_live_bytes'] for r in heap_tail)],
        'malloc_free_tail_range_bytes': [min(r['malloc_free_bytes'] for r in heap_tail),
                                        max(r['malloc_free_bytes'] for r in heap_tail)],
        'rss_tail_range_bytes': [min(r['rss_bytes'] for r in heap_tail),
                                 max(r['rss_bytes'] for r in heap_tail)],
        'asan_ubsan_leak_checked_encodes': asan_endurance[-1]['encodes'],
        'note': 'RSS includes malloc retained free pages. Leak gate uses constant live '
                'managed ownership across 20000 encodes, flat VRAM, and a separate '
                '10000-encode ASan/UBSan run with leak detection enabled.',
    },
    'cuda_sanitizers': cuda_sanitizers, 'exit_codes': exit_codes,
    'raw_evidence_remote': 'root@sat-5090:/root/jxl-hybrid/e3/',
}
print(json.dumps(result, indent=2))
sys.exit(0 if result['passed'] else 1)
