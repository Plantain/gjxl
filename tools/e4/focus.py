#!/usr/bin/env python3
"""Focused final-default qualification; never run a throughput benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from variants import DEFAULT_ENABLED, TOGGLES, enabled_for_mask, environment


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def options(root):
    exe = root / 'release/gjxl_cuda_backend_test'
    cases = [('unset', environment(unset=True), 3)]
    # Test exact-string behavior, not truthiness or prefix parsing.
    for bit, flag in enumerate(TOGGLES.values()):
        for value in ('0', '1', '', '00', 'false', ' 0', '0 '):
            env = environment(unset=True)
            env[flag] = value
            enabled = value != '0' if bit in (0, 1) else value == '1'
            expected = (3 & ~(1 << bit)) | (int(enabled) << bit)
            cases.append((f'{flag}={value!r}', env, expected))
    for mask in range(8):
        cases.append((f'explicit-mask-{mask}', environment(enabled_for_mask(mask)), mask))
    rows = []
    for label, env, expected in cases:
        run = subprocess.run([str(exe), '--e4-options'], env=env, text=True,
                             capture_output=True, timeout=10, check=True)
        assert not run.stderr and int(run.stdout) == expected, (label, run)
        rows.append(dict(case=label, expected_mask=expected, actual_mask=int(run.stdout)))
    return dict(passed=True, cases=rows, processes=len(rows), gpu_encodes=0,
                binary_sha256=digest(exe))


def decode(root):
    decoder = Path('/w/wp0/libjxl/build/tools/djxl')
    paths = sorted((root / 'codestreams/poc120/unset/edges').rglob('*.jxl'))
    assert len(paths) == 21
    for corpus, count in [('poc120', 120), ('dev', 400)]:
        for preset in (0, 7, 8):
            files = sorted((root / f'codestreams/{corpus}/unset/identity/{preset}').glob('*.jxl'))
            assert len(files) == count
            paths += [files[i * (count - 1) // 7] for i in range(8)]
    rows = []
    with tempfile.TemporaryDirectory(prefix='e4-default-decode-') as directory:
        output = Path(directory) / 'decoded.ppm'
        for path in paths:
            output.unlink(missing_ok=True)
            subprocess.run([str(decoder), str(path), str(output), '--num_threads=1', '--quiet'],
                           capture_output=True, text=True, timeout=20, check=True)
            assert output.stat().st_size >= 512 * 512 * 3, path
            rows.append(dict(file=str(path.relative_to(root)), sha256=digest(path)))
    return dict(passed=True, stock_djxl=str(decoder), decoded=len(rows), failed=0,
                selection='All 21 edges plus 8 evenly spaced tiles/corpus/preset', files=rows)


def asan(root):
    env = environment(unset=True)
    env.update(ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:protect_shadow_gap=0',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    command = [str(root / 'asan/gjxl_transfer_gate'), 'test', '2', '1']
    run = subprocess.run(command, env=env, text=True, capture_output=True, timeout=235)
    result = dict(command=command, exitcode=run.returncode, stdout=run.stdout,
                  stderr=run.stderr, e4_environment='unset', passed=run.returncode == 0 and not run.stderr)
    print(json.dumps(result), flush=True)
    run.check_returncode()
    assert not run.stderr, run.stderr


def memory(root):
    command = [str(root / 'release/gjxl_transfer_gate'), 'endurance', '12', '25', '/w/corpus/dev']
    run = subprocess.run(command, env=environment(unset=True), text=True,
                         capture_output=True, timeout=235)
    # Preserve the raw output even if a plateau assertion in collect() fails.
    result = dict(command=command, exitcode=run.returncode, stdout=run.stdout,
                  stderr=run.stderr, contexts=12, e4_environment='unset')
    print(json.dumps(result), flush=True)
    run.check_returncode()
    assert not run.stderr, run.stderr


def memory_summary(result):
    assert result['exitcode'] == 0 and not result['stderr']
    assert result['contexts'] == 12 and result['e4_environment'] == 'unset'
    rows = [json.loads(line) for line in result['stdout'].splitlines()]
    assert [row['contexts'] for row in rows if 'create_seconds' in row] == [12]
    samples = [row for row in rows if row.get('endurance')]
    assert [r['encodes'] for r in samples] == list(range(400, 10001, 400))
    assert all(r['identity'] for r in samples)
    tail, before = samples[12:], samples[:12]
    keys = ('rss_bytes', 'encoder_vram_bytes', 'managed_live_bytes', 'malloc_live_bytes')
    spans = {key: dict(min=min(r[key] for r in tail), max=max(r[key] for r in tail),
                       range=max(r[key] for r in tail) - min(r[key] for r in tail),
                       first=tail[0][key], last=tail[-1][key]) for key in keys}
    peak = max(r['encoder_vram_bytes'] for r in samples)
    rss_range = max(r['rss_bytes'] for r in samples) - min(r['rss_bytes'] for r in samples)
    # Retain the phase-2 plateau criteria: stable device/managed allocations,
    # bounded live malloc storage, and no growing RSS upper envelope.
    rss_envelope_growth = max(r['rss_bytes'] for r in tail) - max(r['rss_bytes'] for r in before)
    assert peak <= 2048 << 20
    assert spans['encoder_vram_bytes']['range'] == 0
    assert spans['managed_live_bytes']['range'] == 0
    assert spans['malloc_live_bytes']['range'] <= 256 << 10
    assert rss_envelope_growth <= 1 << 20
    return dict(passed=True, contexts=12, encodes=10000, warmup_encodes=800, identity=True,
                peak_encoder_vram_bytes=peak, tail_from_encode=tail[0]['encodes'],
                full_rss_range_bytes=rss_range, rss_source='smaps_rollup',
                rss_envelope_growth_bytes=rss_envelope_growth, tail_memory=spans, samples=samples)


def collect(root):
    results = root / 'results'
    def read(name):
        assert (results / (name + '.exitcode')).read_text().strip() == '0', name
        return json.loads((results / (name + '.jsonl')).read_text())
    for kind in ('release', 'asan'):
        assert (results / f'release-build-{kind}.exitcode').read_text().strip() == '0'
    parsing = read('defaults-options')
    assert parsing['passed'] and parsing['processes'] == 30
    identity = [read('defaults-' + corpus) for corpus in ('poc120', 'dev')]
    for item, count in zip(identity, (381, 1221)):
        assert item['passed'] and item['mismatches'] == 0 and item['files'] == count
        assert item['enabled'] == list(DEFAULT_ENABLED)
        assert all(v is None for v in item['toggles'].values())
    decoded, sanitized = read('defaults-decode'), read('defaults-asan')
    assert decoded['passed'] and decoded['decoded'] == 69 and decoded['failed'] == 0
    assert sanitized['passed'] and sanitized['exitcode'] == 0 and not sanitized['stderr']
    coverage = [json.loads(s) for s in sanitized['stdout'].splitlines()]
    presets = [r for r in coverage if 'preset' in r]
    assert {r['preset'] for r in presets} == {0, 7, 8}
    assert all(r['identity'] and r['tiles'] == 7 and r['device_layouts'] == 4 for r in presets)
    endurance = memory_summary(read('defaults-memory'))
    holds = {f.stem: int(f.read_text()) for f in results.glob('*.lock_seconds')}
    assert max(holds.values()) <= 300
    return dict(phase='E4-phase4', focused_gate_passed=True,
                default_enabled=DEFAULT_ENABLED, option_processes=parsing['processes'],
                frozen_comparisons=sum(r['files'] for r in identity), identities=identity,
                stock_decoded=decoded['decoded'], asan_executions=1,
                memory_executions=1, memory=endurance,
                asan_coverage=coverage, max_functional_lock_seconds=max(holds.values()),
                binaries={name: digest(root / name) for name in (
                    'release/gjxl_transfer_gate', 'release/libgjxl.so',
                    'release/gjxl_cuda_backend_test', 'asan/gjxl_transfer_gate', 'asan/libgjxl.so')},
                full_matrix='Not repeated; phase-2 full matrix remains valid for these paths.',
                performance_status='Original performance goal not reached. Final defaults follow '
                                   'Claude\'s phase-2/phase-3 clean decisions; no more windows requested.',
                clean_results=['results/E4/phase2/clean-window.md', 'results/E4/phase3/clean-window.md'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('section', choices=['options', 'decode', 'asan', 'memory', 'collect'])
    p.add_argument('--root', type=Path, default=Path('/w/e4/phase4'))
    a = p.parse_args()
    result = globals()[a.section](a.root)
    if result is not None:
        print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
