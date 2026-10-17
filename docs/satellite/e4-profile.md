# Final default decision (phase 4)

Claude’s six phase-3 clean windows selected DC pipelining alongside blocking
waits. Both now default on, with exact `"0"` as the opt-out. Butteraugli graphs
remain default off because their clean throughput effects changed sign across
corpora and context counts. See
the phase-3 clean results (satellite repository `codecs/jxl-gpu-hybrid/results/E4/phase3/clean-window.md`).

Claude reports 1.05–1.13× throughput and 1.7–1.9× lower CPU time per tile at
12 contexts versus satellite, freeing about 4.5 cores. The original target
was not reached. Phase 4 only qualifies these final defaults; no more
throughput measurements or clean windows are planned. The final focused gate passed: 30 parser cases, 1,602 frozen comparisons,
69 stock decodes, one ASan/UBSan run and one 10,000-encode memory run at
12 contexts. Peak encoder VRAM was 1,564 MiB; device/managed ranges were
zero, late RSS upper-envelope growth was 60 KiB, and the longest lock hold
was 30 seconds. See `phase4/results/gate.json` remotely and
[REPORT.md](e4-gpu-efficiency-report.md) for the evidence.
Earlier attribution and decisions below are historical.

# Historical phase-3 default decision

Claude's eight phase-2 clean windows (2026-10-17, 13:18–13:45Z) selected
blocking waits as the default. At 12 contexts, poc120/dev CPU reductions were
**1.77× / 1.82×**, with throughput ratios **1.059× / 1.069×**. All-on reached
1.92× CPU reduction on dev and 1.64× on poc120; the original goal was not met.
See `results/E4/phase2/clean-window.md` for the clean evidence and decisions.

Only exact `GJXL_E4_BLOCKING_WAITS=0` now selects spinning. DC and graph remain
off unless explicitly enabled. The next six brackets hold blocking waits on
in both arms and compare DC, graph and both at 8/12/16 contexts on both corpora.
They use the same updated binary in both arms; each is bounded below 80 s.
The phase-3 focused gate passed: 30 option-parsing cases, 1,602 byte comparisons,
69 stock decodes and one ASan/UBSan run. Maximum gate lock hold was 21 s.
No new CPU or throughput claim is inferred from loaded-host runs. Historical
attribution follows.

# Historical phase-2 CPU attribution

Attribution and correctness/resource qualification complete, 2026-10-17;
clean performance acceptance awaits Claude. Claude's phase-1 measurements reject CfL
warp (0.91–0.95×); DC pipelining stays default off. Baseline at 12 lanes
uses about 9.4 CPU ms/tile. CPU samples with DWARF backtraces, runtime
correlation and scheduling data separate busy waits, launches,
entropy, host decisions and other costs. The historical GPU profile below
is retained as evidence, not as a current recommendation.

## Initial host attribution (dev, 12 lanes)

`host-before-c12`: 4,000 encodes, 34,768 running lane samples, DWARF
backtraces and CUDA/OSRT correlation. All outer stacks hit an unwind boundary;
inner application frames resolve and CUDA API categories use timestamps/TIDs.
The 12 persistent lane threads also perform entropy work; there is no separate
entropy pool. Three non-lane threads have 2,541 samples, mostly profiler work.

| Lane CPU category | Samples | Share | Estimated CPU ms/tile |
| --- | ---: | ---: | ---: |
| Entropy and serialization | 8,951 | 25.74% | 3.664 |
| CUDA launches | 6,523 | 18.76% | 2.670 |
| Allocation and resource accounting | 5,363 | 15.43% | 2.195 |
| CUDA waits | 4,354 | 12.52% | 1.782 |
| Host preparation/decisions | 3,457 | 9.94% | 1.415 |
| Mutex/other synchronization | 2,459 | 7.07% | 1.007 |
| Copies/other CUDA APIs | 2,387 | 6.87% | 0.977 |
| Profiler | 1,235 | 3.55% | 0.506 |
| Unresolved other | 39 | 0.11% | 0.016 |

