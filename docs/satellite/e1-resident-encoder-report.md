# E1: resident CUDA encoder with device RGB8 input

**Gate passed, 2026-10-17.** No blockers. Changes are uncommitted on `e1-device`
(base `bdafca7`). Claude can review and rerun the commands below. Production
services stayed running throughout; clean-window confirmation remains Claude's.

Evidence: `/Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/E1/`.
`gate.json` aggregates the checks. Remote source/builds, codestreams and raw
logs are in `/root/jxl-hybrid/e1/` (1.9 GB, below the 50 GB limit).

## What changed

- Added the four C functions and structs from PLAN-E2E.md. Existing C APIs and
  default codestreams are unchanged, verified against the pre-E1 G4 binary.
- An encoder owns private CUDA lanes, nonblocking streams, completion events,
  fixed device arenas, an event-join stream, and persistent CPU workers.
  Creation initializes the conversion table and warms efforts 1/7/8/10.
  Encoding suballocates existing arenas; it never falls back to cudaMalloc.
- A templated first kernel reads caller RGB8 using channel/pixel/row strides,
  zero-fills outside the valid rectangle, and performs sRGB lookup plus opsin.
  It uses the same rounded 256-entry table and arithmetic as the old path.
  Device encoding has no host RGB allocation/conversion/upload. Resident host
  encoding uploads RGB8 once and uses that same kernel.
- The internal resident workflow accepts source geometry without host samples.
  Device images still undergo the existing backend validation; CPU input
  validation stays enabled on CPU paths.
- Concurrent batches rotate one tile at a time through a queue. Worker count
  is `min(contexts, cpu_threads)`; all contexts are created up front. Each lane
  is used exclusively by one worker, including its arena and reusable events.
- Producer dependencies use `cudaStreamWaitEvent`. Each lane records input
  consumption immediately after the fused kernel, and the join stream records
  the batch's consumed event after all those reads. Errors drain submitted work
  and leave every output empty. Destroy requires callers to finish their calls.
- CUDA runtime/driver validation ensures the selected primary context is used.
  DCT tables initialize once per CUDA context, avoiding rewrites racing live lanes.

## Gate results

| Check | Result |
| --- | --- |
| poc120 + dev identity | 520 tiles × e8-balanced/e7/e8; resident host, pitched HWC and tight CHW match `gjxl_encode`. |
| Independent pre-E1 reference | All **1,560** codestreams also match G4's existing `gjxl_tiles` byte-for-byte. |
| Edges/layouts | 1×1, 1×512, 512×1, 511×509, 31×27, 257×199, 512×512; three presets; HWC3, HWC4, tight CHW, pitched CHW, and resident host all match explicitly zero-padded legacy input. |
| Thread safety | Six concurrent callers × three batches; byte identity passes. |
| Primary context/events | CUDA C++ CuPy-equivalent test delays the producer and overwrites **24 input tiles across two contexts** as soon as consumed completes, before encode returns; output remains identical. |
| Stock decode | Pinned stock djxl decoded **1,560/1,560**, zero failures. |
| Steady allocation | nsys records **zero** device allocation/free, event-create or stream-create calls during the 120-tile device range. |
| RGB H2D | **0 bytes**. Exactly 120 fused device-RGB8 kernels; largest remaining H2D transfer is 98,304 bytes. |
| VRAM | **1,918 MiB** at 16 contexts; **1,564 MiB** at 12; both below 2,048 MiB including CUDA module/runtime overhead. |
| ASan/UBSan | Final functional gate and existing C API test exit **0**, with empty stderr and leak detection enabled. |
| Endurance | **10,000 measured encodes** (+800 warm-up), flat VRAM and flat host RSS after warm-up. |

Corpus byte totals, e8-balanced / e7 / e8: **8,330,349 / 8,325,436 /
8,216,332**. The e8-balanced split is poc120 **2,856,680**, dev **5,473,669**.
Identity means no new quality sweep or held-out access was needed.

### Throughput

