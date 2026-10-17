#!/usr/bin/env python3
"""Shared E3 switch definitions for correctness and clean-window brackets."""
import os

TOGGLES = {
    'resident-tables': 'GJXL_E3_RESIDENT_TABLES',
    'compact-histograms': 'GJXL_E3_COMPACT_HISTOGRAMS',
    'narrow-coefficients': 'GJXL_E3_NARROW_COEFFICIENTS',
    'batched-readbacks': 'GJXL_E3_BATCHED_READBACKS',
    'sync-removal': 'GJXL_E3_SYNC_REMOVAL',
    'cpu-tokens': 'GJXL_E3_CPU_TOKENS',
    'narrow-tokens': 'GJXL_E3_NARROW_TOKENS',
}
DEFAULT_ENABLED = ('compact-histograms', 'narrow-coefficients')
DEFAULT_MASK = sum(1 << bit for bit, name in enumerate(TOGGLES)
                   if name in DEFAULT_ENABLED)
TOKEN_OVERRIDES = (
    'GJXL_GPU_TOKENIZATION',
    'GJXL_EXPERIMENT_GPU_TOKENS',
    'GJXL_EXPERIMENT_CUDA_GPU_TOKENS',
)


def environment(enabled=(), *, unset=False, blocking_waits=True, dc_pipeline=True):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('GJXL_E3_', 'GJXL_E4_')) and k not in TOKEN_OVERRIDES}
    # Keep E4 defaults fixed while comparing E3 settings. Explicit False for
    # both options reproduces E4 all-off; inherited experiments cannot leak in.
    env.update(GJXL_E4_BLOCKING_WAITS='1' if blocking_waits else '0',
               GJXL_E4_DC_PIPELINE='1' if dc_pipeline else '0',
               GJXL_E4_BUTTERAUGLI_GRAPH='0')
    if not unset:
        env.update({flag: '1' if name in enabled else '0'
                    for name, flag in TOGGLES.items()})
    return env


def enabled_for_mask(mask):
    if not 0 <= mask < (1 << len(TOGGLES)):
        raise ValueError(f'Invalid E3 mask: {mask}')
    return [name for bit, name in enumerate(TOGGLES) if mask & (1 << bit)]