Estimated times scale sample shares by the lane schedule interval sum
(14.232 CPU ms/tile). OSRT tracing is intrusive; these loaded, instrumented
numbers cannot be compared with Claude's 9.4 clean CPU ms/tile or used as a
throughput result. Entropy leaf stacks include `OptimizeOrdinaryEntropyCode`,
`PrepareDirectAnsPartition`, `EncodeHybridUintValidated`, `WriteAnsTokenStream`
and weighted DC tokenization. Host decisions include `MakeCandidates` and
`FindBestFirstLevelDivision`. Allocation/mutex frames include resource-budget
accounting and malloc; classifier assigns those before outer entropy frames.

Baseline CUDA waits spend 1.461 scheduled CPU ms/tile out of 1.555 wall ms/tile
(sum across lanes): strong evidence of busy waiting. A subsequent blocking-only
800-encode capture has 46 event waits/tile, zero stream waits and 0.170 scheduled
CPU ms/tile out of 1.356 wall ms/tile. Scheduling cannot distinguish preemption
from blocking, but the event flag explicitly requests blocking. CPU shares
inside waits fall to 0.73% in that capture. It uses no OSRT tracing and has
variable production load, so this is mechanism evidence, not a speed ratio.
A baseline/candidate/baseline set with matching instrumentation follows below.

The launch share justifies testing `GJXL_E4_BUTTERAUGLI_GRAPH`, independently
of `GJXL_E4_BLOCKING_WAITS` and the retained `GJXL_E4_DC_PIPELINE`. Graph topology
is built once per resident lane with explicit kernel nodes. All parameter values
and dimensions are checked each reuse; changed nodes use
`cudaGraphExecKernelNodeSetParams`. Unchanged arguments skip driver updates.
The fixed comparison prefix ends before per-tile anchor reductions, and
nonmatching geometries retain ordinary dispatch. This uses no stream capture
state or primary-context flag changes. All three switches default off.

Raw evidence stays remote: `e4/profiles/host-before-c12.*` and
`e4/phase2/profiles/host-blocking-c12-retry.*`. The first blocking capture lost
its Nsight agent despite exit 0; it is not evidence. `tools/e4/host_profile.py`
contains the sample classifier and scheduling intersections.


## Matched CPU-sampling captures

All use 800 dev tiles / 12 lanes, `--trace=cuda,nvtx`, process-tree sampling,
DWARF backtraces and two warmups. Capture order was baseline → graph → all-on
→ baseline; the intervening failed blocking capture is excluded. Production
continued throughout. No throughput measurements or selections were made.

| CPU sample share (%) | Baseline before | Graph alone | All-on | Baseline after |
| --- | ---: | ---: | ---: | ---: |
| Launch APIs | 21.1 | 10.1 | 18.3 | 21.7 |
| CUDA waits | 5.5 | 43.9 | 0.7 | 6.4 |
| Entropy/serialization | 29.7 | 19.2 | 33.3 | 29.8 |
| Host preparation/decisions | 10.7 | 6.1 | 11.5 | 10.6 |
| Allocation/resource accounting | 19.4 | 9.5 | 21.0 | 18.1 |
| Mutexes/other synchronization | 5.4 | 4.8 | 5.2 | 5.6 |
| Copies/other CUDA | 7.9 | 6.4 | 9.7 | 7.6 |
| Profiler/unresolved | 0.3 | 0.1 | 0.3 | 0.3 |
| Lane samples | 9,031 | 5,032 | 8,681 | 8,662 |
| Lane scheduled CPU ms/tile (instrumented) | 17.385 | 9.416 | 17.049 | 17.362 |

Runtime counts establish the mechanisms independently of the varying load:

