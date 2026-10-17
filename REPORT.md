# G3 throughput work report

Status: throughput target missed by both profiled candidates (2026-10-17).
Stopped at a profile-backed plateau under the PLAN's two-miss rule. Final
byte identity and stock-decoder PFM conformance pass for all 1,040 outputs;
all six focused tests pass. Paired timing and profiling are complete. Best
poc120 e8 throughput is 141.317 tiles/s; its paired ratios are 7.648–7.846×
libjxl e8, below the 503 tiles/s / 10× target. Peak sampled VRAM across final
ordinary runs is 1566 MiB, with at most sixteen encoder participants.
No throughput gate pass or clean-window result is claimed.

## Scope and acceptance

CUDA, host 512×512 RGB8 sRGB input, independent bare codestream output,
distance 1.2 at unchanged gjxl efforts 7 and 8. Every performance change must
match all poc120 hashes at both efforts; the final check also covers dev.
Target: e8 ≥503 tiles/s, ≤16 CPU participants and ≤2048 MB device memory.
Production stays running. Timing holds the shared lock for at most five
minutes per run; builds use nice 10 and at most eight CPUs. No sub-agents,
commits, pushes or edits to the integration checkout.

## Initial observations

- Clean starting measurements supplied in the brief: e8 301 tiles/s at eight
  contexts, e7 509 tiles/s at sixteen; clean libjxl e8 50.3 tiles/s.
- Initial remote check: RTX 5090 memory free 6791 MiB, GPU utilization 98%.
  This is production load, not an isolated encoder measurement.
- `nsys` was initially absent from the host and build image.
- Work directory: `/root/jxl-hybrid/g3/`; baseline source is copied once from
  `/root/jxl-hybrid/gjxl-base`. All subsequent edits originate locally.

## Changes and validation

- Added Linux/CUDA `satellite_tile_bench` under `GJXL_BUILD_BENCHMARKS`.
  Inputs are raw 512×512 RGB8 files or a newline tile list. Options include
  contexts, effort, distance, warmup count, repetitions, output directory,
  and a CUDA-profiler measured range. It retains outputs through the timed
  interval, validates all repeats byte-for-byte afterward, and emits per-tile
  SHA-256 plus an aggregate digest. JSON includes nearest-rank latency
  percentiles, process user+system CPU time, execution-domain participant peak,
  and NVML per-process VRAM samples (context-0 tile boundaries, including warmup;
  sampled peak, not an exact allocation high-water mark). Main is one of the
  requested encoder threads, so there is no extra sampler thread.
- Both local and remote baseline are `7216e07aff89346d25a52ea35ec8d27afba1e152`.
- Remote build succeeded (116 steps), with `nice -n 10`, Docker `--cpus=8`,
  Release, SM120, benchmarks and tests configured ON; targets
  `satellite_tile_bench gjxl_cuda_encoding_benchmark`. Source and build are
  `/w/g3/gjxl` and `build/g3` in the standard build image. The separate build
  directory avoids reusing the base checkout's absolute CMake paths.
- Nsight Systems 2025.6.3 was downloaded from the image's configured NVIDIA
  apt repository and extracted under `/root/jxl-hybrid/g3/nsys`; no operational
  container or host service was changed. G3 disk usage was 2.0 GB after setup.
- Code inspection found only **two** process-global production CUDA lanes,
  assigned by caller thread modulo two. Copies synchronize while holding a
  lane submission mutex. Nsight confirms contention on these lanes.

Six baseline Nsight traces and six existing-hook dispatch/host profiles cover
both efforts at 1/8/16 contexts; see `profile.md`. A seventh trace and final
host-stage profile cover the combined candidate at e8/c16. All required
timing, final byte-identity and PFM conformance runs have completed.

### First profile and candidate

- Baseline poc120 and dev SHA-256 inventories collected at both efforts.
  poc120 hashes also match across 1/8/16 contexts and repetitions. Inventories
  are in `results/G3/raw/baseline-*.stdout` (JSON).
- First baseline e8/c8 Nsight range: 120 tiles, 51,875 kernels on exactly two
  streams; 385.386 ms summed kernel duration; 7,355 stream synchronizations,
  1,088 event synchronizations, 849 pool allocations and frees. Summed launch
  API time 218.575 ms; summed pthread mutex-lock elapsed time 2,858.186 ms.
  Sampled long lock stacks include `CudaBackend::SubmitCompute`, allocation,
  buffer destruction, and resource-budget accounting. These are instrumented
  aggregate thread durations, not additive wall times.
- Candidate 1 increases the bounded production CUDA lane count from 2 to 16,
  preserving eager initialization before any shared DCT constants are used.
  No math, quantization, entropy policy or kernel changes.
