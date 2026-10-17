#!/usr/bin/env python3
"""Collect E4 correctness gates; speed remains pending Claude's clean window."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root', type=Path)
    a = p.parse_args()
    results = a.root / 'results'
    for build in ('release', 'asan'):
        assert (results / f'release-build-{build}.exitcode').read_text().strip() == '0'
    def read(label):
        assert (results / (label + '.exitcode')).read_text().strip() == '0', label
        return json.loads((results / (label + '.jsonl')).read_text())
    identities = []
    for variant in (*map(str, range(8)), 'unset'):
        for corpus in ('poc120', 'dev'):
            result = read(f'identity-{variant}-{corpus}')
            assert result['passed'] and result['mismatches'] == 0
            assert result['files'] == (381 if corpus == 'poc120' else 1221)
            manifest = a.root / 'codestreams' / corpus / variant / 'identity.json'
            result['manifest_sha256'] = sha(manifest)
            identities.append(result)
    decodes = [read('decode-poc120-edges'), read('decode-dev')]
    assert sum(r['decoded'] for r in decodes) == 1581
    assert all(r['failed'] == 0 for r in decodes)
    checks = []
    for tool in ('asan', 'memcheck', 'initcheck'):
        for mask in range(8):
            for section in ('dc', 'backend', 'resident'):
                result = read(f'{tool}-{mask}-{section}')
                assert result['exitcode'] == 0
                logs = result['stdout'] + result['stderr']
                if tool == 'asan':
                    assert not result['stderr'], (tool, mask, section, result['stderr'])
                else:
                    assert 'ERROR SUMMARY: 0 errors' in logs
                checks.append(result)
    for tool in ('racecheck', 'synccheck'):
        for section in ('dc', 'resident'):
            result = read(f'{tool}-7-{section}')
            assert result['exitcode'] == 0
            logs = result['stdout'] + result['stderr']
            assert ('ERROR SUMMARY: 0 errors' in logs or
                    'RACECHECK SUMMARY: 0 hazards' in logs), result
            checks.append(result)
    asan_endurance = read('asan-endurance-7')
    assert asan_endurance['exitcode'] == 0 and not asan_endurance['stderr']
    asan_samples = [r for line in asan_endurance['stdout'].splitlines()
                    if (r := json.loads(line)).get('endurance')]
    assert len(asan_samples) == 25 and asan_samples[-1]['encodes'] == 10000
    assert all(r['identity'] for r in asan_samples)
    checks.append(asan_endurance)
    endurance = []
    for mask in range(8):
        batches = {3: 75, 6: 75, 7: 125}.get(mask, 25)
        extended = batches > 25
        suffix = '-extended50k' if mask == 7 else '-extended' if extended else ''
        label = f'endurance-accurate-{mask}' + suffix
        result = read(label)
        assert result['exitcode'] == 0 and not result['stderr']
        rows = [json.loads(line) for line in result['stdout'].splitlines()]
        samples = [row for row in rows if row.get('endurance')]
        assert len(samples) == batches
        assert samples[-1]['encodes'] == batches * 400
        assert all(r['identity'] for r in samples)
        # Extended runs compare two complete late 10,000-encode windows,
        # retaining all samples and the earlier short-run evidence.
        tail = samples[-25:] if extended else samples[12:]
        before = samples[-50:-25] if extended else samples[:12]
        keys = ('rss_bytes', 'encoder_vram_bytes', 'managed_live_bytes', 'malloc_live_bytes')
        spans = {key: dict(min=min(r[key] for r in tail), max=max(r[key] for r in tail),
                           range=max(r[key] for r in tail) - min(r[key] for r in tail),
                           first=tail[0][key], last=tail[-1][key]) for key in keys}
        peak = max(r['encoder_vram_bytes'] for r in samples)
        rss_range = max(r['rss_bytes'] for r in samples) - min(r['rss_bytes'] for r in samples)
        # Freed allocator pages may be returned to the OS and faulted back in.
        # Check for a growing RSS envelope, not for zero reclaim oscillation;
        # independently require constant owned/device memory and bounded live
        # malloc storage. Preserve the entire RSS range and every sample.
        rss_envelope_growth = (max(r['rss_bytes'] for r in tail) -
                               max(r['rss_bytes'] for r in before))
        assert peak <= 2048 << 20
        assert spans['encoder_vram_bytes']['range'] == 0
        assert spans['managed_live_bytes']['range'] == 0
        assert rss_envelope_growth <= 1 << 20
        assert spans['malloc_live_bytes']['range'] <= 256 << 10
        endurance.append(dict(mask=mask, encodes=samples[-1]['encodes'], identity=True,
                              peak_encoder_vram_bytes=peak, tail_from_encode=tail[0]['encodes'],
                              full_rss_range_bytes=rss_range, rss_source='smaps_rollup',
                              rss_envelope_growth_bytes=rss_envelope_growth,
                              tail_memory=spans, samples=samples))
    binaries = {name: sha(a.root / name) for name in (
        'release/gjxl_transfer_gate', 'release/libgjxl.so',
        'asan/gjxl_transfer_gate', 'asan/libgjxl.so',
        'release/gjxl_cuda_backend_test', 'asan/gjxl_cuda_backend_test')}
    holds = {str(f.relative_to(results)): int(f.read_text())
             for f in results.rglob('*.lock_seconds')}
    assert max(holds.values()) <= 300, holds
    output = dict(max_functional_lock_seconds=max(holds.values()), correctness_passed=True, throughput_gate_passed=None,
                  throughput_status='Pending Claude clean-window ABBA; worker did not measure throughput.',
                  phase='E4b', switches=['GJXL_E4_DC_PIPELINE', 'GJXL_E4_BLOCKING_WAITS',
                                        'GJXL_E4_BUTTERAUGLI_GRAPH'],
                  defaults='all off',
                  identities=identities, frozen_comparisons=sum(r['files'] for r in identities),
                  distinct_outputs_per_configuration=1581,
                  stock_decoded=sum(r['decoded'] for r in decodes),
                  sanitizer_executions=len(checks),
                  sanitizers=[{k: v for k, v in r.items() if k not in ('stdout', 'stderr')} for r in checks],
                  endurance=endurance, binaries=binaries)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