| Calls per tile | Baseline | Graph alone | All-on |
| --- | ---: | ---: | ---: |
| Ordinary kernel launches | 416.2675 | 278.2675 | 274.2675 |
| Graph launches | 0 | 3 | 3 |
| Stream synchronizations | 37 | 37 | 0 |
| Event synchronizations | 9 | 9 | 46 |

The fixed graph replaces 46 kernel launches per AQ comparison, 138 per tile.
DC pipelining removes four more. Blocking events change the host waiting
mechanism while preserving completion boundaries. In all-on, event waits use
0.188 scheduled CPU ms/tile of 2.019 summed wall ms/tile; 1.831 ms is off-CPU.
Graph-only waits still spend 3.701 scheduled CPU ms/tile across event/stream
waits. That supports combining graph replay with blocking waits.

Absolute CPU figures vary with production and profiler overhead: tracing
hundreds of individual launches itself costs more than tracing three graphs.
The graph-only sample distribution is especially different from the bracketing
baselines. It is **not** evidence of a 1.85× CPU improvement or a throughput win.
Entropy and allocation/accounting remain substantial in all-on. These profiles
do not establish either clean gate; Claude must measure them independently.

Small reducers: `phase2/results/cpu-{base-before,graph,all,base-after}-attribution.json`.
Traces and stdout: `phase2/profiles/cpu-{base-before,graph,all,base-after}.*`.

An additional warmed **400-dev-tile / 12-lane** capture enabled
`--cuda-trace-all-apis=true`, with CPU sampling off. It records **1,200 graph
launches**, **111,307 ordinary kernel launches**, **zero graph parameter
updates**, and **zero CUDA runtime allocation/free/create/destroy/instantiate
calls**. The fixed arena keeps arguments unchanged in this corpus, so replay
skips the driver update calls after checking every argument. The graph still
updates changed parameters if another allocation plan requires it. This audit
contains runtime API records, not hidden driver allocator internals; endurance
and sanitizer checks independently cover ownership. Evidence:
`phase2/results/graph-api-audit-summary.json`, reduced by `tools/e4/api_audit.py`;
raw `phase2/profiles/graph-api-audit.{nsys-rep,sqlite}` stays remote.

The phase-2 clean handoff is `tools/e4/clean-windows.txt`: eight independent
invocations, each ≤80 s, single comparison and corpus, contexts 8/12/16.
The all-on combination is proposed for clean evaluation; all defaults stay off.
It compares with frozen satellite/E3 at 12 for gate decisions and reports busy
CPU cores, CPU ms/tile, throughput, bytes and VRAM.

Memory qualification at 16 lanes keeps encoder VRAM constant at **1,918 MiB**
for masks 0–3 and **1,920 MiB** for masks 4–7. Every mask is byte-checked for
at least 10,000 encodes; masks 3/6 extend to 30,000 and all-on to 50,000 after
earlier RSS-envelope checks exceeded the fixed 1 MiB limit. The final windows
pass: maximum RSS-envelope growth 208,896 bytes, maximum malloc-live range
51,136 bytes, zero managed/device range. RSS reclaim/fault oscillations remain
in the raw samples; neither the limits nor the samples were discarded.

---

# E4 GPU profile

2026-10-17. Baseline `67dca65` (frozen E3 defaults). RTX 5090, CUDA 12.8,
SM120. Production remained running. These are attribution captures, not
throughput comparisons. All GPU captures used the timing lock and at most a
250-second child timeout, with cleanup. The final wrapper uses 245 seconds
plus bounded termination/cleanup, and records each lock-hold duration. Raw traces stay on sat-5090 under
`/root/jxl-hybrid/e4/profiles/`; reduced JSON is in `results/E4/`.

## Current baseline

| Lanes | Kernels/tile | Kernel sum ms/tile | Kernel interval union | Stream/event syncs/tile |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 434.2167 | 3.1278 | 0.4696 | 37 / 8.9917 |
| 12 | 434.2167 | 4.2987 | 0.9841 | 37 / 8.9917 |

