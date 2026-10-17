#!/usr/bin/env python3
"""Claude's clean-window ABBA harness. Run on sat-5090; takes its own lock."""
import argparse
import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

from variants import DEFAULT_ENABLED, TOGGLES, environment

RUN_BUDGET_SECONDS = 70
CLEANUP_SECONDS = 5
COMPARISONS = ('dc-pipeline', 'butteraugli-graph', 'all-on', 'spinning-waits')


def arms(a):
    baseline = set(DEFAULT_ENABLED) | set(a.base)
    candidate = set(baseline)
    if a.comparison == 'spinning-waits':
        if 'blocking-waits' in a.base:
            raise ValueError('spinning-waits conflicts with --base blocking-waits')
        candidate.discard('blocking-waits')
    else:
        candidate.update(TOGGLES if a.comparison == 'all-on' else [a.comparison])
    if baseline == candidate:
        raise ValueError('Comparison does not change any switch relative to the base')
    return tuple(name for name in TOGGLES if name in baseline), tuple(
        name for name in TOGGLES if name in candidate)


def expected_seconds(a):
    # Conservative planning allowance from Claude's phase-1 windows: 800 tiles/s,
    # two warmup batches per process, per-lane creation and process overhead.
    # This is not a prediction of candidate speed. The deadline is independent.
    tiles = 120 if a.corpus == 'poc120' else 400
    return 3 + 4 * sum(0.15*c + 0.4 + tiles*(a.reps + 2)/800 for c in a.contexts)


def commands(a, corpus):
    baseline, candidate = arms(a)
    for contexts in a.contexts:
        for position, variant in enumerate(('baseline', a.comparison, a.comparison, 'baseline')):
            env = environment(baseline if variant == 'baseline' else candidate)
            command = [a.executable, 'devicebench', str(contexts), str(a.reps), '/w/corpus/' + corpus]
            metadata = dict(corpus=corpus, contexts=contexts, comparison=a.comparison,
                            base=baseline, phase='E4-phase4', variant=variant,
                            abba_position=position,
                            toggles={k: v for k, v in env.items()
                                     if k.startswith(('GJXL_E3_', 'GJXL_E4_'))})
            yield command, env, metadata


def worker(a):
    if not a.dry_run:
        print(json.dumps(dict(binaries={a.executable: hashlib.sha256(
            Path(a.executable).read_bytes()).hexdigest()})), flush=True)
    totals = {}
    deadline = time.monotonic() + 65
    for corpus in [a.corpus]:
        for command, env, metadata in commands(a, corpus):
            if a.dry_run:
                print(json.dumps(dict(command=command, **metadata)), flush=True)
                continue
            run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=max(0.01, deadline - time.monotonic()))
            if run.stderr:
                print(run.stderr, file=sys.stderr, end='')
            run.check_returncode()
            count = 0
            for line in run.stdout.splitlines():
                row = json.loads(line)
                if row.get('path') == 'device':
                    count += 1
                    row['busy_cpu_cores'] = row['cpu_seconds'] / row['seconds']
                    row['cpu_ms_per_tile'] = 1000 * row['cpu_seconds'] / row['tiles']
                    expected = totals.setdefault(corpus, row['bytes'])
                    if row['bytes'] != expected or row['encoder_vram_bytes'] > 2048 << 20:
                        raise RuntimeError('ABBA bytes/memory invariant failed')
                row.update(metadata)
                print(json.dumps(row), flush=True)
            if count != a.reps:
                raise RuntimeError('Incomplete ABBA measurement')


