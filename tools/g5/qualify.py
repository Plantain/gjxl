"""Run short G5 chunks on sat-5090, preserving every resource deferral.

Waiting for physical headroom does not hold the timing lock. Only exit 75/76
(resource deferral/floor loss) is retried; encode/identity failures stop work.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

root = Path('/root/jxl-hybrid/g5')
run = root/'gjxl/tools/g5/run.sh'
gate = '/w/g5/gjxl/tools/g5/gate.py'
candidate = '/w/g5/gjxl/build/g5/libgjxl.so'


def invoke(label, command, env=None):
    for attempt in range(1, 4):
        # Avoid launching into a known production allocation peak. The guard
        # still enforces expected peak + 12 GiB after lock acquisition.
        deadline = time.monotonic()+180
        while True:
            free = int(subprocess.check_output(['nvidia-smi', '--query-gpu=memory.free',
                       '--format=csv,noheader,nounits'], text=True).strip())
            if free >= int(os.environ.get('G5_START_FREE_MIB', '14336')):
                break
            if time.monotonic() > deadline:
                raise RuntimeError('No quiet GPU headroom for '+label)
            time.sleep(1)
        name = f'{label}-attempt{attempt}'
        # Never overwrite a receipt from an earlier invocation.
        while (root/'results'/(name+'.exitcode')).exists():
            name += '-next'
        code = subprocess.call(['bash', str(run), name, *command], env=env)
        print(json.dumps(dict(label=label, receipt=name, exitcode=code)), flush=True)
        if code == 0:
            (root/'results'/(label+'.receipt.json')).write_text(
                json.dumps(dict(passed=True, receipt=name, command=command), indent=2)+'\n')
            return
        if code not in (75, 76):
            raise RuntimeError(f'{label}: exit {code}')
    raise RuntimeError('Repeated physical-memory interruption: '+label)


def task(name):
    if name in ('plateau-0', 'plateau-1'):
        invoke(name, ['python3', gate, 'endurance', '--library', candidate,
                      '--manifest', '/w/g5/repro.json', '--output', f'/w/g5/results/{name}.json'],
               dict(os.environ, GJXL_E4_BLOCKING_WAITS=name[-1]))
        return
    if name.startswith('sanitize-'):
        kind = name.removeprefix('sanitize-')
        assert kind in ('memcheck', 'initcheck', 'racecheck')
        invoke(name, ['/usr/local/cuda/bin/compute-sanitizer', '--tool', kind,
                      '--error-exitcode', '91',
                      '/w/g5/gjxl/build/g5/gjxl_cuda_raw_quant_readback_test',
                      '/w/g5/gjxl/testdata/satellite/raw-quant-257.rgb', '1', '1'],
               dict(os.environ, G5_IMAGE='satellite-cujpegxl-build:cuda12.8'))
        return
    if name == 'regression-native':
        invoke(name, ['/w/g5/gjxl/build/g5/gjxl_cuda_raw_quant_readback_test',
                      '/w/g5/gjxl/testdata/satellite/raw-quant-257.rgb', '10', '12',
                      '/w/g5/results/regression.jxl'],
               dict(os.environ, G5_IMAGE='satellite-cujpegxl-build:cuda12.8'))
        return
    if name == 'ctest':
        invoke(name, ['ctest', '--test-dir', '/w/g5/gjxl/build/g5',
                      '-R', '^cuda_raw_quant_readback$', '--output-on-failure'],
               dict(os.environ, G5_IMAGE='satellite-cujpegxl-build:cuda12.8'))
        return
    if name.startswith('matrix-'):
        part = int(name.split('-')[1])
        assert 0 <= part < 12
        args = ['--manifest', '/w/g5/manifest-exact.json', '--start', str(part*1000), '--count', '1000']
    else:
        assert name in ('mutations', 'published', 'synthetic', 'mixtures')
        args = ['--manifest', f'/w/g5/{name}.json']
    for variant in ('baseline', 'candidate'):
        label = name+'-'+variant
        output = f'/w/g5/results/{label}.json'
        command = ['python3', gate, 'scan', *args, '--release', '--output', output]
        if variant == 'candidate':
            command += ['--library', candidate, '--baseline', f'/w/g5/results/{name}-baseline.json',
                        '--save', '/w/g5/codestreams']
        invoke(label, command)
        report = json.loads((root/'results'/(label+'.json')).read_text())
        assert not report['mismatches'], label
        if variant == 'candidate':
            assert report['failures'] == 0, label


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('tasks', nargs='+')
    for name in parser.parse_args().tasks:
        task(name)