Both traces encode the 120 poc120 tiles from device CHW input at e8-balanced
d1.2, following two warm-up passes. The 12-lane trace has twelve distinct
kernel streams. Its near-continuous union of kernel intervals differs from
G3's older observations. It still says nothing about how many SMs are busy:
DC launches use just one or two blocks on a 170-SM device.

The next table is per kernel family (the stage granularity available without
adding perturbing internal event hooks). `grid` is the number of blocks,
`block` is threads/block; ranges cover all observed launch shapes. Full XYZ
dimensions, frequencies, register and shared-memory counts are in the JSON.
Occupancy is **measured** `sm__warps_active.avg.pct_of_peak_sustained_active`
from Nsight Compute on `ahi-022-001.rgb`, one lane, kernel replay, no clock or
cache control. It averages active warps over active-SM cycles; it is not the
fraction of all SMs in use. Replay serializes launches, so these representative
per-kernel counters do **not** measure twelve-lane concurrent occupancy.
A dash means that family was not encountered in the representative tile.

| Kernel family | Count/tile | Grid blocks | Threads/block | Achieved occupancy % | ms/tile, 1 lane | ms/tile, 12 lanes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `QuantizeDcKernel` | 8.00 | 1–2 | 64 | 4.17 | 1.5491 | 2.1086 |
| `NonlinearFinalCflKernel` | 1.00 | 64 | 128 | 8.33 | 0.2850 | 0.3630 |
| `SelectionBucketKernel` | 40.00 | 1 | 256 | 16.59 | 0.1587 | 0.1919 |
| `DirectShortFilterKernel` | 40.00 | 64–256 | 256 | 20.00 | 0.1271 | 0.1803 |
| `PairedMaltaScaleResponseKernel` | 36.00 | 88–352 | 256 | 22.63 | 0.1176 | 0.1902 |
| `PrefetchedInitialCflKernel` | 1.00 | 8 | 32 | 2.08 | 0.1069 | 0.1262 |
| `EncodeResidentCoefficientsShapeKernel` | 20.40 | 1–3950 | 64–256 | 18.97 | 0.0815 | 0.1145 |
| `SelectAdjustedQuantizationCooperativeKernel` | 20.40 | 1–3950 | 96 | 7.15 | 0.0753 | 0.1496 |
| `ConvolutionLowMediumRowsKernel` | 8.00 | 48–176 | 256 | 16.41 | 0.0575 | 0.0713 |
| `FusedAcStrategyKernel` | 7.00 | 288–896 | 192 | 38.57 | 0.0557 | 0.0748 |
| `ConvolutionTiledKernel` | 20.00 | 32–256 | 256 | 17.15 | 0.0479 | 0.0660 |
| `DcLowFrequenciesKernel` | 15.30 | 1–48 | 256 | 15.13 | 0.0454 | 0.0594 |
| `SelectionHistogramKernel` | 40.00 | 16 | 256 | 15.11 | 0.0429 | 0.0563 |
| `ConvolutionHorizontalPairsKernel` | 8.00 | 64–256 | 256 | 15.11 | 0.0426 | 0.0557 |
| `FusedMirroredOpsinKernel` | 8.00 | 256–512 | 256 | 34.26 | 0.0333 | 0.0459 |
| `GaborishEpfKernel` | 3.00 | 256 | 256 | 25.01 | 0.0285 | 0.0406 |
| `ComposeReductionKernel` | 13.25 | 1–256 | 256 | 15.96 | 0.0262 | 0.0358 |
| `ErosionL2FinalKernel` | 6.00 | 256–1024 | 256 | 54.97 | 0.0258 | 0.0350 |
| `InverseDctFactoredKernel` | 15.30 | 1–1482 | 64 | — | 0.0204 | 0.0368 |
| `EpfTiledKernel` | 3.00 | 256 | 256 | 24.87 | 0.0173 | 0.0224 |
| `OpsinMatrixScaleStatsKernel` | 1.00 | 1024 | 256 | 61.29 | 0.0115 | 0.0128 |
| `SubsampleKernel` | 12.00 | 256 | 256 | 23.94 | 0.0113 | 0.0179 |
| `MaskPrecomputeKernel` | 10.00 | 256–1024 | 256 | 41.63 | 0.0111 | 0.0166 |
| `Symmetric5ConvolutionKernel` | 4.00 | 1024 | 256 | 70.66 | 0.0110 | 0.0149 |
| `PublishShortHighKernel` | 8.00 | 256–1024 | 256 | 44.41 | 0.0095 | 0.0139 |
| `PrepareQuantNormsKernel` | 7.00 | 3–16 | 256 | 15.67 | 0.0094 | 0.0142 |
| `ModulationKernel` | 1.00 | 16 | 256 | 16.49 | 0.0093 | 0.0180 |
| `SuppressXKernel` | 8.00 | 256–1024 | 256 | 48.00 | 0.0092 | 0.0141 |
| `gjxl_ac_token_offsets` | 1.00 | 4 | 32 | 2.08 | 0.0088 | 0.0101 |
| `gjxl_ac_token_emit` | 1.00 | 192–2999 | 128 | 7.48 | 0.0088 | 0.0114 |
| `PackAcGroupsKernel` | 5.10 | 1–3950 | 64–256 | 18.86 | 0.0078 | 0.0116 |
| `FinalizeCostKernel` | 7.00 | 3–16 | 256 | 15.07 | 0.0073 | 0.0102 |
| `ForwardDctFactoredKernel` | 5.10 | 1–1482 | 64 | — | 0.0068 | 0.0128 |
| `SmoothDcKernel` | 3.00 | 16 | 256 | 16.01 | 0.0062 | 0.0096 |
| `AdjustQuantFieldKernel` | 5.10 | 1–16 | 256 | 7.55 | 0.0061 | 0.0098 |
| `InitialGradientKernel` | 1.00 | 64 | 256 | 16.43 | 0.0060 | 0.0087 |
| `ReduceMaximumKernel` | 5.22 | 1–16 | 256 | 15.15 | 0.0046 | 0.0068 |
| `gjxl_ac_token_metadata` | 1.00 | 192–2999 | 128 | 9.31 | 0.0042 | 0.0075 |
| `SelectionInitializeKernel` | 10.00 | 1 | 256 | 12.81 | 0.0040 | 0.0064 |
| `CompactTokenReadback` | 1.00 | 743 | 256 | 56.34 | 0.0036 | 0.0046 |
| `ComposeDct8ReductionKernel` | 2.05 | 1–988 | 128 | — | 0.0035 | 0.0050 |
| `RawQuantKernel` | 5.00 | 16 | 256 | 16.40 | 0.0034 | 0.0049 |
| `LinearRgbToOpsinKernel` | 1.00 | 1024 | 256 | 74.47 | 0.0033 | 0.0046 |
| `FinalizeQuantizerKernel` | 5.00 | 1 | 1 | 2.08 | 0.0030 | 0.0041 |
| `ResidentPolicyUpdateKernel` | 3.00 | 16 | 256 | 16.38 | 0.0030 | 0.0052 |
| `SparseAc` | 0.99 | 3072 | 256 | 64.64 | 0.0023 | 0.0036 |
| `FuzzyErosionKernel` | 1.00 | 16 | 256 | 14.77 | 0.0022 | 0.0031 |
| `CoefficientOrderPopulationKernel` | 1.00 | 128–204 | 256 | 15.86 | 0.0022 | 0.0057 |
| `CompactAcKernel` | 1.00 | 768 | 256 | 58.19 | 0.0013 | 0.0020 |
| `gjxl_ac_token_group_offsets` | 1.00 | 1 | 32 | 2.08 | 0.0008 | 0.0012 |
| `ReducePositiveRangeKernel` | 1.00 | 16 | 256 | 16.36 | 0.0007 | 0.0013 |
| `ResidentPolicyInitializeKernel` | 1.00 | 16 | 256 | 16.27 | 0.0007 | 0.0013 |
| `InitializePositiveRangeKernel` | 1.00 | 1 | 1 | 2.08 | 0.0004 | 0.0008 |

