#!/usr/bin/env python3
"""Functional byte comparisons only; one process configuration per invocation."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from variants import DEFAULT_MASK, TOGGLES, enabled_for_mask, environment


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mask', type=int, nargs='?', help='Bits in variants.TOGGLES order, 0..127')
    p.add_argument('--unset', action='store_true', help='Verify default behavior without E3 variables')
    p.add_argument('--default-mask', type=int, default=DEFAULT_MASK,
                   help='Expected unset defaults; use 0 only for the frozen historical toggle build')
    p.add_argument('--executable', help='Defaults to defaults/ for current unset checks, otherwise toggles/')
    p.add_argument('--root', type=Path, default=Path('/w/e3'))
    p.add_argument('--corpus', type=Path, default=Path('/w/corpus/poc120'))
    p.add_argument('--output-root', type=Path,
                   help='Separate evidence directory when checking another corpus')
    a = p.parse_args()
    if a.unset == (a.mask is not None):
        p.error('Specify either a mask or --unset')
    mask = a.default_mask if a.unset else a.mask
    enabled = enabled_for_mask(mask)
    label = 'unset' if a.unset else f'{mask:03d}'
    current_defaults = a.unset and mask == DEFAULT_MASK
    executable = a.executable or str(a.root / ('defaults' if current_defaults else 'toggles') /
                                     'gjxl_transfer_gate')
    output_root = a.output_root or (a.root / 'default-codestreams' / a.corpus.name
                                    if current_defaults else a.root / 'toggle-codestreams')
    output = output_root / label
    env = environment(enabled, unset=a.unset)
    manifest = []
    for mode, reference in [('identity', 'baseline-codestreams'), ('edges', 'baseline-edges')]:
        dest = output / mode
        command = [executable, mode, '12' if mode == 'identity' else '2', '1', str(dest)]
        if mode == 'identity':
            command.append(str(a.corpus))
        run = subprocess.run(command, env=env, capture_output=True, text=True, timeout=220)
        output.mkdir(parents=True, exist_ok=True)
        (output / f'{mode}.stdout').write_text(run.stdout)
        (output / f'{mode}.stderr').write_text(run.stderr)
        run.check_returncode()
        rows = [json.loads(line) for line in run.stdout.splitlines()]
        identities = [row for row in rows if row.get('identity') and 'preset' in row]
        expected_count = len(list(a.corpus.glob('*.rgb'))) if mode == 'identity' else 7
        if {row['preset'] for row in identities} != {0, 7, 8} or any(
                row['tiles'] != expected_count for row in identities):
            raise RuntimeError(f'Incomplete identity coverage: {rows}')
        expected = ({Path(str(preset)) / (tile.stem + '.jxl')
                     for preset in (0, 7, 8) for tile in a.corpus.glob('*.rgb')}
                    if mode == 'identity' else
                    {path.relative_to(a.root / reference) for path in (a.root / reference).rglob('*.jxl')})
        actual = {path.relative_to(dest) for path in dest.rglob('*.jxl')}
        if not expected or expected != actual:
            raise RuntimeError(f'File coverage differs for {label}/{mode}')
        for path in sorted(expected):
            before = (a.root / reference / path).read_bytes()
            after = (dest / path).read_bytes()
            if before != after:
                raise RuntimeError(f'Byte mismatch for {label}/{mode}/{path}')
            manifest.append(dict(file=f'{mode}/{path}', bytes=len(after),
                                 sha256=hashlib.sha256(after).hexdigest()))
    result = dict(mask=mask, unset=a.unset, enabled=enabled,
                  toggles={flag: env.get(flag) for flag in TOGGLES.values()},
                  files=len(manifest), mismatches=0, passed=True,
                  corpus=str(a.corpus), manifest=manifest)
    (output / 'identity.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'manifest'}), flush=True)


if __name__ == '__main__':
    main()
