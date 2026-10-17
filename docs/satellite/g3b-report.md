# G3b entropy and accounting report

Status: **stopped at the measured poc120 throughput limit**, 2026-10-17.
Both performance candidates missed the full gate; no further performance edits
were made under PLAN's two-miss rule. Final repeated timing and profiling are
complete. The final candidate's best ordinary e8 throughput is **422.710 tiles/s
on poc120** (8.642× its libjxl brackets) and **526.342 on dev** (10.306×).
Dev has a passing measured observation; poc120 remains below 503 tiles/s.
No full gate pass or Claude clean-window confirmation is claimed.

**Correctness passes:** 1,040/1,040 final poc120/dev × e7/e8 outputs are
byte-identical to the frozen satellite baseline and decode with stock djxl to
PFM. All 50 retained benchmark inventories match; all seven focused tests pass.
Peak sampled final GPU memory is **1630 MiB (1,709,178,880 bytes)**, with at most
**16 encoder CPU participants**. This is within the 2048 MB limit, subject to
the sampling qualification below.

## Scope and provenance

- Worktree starts at `satellite` commit
  `2c7c72562264e2d01eaa13930e8569d1637da924`, initially clean.
- Host input: independent 512×512 RGB8 sRGB tiles, bare JXL output, d1.2,
  unchanged efforts 7 and 8. No preset, image math, GPU kernel, API or search
  policy changes. No held-out corpus was touched.
- Read COMMON.md, PLAN.md, GJXL-EVALUATION.md, G3b's brief and G3's integration
  REPORT.md/profile.md. No sub-agents, commits, pushes or integration-tree edits.
- Remote work root: `/root/jxl-hybrid/g3b/`. The base tree was copied once,
  then local sources were rsynced excluding `.git`, `build*` and `third_party`.
  Frozen executables: `bin/baseline`, `bin/hist-scratch`, `bin/map-reuse`, plus
  their `profile-*` companions. Baseline was built before source edits.
- Evidence root:
  `/Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/G3b/`.
  `source.patch` is the final code diff; `hist-scratch.patch` is candidate 1.
  `source-manifest.json` and `build/binary-sha256.txt` identify the tested source
  and binaries. The final ans.cpp hash matches the remote built source.

## Changes and rationale

1. **Bounded histogram scratch (`hist-scratch`).** Private 256-entry frequency
   arrays replace managed allocations for trial histograms. Configuration
   candidates retain their frequencies inline; cost-only cluster refinement
   uses stack scratch. The known configuration count is reserved once. Only
   selected model frequencies acquire managed backing. The storage plan counts
   the larger inline objects and removes the eliminated separate arrays.
   Population arithmetic, candidate iteration and strict comparison/tie order
   are unchanged.
2. **Context-map reuse (`map-reuse`, final).** Alphabet-width candidates share
   the exact partition. Compress its context map once and copy the resulting
   encoding into subsequent candidates, avoiding repeated raw/MTF, Prefix/ANS
   and RLE searches. Each model still owns accounted cache storage. Public
   mutable-model validation remains unchanged. This builds on candidate 1.

The source change is confined to `src/codestream/ans.cpp`. Existing finite
reservation, allocation-failure, entropy and deterministic parallel tests cover
both changes. No allocation accounting is disabled for retained storage.

## Build and focused tests

Inside `satellite-cujpegxl-build:cuda12.8`, mounted with
`-v /root/jxl-hybrid:/w`, Docker `--cpus=8` and no GPU for builds:

```sh
cd /w/g3b/gjxl
nice -n 10 cmake -S . -B build/g3b -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DGJXL_ENABLE_CUDA=ON -DGJXL_ENABLE_METAL=OFF \
  -DGJXL_ENABLE_LIBJXL_REFERENCE=OFF -DCMAKE_CUDA_ARCHITECTURES=120 \
  -DGJXL_BUILD_BENCHMARKS=ON -DGJXL_BUILD_TESTS=ON
nice -n 10 cmake --build build/g3b --target satellite_tile_bench \
  satellite_tile_profile gjxl_entropy_test gjxl_ans_reverse_bits_test \
  gjxl_resource_budget_test gjxl_managed_allocator_test gjxl_c_api_cpp_test \
  gjxl_entropy_storage_plan_test gjxl_codestream_batch_workflow_test -j8
nice -n 10 ctest --test-dir build/g3b --output-on-failure -R \
  '^(entropy|ans_reverse_bits|resource_budget|managed_allocator|c_api_cpp|entropy_storage_plan|codestream_batch_workflow)$'
```