## Dependent chain and waits

A worker submits one tile at a time to its private stream. The reducer starts
each tile at `LinearRgbToOpsinKernel` and follows every ordered kernel, copy
and memset through that stream's final operation before the next RGB input.
This is the observed serial GPU chain, not an inferred full CPU/CUDA DAG.
CPU entropy after the final operation and host preparation before the input
are outside its bounds. The full longest chains, in order, are retained in
`profile-base-c{1,12}.json` under `chains.longest.sequence`.

| Lanes | Mean GPU-chain span ms | Mean device work ms | Mean inter-operation gap ms | Gap before next API returns ms | Gap after next API returns ms | Longest span ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 6.658 | 3.191 | 3.468 | 3.264 | 0.204 | 9.315 |
| 12 | 9.977 | 4.386 | 5.591 | 4.882 | 0.709 | 14.357 |

The structural chain is RGB/opsin and reference Butteraugli preparation →
initial AQ/CfL → AC strategy and host decision/readback → forward transforms
and nonlinear final CfL → three AQ reconstructions, each including quantizer
selection, AC coefficients, DC X/Y then B, smoothing, inverse transforms,
loop filters, Butteraugli evaluation and policy update → final coefficients
and DC X/Y then B → packing/readback → tokenization/readback → CPU entropy.