- Added a diagnostic `satellite_tile_profile` companion using existing
  workflow and GPU dispatch hooks, with explicit shared backend lanes and
  per-tile ordinary/profiling byte-and-summary comparisons. Unlike the main
  benchmark, these diagnostics start from preconverted linear RGB and use the
  detailed serializer schedule. They are attribution evidence only.
- Candidate 1 poc120 hashes pass e7 and e8 after the lane change. First paired
  screen at eight contexts: e7 893.64 vs baseline 496.64 tiles/s (1.799×), but
  e8 118.64 vs 202.82 (0.585×); at sixteen, e8 150.71 vs 172.42 (0.874×).
  These first screens do not establish the lane-only candidate as an e8
  improvement. Preserve both favorable and unfavorable
  runs (`screen2-*`), without treating separate load windows as comparable.
- Existing hooks show e8/c1 mean entropy optimization 14.669 ms/tile in the
  instrumented 40-tile sample, vs e7 2.059 ms. At e8/c16 it grows to 84.485 ms
  per call. Long traced locks include resource-allocation prepare/commit/free.
- Candidate 2 replaces ANS alias-table temporary vectors with fixed bounded
  stack arrays. The alphabet already caps these at 256 entries. The LIFO
  worklist order, arithmetic and resulting tables are unchanged. The managed
  storage plan drops the removed allocations. The five focused tests pass:
  `ctest --test-dir /w/g3/gjxl/build/g3 --output-on-failure -R
  '^(entropy|ans_reverse_bits|resource_budget|c_api_cpp|codestream_batch_workflow)$'`
  (2.02 s). First interleaved e8/c8 pair: candidate 141.317, unchanged gjxl
  107.160, libjxl e8 before 18.858 tiles/s. Complete paired timings follow
  below; no throughput gate pass.
- `entropy_storage_plan` also passes (5.81 s), including finite reservations
  and allocation-failure sweeps after the alias scratch storage-plan change:
  `ctest --test-dir /w/g3/gjxl/build/g3 --output-on-failure -R '^entropy_storage_plan$'`.
- Candidate 2 e8 paired results: eight contexts 141.317 tiles/s, 7.648× the
  mean of libjxl's bracketing 18.858/18.098 tiles/s, 1.319× unchanged gjxl;
  sixteen contexts 136.146 tiles/s, 7.846× bracketing libjxl 18.375/16.329,
  1.498× unchanged gjxl. Both miss 503 tiles/s and 10× concurrent libjxl.
  Straight scaling by the clean 50.3 baseline would suggest 385–395 tiles/s,
  but that is an estimate, not a clean-window measurement or gate pass.
- Final candidate inventories pass all 1,040 poc120/dev × e7/e8 outputs
  against the unmodified baseline. Peak sampled device memory is 1566 MiB
  across final ordinary runs with sixteen participants. E7/c8 throughput is 188.892 tiles/s,
  11.562× bracketing libjxl 16.717/15.957 and 1.000× unchanged gjxl 188.973.
  Strong variation from the earlier e7 screen reinforces the need for loaded
  paired comparisons and Claude's eventual clean-window confirmation.
- The final e8/c16 trace confirms sixteen active streams. Long submission
  mutex calls fall from 23.02 to 0.003 aggregate ms/tile, but resource-budget
  prepare/commit/destruction locks remain prominent (49.07/24.21/33.32
  aggregate ms/tile). The host hook reports entropy optimization at
  64.18 of 114.12 elapsed ms/call, with histogram/model construction at
  19.71/25.94 ms. These separate instrumented runs identify bottlenecks;
  their differences are not controlled performance deltas.

## Gate commands and results

Evidence root:
`/Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/G3/`.
Remote commands run as root on sat-5090. The local result directory retains
the exact runner scripts. `run_locked.sh` checks ≥6144 MiB free for GPU jobs,
holds the timing lock, uses Docker `--cpus=16 --pid=host`, and bounds the hold
with timeout/cleanup. `run_pair.sh` brackets candidate/unchanged-gjxl runs with
stock libjxl e8, using sixteen single-thread tile workers for the latter.

Build (inside `satellite-cujpegxl-build:cuda12.8`, Docker `--cpus=8`):

```sh
cd /w/g3/gjxl
nice -n 10 cmake -S . -B build/g3 -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DGJXL_ENABLE_CUDA=ON -DGJXL_ENABLE_METAL=OFF \
  -DGJXL_ENABLE_LIBJXL_REFERENCE=OFF -DCMAKE_CUDA_ARCHITECTURES=120 \
  -DGJXL_BUILD_BENCHMARKS=ON -DGJXL_BUILD_TESTS=ON
nice -n 10 cmake --build build/g3 --target satellite_tile_bench \
  satellite_tile_profile gjxl_entropy_test gjxl_ans_reverse_bits_test \
  gjxl_codestream_batch_workflow_test gjxl_resource_budget_test \
  gjxl_c_api_cpp_test gjxl_entropy_storage_plan_test -j8
```