Baseline build: 128 steps. Each candidate rebuild: 10 steps. Candidate 1:
**7/7 tests pass, 4.96 s**. Final candidate: **7/7 pass, 4.20 s**, including
storage-plan reservation and allocation-failure sweeps. Full logs are in
`build/build-baseline.log`, `build/build-hist-scratch.log` and
`build/build-map-reuse.log`. Final `git diff --check` passes.

## Byte identity and decoder gate

The complete identity/decode gate ran after each source candidate. Both candidates
match every baseline file in byte count and SHA-256. All repeated outputs are
also compared byte-for-byte by satellite_tile_bench after timing. Aggregate
SHA-256 is over ordered per-file hex digests, each followed by a newline.

| Set | Effort | Outputs | Total bytes | Aggregate SHA-256 |
| --- | ---: | ---: | ---: | --- |
| poc120 | 7 | 120 | 2856042 | `2896103b8abe17377e9415e6a4eb62129d9f0c6075374dd1eaf121c8d76393c7` |
| poc120 | 8 | 120 | 2821848 | `89649b11171ef05606c8695b0271bbda2bb855fa39ff888c362cb874d9a64941` |
| dev | 7 | 400 | 5470954 | `45bd5f2abaf2891b6737c92ac69ba008546f61a99634761913dc62d9dadc0900` |
| dev | 8 | 400 | 5396044 | `29bd5513918ea9f421560d0f7115d77f476caa74d0d009e7ece2bb479fdc285e` |

All three stock-decoder sweeps (baseline and both candidates) pass 1,040/1,040.
The final record is `raw/conformance-map-reuse.json`. Per-output invocation,
with eight concurrent single-thread decoder processes:

```sh
/w/wp0/libjxl/build/tools/djxl INPUT.jxl - --output_format=pfm --num_threads=1 --quiet
```

G3 already documented an integer-PPM output-bit-depth setup limitation in the
pinned decoder for gjxl's float-linear codestream headers. The successful PFM
check qualifies stock decoding; integer/GDAL consumer compatibility remains G5
work. These edits do not change headers or decoded pixels. No new quality
measurements are needed for identical codestreams.

## Ordinary throughput gate

The existing public-C-API benchmark loads raw RGB8 tiles before timing, creates
one context per caller, uses two warmups per context and four complete corpus
repetitions, and retains outputs through the measured interval. Hashing,
repeat comparison and file writing occur after timing. CPU cores busy is
process user+system time divided by wall time. CPU participation is one worker
per context, capped by the shared execution domain; driver/profiler helpers are
not encoder participants. No profiler runs during these measurements.

Each row brackets frozen baseline and candidate with libjxl e8 at sixteen
single-thread tile workers. Odd rounds run baseline then candidate; even
rounds reverse that order. Ratios use the arithmetic mean of the two libjxl
throughputs. The reference uses `poc_driver full 8 1.2 16 1 /unused tiles...`.
Every set uses its entire sorted list (poc120: 120 tiles; dev: 400).