The critical *device-work* dependency is the DC wavefront: within each group,
weighted prediction follows `x + 2*y`; its west, north, northeast and northwest
state must precede the current sample. B also depends on quantized Y at the
same position. The baseline waits for every Y sample before launching B.
Four evaluations/finalizations give eight DC launches and 49.5% of the
single-lane summed kernel duration. Nonlinear CfL is another 9.1%.

The captures contain no `cudaStreamWaitEvent` calls in the measured range:
these batches supply no external producer or consumed event. There is no
explicit cross-lane GPU dependency or two-stream sharing as in G3. Each lane
does wait on its own completion/readback: stream synchronization sums to
0.101/0.334 ms per tile at 1/12 lanes; event synchronization to 2.320/3.148 ms.
Those host durations overlap device work and each other; do not add them to
kernel sums. The gap split is observational (at the next launch/copy API's
return), not proof of driver contention, CPU scheduling or another lane
causing a delay. This CUDA-only trace cannot attribute host mutex contention.

## Implemented experiments

- `GJXL_E4_DC_PIPELINE=1`: for fields at most 64×64, one 192-thread block
  contains independent X/Y/B rings, with B one wave behind Y. It preserves
  all predictor dependencies and arithmetic. Four launches replace eight.
  Rings use 18 KiB shared per block versus the old 24 KiB per channel block.
  Larger fields retain the existing dispatch.
- `GJXL_E4_CFL_WARP=1`: process 32-coefficient chunks with a single warp and
  warp barriers. The four accumulation lanes and coefficient order are
  unchanged. Default 128-thread execution remains available.

Both variables default off. They allocate no new device buffers and do not
change the resident lane count, E3 defaults, or input/event contract.
Candidate attribution follows. Clean-window throughput remains pending Claude.

## Reproduction

See `e4-gpu-efficiency-report.md` for complete capture commands and `tools/e4/profile.py` for
the reducer. `nsys export --type sqlite` runs in the build image; reduction
uses host Python standard-library sqlite3. The initial NCU counter attempt
without SYS_ADMIN was denied. `E4_COUNTERS=1` adds that capability only to
our profiling container; the driver policy and production services stayed
unchanged. Keep all `.sqlite` and `.nsys-rep` files remote.

## Candidate attribution (not throughput)

Baseline → all-on → baseline captures were interleaved, followed by a DC-only
profile to isolate that switch. Every row uses 120 device poc120 tiles.
Production load varied, especially during the all-on twelve-lane capture.