The frozen `/w/g3/bin/baseline` was built before performance edits;
`lanes16` contains only the lane change; `alias-stack` contains both changes.
SHA-256 binary hashes, configuration and build logs are in `build/`.
`source.patch` and `source-manifest.json` snapshot the code changes; all five
source hashes match the remote files used for the final build. Reports are
also copied into the evidence root. Changes remain uncommitted for review.

Paired gate commands (substitute effort 7 and contexts 8/16 as recorded):

```sh
bash /root/jxl-hybrid/g3/run_locked.sh pair-poc120-e8-c16-alias-stack-r1 gpu \
  bash /w/g3/run_pair.sh poc120 8 16 alias-stack 1
bash /root/jxl-hybrid/g3/run_locked.sh finish-dev gpu bash /w/g3/finish.sh dev
bash /root/jxl-hybrid/g3/run_locked.sh finish-poc gpu bash /w/g3/finish.sh poc
```

Each ordinary gjxl timing uses `--warmups 2` (the default), `--reps 4`,
`--distance 1.2` (the default), and the complete sorted raw-tile list.
Libjxl runs `poc_driver full 8 1.2 16 1 /unused tiles...`. Input loading,
context creation, warmups, hash computation, repeat byte checks and optional
file writing are excluded from gjxl timing; returned buffers stay alive until
after timing. Process CPU time includes the low-rate NVML sampling overhead.
The encoder uses exactly the requested number of caller threads and one CPU
participant per context; CUDA driver helper threads are not encoder workers.

### Final ordinary measurements

All rows use the combined `alias-stack` candidate. The libjxl reference is
always e8, including the rows reporting gjxl e7. Ratios use the arithmetic
mean of the before/after libjxl throughputs. poc120 has 120 tiles × four
repetitions; dev has 400 × four. Each is one short interleaved observation,
not a confidence interval. Production remained active throughout.

| Set | Effort | Contexts | Candidate tiles/s | Unchanged gjxl tiles/s | Libjxl e8 before / after | × libjxl | × unchanged gjxl | CPU cores busy | Sampled VRAM MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| poc120 | 8 | 8 | 141.317 | 107.160 | 18.858 / 18.098 | 7.648 | 1.319 | 7.203 | 1054 |
| poc120 | 8 | 16 | 136.146 | 90.876 | 18.375 / 16.329 | 7.846 | 1.498 | 7.870 | 1534 |
| poc120 | 7 | 8 | 188.892 | 188.973 | 16.717 / 15.957 | 11.562 | 1.000 | 4.875 | 1086 |
| poc120 | 7 | 16 | 212.116 | 91.701 | 19.220 / 17.344 | 11.602 | 2.313 | 7.489 | 1566 |
| dev | 8 | 16 | 185.190 | 130.731 | 19.816 / 19.588 | 9.400 | 1.417 | 13.437 | 1534 |
| dev | 7 | 16 | 364.802 | 228.640 | 19.230 / 19.033 | 19.068 | 1.596 | 8.952 | 1534 |

| Set | Effort | Contexts | Latency p50 ms | p95 ms | p99 ms | Maximum ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| poc120 | 8 | 8 | 57.611 | 84.939 | 96.614 | 108.263 |
| poc120 | 8 | 16 | 113.288 | 181.894 | 220.595 | 261.568 |
| poc120 | 7 | 8 | 41.149 | 65.230 | 78.789 | 89.953 |
| poc120 | 7 | 16 | 74.154 | 112.862 | 131.165 | 148.062 |
| dev | 8 | 16 | 80.748 | 137.763 | 161.593 | 230.035 |
| dev | 7 | 16 | 42.387 | 64.005 | 87.017 | 141.497 |

### Identity and decoder gate

The final candidate's 120 + 400 tiles at both efforts match the baseline
per file in both byte count and SHA-256. All 37 complete retained benchmark
inventories, including repeated outputs and profiling ranges, also match.
The aggregate digest is SHA-256 over the ordered per-file hex digests, each
followed by a newline; it is not a digest of concatenated codestream bytes.

| Set | Effort | Outputs | Total bytes | Aggregate SHA-256 |
| --- | ---: | ---: | ---: | --- |
| poc120 | 7 | 120 | 2856042 | `2896103b8abe17377e9415e6a4eb62129d9f0c6075374dd1eaf121c8d76393c7` |
| poc120 | 8 | 120 | 2821848 | `89649b11171ef05606c8695b0271bbda2bb855fa39ff888c362cb874d9a64941` |
| dev | 7 | 400 | 5470954 | `45bd5f2abaf2891b6737c92ac69ba008546f61a99634761913dc62d9dadc0900` |
| dev | 8 | 400 | 5396044 | `29bd5513918ea9f421560d0f7115d77f476caa74d0d009e7ece2bb479fdc285e` |

