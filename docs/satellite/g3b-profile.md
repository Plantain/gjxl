# G3b entropy and accounting profile

2026-10-17. Baseline is satellite `2c7c72562264e2d01eaa13930e8569d1637da924`;
`hist-scratch` adds bounded histogram trials, and `map-reuse` also reuses
compressed context maps across alphabet-width candidates. All profiles use
e8, d1.2, production running, and the shared timing lock. Exact commands,
ordinary paired timings and the gate verdict are in REPORT.md.

Evidence: `results/G3b/profiles/`, `profile-summary.json`, and `verification.json`
under `/Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/`.

## Host-stage means

Forty poc120 tiles selected by G3's profile40 list cover all five routes. The
existing diagnostic hook starts from preconverted linear RGB, uses a detailed
serializer schedule and sixteen explicit CUDA lanes, and checks every output
and full summary against an ordinary encode. Each of the six profiles passes
all forty comparisons. These are elapsed ms per call, not CPU time. Nested
rows must not be added to their parents. Separate profiles have different
production load; the table does not establish isolated optimization savings.

### 1 context(s)

| Phase | Baseline | Histogram scratch | + Map reuse |
| --- | ---: | ---: | ---: |
| Total | 51.486 | 18.767 | 23.274 |
| Input preparation | 2.007 | 0.362 | 1.021 |
| Quantization pipeline | 24.595 | 4.057 | 4.714 |
| Serialization | 24.697 | 14.264 | 17.378 |
| Entropy optimization (nested) | 17.408 | 10.820 | 12.347 |
| ANS histogram build (nested) | 6.224 | 3.727 | 4.861 |
| ANS model build (nested) | 3.295 | 2.203 | 1.721 |
| ANS token cost (nested) | 5.496 | 3.607 | 4.051 |
| Section writing (nested) | 3.434 | 2.445 | 2.831 |

### 16 context(s)

| Phase | Baseline | Histogram scratch | + Map reuse |
| --- | ---: | ---: | ---: |
| Total | 77.889 | 52.102 | 86.409 |
| Input preparation | 1.921 | 1.618 | 11.022 |
| Quantization pipeline | 11.525 | 9.676 | 33.672 |
| Serialization | 64.075 | 40.617 | 38.894 |
| Entropy optimization (nested) | 46.027 | 26.905 | 27.090 |
| ANS histogram build (nested) | 13.822 | 4.482 | 9.031 |
| ANS model build (nested) | 19.330 | 15.089 | 6.628 |
| ANS token cost (nested) | 4.954 | 3.897 | 6.707 |
| Section writing (nested) | 12.304 | 10.275 | 6.375 |

The large quantization-time changes, despite unchanged GPU code, demonstrate
the load confounding. The final c16 entropy stage still takes 27.090 ms/call:
9.031 ms histogram construction, 6.628 ms model construction and 6.707 ms exact
token costing. At c1 these are 4.861, 1.721 and 4.051 ms respectively.

## perf attribution

Host perf attaches before the container execs its frozen benchmark binary;
new encoder threads inherit `cycles:u` sampling at 199 Hz, with 8192-byte DWARF
stacks. Six repetitions of all 120 tiles follow two warmups per context.
Startup, warmup and post-timing hashes are included in perf samples, so these
are attribution captures, not gate timings. All six benchmark inventories
match the baseline. Some shared-library symbols remain unresolved; do not
infer exact libc/driver functions from those raw addresses. Perf samples CPU
cycles while runnable, not off-CPU mutex wait duration.

Final e8/c16 leading gjxl self samples:

| Function | Self samples |
| --- | ---: |
| HybridUint conversion | 17.36% |
| BuildBestAnsHistogram | 8.93% |
| Direct ANS partition preparation | 3.96% |
| Prepared-section token costing | 3.18% |
| ANS model validation | 2.95% |
| Ordinary entropy setup | 2.48% |
| ANS encoder-table construction | 2.09% |

Baseline c16 HybridUint conversion was 15.44%; histogram rebalancing was
7.96%. Inlining differs after the scratch refactor, so the separate histogram
function percentages are not a directly comparable sum. The host-hook
histogram timing is the more useful before/after attribution.

## Fresh Nsight comparison

Both captures cover 120 measured poc120 tiles after warmup, at sixteen contexts,
using CUDA profiler-range capture and identical tracing options. Neither is an
ordinary timing. OS-runtime stack tracing greatly perturbs the heavily
allocating baseline: its instrumented throughput is 56.665 tiles/s versus
268.180 for the final candidate. Do not report that ratio as an encoder speedup.
Kernel busy fraction is this process's union of kernel intervals divided by
its host interval, not device-wide utilization or SM occupancy.

| Metric | Baseline | Final |
| --- | ---: | ---: |
| Kernel busy fraction | 0.150 | 0.505 |
| Summed kernel ms/tile | 3.313 | 3.570 |
| Kernels/tile | 432.392 | 432.400 |
| CUDA streams | 16.000 | 16.000 |
| Launch API aggregate ms/tile | 3.635 | 1.539 |
| Stream synchronizations/tile | 60.750 | 60.675 |
| Stream-sync aggregate ms/tile | 0.374 | 0.192 |
| Event waits/tile | 9.167 | 9.175 |
| Event-wait aggregate ms/tile | 0.965 | 2.299 |

Long traced mutex calls, classified by their first resolved gjxl stack owner:

| Owner | Baseline aggregate ms/tile | Final aggregate ms/tile |
| --- | ---: | ---: |
| Allocation prepare | 42.295 | 0.078 |
| Allocation destruction | 31.954 | 0.046 |
| Managed byte allocator | 31.860 | 0.114 |
| Allocation commit | 21.987 | 0.111 |
| Unresolved | 62.524 | 23.206 |

These overlapping thread durations are not additive wall time. Tracing
amplifies the baseline's lock contention, but the classification supports the
intended removal of repeated shared-accounting work. Unresolved waits remain;
this is not proof that all serialization or driver contention is gone.

QuantizeDcKernel remains the largest kernel family: 1.615 ms/tile baseline,
1.740 final; final nonlinear CfL is 0.315 ms/tile. Kernel counts and approximately
61 stream synchronizations / nine event waits per tile are unchanged. The
CPU-only edits do not remove those host/device handoffs.

Both traces report a 1 GiB CUDA memory-pool high-water value. That excludes
other process/context allocations; ordinary gate runs use per-process NVML
samples. Neither the pool value nor boundary sampling proves an exact total
VRAM high-water mark. REPORT.md and gate.json retain the actual process peak.

## Remaining options for review

- HybridUint conversion and exact token costing are now leading CPU targets.
  Consider inlining/specialization or reuse of repeated conversions without
  changing the ordered ANS recurrence or width tie-breaking.
- Histogram rebalancing still evaluates the same precision choices. Reuse
  count totals and exact cost work across candidates, or introduce only proven
  lower bounds. The search policy and selected bytes must remain unchanged.
- Model validation still traverses full reverse tables. Internal validated
  paths could avoid duplicate checks while public mutable models remain checked.
- At higher concurrency, remaining model/bit-writer allocations could use a
  bounded per-call arena with correct lifetime and finite-reservation accounting.
- GPU batching or fewer host handoffs may become useful after the CPU work is
  reduced; the unchanged small DC grids and synchronization counts are specific
  targets. Kernel busy fraction alone does not prove available device headroom.

No further performance changes were made after the two candidates. The
ordinary paired gate, including lighter-load confirmation, governs acceptance;
profile timing ratios and clean-throughput extrapolations do not.
