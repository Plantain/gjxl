#!/usr/bin/env python3
"""Verify the selected-default functional evidence; never run throughput timing."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from variants import DEFAULT_ENABLED, DEFAULT_MASK, TOGGLES


p = argparse.ArgumentParser(description=__doc__)
p.add_argument('root', type=Path)
a = p.parse_args()
results = a.root / 'results'


def completed(label):
    assert (results / f'defaults-{label}.exitcode').read_text().strip() == '0', label
    if not label.startswith('build-'):
        assert not (results / f'defaults-{label}.stderr').read_text(), label


def read(label):
    completed(label)
    return json.loads((results / f'defaults-{label}.jsonl').read_text())


def configuration(data):
    assert data['unset'] and data['enabled'] == list(DEFAULT_ENABLED)
    assert data['toggles'] == dict.fromkeys(TOGGLES.values())


identities, manifests, reservations = [], {}, []
for corpus, count in [('poc120', 381), ('dev', 1221)]:
    row = read(f'identity-{corpus}')
    configuration(row)
    assert row['mask'] == DEFAULT_MASK and row['files'] == count
    assert row['passed'] and row['mismatches'] == 0
    output = a.root / 'default-codestreams' / corpus / 'unset'
    data = json.loads((output / 'identity.json').read_text())
    assert {k: v for k, v in data.items() if k != 'manifest'} == row
    assert len(data['manifest']) == count
    # Collapse the intentionally repeated edge checks, checking their digests too.
    for entry in data['manifest']:
        old = manifests.setdefault(entry['file'], entry)
        assert old == entry
    row['manifest_sha256'] = hashlib.sha256(
        json.dumps(data['manifest'], sort_keys=True).encode()).hexdigest()
    identities.append(row)
    for mode in ('identity', 'edges'):
        assert not (output / f'{mode}.stderr').read_text()
        rows = [json.loads(line) for line in (output / f'{mode}.stdout').read_text().splitlines()]
        reservations.extend(r['vram_bytes'] for r in rows if 'create_seconds' in r)
        assert {r['preset'] for r in rows if r.get('identity') and 'preset' in r} == {0, 7, 8}
        if mode == 'edges':
            assert any(r.get('concurrent_callers') == 6 and r['identity'] for r in rows)
            assert any(r.get('primary_context_events') and r['producer_wait'] and r['early_recycle']
                       for r in rows)

assert len(manifests) == 1581
assert max(reservations) <= 2048 * 1024**2
decoded = []
for label, count, prefix in [('decode-poc120-edges', 381, ''), ('decode-dev', 1200, 'identity/')]:
    data = read(label)
    assert data['failed'] == 0 and data['decoded'] == count and len(data['files']) == count
    for entry in data['files']:
        expected = manifests[prefix + entry['file']]
        assert entry['decoded'] and entry['sha256'] == expected['sha256']
        assert entry['bytes'] == expected['bytes']
    decoded.append(dict(label=label, decoded=count, failed=0, stock_djxl=data['stock_djxl']))

sanitizers = []
for tool in ('asan', 'memcheck', 'initcheck'):
    sections = ('providers', 'coefficients', 'backend', 'resident') if tool == 'asan' else (
        'providers', 'coefficients', 'resident')
    for section in sections:
        label = f'{tool}-{section}'
        completed(label)
        rows = [json.loads(line) for line in (results / f'defaults-{label}.jsonl').read_text().splitlines()]
        assert len(rows) == (2 if section == 'backend' else 1)
        for row in rows:
            configuration(row)
            assert row['exitcode'] == 0
            if tool == 'asan':
                assert not row['stderr']
            else:
                log = row['stdout'] + row['stderr']
                counts = re.findall(r'ERROR SUMMARY: (\d+) errors', log)
                assert counts and all(int(n) == 0 for n in counts)
                if tool == 'memcheck':
                    leaks = re.findall(r'LEAK SUMMARY: (\d+) bytes leaked in (\d+) allocations', log)
                    assert leaks and all(int(size) == int(count) == 0 for size, count in leaks)
        sanitizers.append(dict(tool=tool, section=section, tests=len(rows), passed=True))

for kind in ('release', 'asan'):
    completed(f'build-{kind}')
hashes = {f'{build}/{name}': hashlib.sha256((a.root / build / name).read_bytes()).hexdigest()
          for build in ('defaults', 'defaults-asan')
          for name in ('gjxl_transfer_gate', 'libgjxl.so')}
inventory = json.loads((results / 'defaults-inventory.json').read_text())
assert inventory['selected_defaults']['enabled'] == list(DEFAULT_ENABLED)
assert inventory['selected_defaults']['inventory_derived']
bracket = json.loads((results / 'defaults-bracket-check.json').read_text())
assert bracket['passed'] and bracket['real_encodes'] == 0
print(json.dumps(dict(passed=True, gate='selected-default correctness and sanitizers',
                     throughput_timing_run=False, default_mask=DEFAULT_MASK,
                     default_enabled=DEFAULT_ENABLED, unique_codestreams=len(manifests),
                     frozen_e1_comparisons=sum(r['files'] for r in identities),
                     repeated_edge_comparisons=21, mismatches=0, identity=identities,
                     stock_decode=decoded, sanitizers=sanitizers,
                     encoder_creation_vram_bytes=max(reservations),
                     binary_sha256=hashes, inventory=inventory['selected_defaults'],
                     bracket_environment_check=bracket), indent=2))
