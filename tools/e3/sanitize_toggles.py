#!/usr/bin/env python3
"""Sanitize independently selectable token paths; no throughput runs."""
import argparse
import json
from pathlib import Path
import subprocess

from variants import DEFAULT_ENABLED, TOGGLES, enabled_for_mask, environment


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('tool', choices=['asan', 'memcheck', 'initcheck'])
p.add_argument('--section', choices=['all', 'providers', 'coefficients', 'backend', 'resident'], default='all',
               help='Split ASan checks into bounded lock holds')
p.add_argument('--defaults', action='store_true', help='Check only the defaults, with all E3 variables unset')
p.add_argument('--build', type=Path, help='Override the frozen historical build directory')
a = p.parse_args()
if a.tool != 'asan' and (a.section == 'backend' or (a.section == 'resident' and not a.defaults)):
    p.error('CUDA resident checks require --defaults; backend checks use ASan')
build_name = 'defaults' if a.defaults else 'toggles'
build = a.build or Path('/w/e3') / (build_name + ('-asan' if a.tool == 'asan' else ''))
prefix = [] if a.tool == 'asan' else [
    '/usr/local/cuda/bin/compute-sanitizer', '--tool', a.tool, '--error-exitcode', '99']
if a.tool == 'memcheck':
    prefix += ['--leak-check', 'full']


def run(test, enabled, args=()):
    env = environment(enabled, unset=a.defaults)
    if a.tool == 'asan':
        env.update(ASAN_OPTIONS='detect_leaks=1:halt_on_error=1:protect_shadow_gap=0',
                   UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    command = [*prefix, str(build / test), *args]
    result = subprocess.run(command, env=env,
                            capture_output=True, text=True)
    print(json.dumps(dict(tool=a.tool, test=test, enabled=enabled, args=args,
                          unset=a.defaults, command=command,
                          toggles={flag: env.get(flag) for flag in TOGGLES.values()},
                          exitcode=result.returncode, stdout=result.stdout,
                          stderr=result.stderr)), flush=True)
    result.check_returncode()


if a.section in ('all', 'providers'):
    configurations = [DEFAULT_ENABLED] if a.defaults else [
        [name for bit, name in enumerate(('compact-histograms', 'narrow-tokens', 'sync-removal'))
         if mask & (1 << bit)] for mask in range(8)]
    for enabled in configurations:
        run('gjxl_cuda_token_provider_test', enabled)
if a.section == 'coefficients' or (a.defaults and a.section == 'all'):
    run('gjxl_cuda_compact_ac_test', DEFAULT_ENABLED if a.defaults else [])
if a.tool == 'asan' and a.section in ('all', 'backend'):
    for enabled in ([DEFAULT_ENABLED] if a.defaults else ([], list(TOGGLES))):
        run('gjxl_cuda_backend_test', enabled)
        run('gjxl_cuda_low_effort_test', enabled)
if a.tool == 'asan' and a.section in ('all', 'resident'):
    for enabled in ([DEFAULT_ENABLED] if a.defaults else [enabled_for_mask(mask) for mask in (0, 95, 127)]):
        run('gjxl_transfer_gate', enabled, ('test', '2', '1'))
if a.tool != 'asan' and a.defaults and a.section in ('all', 'resident'):
    # Exercise both selected defaults through the full encoder without a timing mode.
    run('gjxl_transfer_gate', DEFAULT_ENABLED,
        ('identity', '1', '1', f'/w/e3/default-sanitized/{a.tool}',
         '/w/corpus/poc120/ahi-022-001.rgb'))