| Configuration | Lanes | DC launches/tile | DC sum ms/tile | CfL sum ms/tile | All kernel sum ms/tile |
| --- | ---: | ---: | ---: | ---: | ---: |
| base | 1 | 8 | 1.5491 | 0.2850 | 3.1278 |
| base | 12 | 8 | 2.1086 | 0.3630 | 4.2987 |
| all | 1 | 4 | 0.9576 | 0.6467 | 2.8992 |
| all | 12 | 4 | 3.1532 | 1.6994 | 8.3055 |
| base-after | 1 | 8 | 1.5508 | 0.2850 | 3.1307 |
| base-after | 12 | 8 | 2.0051 | 0.3596 | 4.1418 |
| dc | 1 | 4 | 0.9541 | 0.2849 | 2.5338 |
| dc | 12 | 4 | 1.3505 | 0.3709 | 3.5821 |

The DC-only one-lane profile removes about 0.595 ms of summed kernel duration
per tile (19% of the baseline kernel sum). Its single 192-thread block has
18,432 shared bytes. Isolated NCU achieved occupancy is 12.5% on the active
SM, versus 4.17% for each baseline 64-thread block. It uses one SM at a time
instead of the baseline's two for X/Y followed by one for B. This reduces
the DC dependency span and SM work, but does not establish a throughput ratio.

The warp CfL experiment has a negative profile result: one-lane CfL takes
0.647 ms versus 0.285 ms. NCU achieved occupancy falls from 8.33% to 2.08%;
32-coefficient chunks require four times as many chunk iterations and expose
fewer warps to hide instruction latency. It is retained, default off, for
the required independent clean ABBA comparison. No throughput/default choice
has been made from loaded-host results. All-on is not recommended as a
presumed improvement.

The candidate removes only four of 434 launches per tile; sync and copy
counts are unchanged. Even DC-only retains about 1.58 ms/tile of other
single-lane kernel work and the host submission/readback gaps. Removing
0.595 ms from a 3.13 ms kernel sum gives a **kernel-sum-only** ratio of about
1.24, not a throughput prediction or upper bound for concurrent lanes.
There is no profile-backed claim of 1.5x throughput from these switches.
Claude's clean comparison is required to accept/reject the gate. A miss
would motivate batching across tiles or graph reuse over the long AQ
sequence, rather than assuming this local wavefront change closes the gap.

Cross-tile batching would need an explicit rendezvous/batch executor in place
of independently progressing resident lane callbacks, with per-tile strategy,
quantizer, reduction and error state. Graph reuse must handle per-tile anchor
counts, varying transform batches, pointer lifetimes, and host readback
boundaries; simply capturing/instantiating hundreds of nodes afresh per tile
is not an established saving. Neither architectural change is implemented or
claimed here. The retained switches are deliberately independently measurable.

## Historical phase-1 handoff (superseded)

These were the old phase-1 commands. Current invocations are in
`tools/e4/clean-windows.txt`:

```sh
python3 /root/jxl-hybrid/e4/gjxl/tools/e4/bracket.py --variants --corpora poc120 dev --contexts 8 12 16 --reps 5
python3 /root/jxl-hybrid/e4/gjxl/tools/e4/summarize_bracket.py /root/jxl-hybrid/e4/results/e4-abba-<stamp>-poc120.jsonl /root/jxl-hybrid/e4/results/e4-abba-<stamp>-dev.jsonl
```

The harness locks once per corpus and bounds the subprocess plus cleanup
below 260 seconds. It fixes all E3 switches to the selected satellite
configuration, clears inherited E4/token overrides, and compares all-off,
each E4 switch and all-on using the same binary. It covers 8/12/16 lanes,
checks bytes and the 2,048 MiB cap in every process, and records per-run CPU,
VRAM, timings, toggle settings and executable hash. `--only dc-pipeline`
can shorten a window. Only Claude may provide the production-paused window.