def host(a):
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    a.out.mkdir(parents=True, exist_ok=True)
    for corpus in [a.corpus]:
        base, _ = arms(a)
        label = f'e4d-abba-{stamp}-{corpus}-{a.comparison}-base-' + '-'.join(base)
        prefix = a.out / label
        # No encoder process exists while waiting for the lock. close_fds and
        # Python's non-inheritable descriptors keep it out of every child.
        with open(a.lock, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            begin = time.monotonic()
            free = int(subprocess.check_output(
                ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                text=True, timeout=5).splitlines()[0])
            if free < 6144:
                raise RuntimeError(f'GPU launch deferred: {free} MiB free')
            command = ['docker', 'run', '--rm', '--name', label, '--pid=host', '--cpus=16',
                       '--gpus', 'device=0', '-v', '/root/jxl-hybrid:/w',
                       '--entrypoint', 'python3', 'satellite-cujpegxl-build:cuda12.8',
                       '/w/e4/gjxl/tools/e4/bracket.py', '--worker',
                       '--comparison', a.comparison, '--corpus', corpus,
                       '--contexts', *map(str, a.contexts),
                       '--reps', str(a.reps), '--executable', a.executable]
            if a.base:
                command += ['--base', *a.base]
            result = None
            try:
                with prefix.with_suffix('.jsonl').open('w') as out, prefix.with_suffix('.stderr').open('w') as err:
                    result = subprocess.run(command, stdout=out, stderr=err, close_fds=True,
                                            timeout=max(0.01, RUN_BUDGET_SECONDS - (time.monotonic() - begin)))
                    result.check_returncode()
            finally:
                cleanup_error = None
                try:
                    cleanup = subprocess.run(['docker', 'rm', '-f', label],
                                             capture_output=True, timeout=CLEANUP_SECONDS)
                    if cleanup.returncode != 0 and result is None:
                        cleanup_error = cleanup.stderr.decode(errors='replace')
                except subprocess.TimeoutExpired:
                    cleanup_error = 'Container removal timed out; inspect ' + label
                held = time.monotonic() - begin
                fcntl.flock(lock, fcntl.LOCK_UN)
                prefix.with_suffix('.meta.json').write_text(json.dumps(dict(
                    command=command, lock=a.lock, lock_seconds=held, free_mib=free,
                    exitcode=None if result is None else result.returncode,
                    expected_seconds=expected_seconds(a), hard_limit_seconds=80,
                    cleanup_error=cleanup_error), indent=2) + '\n')
            if cleanup_error is not None:
                raise RuntimeError(cleanup_error)
            print(json.dumps(dict(corpus=corpus, evidence=str(prefix), lock_seconds=held)), flush=True)


def main():
    # Let finally remove our container and release the lock on TERM as well
    # as Ctrl-C. The clean-window controller must not take the lock itself.
    signal.signal(signal.SIGTERM, lambda signum, frame: sys.exit(128 + signum))
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--comparison', required=True, choices=COMPARISONS,
                   help='Add to current defaults, or explicitly compare old spinning waits')
    p.add_argument('--base', nargs='+', choices=TOGGLES, default=[],
                   help='Additional switches enabled in both arms; DC pipelining and blocking waits default on')
    p.add_argument('--corpus', required=True, choices=['poc120', 'dev'])
    p.add_argument('--contexts', nargs='+', type=int, default=[8, 12, 16])
    p.add_argument('--reps', type=int, default=5)
    p.add_argument('--executable', default='/w/e4/phase4/release/gjxl_transfer_gate',
                   help='Same updated binary in both arms, including the baseline')
    p.add_argument('--out', type=Path, default=Path('/root/jxl-hybrid/e4/phase4/results'))
    p.add_argument('--lock', default='/root/jxl-hybrid/locks/timing.lock')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    a = p.parse_args()
    if a.reps < 1 or any(c < 1 or c > 16 for c in a.contexts):
        p.error('Positive reps and 1..16 contexts required')
    if len(set(a.contexts)) != len(a.contexts):
        p.error('Duplicate contexts are not allowed')
    if len(set(a.base)) != len(a.base):
        p.error('Duplicate base switches are not allowed')
    try:
        base, _ = arms(a)
    except ValueError as error:
        p.error(str(error))
    expected = expected_seconds(a)
    if expected > 70:
        p.error(f'Expected {expected:.1f}s exceeds 70s run budget; split contexts or reduce reps')
    print(json.dumps(dict(expected_seconds=round(expected, 1), hard_lock_limit_seconds=80,
                          comparison=a.comparison, corpus=a.corpus,
                          contexts=a.contexts, reps=a.reps, base=base,
                          phase='E4-phase4')), flush=True)
    worker(a) if a.worker or a.dry_run else host(a)


if __name__ == '__main__':
    main()