| Set | Candidate | Contexts | Round | Candidate tiles/s | Baseline tiles/s | Libjxl before / after | × libjxl | × baseline | CPU busy | VRAM MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| poc120 | hist-scratch | 8 | 1 | 377.491 | 349.725 | 46.477 / 45.753 | 8.186 | 1.079 | 7.759 | 1086 |
| poc120 | hist-scratch | 16 | 1 | 301.488 | 224.905 | 47.081 / 45.680 | 6.500 | 1.341 | 14.609 | 1534 |
| poc120 | map-reuse | 8 | 1 | 147.187 | 118.174 | 18.714 / 16.636 | 8.327 | 1.246 | 7.132 | 1022 |
| poc120 | map-reuse | 8 | 2 | 148.984 | 124.217 | 16.658 / 17.338 | 8.765 | 1.199 | 5.643 | 1054 |
| poc120 | map-reuse | 8 | 3 | 422.710 | 383.379 | 48.827 / 49.000 | 8.642 | 1.103 | 7.836 | 1022 |
| poc120 | map-reuse | 16 | 1 | 157.937 | 122.329 | 16.240 / 16.336 | 9.697 | 1.291 | 8.457 | 1534 |
| poc120 | map-reuse | 16 | 2 | 156.118 | 121.042 | 18.066 / 17.050 | 8.892 | 1.290 | 9.031 | 1534 |
| poc120 | map-reuse | 16 | 3 | 296.415 | 193.219 | 38.222 / 25.085 | 9.364 | 1.534 | 14.519 | 1630 |
| dev | hist-scratch | 16 | 1 | 135.044 | 154.400 | 22.689 / 18.290 | 6.591 | 0.875 | 6.284 | 1534 |
| dev | map-reuse | 8 | 1 | 215.451 | 149.996 | 18.430 / 18.373 | 11.708 | 1.436 | 7.498 | 1086 |
| dev | map-reuse | 8 | 2 | 171.078 | 120.503 | 18.622 / 20.325 | 8.785 | 1.420 | 7.244 | 1118 |
| dev | map-reuse | 8 | 3 | 526.342 | 475.763 | 50.978 / 51.167 | 10.306 | 1.106 | 7.875 | 1086 |
| dev | map-reuse | 16 | 1 | 172.912 | 147.928 | 19.338 / 18.150 | 9.225 | 1.169 | 6.865 | 1534 |
| dev | map-reuse | 16 | 2 | 197.861 | 162.243 | 19.188 / 18.739 | 10.434 | 1.220 | 6.815 | 1534 |
| dev | map-reuse | 16 | 3 | 193.754 | 198.886 | 21.157 / 19.029 | 9.643 | 0.974 | 8.865 | 1534 |

All observations, including the unfavorable dev rows, are retained. These are
short loaded comparisons, not confidence intervals. The final candidate's
paired ratios to baseline span 0.974–1.534. Round 3 at c8 captures a lighter-load
period: poc120 422.710 (1.103× baseline), dev 526.342 (1.106×). Its subsequent
c16 check waited for Claude's independent clean-window lock and is a separate
load observation; libjxl's changing brackets make that distinction visible.
Workers did not pause, stop, restart or reconfigure production services.
None of these worker results is claimed as Claude's clean-window acceptance.

Best poc120 at c8 has latency p50/p95/p99 18.081/28.820/34.197 ms; best dev at
c8 has 13.251/27.539/30.791 ms. All rows' latency, CPU and memory fields are in
`verification.json` and `gate.json`.

## Profile-backed limits

`profile.md` gives the complete before/after stage tables, perf attribution and
fresh Nsight CUDA/accounting comparison. At c16, baseline → scratch → final:

| Nested host phase (elapsed ms/call) | Baseline | Scratch | Final |
| --- | ---: | ---: | ---: |
| Entropy optimization | 46.027 | 26.905 | 27.090 |
| Histogram construction | 13.822 | 4.482 | 9.031 |
| Model construction | 19.330 | 15.089 | 6.628 |
| Exact token costing | 4.954 | 3.897 | 6.707 |

Production load differs between captures, and nested phases are not additive
wall-time savings. The final perf capture's leading gjxl self samples are
HybridUint conversion (17.36%), histogram construction (8.93%), partition
preparation (3.96%) and exact prepared-section costing (3.18%). Internal model
validation and table construction remain measurable costs.

Fresh traced allocation prepare/destruction/commit waits fall from
42.295/31.954/21.987 to 0.078/0.046/0.111 aggregate ms/tile. These durations are
from overlapping threads, and tracing magnifies the baseline's contention;
do not interpret their ratio as an ordinary speedup. The final process has
50.5% kernel-interval busy fraction, about 432 kernels, 61 stream syncs and
nine event waits per tile. DC quantization remains 1.740 summed GPU ms/tile.
Remaining options are exact conversion/cost reuse, reduced internal validation,
correctly accounted per-call model scratch, and eventually GPU batching or
fewer host handoffs. No further implementation was attempted after two misses.

Poc120 needs 503/422.710 = **1.190×** the best observed final throughput, or
about **16.0% less elapsed time per tile**, to meet the absolute target under
an otherwise identical schedule. This is arithmetic headroom, not a prediction
or extrapolated clean-window pass. The eight-context run already uses 7.836
CPU cores; raising contexts has not established the required throughput.

## Exact runners and reproduction

