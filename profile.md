# G3 CUDA throughput profile

2026-10-17, baseline `7216e07aff89346d25a52ea35ec8d27afba1e152`, CUDA 12.8,
SM120, RTX 5090. Production services remain running. All traces and timing
runs use `/root/jxl-hybrid/locks/timing.lock`, with a 260-second timeout and
container cleanup. These are instrumented attribution runs, not clean timings.

Raw evidence and the reducer are in
`/Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/G3/`:
`profiles/*.nsys-rep`, `profiles/*.sqlite`, `profiles/hooks-*.json`,
`raw/*.stdout`, and `analyze_profiles.py`. `profile-summary.json` retains all
kernel, CUDA API, copy, mutex-stack and host-stage aggregates.

## Baseline system trace

Each row captures 120 poc120 tiles at d1.2, after two warmups per context.
GPU busy is the union of this process's kernel intervals divided by its
measured host interval. It is not SM occupancy or device-wide utilization.
Summed device and CPU-thread durations overlap and must not be added together.

| Effort | Contexts | Kernel busy fraction | Kernel ms/tile (sum) | Kernels/tile | Kernel streams | Launch API ms/tile | Stream-sync ms/tile | Event-wait ms/tile |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 7 | 1 | 0.081 | 3.108 | 333.0 | 1 | 0.725 | 20.564 | 11.052 |
| 7 | 8 | 0.487 | 2.337 | 333.0 | 2 | 1.890 | 0.752 | 1.034 |
| 7 | 16 | 0.293 | 2.327 | 333.0 | 2 | 2.864 | 0.688 | 0.842 |
| 8 | 1 | 0.175 | 3.119 | 432.2 | 1 | 0.819 | 0.115 | 2.304 |
| 8 | 8 | 0.338 | 3.212 | 432.3 | 2 | 1.821 | 0.758 | 2.021 |
| 8 | 16 | 0.357 | 5.348 | 432.3 | 2 | 1.233 | 11.355 | 12.422 |

Load varies substantially: the e7/c1 capture is especially wait dominated.
These separate rows establish structural costs, not controlled speed ratios.

The public API shares only two nonblocking CUDA streams, assigned by thread
modulo two. A submission mutex covers each stream's entire launch callback;
uploads, readbacks and cached-buffer returns also hold it while synchronizing.
The e8/c16 trace attributes 23.73 aggregate ms/tile of long mutex calls to
buffer destruction, 23.02 to submission, 18.76 to individual D2H copies,
10.42 to batched D2H, 9.57 to H2D, 7.89 to allocation, and 6.97 to batched
H2D. This directly demonstrates lane contention. No default-stream kernels
appear in the measured public pipeline. Kernel busy fraction alone does not
show GPU saturation.

At e8/c8 there are 61.29 stream synchronizations, 9.07 event waits, and 7.08
pool allocations/frees per tile. Allocation API time is only 0.072 ms/tile,
but shared stream/cache/domain locks and cleanup add costs outside that API.
Long mutex stacks also reach allocation prepare/commit/free accounting.
Admission itself has not yet been separately timed; it must not be inferred
from allocation or backend-selection timings.

At e8/c1 the summed device work is dominated by prediction-aware DC
quantization: eight launches, 1.550 ms/tile, about half of total kernel time.
Each 64×64 block field launches only two blocks (X/Y), then one block (B),
with a dependent wavefront and block barriers. Nonlinear final CfL adds
0.286 ms/tile. These small grids can benefit from independent tiles in flight.
The four tokenization kernel families total about 0.023 ms/tile; their host
handoff and synchronization cost is substantially larger than device work.
Input `LinearRgbToOpsinKernel` plus `OpsinMatrixScaleStatsKernel` total
0.015 ms/tile; this excludes host RGB8 conversion and transfers.

## Existing gjxl hooks

Forty tiles selected by `NR % 3 == 1` from the sorted poc120 list cover all
five routes. The companion profiler converts RGB8 with the C adapter's
conversion routine, then uses two explicit shared CUDA backends to reproduce
the production stream topology. It checks each diagnostic codestream and full
summary against an ordinary encode. All six e7/e8 × 1/8/16-context runs pass.
The existing detailed serializer schedule and per-dispatch CUDA events perturb
execution; these calls do not measure the public host-RGB8 throughput boundary.

