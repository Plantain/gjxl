# G2 preset work report

Both G2 gates PASS. Work complete; code remains uncommitted. Updated 2026-10-17.

## Gate results

**Gate 1 PASS:** 240/240 default codestreams are byte-identical to satellite:
120 poc120 tiles at each of e7/e8, d1.2; zero mismatches. Baseline revision:
`7216e07aff89346d25a52ea35ec8d27afba1e152`. The original satellite libraries and
the modified libraries were linked to the same dump driver. Per-tile SHA-256,
sizes, and comparison results are in `default-parity.json` and `parity.log`.

**Gate 2 PASS:** recommend **e7-aq3**, effort 7 with
`--aq-updates 3`. All six dev routes pass at bytes <= 1.000;
overall quality-feasible bytes are **0.986497**
at d1.2050, meeting the 0.990 margin target.
Worst-route bytes are **0.989682**. The route-optimal
distances together give **0.981645** overall bytes
and pass the overall quality limits. No single standard-grid distance satisfies
both quality and size on every route; use the per-route/product distances in
`preset.md` and `feasibility.json`.

| Contexts | Median tiles/s | vs gjxl e7 | vs gjxl e8 | CPU ms/tile | Peak encoder MiB | Rounds faster than e8 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 8 | 79.06 | 0.684x | 1.252x | 44.054 | 1080 | 4/6 |
| 16 | 233.92 | 0.935x | 1.926x | 23.832 | 1528 | 6/6 |

These are interleaved measurements under normal operational load, not clean
production-paused throughput. They establish the G2 relative-speed gate, not
the project's later 503 tiles/s target. Claude re-runs the gate and owns clean
qualification. No held-out evaluation was performed.

Selection: e7-aq3 retains balanced entropy and fast final CfL, while the third
AQ update supplies the quality margin that the cheaper one/two-update recipes
lack. It has the highest paired 16-context speed ratio among passing candidates
tested. E8-balanced is a close alternative with stronger eight-context timing
and 12/12 wins over e8, versus e7-aq3's 10/12. The small 16-context difference
between finalists needs clean-window confirmation; this is not a claim of a
globally optimal preset.

## What changed

Added independent C++ options, ABI-compatible appended C API fields, and flags
in `gjxl_encode` / `gjxl_tiles` for AQ updates, entropy policy, coefficient
orders, final CfL iterations, AC search spacing, and EPF sharpness. Also exposed
effort-derived fixed DCT8, initial quantization, Gaborish, AC adjustment,
adaptive quantization matrices, and DC integer-search policies. Existing DC
controls remain available. Defaults derive from effort.

The C options struct retains its original 28-byte prefix and appends fields
to 76 bytes. Reads and initialization respect `struct_size`, including partial
tails. New automatic sentinels are initialized explicitly. Added CMake target
`gjxl_tiles`, using the provided public-C tile driver with preset flags,
per-process CPU accounting, and a codestream dump mode for parity.

CUDA already supports nonlinear final CfL: automatic e8–10 uses eight
iterations on CUDA as well as Metal. Corrected comments and the misleading
resolver parameter name without changing that behavior. CUDA EPF sharpness
remains fixed. Sampled coefficient orders apply only to DCT8-only frames;
mixed-transform frames use full populations under either setting.

## Validation and candidate evidence

- Release CUDA SM120 build passed. CTest `c_api`, `c_api_cpp`, and
  `low_effort_strategy_policy`: **3/3 passed**, 0.35 seconds. Tests cover
  automatic/explicit e7 identity, every struct tail size from 28 through 76
  with write-boundary canaries, invalid overrides, and AQ storage planning.
- CLI automatic/explicit e7/e8 comparisons passed; six invalid flag values
  were rejected (`cli-check.log`).
- **26/26** GPU control smoke encodes decoded with stock djxl using the WP0
  float32 sRGB PFM protocol. Explicit CfL and fixed CUDA EPF identity checks
  passed (`knob-smoke.json`).
- **1320/1320** ordinary/profiled poc120 encodes were byte-identical across
  eleven recipes. `profile.jsonl` contains GPU submission stages, process CPU
  time, and serializer wall time. This diagnostic excludes public-C RGB8
  conversion and is separate from the throughput measurement.
- **18,000** completed dev candidate rows: 400 tiles × five standard distances
  per candidate. `analyze.py` invokes the unchanged project `feasible.py`,
  checks exact tile/distance coverage, and also checks shared distances and
  aggregate quality at the route-optimal operating points.

The five requested starting candidates and four refinements are defined in
`candidates.json`. One-AQ recipes fail the size gate because Butteraugli max-p95
tails constrain their usable distances. Balanced entropy with two AQ updates
fails CONUS (1.005276). Full coefficient orders alone exactly match all 2000
e7 rows; e7-both exactly matches e7-rate. Rate-optimized e7 preserves all 2000
decoded metric rows but showed no reliable speed advantage over e8 in its
original timing groups. E8-balanced preserves all 2000 default-e8 metric rows.
`preset.md` ranks candidates and reports every quality margin and relative cost.

## Commands and timing protocol

All remote files are under `/root/jxl-hybrid/g2/`. SSH prefix:
`ssh -o BatchMode=yes -o ConnectTimeout=10 root@sat-5090`.
Build command (private copy of `gjxl-base`, never the shared checkout):