All scripts are retained in the evidence root and copied to `/root/jxl-hybrid/g3b`.
`run_locked.sh` checks at least 6144 MiB free before every GPU launch, holds the
shared timing lock, bounds a run at 260 seconds plus ten-second cleanup, and
removes its container. Grouped suites have a 250-second outer timeout plus
ten-second cleanup. Background perf and Docker children close fd 9. Ordinary
containers use `--cpus=16 --pid=host --gpus device=0` and the standard image.

Commands on sat-5090:

```sh
bash /root/jxl-hybrid/g3b/run_locked.sh identity-baseline gpu \
  bash /w/g3b/run_identity.sh baseline
bash /root/jxl-hybrid/g3b/run_suite.sh hist-scratch
bash /root/jxl-hybrid/g3b/run_suite.sh map-reuse
bash /root/jxl-hybrid/g3b/run_final.sh map-reuse
bash /root/jxl-hybrid/g3b/run_locked.sh final-round3 gpu bash -c \
  'bash /w/g3b/run_pair.sh poc120 8 map-reuse 3 && bash /w/g3b/run_pair.sh dev 8 map-reuse 3'
bash /root/jxl-hybrid/g3b/run_locked.sh final-round3-c16 gpu bash -c \
  'bash /w/g3b/run_pair.sh poc120 16 map-reuse 3 && bash /w/g3b/run_pair.sh dev 16 map-reuse 3'
```

The suites collect host hooks and perf at c1/c16, full identity/decode, paired
rounds, and final CUDA traces. Their already-complete-file checks allow a
VRAM-deferred suite to resume. `run_identity.sh` invokes, for each set/effort:

```sh
/w/g3b/bin/map-reuse --contexts 16 --effort 8 --reps 1 \
  --list /w/g3b/lists/dev.txt --output-dir /w/g3b/codestreams/map-reuse-dev-e8
python3 /w/g3b/decode_outputs.py map-reuse
```

Recompute local evidence:

```sh
cd /Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/G3b
python3 analyze_profiles.py
python3 summarize_gate.py  # expected exit 2: correctness/resources pass; poc120 speed fails
```

`raw/` holds all ordinary JSON, decoder records and command logs; `profiles/`
holds six host hooks, six perf captures/reports and two Nsight reports/SQLite
exports. `verification.json` checks every complete inventory and recomputes
paired ratios. `profile-summary.json` reduces the profiles. `gate.json` records
the explicit unmet speed verdict. Reports are copied beside the evidence.

## Deviations, blockers and resource qualifications

- The remaining blocker is poc120 throughput. Both candidate implementations
  missed the complete gate, so PLAN requires review/re-planning. Follow-up runs
  completed the evidence and used the frozen final binary; no third performance
  candidate was introduced.
- One profiling suite deferred with 3865 MiB free, and the final suite later
  deferred with 3823 MiB free. Their logs are retained. Both resumed with
  sufficient memory; no required check remains pending.
- The original separately queued baseline c16 job was cancelled while waiting;
  grouped suites completed the baseline profiles. No operational process was
  interrupted. Long shared-lock queues are reflected in the logs.
- PFM conformance inherits G3's integer-output qualification described above.
- NVML samples the current benchmark process at context-0 tile boundaries,
  including warmup, rather than continuously. The 1630 MiB peak is observed,
  not proof of an exact allocation high-water mark. Nsight additionally reports
  a 1 GiB CUDA pool high-water value, which excludes context/driver allocations.
  The benchmark domain has unlimited memory admission; this change does not
  implement a hard 2048 MB cap. Larger images/other efforts are not throughput
  qualified here.
- Final remote disk use is about 1.2 GB, well below 50 GB. All started GPU jobs,
  perf samplers and containers have completed; cleanup is checked before handoff.

## Intended commits for Claude

Leave changes uncommitted. Suggested separation:

1. `Use bounded scratch for ANS histogram search` — scratch/storage-plan parts
   of `src/codestream/ans.cpp`; candidate 1 diff is `hist-scratch.patch`.
2. `Reuse context maps across ANS alphabet candidates` — remaining ans.cpp
   change in `source.patch` relative to candidate 1.
3. `Document G3b gate results and remaining limits` — `REPORT.md`, `profile.md`.
   Evidence stays in the permitted satellite `results/G3b/` directory; no
   satellite repository changes were committed or otherwise rewritten.