| Effort | Contexts | Reference preparation GPU ms/tile | Initial quantization | AC search | AQ policy GPU ms/tile | CPU entropy elapsed ms/tile |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 7 | 1 | 0.236 | 0.183 | 0.177 | 2.842 | 2.059 |
| 7 | 8 | 0.862 | 0.497 | 0.635 | 7.405 | 4.087 |
| 7 | 16 | 0.777 | 0.473 | 0.714 | 9.034 | 4.950 |
| 8 | 1 | 0.254 | 0.185 | 0.186 | 4.082 | 14.669 |
| 8 | 8 | 0.866 | 0.432 | 0.718 | 10.245 | 36.268 |
| 8 | 16 | 1.250 | 0.503 | 0.852 | 10.717 | 84.485 |

The AQ submission includes the update evaluations and final encode. Summing
dispatch durations between `ResidentPolicyUpdateKernel` boundaries gives:

| Effort | Contexts | Evaluation + update 0 ms | Update 1 | Update 2 | Final encoding |
| --- | ---: | ---: | ---: | ---: | ---: |
| 7 | 1 | 1.095 | 0.901 | — | 0.568 |
| 7 | 8 | 2.223 | 1.601 | — | 0.816 |
| 7 | 16 | 2.507 | 1.896 | — | 0.913 |
| 8 | 1 | 1.334 | 0.901 | 0.901 | 0.570 |
| 8 | 8 | 2.320 | 1.665 | 1.570 | 0.810 |
| 8 | 16 | 2.288 | 1.630 | 1.567 | 0.838 |

The first evaluation includes forward coefficients and final CfL. These sums
exclude inter-kernel gaps and therefore differ from whole-submission times.
At e8/c1,
host input preparation averages 0.935 ms and codestream serialization averages
19.981 ms. At e8/c16 these become 8.656 and 110.403 ms. CPU entropy is therefore
another scaling constraint once stream serialization is reduced.

## Experiments

1. Sixteen bounded production lanes: poc120 bytes unchanged at both efforts.
   Initial paired e7/c8 throughput 893.64 vs 496.64 tiles/s, but e8/c8 118.64
   vs 202.82 and e8/c16 150.71 vs 172.42. No e8 speedup established.
2. Bounded ANS alias-table temporaries on stack, with sixteen lanes: five
   focused tests and the entropy storage-plan failure sweeps pass. Interleaved
   e8/c8 is 141.317 vs unchanged gjxl 107.160 tiles/s, with bracketing libjxl
   18.858/18.098 (7.648×). At c16 it is 136.146 vs 90.876, with libjxl
   18.375/16.329 (7.846×). Both remain below 503 tiles/s and 10×.

The final candidate also measures 185.190 tiles/s on dev at e8/c16,
9.400× bracketing libjxl e8 19.816/19.588 and 1.417× unchanged gjxl.
E7/c16 measures 212.116 tiles/s on poc120 (11.602× libjxl e8) and
364.802 on dev (19.068×). The e7 comparisons are against libjxl **e8**.
`REPORT.md` retains all six paired rows, latency percentiles, CPU usage,
and sampled memory. All final 1,040 outputs match the baseline and decode
with stock djxl to PFM. The integer PPM output limitation is recorded there.

## Final combined-candidate profile

The final e8/c16 Nsight capture contains 120 tiles, 51,890 kernels, and
sixteen active streams. Its kernel busy fraction is 0.175, summed kernel
time 5.453 ms/tile, and launch API sum 4.612 ms/tile. There are still 61.32
stream synchronizations and 9.19 event waits per tile, totaling 12.661 and
8.774 aggregate ms/tile. D2H copies total 1,616,848 bytes and 0.081 ms/tile
of device copy time; the host synchronization cost is much larger. Input
opsin/matrix kernels total 0.017 ms/tile and the four tokenization families
total 0.030 ms/tile, excluding their host handoff. The memory-pool high-water
value is 1 GiB; it does not include all process GPU allocations.

Long mutex-call stacks now primarily concern resource accounting:

| First resolved gjxl stack owner | Aggregate mutex elapsed ms/tile |
| --- | ---: |
| Resource allocation prepare | 49.073 |
| Resource allocation destruction | 33.318 |
| Managed byte allocator | 30.437 |
| Resource allocation commit | 24.205 |
| CUDA buffer destruction | 0.922 |
| CUDA allocation | 0.835 |
| CUDA submission | 0.003 |