```sh
docker run --rm --name g2-build --cpus=8 -v /root/jxl-hybrid:/w \
  -w /w/g2/gjxl satellite-cujpegxl-build:cuda12.8 bash -c '
  nice -n 10 cmake -S . -B build/cuda -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DGJXL_ENABLE_CUDA=ON \
    -DGJXL_ENABLE_METAL=OFF -DGJXL_ENABLE_LIBJXL_REFERENCE=OFF \
    -DGJXL_BUILD_TESTS=ON -DCMAKE_CUDA_ARCHITECTURES=120 &&
  nice -n 10 cmake --build build/cuda -j8 --target gjxl_tiles gjxl_encode \
    gjxl_c_api_test gjxl_c_api_cpp_test gjxl_low_effort_strategy_policy_test'
```

The immutable measured executable is `/root/jxl-hybrid/g2/bin/gjxl_tiles-v1`;
the baseline is `gjxl_tiles-satellite`. Binary/manifest hashes are in
`inputs.sha256`; final source hashes and base revision are in `source.json`.
Only comments/documentation changed after the measured binary was built.

Gate/evaluation commands and saved helpers:

```sh
# On sat-5090; helpers acquire the shared lock and check GPU memory.
bash /root/jxl-hybrid/g2/run_parity.sh
python3 /root/jxl-hybrid/g2/run_quality.py
python3 /root/jxl-hybrid/g2/run_speed.py e7-rate e7-full e7-both e8-aq2 e8-aq2-balanced
G2_SPEED_REPEATS=1 python3 /root/jxl-hybrid/g2/run_speed.py e7-rate-aq1 e8-aq1-balanced
python3 /root/jxl-hybrid/g2/confirm_speed.py e8-balanced e7-aq3
python3 /root/jxl-hybrid/g2/run_profile.py

# Locally, from satellite/codecs/jxl-gpu-hybrid/results/G2:
python3 analyze.py
python3 summarize_speed.py
python3 summarize_confirmation.py
python3 compare_rows.py
python3 merge_speed.py
python3 check_gate.py e7-aq3
```

Exact scoreboard and timing commands are preserved in runner logs and each
JSONL row's `command`. Quality and timing runners skip completed results; preserve the
existing evidence and use fresh output/cache IDs for a fresh rerun. Scoreboard
uses `--set dev --jobs 8`, five standard distances, and a unique immutable-v1
encoder ID for each recipe. Each quality chunk has a 240-second timeout and
resumes completed rows from its private cache.

Timing uses poc120, d1.2, 8/16 contexts (one CPU worker per context), plus a
16-thread libjxl e8 baseline. Initial candidates use two eight-sample groups
per context count; the one-AQ refinements use one group. Each group interleaves
two samples each of candidate/e7/e8/libjxl, with 720 encodes per GPU sample.
Ratios are geometric means of within-group median ratios.

Strong host-load drift motivated the final confirmation protocol: six rounds
cover all permutations of e7/candidate/e8, 240 encodes per GPU sample, and a
libjxl sample before/after. Ratios are geometric means of within-round ratios;
all ranges and individual ratios are retained. Each block owns the timing lock
throughout and has a 240-second timeout plus 10-second kill grace. Encoder VRAM
is sampled per process about every 100 ms, including warmup. `speed.jsonl`
combines both protocols; `speed-primary.jsonl` and `confirmation-speed.jsonl`
preserve their inputs. GPU/CPU diagnostic stages are in `profile.jsonl`.

Final evidence check: `python3 check_gate.py e7-aq3` passes both gates, validates
all 18,000 candidate rows and 1320 profiling identity checks, and writes
`gate.json`. The complete cost matrix contains 272 raw timing samples (192
primary and 80 confirmation). Maximum observed encoder VRAM across all timing
samples is 1624 MiB; the recommendation peaks at 1528 MiB. `git diff --check`
passes.

## Deviations, resource handling, and blockers

No remaining code blocker. The original C++ ABI test asserted total size 28;
it was updated to assert the unchanged prefix plus the extended total size.
An initial smoke harness used djxl's default PPM output and all cases failed
with `JxlDecoderSetImageOutBitDepth failed`. Re-running with the exact WP0
float32 sRGB PFM settings passed all 26 cases; no encoder fix was involved.
The initial failure is retained in `knob-smoke-ppm-default.json`. Consumer
runtime qualification remains G5 work.

Free VRAM temporarily dropped below the mandatory 6144 MiB threshold; guards
returned 75 and retried outside the timing lock. Shared-lock queues also delayed
work. No operational container/service was stopped, paused, restarted, or
reconfigured. Builds used `nice -n 10` and at most eight CPUs; all timings used
the shared lock for at most five minutes. All experiments used private paths.

Final remote audit at 2026-10-17 06:07 UTC: no G2 containers or evaluation
runners remain active. The private work directory occupies 676 MiB, below the
50 GB allowance. No blockers remain.

Read COMMON, PLAN, GJXL-EVALUATION, and the G2 brief in the requested order.
No applicable AGENTS.md was found. No sub-agents, commits, pushes, or edits to
other workers' files. Evidence is copied to:
`/Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/G2/`.

## Intended commits (left uncommitted for Claude)

1. `Expose independent VarDCT preset controls`
   - `include/gjxl/gjxl.h`, `src/c_api/gjxl.cpp`
   - `src/codestream/workflow.h`, `src/codestream/workflow_internal.h`,
     `src/codestream/workflow.cpp`, `src/codestream/encoder.h`
   - `tools/gjxl_encode.cpp`, `docs/c-api.md`
   - `tests/c_api_test.c`, `tests/c_api_cpp_test.cpp`,
     `tests/low_effort_strategy_policy_test.cpp`
2. `Add satellite tile preset evaluation driver`
   - `CMakeLists.txt`, `tools/gjxl_tiles.cpp`
3. `Record G2 preset gate evidence`
   - `REPORT.md`; the project owner can record the separate satellite
     `results/G2/` artifacts when integrating this work.
