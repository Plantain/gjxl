#!/usr/bin/env python3
"""One E4 configuration/corpus: legacy, resident host, HWC, CHW and edges."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from variants import DEFAULT_MASK, TOGGLES, enabled_for_mask, environment


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('variant', choices=['unset', *map(str, range(8))])
    p.add_argument('corpus', choices=['poc120', 'dev'])
    p.add_argument('--root', type=Path, default=Path('/w/e4/phase4'))
    p.add_argument('--reference', type=Path, default=Path('/w/e3/default-codestreams'))
    p.add_argument('--contexts', type=int, default=12)
    a = p.parse_args()
    mask = DEFAULT_MASK if a.variant == 'unset' else int(a.variant)
    env = environment(enabled_for_mask(mask), unset=a.variant == 'unset')
    output = a.root / 'codestreams' / a.corpus / a.variant
    output.mkdir(parents=True, exist_ok=True)
    reference = a.reference / a.corpus / 'unset'
    manifest = []
    for mode in ('identity', 'edges'):
        dest = output / mode
        command = [str(a.root / 'release/gjxl_transfer_gate'), mode,
                   str(a.contexts if mode == 'identity' else 2), '1', str(dest)]
        if mode == 'identity':
            command.append('/w/corpus/' + a.corpus)
        run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=220)
        (output / f'{mode}.stdout').write_text(run.stdout)
        (output / f'{mode}.stderr').write_text(run.stderr)
        run.check_returncode()
        rows = [json.loads(line) for line in run.stdout.splitlines()]
        coverage = [r for r in rows if r.get('identity') and 'preset' in r]
        count = (120 if a.corpus == 'poc120' else 400) if mode == 'identity' else 7
        if {r['preset'] for r in coverage} != {0, 7, 8} or any(
                r['tiles'] != count for r in coverage):
            raise RuntimeError(f'Incomplete identity coverage: {rows}')
        expected = {f.relative_to(reference / mode)
                    for f in (reference / mode).rglob('*.jxl')}
        actual = {f.relative_to(dest) for f in dest.rglob('*.jxl')}
        if len(expected) != 3 * count or expected != actual:
            raise RuntimeError(f'Codestream coverage differs: {mode}')
        for file in sorted(expected):
            before, after = (reference / mode / file).read_bytes(), (dest / file).read_bytes()
            if before != after:
                raise RuntimeError(f'Byte mismatch: {mode}/{file}')
            manifest.append(dict(file=f'{mode}/{file}', bytes=len(after),
                                 sha256=hashlib.sha256(after).hexdigest()))
    result = dict(variant=a.variant, corpus=a.corpus, enabled=enabled_for_mask(mask),
                  toggles={flag: env.get(flag) for flag in TOGGLES.values()},
                  reference=str(reference), files=len(manifest), mismatches=0,
                  passed=True, manifest=manifest)
    (output / 'identity.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'manifest'}), flush=True)


if __name__ == '__main__':
    main()