All rates below are total tiles / total measured seconds, not an average of
rounded instantaneous rates. Normal services remained active. Each bracket
held the timing lock for well under five minutes and alternated old G4 runs
with resident H-D-D-H batches.

| Set, contexts | Device tiles/s | Resident host tiles/s | Old G4 host tiles/s |
| --- | ---: | ---: | ---: |
| poc120, 12, lighter load | **945.1** | 945.8 | — |
| dev, 12, lighter load | **1114.2** | 1128.4 | — |
| poc120, 16, initial run | **936.5** | 905.6 | — |
| dev, 16, loaded run | **556.7** | 550.3 | — |
| poc120, 12, G4 bracket under heavy load | **496.3** | 476.6 | 331.8 |
| dev, 12, G4 bracket under heavy load | **534.8** | 521.3 | 391.1 |

The brackets pass the relative gate: device is **4.1% / 2.6% faster** than
resident host and **49.6% / 36.7% faster** than pre-E1 G4. The separate
12-context runs exceed the 900 tiles/s target on both sets. Those short,
lighter-load comparisons put resident host and device within 0.1–1.3%; all
samples, including that variation, are retained in `gate.json`. Claude should
use a clean window for the definitive absolute comparison.

Create/destroy measured once per process: **1.921 s / 4.48 ms** at 12 contexts;
**2.450 s / 5.08 ms** at 16 in the initial poc120 run. Later loaded runs are
also retained. These costs are outside the steady-state timing ranges.

### Transfer profile and memory

`profiles/device-steady.nsys-rep` and `.sqlite`, summarized by
`profile-summary.json`, cover 120 e8-balanced device CHW tiles, 12 contexts:

- RGB H2D **0**; all H2D **74,189,016 bytes**, **618,241.8 bytes/tile**.
- D2H **194,021,714 bytes**, **1,616,847.6 bytes/tile**.
- D2D **379,453,440 bytes**, **3,162,112 bytes/tile**.
- **51,866 kernels**, **432.2167/tile**.
- **4,440 stream + 1,079 event synchronizations**, **45.9917/tile**.
- Remaining copies are the existing transform/quantization metadata and
  coefficient/token/frame pipeline. E1 does not optimize those later stages.

Every explicit encoder device allocation belongs to fixed arenas, at most
**88 MiB/context**. A conservative **640 MiB** allowance is charged to the
configured cap for primary-context/kernel/module/static storage; a smaller cap
reduces each arena and creation fails if its warm-up does not fit. No
per-encode allocation fallback exists. The measured 16-context arena total is
1,408 MiB, plus about 510 MiB runtime/module overhead = 1,918 MiB.

Caller input storage is separate. For dev, NVML reports 2,430,599,168 bytes
including 400 caller allocations (400 MiB actual backing, 300 MiB requested).
Subtracting that backing gives the 1,918 MiB encoder footprint. The later
bench logs explicitly measure this before/after input allocation delta.

Across the endurance run VRAM is exactly 2,430,599,168 bytes. Host RSS ranges
693,817,344–693,899,264 bytes, then remains **693,899,264 bytes** from encode
5,200 through 10,000 (zero tail growth). All 25 batches produce the same byte
total. Destroy releases private arenas; shared CUDA runtime/modules remain
until process exit. `endurance.jsonl` preserves every sample.

## Reproduction commands

Local source sync (no .git/build/third_party mutation):

```sh
rsync -az --exclude=.git --exclude='build*' --exclude=third_party ./ root@sat-5090:/root/jxl-hybrid/e1/gjxl/
scp tools/e1/run_locked.sh root@sat-5090:/root/jxl-hybrid/e1/run_locked.sh
```

Build inside `satellite-cujpegxl-build:cuda12.8`, mounted with
`-v /root/jxl-hybrid:/w`, `--cpus=8`, working directory `/w/e1/gjxl`:

```sh
nice -n 10 cmake -S . -B build/e1 -G Ninja -DCMAKE_BUILD_TYPE=Release -DGJXL_ENABLE_CUDA=ON -DGJXL_ENABLE_METAL=OFF -DGJXL_ENABLE_LIBJXL_REFERENCE=OFF -DCMAKE_CUDA_ARCHITECTURES=120 -DGJXL_BUILD_SHARED_LIBRARY=ON -DGJXL_BUILD_BENCHMARKS=ON
nice -n 10 cmake --build build/e1 --target gjxl_shared gjxl_resident_gate gjxl_c_api_test satellite_tile_bench -j8
```

Sanitizer build uses the same CUDA/benchmark settings, `-B build/asan`,
`-DCMAKE_BUILD_TYPE=RelWithDebInfo`,
`-DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer'`, and
`-DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined` /
`-DCMAKE_SHARED_LINKER_FLAGS=-fsanitize=address,undefined`. Build targets
`gjxl_resident_gate gjxl_c_api_test` with `nice -n 10` and `-j8`.

Run on sat-5090. The wrapper checks ≥6 GiB free before GPU launches, takes
`flock /root/jxl-hybrid/locks/timing.lock`, bounds the hold with a 260-second
timeout, uses `--rm --pid=host --cpus=16`, and cleans up its own container.
It records stdout, stderr, metadata and (latest version) the exit code.

```sh
bash /root/jxl-hybrid/e1/run_locked.sh functional-final /w/e1/gjxl/build/e1/gjxl_resident_gate test 2 1
bash /root/jxl-hybrid/e1/run_locked.sh identity /w/e1/gjxl/build/e1/gjxl_resident_gate identity 16 1 /w/e1/codestreams /w/corpus/poc120 /w/corpus/dev
bash /root/jxl-hybrid/e1/run_locked.sh bench-poc120-c12 /w/e1/gjxl/build/e1/gjxl_resident_gate bench 12 5 /w/corpus/poc120
bash /root/jxl-hybrid/e1/run_locked.sh bench-dev-c12 /w/e1/gjxl/build/e1/gjxl_resident_gate bench 12 5 /w/corpus/dev
bash /root/jxl-hybrid/e1/run_locked.sh bench-poc120-c16 /w/e1/gjxl/build/e1/gjxl_resident_gate bench 16 3 /w/corpus/poc120
bash /root/jxl-hybrid/e1/run_locked.sh bench-dev-c16 /w/e1/gjxl/build/e1/gjxl_resident_gate bench 16 5 /w/corpus/dev
bash /root/jxl-hybrid/e1/run_locked.sh endurance /w/e1/gjxl/build/e1/gjxl_resident_gate leak 16 25 /w/corpus/dev
bash /root/jxl-hybrid/e1/run_locked.sh asan-final /usr/bin/env ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:protect_shadow_gap=0 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 /w/e1/gjxl/build/asan/gjxl_resident_gate test 2 1
bash /root/jxl-hybrid/e1/run_locked.sh c-api-final /usr/bin/env ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:protect_shadow_gap=0 UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 /w/e1/gjxl/build/asan/gjxl_c_api_test
E1_CPU_ONLY=1 bash /root/jxl-hybrid/e1/run_locked.sh conformance python3 /w/e1/gjxl/tools/e1/decode_gate.py /w/e1/codestreams /w/wp0/libjxl/build/tools/djxl
```

G4 brackets, replacing all `poc120` occurrences with `dev` and baseline
reps `10` with `5` for the dev run:

```sh
bash /root/jxl-hybrid/e1/run_locked.sh bracket-poc120-c12 /bin/bash -lc 'for round in 1 2; do /w/g4/gjxl/build/g4/gjxl_tiles bench 12 10 1.2 8 --entropy-behavior balanced /w/corpus/poc120/*.rgb; /w/e1/gjxl/build/e1/gjxl_resident_gate bench 12 5 /w/corpus/poc120; done; /w/g4/gjxl/build/g4/gjxl_tiles bench 12 10 1.2 8 --entropy-behavior balanced /w/corpus/poc120/*.rgb'
```

