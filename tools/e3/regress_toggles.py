#!/usr/bin/env python3
"""Functional regression matrix; no benchmarks or throughput measurements."""
import json
import subprocess

from variants import TOGGLES, environment

root = '/w/e3/toggles/'
for enabled in ([], list(TOGGLES)):
    for test in ('gjxl_cuda_backend_test', 'gjxl_cuda_resource_test',
                 'gjxl_cuda_profiling_test', 'gjxl_cuda_sparse_resident_test',
                 'gjxl_cuda_workflow_profile_test', 'gjxl_cuda_compact_ac_test',
                 'gjxl_cuda_low_effort_test', 'gjxl_cuda_resident_storage_plan_test',
                 'gjxl_c_api_test'):
        result = subprocess.run([root + test], env=environment(enabled),
                                capture_output=True, text=True)
        print(json.dumps(dict(test=test, enabled=enabled, exitcode=result.returncode,
                              stdout=result.stdout, stderr=result.stderr)), flush=True)
        result.check_returncode()
# Exact token values, contexts, histogram totals/maxima/extra bits, int32
# extremes, resize retry, failure recovery and ownership for all eight paths.
for mask in range(8):
    enabled = [name for bit, name in enumerate(
        ('compact-histograms', 'narrow-tokens', 'sync-removal')) if mask & (1 << bit)]
    result = subprocess.run([root + 'gjxl_cuda_token_provider_test'],
                            env=environment(enabled), capture_output=True, text=True)
    print(json.dumps(dict(test='gjxl_cuda_token_provider_test', enabled=enabled,
                          exitcode=result.returncode, stdout=result.stdout,
                          stderr=result.stderr)), flush=True)
    result.check_returncode()
