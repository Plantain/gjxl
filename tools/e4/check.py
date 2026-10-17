#!/usr/bin/env python3
"""One bounded functional or sanitizer job, with explicit experiment flags."""
import argparse
import json
from pathlib import Path
import subprocess

from variants import TOGGLES, enabled_for_mask, environment


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('tool', choices=['release', 'asan', 'memcheck', 'initcheck', 'racecheck', 'synccheck'])
    p.add_argument('mask', type=int, choices=range(8))
    p.add_argument('section', choices=['dc', 'cfl', 'resident', 'backend', 'api', 'endurance'])
    p.add_argument('--reps', type=int, default=25,
                   help='Batches of 400 dev tiles for endurance only')
    a = p.parse_args()
    enabled = enabled_for_mask(a.mask)
    env = environment(enabled)
    build = Path('/w/e4/phase2/asan' if a.tool == 'asan' else '/w/e4/phase2/release')
    if a.tool == 'asan':
        env.update(ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:protect_shadow_gap=0',
                   UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    prefix = []
    if a.tool not in ('release', 'asan'):
        prefix = ['/usr/local/cuda/bin/compute-sanitizer', '--tool', a.tool, '--error-exitcode', '99']
        if a.tool == 'racecheck':
            prefix += ['--racecheck-num-workers', '4', '--force-synchronization-limit', '1']
        if a.tool == 'memcheck':
            prefix += ['--leak-check', 'full']
    if a.section == 'dc':
        args = ['gjxl_cuda_dc_processing_test'] + ([] if a.tool in ('release', 'asan') else ['--quick'])
    elif a.section == 'cfl':
        args = ['gjxl_cuda_final_cfl_test'] + ([] if a.tool in ('release', 'asan') else ['--sanitizer'])
    elif a.section == 'backend':
        args = ['gjxl_cuda_backend_test'] + ([] if a.tool in ('release', 'asan') else ['--sanitizer'])
    elif a.section == 'api':
        args = ['gjxl_c_api_test']
    elif a.section == 'endurance':
        if a.tool not in ('release', 'asan'):
            p.error('Endurance uses Release or ASan')
        if a.reps < 25:
            p.error('Endurance requires at least 10,000 encodes')
        args = ['gjxl_transfer_gate', 'endurance', '16', str(a.reps), '/w/corpus/dev']
    elif a.tool == 'racecheck':
        args = ['gjxl_transfer_gate', 'trace', '1', '1', '/w/corpus/poc120/ahi-022-001.rgb']
    elif a.tool in ('release', 'asan'):
        args = ['gjxl_transfer_gate', 'test', '2', '1']
    else:
        args = ['gjxl_transfer_gate', 'identity', '1', '1',
                f'/w/e4/phase2/sanitized/{a.tool}-{a.mask}', '/w/corpus/poc120/ahi-022-001.rgb']
    command = [*prefix, str(build / args[0]), *args[1:]]
    details = Path('/w/e4/phase2/results/details')
    details.mkdir(parents=True, exist_ok=True)
    log = details / f'{a.tool}-{a.mask}-{a.section}'
    with log.with_suffix('.stdout').open('w') as out, log.with_suffix('.stderr').open('w') as err:
        try:
            result = subprocess.run(command, env=env, stdout=out, stderr=err, timeout=235)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(command, 124)
    result.stdout = log.with_suffix('.stdout').read_text()
    result.stderr = log.with_suffix('.stderr').read_text()
    print(json.dumps(dict(tool=a.tool, mask=a.mask, section=a.section, command=command,
                          toggles={flag: env[flag] for flag in TOGGLES.values()},
                          exitcode=result.returncode, stdout=result.stdout, stderr=result.stderr)), flush=True)
    result.check_returncode()


if __name__ == '__main__':
    main()
