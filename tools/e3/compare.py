#!/usr/bin/env python3
"""Compare frozen baseline and candidate codestream trees, recording hashes."""
import hashlib
import json
from pathlib import Path
import sys

baseline, candidate = map(Path, sys.argv[1:3])
expected = {p.relative_to(baseline) for p in baseline.rglob('*.jxl')}
actual = {p.relative_to(candidate) for p in candidate.rglob('*.jxl')}
assert expected and expected == actual, (len(expected), len(actual))
rows = []
for p in sorted(expected):
    before, after = (baseline/p).read_bytes(), (candidate/p).read_bytes()
    rows.append({'file': str(p), 'bytes': len(after), 'identical': before == after,
                 'baseline_sha256': hashlib.sha256(before).hexdigest(),
                 'candidate_sha256': hashlib.sha256(after).hexdigest()})
result = {'files': len(rows), 'mismatches': sum(not r['identical'] for r in rows),
          'bytes': sum(r['bytes'] for r in rows), 'codestreams': rows}
print(json.dumps(result, indent=2))
sys.exit(bool(result['mismatches']))