The identity block in `run_pair.sh` invoked the following for each set/effort;
the decode sweep then succeeded under its own timing-lock hold:

```sh
# Inside the standard GPU container, through run_locked.sh:
/w/g3/bin/alias-stack --contexts 16 --effort 8 --reps 1 \
  --list /w/g3/lists/dev.txt --output-dir /w/g3/codestreams/alias-stack-dev-e8
python3 /w/g3/decode_outputs.py alias-stack
# Decoder invocation per output (eight concurrent single-thread processes):
/w/wp0/libjxl/build/tools/djxl INPUT.jxl - --output_format=pfm --num_threads=1 --quiet
```

The decoder records are `raw/conformance-alias-stack.json`: **1040/1040 pass,
zero failures** with PFM output. See the observed integer-output limitation
below. No new image-quality measurements are needed for byte-identical output.

```sh
python3 /Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/G3/summarize_gate.py
# Expected exit 2: correctness passes; the measured speed gate is unmet.
python3 /Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/G3/analyze_profiles.py
```

`measurements/` holds ordinary JSON records, `verification.json` holds full
inventory comparisons and paired ratios, and `profile-summary.json` holds
reduced trace/hook data, including the final host-only profile. `gate.json`
records the explicit failed speed verdict and passed correctness checks.
`measurements/` also includes marked diagnostic and identity runs; use the
paired rows above for speed, rather than selecting the fastest diagnostic run.

## Deviations and blockers

The throughput target is the blocker. Both tested candidates miss it; the
PLAN's two-miss rule stops further optimization. `profile.md` explains lane
contention, the e8 CPU entropy cost, and remaining batching/graph/allocation
options with explicit estimates. Production load requires paired measurements;
only Claude may confirm clean-window throughput. No public batch API was added
because no true multi-image GPU batch implementation landed.

Two harness setup failures are preserved, not timing results: the first
diagnostic hook call rejected a null test backend (fixed by explicit backend
lanes), and `screen1` launched before its candidate executable copy completed
(exit 127; rerun as `screen2`).

Some queued GPU runs returned exit 75 before launching because only 5935 MiB
was free. Those have no timing result. The required runs subsequently completed
with adequate headroom under the shared lock; all original failure logs remain.
No G3 containers or timing jobs remain running. Final remote disk use is 2.4 GB.

VRAM is sampled at tile boundaries, not an exact device allocation high-water
mark. The final Nsight capture additionally reports a 1 GiB CUDA memory-pool
high-water value, which excludes other driver/context allocations. The 1566 MiB
process sample is below even a decimal 2048 MB limit, but neither measurement
proves the absence of unsampled transient spikes. Admission capacity is
unlimited; its C-adapter planning cost is not separately instrumented. These
measurement limitations are explicit in `profile.md` and `gate.json`.

The first stock-decoder sweep requested integer PPM and all outputs failed
at `JxlDecoderSetImageOutBitDepth`, before useful decode output. A PFM smoke
decode succeeds with the same stock binary, producing a 512×512 float image.
The complete PFM sweep passes **1040/1040**, zero errors. The original failure records remain
as `conformance-alias-stack-ppm-failed.json`; they are not suppressed or
counted as successful conformance. `jxlinfo` is not built in the WP0 tools tree.
The existing header writer explicitly declares float32 linear sRGB
(`src/codestream/headers.cpp`); this behavior is unchanged by G3.
Explicit `--bits_per_sample=8` did not fix the pinned decoder's PPM path.
PFM conformance does not qualify integer-output/GDAL consumer compatibility;
G5 must check that existing limitation against the actual COG runtime.

## Intended commits for review

Leave all work uncommitted for Claude. Suggested separation:

1. `Add satellite CUDA tile benchmarks and profiling tools` — `CMakeLists.txt`,
   `tools/satellite_tile_bench.cpp`, `tools/satellite_tile_profile.cpp`,
   `REPORT.md`, `profile.md`; results and runners remain in the permitted
   satellite `results/G3/` directory.
2. `Increase CUDA lanes for concurrent tile encoding` —
   `src/codestream/workflow.cpp`. Experimental: do not characterize this alone
   as an e8 speedup. Initial e8 observations regress; the combined candidate
   and clean-window review must govern acceptance. Other image sizes have not
   received a throughput/memory regression screen.
3. `Use bounded stack scratch for ANS alias tables` —
   `src/codestream/ans.cpp`. Preserves worklist order and output bytes; reduces
   temporary allocation/accounting work and updates its storage bound.
