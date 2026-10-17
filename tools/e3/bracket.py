#!/usr/bin/env python3
"""Short process brackets. Claude runs under run_locked.sh in a clean window."""
import argparse
import json
import os
import subprocess
import sys

from variants import TOGGLES, environment


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('corpus')
    p.add_argument('reps', type=int, nargs='?', default=8)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--token-choice', action='store_true')
    mode.add_argument('--variants', action='store_true',
                      help='Same binary: all off vs each single flag and all on, ABBA per comparison')
    p.add_argument('--blocks', type=int)
    p.add_argument('--block-start', type=int, default=0)
    p.add_argument('--only', choices=[*TOGGLES, 'all-on'],
                   help='One comparison within --variants, for shorter lock holds')
    p.add_argument('--executable', default='/w/e3/toggles/gjxl_transfer_gate',
                   help='Single executable for --variants')
    p.add_argument('--dry-run', action='store_true', help='Print commands; do not encode or time')
    a = p.parse_args()
    blocks = a.blocks if a.blocks is not None else (1 if a.variants else 2 if a.token_choice else 3)
    if a.reps <= 0 or not 1 <= blocks <= 3 or a.block_start < 0:
        p.error('reps must be positive, blocks 1..3 and block-start nonnegative')
    if a.only and not a.variants:
        p.error('--only requires --variants')
    comparisons = ([a.only] if a.only else [*TOGGLES, 'all-on']) if a.variants else [None]
    for block in range(a.block_start, a.block_start + blocks):
        for comparison in comparisons:
            order = (('baseline', comparison, comparison, 'baseline') if a.variants else
                     ('baseline', 'candidate-cpu', 'candidate-gpu', 'candidate-gpu',
                      'candidate-cpu', 'baseline') if a.token_choice else
                     ('baseline', 'candidate', 'candidate', 'baseline'))
            for position, variant in enumerate(order):
                if a.variants:
                    exe = a.executable
                    enabled = list(TOGGLES) if variant == 'all-on' else [variant]
                    env = environment(enabled)
                else:
                    exe = ('/w/e3/baseline/gjxl_transfer_gate' if variant == 'baseline'
                           else '/w/e3/gjxl/build/e3/gjxl_transfer_gate')
                    env = os.environ.copy()
                    if a.token_choice and variant != 'baseline':
                        env['GJXL_EXPERIMENT_CUDA_GPU_TOKENS'] = '0' if variant.endswith('cpu') else '1'
                command = [exe, 'devicebench', '12', str(a.reps), a.corpus]
                metadata = dict(variant=variant, block=block, corpus=a.corpus)
                if a.variants:
                    metadata.update(comparison=comparison, abba_position=position,
                                    toggles={flag: env[flag] for flag in TOGGLES.values()})
                if a.dry_run:
                    print(json.dumps(dict(command=command, **metadata)), flush=True)
                    continue
                result = subprocess.run(command, env=env, capture_output=True, text=True)
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end='')
                result.check_returncode()
                for line in result.stdout.splitlines():
                    row = json.loads(line)
                    row.update(metadata)
                    print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
