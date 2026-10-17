#!/usr/bin/env python3
"""E4 experiments, always against the selected satellite/E3 defaults."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'e3_variants', Path(__file__).resolve().parents[1] / 'e3' / 'variants.py')
e3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e3)

TOGGLES = {'dc-pipeline': 'GJXL_E4_DC_PIPELINE',
           'blocking-waits': 'GJXL_E4_BLOCKING_WAITS',
           'butteraugli-graph': 'GJXL_E4_BUTTERAUGLI_GRAPH'}
DEFAULT_ENABLED = ('dc-pipeline', 'blocking-waits')
DEFAULT_MASK = sum(1 << bit for bit, name in enumerate(TOGGLES)
                   if name in DEFAULT_ENABLED)


def environment(enabled=DEFAULT_ENABLED, *, unset=False):
    # An explicit empty collection (or mask 0) retains the old spinning path.
    env = {k: v for k, v in e3.environment(e3.DEFAULT_ENABLED).items()
           if not k.startswith('GJXL_E4_')}
    if not unset:
        env.update({flag: '1' if name in enabled else '0'
                    for name, flag in TOGGLES.items()})
    return env


def enabled_for_mask(mask):
    if not 0 <= mask < 1 << len(TOGGLES):
        raise ValueError(f'Invalid E4 mask: {mask}')
    return [name for bit, name in enumerate(TOGGLES) if mask & (1 << bit)]