The independent byte baseline used that same G4 executable's `dump DIR 1.2
EFFORT [--entropy-behavior balanced]` command, with all poc120/dev `.rgb`
files, at e8-balanced/e7/e8. `g4-byte-identity.json` contains all hashes and
zero mismatches. `conformance.jsonl` contains stock-decoder results and hashes.

```sh
bash /root/jxl-hybrid/e1/run_locked.sh trace /w/g3/nsys/opt/nvidia/nsight-systems/2025.6.3/bin/nsys profile --trace=cuda,nvtx --sample=none --cpuctxsw=none --cuda-memory-usage=true --capture-range=cudaProfilerApi --capture-range-end=stop --force-overwrite=true -o /w/e1/profiles/device-steady /w/e1/gjxl/build/e1/gjxl_resident_gate trace 12 1 /w/corpus/poc120
# In the build container, CPU-only:
/w/g3/nsys/opt/nvidia/nsight-systems/2025.6.3/bin/nsys export --type sqlite --force-overwrite=true -o /w/e1/profiles/device-steady.sqlite /w/e1/profiles/device-steady.nsys-rep
# Locally, after copying the evidence directory:
python3 tools/e1/summarize_profile.py /Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/E1/profiles/device-steady.sqlite --tiles 120
python3 tools/e1/collect_results.py /Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/E1
```

Release shared-library SHA-256:
`1d4467be800abdf3c8ee2b0c8cc8cf8fa45251087bfa6192ad3b08a1bbd35fd7`.
G4 reference executable SHA-256:
`1bbefd0211026ba0784a072e1706af1c14f26fd49e642853a958f9a28f384085`.

## Deviations, integration notes, resolved issues

- No scope deviation or current blocker. No commits, pushes, service changes,
  operational-container changes, or sub-agents. No held-out data accessed.
- CUDA's default ASan shadow-gap protection caused `cudaSetDevice` to return
  out-of-memory despite 10 GiB free. `protect_shadow_gap=0` permits CUDA's
  virtual-address reservations; host ASan, UBSan and leak detection remain
  enabled. Final sanitizer runs have exit code 0 and empty stderr.
- A profiling attempt was deferred when only 5,009 MiB was free; it ran later
  after capacity returned. Two SSH connection attempts briefly timed out and
  then recovered. These caused no service intervention or incomplete gate.
- The synchronous ABI has no submission-ready handshake. CUDA queries an
  unrecorded event as complete, and a stream wait observes its current record.
  A caller polling during encode must first arm consumed_event with a pending
  record on an independent stream, as the 24-tile gate test does. Otherwise
  query/wait after return. This native CUDA behavior is documented in the
  public header; E2 can conservatively recycle after return.
- Smaller-than-512 inputs produce 512×512 codestreams; legacy comparison
  explicitly pads those pixels first, matching the G4 satellite tile contract.
- Driver/module allowance is conservative for the qualified SM120/CUDA 12.8
  environment. Explicit device allocations are hard-bounded by the arenas;
  the reported process VRAM measurement includes runtime/module overhead.

## Intended commits (Claude commits at review)

1. **Add resident CUDA tile encoder with device RGB8 input**
   - `CMakeLists.txt`, `include/gjxl/gjxl.h`
   - `src/c_api/gjxl.cpp`, `image_conversion.{h,cpp}`, `resident_encoder.{h,cpp}`
   - `src/codec/adaptive_quantization.cpp`, `src/codec/adaptive_quantization_internal.h`,
     `src/codec/quantization_pipeline.cpp`
   - `src/codestream/workflow.cpp`, `workflow_internal.h`
   - `src/gpu/cuda/cuda_backend.{h,cpp}`, `cuda_backend_internal.h`,
     `cuda_aq_exact_kernels.{h,cu}`, `cuda_input_preparation.cpp`, `cuda_rgb8_input.h`
   - `src/gpu/ops/adaptive_quantization.cpp`
2. **Qualify resident tile encoding and document E1 gates**
   - `tools/e1/resident_gate.cpp`, `run_locked.sh`, `decode_gate.py`,
     `summarize_profile.py`, `collect_results.py`, `REPORT.md`
   - Evidence stays uncommitted in the authorized satellite `results/E1/` directory.
