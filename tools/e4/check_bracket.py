#!/usr/bin/env python3
"""Exercise ABBA environment isolation and deadlines without real encoding."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

import bracket
from variants import DEFAULT_ENABLED, TOGGLES, e3, environment


def main():
    with tempfile.TemporaryDirectory(prefix='e4d-abba-') as temp:
        root = Path(temp)
        exe = root / 'fake_gate'
        exe.write_text('''#!/usr/bin/env python3
import json, os, sys
assert not any(k.startswith('GJXL_E4_UNKNOWN') for k in os.environ)
assert not any(k in os.environ for k in ('GJXL_GPU_TOKENIZATION', 'GJXL_EXPERIMENT_GPU_TOKENS', 'GJXL_EXPERIMENT_CUDA_GPU_TOKENS', 'GJXL_E4_CFL_WARP'))
assert os.environ['GJXL_E3_COMPACT_HISTOGRAMS'] == '1'
assert os.environ['GJXL_E3_NARROW_COEFFICIENTS'] == '1'
assert os.environ['GJXL_E3_SYNC_REMOVAL'] == '0'
for repetition in range(int(sys.argv[3])):
 print(json.dumps(dict(path='device', bytes=123, tiles=120, seconds=1, cpu_seconds=1,
  encoder_vram_bytes=1000, actual={k:v for k,v in os.environ.items() if k.startswith('GJXL_E4_')})))
''')
        exe.chmod(0o755)
        env = dict(os.environ, GJXL_E4_UNKNOWN='1', GJXL_E4_DC_PIPELINE='1',
                   GJXL_E4_CFL_WARP='1', GJXL_E4_BLOCKING_WAITS='0',
                   GJXL_E4_BUTTERAUGLI_GRAPH='1', GJXL_E3_SYNC_REMOVAL='1',
                   GJXL_E3_COMPACT_HISTOGRAMS='0', GJXL_EXPERIMENT_CUDA_GPU_TOKENS='0')
        all_rows, outputs = [], []
        with patch.dict(os.environ, env):
            assert environment()['GJXL_E4_BLOCKING_WAITS'] == '1'
            assert environment()['GJXL_E4_DC_PIPELINE'] == '1'
            assert environment([])['GJXL_E4_BLOCKING_WAITS'] == '0'
            assert environment([])['GJXL_E4_DC_PIPELINE'] == '0'
            assert not any(k.startswith('GJXL_E4_') for k in environment(unset=True))
            assert e3.environment()['GJXL_E4_BLOCKING_WAITS'] == '1'
            assert e3.environment(blocking_waits=False)['GJXL_E4_BLOCKING_WAITS'] == '0'
            assert e3.environment()['GJXL_E4_DC_PIPELINE'] == '1'
            old = e3.environment(blocking_waits=False, dc_pipeline=False)
            assert old['GJXL_E4_BLOCKING_WAITS'] == old['GJXL_E4_DC_PIPELINE'] == '0'
            assert e3.environment()['GJXL_E4_BUTTERAUGLI_GRAPH'] == '0'
        cases = [('butteraugli-graph', []),
                 ('butteraugli-graph', ['blocking-waits']),
                 ('all-on', ['blocking-waits']), ('spinning-waits', []),
                 ('butteraugli-graph', ['dc-pipeline', 'blocking-waits'])]
        for corpus in ('poc120', 'dev'):
            for comparison, base in cases:
                run = subprocess.run([sys.executable, str(Path(bracket.__file__)),
                                      '--comparison', comparison, '--corpus', corpus,
                                      '--worker', '--contexts', '8', '12', '16',
                                      '--reps', '2', '--executable', str(exe),
                                      *(['--base', *base] if base else [])],
                                     env=env, capture_output=True, text=True, check=True)
                outputs.append(run.stdout)
                all_rows += [r for line in run.stdout.splitlines() if (r := json.loads(line)).get('path')]
        assert len(all_rows) == 2 * len(cases) * 3 * 4 * 2
        for row in all_rows:
            expected = {flag: row['toggles'][flag] for flag in TOGGLES.values()}
            assert row['actual'] == expected
            assert (row['abba_position'] in (0, 3)) == (row['variant'] == 'baseline')
            enabled = set(row['base'])
            assert set(DEFAULT_ENABLED) <= enabled
            if row['variant'] == 'spinning-waits':
                enabled.remove('blocking-waits')
            elif row['variant'] != 'baseline':
                enabled.update(TOGGLES if row['variant'] == 'all-on' else [row['variant']])
            assert row['actual'] == {flag: '1' if name in enabled else '0'
                                     for name, flag in TOGGLES.items()}
        evidence = root / 'fake.jsonl'
        evidence.write_text(''.join(outputs))
        summary = subprocess.run([sys.executable,
                                  str(Path(__file__).with_name('summarize_bracket.py')),
                                  str(evidence)], capture_output=True, text=True, check=True)
        best = json.loads(summary.stdout)['best']
        assert len(best) == 6
        assert not json.loads(summary.stdout)['global_goal_evaluated']
        assert all(c['ratio_to_baseline_12'] == 1 for r in best for c in r['candidates'])
        # Report incremental ratios without applying the old frozen-baseline
        # goal, and reject incomplete/mixed-base evidence.
        raw = [json.loads(line) for line in ''.join(outputs).splitlines()]
        summarize = [sys.executable, str(Path(__file__).with_name('summarize_bracket.py')), str(evidence)]
        for seconds in (0.6, 1.0, 1.1):
            altered = []
            for original in raw:
                row = dict(original)
                if row.get('path') == 'device' and row['variant'] != 'baseline':
                    row.update(seconds=seconds, cpu_seconds=0.4)
                altered.append(row)
            evidence.write_text(''.join(json.dumps(r) + '\n' for r in altered))
            result = json.loads(subprocess.check_output(summarize, text=True))
            assert not result['global_goal_evaluated']
            assert all(abs(c['paired_ratio'] - 1 / seconds) < 1e-9 and
                       abs(c['paired_cpu_reduction'] - 2.5) < 1e-9
                       for r in result['best'] for c in r['candidates'])
        evidence.write_text(''.join(json.dumps(r) + '\n' for r in raw[:-1]))
        assert subprocess.run(summarize, capture_output=True).returncode != 0
        changed = [dict(r) for r in raw]
        next(r for r in changed if r.get('path') == 'device')['base'] = []
        evidence.write_text(''.join(json.dumps(r) + '\n' for r in changed))
        assert subprocess.run(summarize, capture_output=True).returncode != 0
        for comparison, base in [('spinning-waits', ['blocking-waits']),
                                 ('dc-pipeline', ['dc-pipeline']),
                                 ('dc-pipeline', ['blocking-waits']),
                                 ('butteraugli-graph', ['butteraugli-graph'])]:
            invalid = subprocess.run([sys.executable, str(Path(bracket.__file__)),
                                      '--comparison', comparison, '--base', *base,
                                      '--corpus', 'poc120', '--dry-run'], capture_output=True)
            assert invalid.returncode != 0
        # Too-long windows must fail before starting a worker/container.
        invalid = subprocess.run([sys.executable, str(Path(bracket.__file__)),
                                  '--comparison', 'all-on', '--corpus', 'dev', '--reps', '999',
                                  '--worker', '--executable', str(exe)], capture_output=True)
        assert invalid.returncode == 2 and b'exceeds 70s' in invalid.stderr
        a = SimpleNamespace(corpus='poc120', contexts=[12], reps=1, comparison='all-on',
                            base=['blocking-waits'], executable=str(exe), out=root, lock=str(root / 'lock'))
        cleanup = []
        for fail in (False, True):
            def fake_run(command, **kwargs):
                if command[:3] == ['docker', 'rm', '-f']:
                    cleanup.append(command)
                    assert kwargs['timeout'] == 5
                else:
                    assert command[-2:] == ['--base', 'blocking-waits']
                    assert 0 < kwargs['timeout'] <= 70
                    assert kwargs['close_fds']
                    if fail:
                        raise subprocess.TimeoutExpired(command, kwargs['timeout'])
                return subprocess.CompletedProcess(command, 0)
            with patch.object(bracket.subprocess, 'check_output', return_value='8192\n'), \
                    patch.object(bracket.subprocess, 'run', side_effect=fake_run):
                try:
                    bracket.host(a)
                    assert not fail
                except subprocess.TimeoutExpired:
                    assert fail
            with open(a.lock, 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(lock, fcntl.LOCK_UN)
        assert len(cleanup) == 2
        # Real deadline expiration using fake host commands (no container/GPU).
        fakebin = root / 'bin'
        fakebin.mkdir()
        for name, body in {
            'nvidia-smi': "print('8192')",
            'docker': "import sys, time\nif sys.argv[1] == 'run': time.sleep(5)",
        }.items():
            path = fakebin / name
            path.write_text('#!' + sys.executable + '\n' + body + '\n')
            path.chmod(0o755)
        start = time.monotonic()
        with patch.dict(os.environ, PATH=str(fakebin) + os.pathsep + os.environ['PATH']), \
                patch.object(bracket, 'RUN_BUDGET_SECONDS', 0.2), \
                patch.object(bracket, 'CLEANUP_SECONDS', 0.1):
            try:
                bracket.host(a)
                assert False, 'Deadline did not expire'
            except subprocess.TimeoutExpired:
                pass
        assert time.monotonic() - start < 1.0
        with open(a.lock, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
    print(json.dumps(dict(passed=True, fake_processes=2 * len(cases) * 3 * 4,
                          comparisons=2 * len(cases) * 3,
                          measured_rows=len(all_rows), cleanup_paths=3, real_deadline_test=True, real_encodes=0)))


if __name__ == '__main__':
    main()
