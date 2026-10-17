#!/usr/bin/env python3
"""Verify ABBA and environment isolation using a fake executable, never CUDA."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from variants import TOGGLES, TOKEN_OVERRIDES


with tempfile.TemporaryDirectory(prefix='e3-bracket-') as directory:
    fake = Path(directory) / 'fake-gate'
    fake.write_text('''#!/usr/bin/env python3
import json, os, sys
print(json.dumps(dict(argv=sys.argv[1:], observed={k:v for k,v in os.environ.items()
    if k.startswith('GJXL_E3_') or k in %r})))
''' % (TOKEN_OVERRIDES,))
    fake.chmod(0o755)
    env = os.environ.copy()
    env.update({key: '1' for key in TOGGLES.values()})
    env.update({key: '0' for key in TOKEN_OVERRIDES})
    env['GJXL_E3_UNRECOGNIZED'] = '1'
    run = subprocess.run([sys.executable, str(Path(__file__).with_name('bracket.py')),
                          '/fake/poc120', '6', '--variants', '--blocks', '1',
                          '--executable', str(fake)], env=env, check=True,
                         capture_output=True, text=True)
    rows = [json.loads(line) for line in run.stdout.splitlines()]
    assert len(rows) == 32
    for i, comparison in enumerate([*TOGGLES, 'all-on']):
        abba = rows[4*i:4*i+4]
        assert [r['variant'] for r in abba] == ['baseline', comparison, comparison, 'baseline']
        assert [r['abba_position'] for r in abba] == [0, 1, 2, 3]
        for row in abba:
            assert row['argv'] == ['devicebench', '12', '6', '/fake/poc120']
            assert row['comparison'] == comparison
            enabled = set(TOGGLES) if row['variant'] == 'all-on' else {row['variant']}
            expected = {flag: '1' if name in enabled else '0' for name, flag in TOGGLES.items()}
            assert row['observed'] == row['toggles'] == expected
print(json.dumps(dict(passed=True, comparisons=8, processes=32, real_encodes=0)))
