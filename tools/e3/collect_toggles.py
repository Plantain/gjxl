#!/usr/bin/env python3
"""Collect the exhaustive functional gate, leaving timing to Claude."""
import argparse
import hashlib
import json
from pathlib import Path

from variants import TOGGLES, enabled_for_mask


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('root', type=Path)
a = p.parse_args()
results = a.root / 'results'
rows = []
for label in ['unset', *(f'{mask:03d}' for mask in range(1 << len(TOGGLES)))]:
    data = json.loads((a.root / 'toggle-codestreams' / label / 'identity.json').read_text())
    assert data['passed'] and data['files'] == 381 and data['mismatches'] == 0
    assert data['enabled'] == enabled_for_mask(data['mask'])
    assert (results / f'toggles-identity-{label}.exitcode').read_text().strip() == '0'
    assert not (results / f'toggles-identity-{label}.stderr').read_text()
    expected = {flag: (None if label == 'unset' else '1' if name in data['enabled'] else '0')
                for name, flag in TOGGLES.items()}
    assert data['toggles'] == expected
    manifest = data.pop('manifest')
    assert len(manifest) == 381
    data['manifest_sha256'] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    rows.append(data)
assert len({row['manifest_sha256'] for row in rows}) == 1
checks = {}
for label, count in [('regression', 26), ('asan-providers', 8), ('asan-backend', 4),
                     ('asan-resident', 3), ('memcheck', 8), ('initcheck', 8)]:
    assert (results / f'toggles-{label}.exitcode').read_text().strip() == '0'
    tests = [json.loads(line) for line in (results / f'toggles-{label}.jsonl').read_text().splitlines()]
    assert len(tests) == count and all(test['exitcode'] == 0 for test in tests)
    checks[label] = dict(passed=True, tests=len(tests))
conformance = json.loads((results / 'toggles-conformance.jsonl').read_text())
assert conformance['failed'] == 0 and conformance['decoded'] == 381
checks['stock_djxl'] = dict(passed=True, decoded=381)
dev = []
for mask in (0, 127):
    data = json.loads((results / f'toggles-dev-{mask}.jsonl').read_text())
    assert data['mask'] == mask and data['files'] == 1221 and data['mismatches'] == 0
    assert data['passed'] and data['enabled'] == enabled_for_mask(mask)
    assert (results / f'toggles-dev-{mask}.exitcode').read_text().strip() == '0'
    dev.append(data)
checks['dev_all_off_all_on'] = dict(passed=True, comparisons=2442, configurations=dev)
binaries = {name: hashlib.sha256((a.root / 'toggles' / name).read_bytes()).hexdigest()
            for name in ('gjxl_transfer_gate', 'libgjxl.so')}
print(json.dumps(dict(passed=True, gate='toggle correctness (not throughput acceptance)',
                     timing_run=False, combinations=128, default_unset_checks=1,
                     codestream_comparisons=128*381, unset_codestream_comparisons=381,
                     mismatches=0, checks=checks, binary_sha256=binaries,
                     configurations=rows), indent=2))