The baseline's submission-mutex value was 23.02 ms/tile. This supports the
intended removal of the two-lane bottleneck, while exposing accounting and
driver costs. These captures occurred at different production loads, and
stack collection itself perturbs contention; the magnitudes are not measured
optimization savings. The low kernel busy fraction does not support declaring
this process GPU-saturated, nor does it establish available device headroom
while production is running.

The final host-only hook has sixteen explicit lanes and checks bytes and full
summaries on all forty sample tiles. Per-call elapsed means are:

| Host phase | ms/call |
| --- | ---: |
| Total | 114.125 |
| Input preparation | 9.721 |
| Quantization pipeline | 15.094 |
| Codestream serialization | 88.833 |
| Entropy optimization (inside serialization) | 64.180 |
| ANS histogram build (inside entropy) | 19.706 |
| ANS model build (inside entropy) | 25.937 |
| ANS token cost (inside entropy) | 7.117 |
| Section writing (inside serialization) | 16.119 |

Nested phases must not be added to their parents. This profile omits GPU
per-dispatch events, while retaining the detailed serializer schedule. Its
entropy fraction is 56.2%, consistent with entropy/accounting remaining a
large scaling constraint. Shared-domain allocation contention is distinct
from a queue caused by exhausting a finite memory limit.

## Plateau and remaining options

Stop performance experiments after these two misses, as required by PLAN.
Final correctness/conformance and dev timing evidence are complete. The
sixteen-lane change alone is not established as an e8 improvement. The combined
change improves all three paired e8 observations, but those are short loaded runs,
not broad regression qualification or a clean-window result.

Scaling the two observed libjxl ratios by its supplied clean 50.3 tiles/s gives
385–395 tiles/s. This is only an estimate: CPU and GPU contention need not scale
alike. Reaching 503 from the better estimate requires about 27% more throughput,
or 21.5% less elapsed work per tile.

- **CPU entropy allocation and model reuse.** The instrumented c1 entropy stage
  is 52% of the whole call. Amdahl's law would require roughly 41% less entropy
  time to remove 21.5% overall, if that serial profile carried over. Further
  bounded histogram scratch, redundant table construction/validation, and
  contention in shared accounting are specific candidates. The final c16
  histogram/model phases sum to 45.64 ms/call, 40.0% of its measured total;
  halving that time would remove about 20% of the call under an idealized
  unchanged schedule, close to the estimated remaining gap. This is a target
  for investigation, not a predicted gain or a proven separable CPU cost.
  Preserve search
  order and tie-breaking; changing entropy policy belongs to G2.
- **Multi-tile device batching.** A fixed-effort B=8 or B=16 batch could amortize
  roughly 432 e8 launch submissions to 54 or 27 per tile (87.5%/93.75% fewer),
  while exposing more independent DC wavefront blocks. This is an operation-
  count estimate, not a speed prediction. Every image needs isolated anchors,
  reductions, CfL, quantization state and neighborhood boundaries. Current
  process peaks around 1.5 GiB at sixteen calls suggest a plausible starting
  envelope, but stacked scratch/double buffering must be budgeted explicitly.
  No batch implementation or public batch C API is included in this work.
- **CUDA graph reuse.** The resident AQ sequence is the largest launch block.
  Stable pointers and graph updates for data-dependent transform populations
  would be necessary. The c1 launch API sum is only about 0.82 ms/tile, so
  eliminating it alone does not establish the needed 27% gain. Under concurrent
  callers it also removes driver contention; a fresh controlled profile is
  needed to quantify that benefit.
- **Wait policy and cleanup.** Completion events currently spin by default;
  cached-buffer destruction synchronizes its shared stream. Blocking completion
  events and deferred, correctly charged frees may reduce CPU consumption and
  interference. Their latency tradeoff is unmeasured. Do not remove a wait
  without preserving cross-lane lifetime and resource-ticket ownership.

Memory-admission capacity is unlimited in the benchmark's shared execution
domain, so it does not impose a finite-memory queue. The current instrumentation
does not isolate C-adapter planning/admission CPU time from the complete call;
this is an explicit attribution gap. The measured allocation API times and
observed mutex stacks do not by themselves fill that gap. The final trace
does attribute 0.034 aggregate ms/tile of long mutex calls to
`WorkflowAdmission::Start`; that is only the captured lock component, not
total admission cost. Additional instrumentation would be needed to separate
planning, reservation setup and short uncontended admission work.
