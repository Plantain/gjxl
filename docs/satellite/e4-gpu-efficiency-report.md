# E4 final report

**Final focused gate passed, 2026-10-17 UTC. Ready for Claude to commit.**
DC pipelining and blocking waits are enabled by default; Butteraugli graphs
remain an optional experiment. No further clean windows or worker tasks are
pending. No commits, production changes, or loaded-host throughput decisions
were made.

## Final defaults and implementation

| Variable | Unset | Explicit opt-out / opt-in |
| --- | --- | --- |
| `GJXL_E4_DC_PIPELINE` | On | Only exact `"0"` disables |
| `GJXL_E4_BLOCKING_WAITS` | On | Only exact `"0"` disables |
| `GJXL_E4_BUTTERAUGLI_GRAPH` | Off | Only exact `"1"` enables |

Options are read once before workers start. Empty or malformed values preserve
the default-on behavior for DC/blocking and leave graphs disabled. The final
E4 mask is **3**. E4 `environment()` explicitly selects these defaults;
`environment([])` selects all-off, and `unset=True` removes the variables to
exercise the library defaults. E3's helper fixes E4 to the same defaults and
supports `blocking_waits=False, dc_pipeline=False` to reproduce all-off.

- DC quantization pipelines X/Y/B in one 192-thread block for fields up to
  64×64, with B one wave behind Y. It preserves predictor arithmetic and
  dependencies, halves the DC launch count, and adds no device buffers.
  Larger fields retain the original dispatch.
- Host waits use blocking completion events and one reusable wait event per
  owned stream under the existing mutex. This covers synchronous copies,
  completion and cleanup without changing shared primary-context flags.
  `cudaSetDeviceFlags` is never called. Explicit device-wide trimming retains
  its existing synchronization contract outside the encoding path.
- The optional Butteraugli experiment reuses a fixed 512×512 kernel graph per
  resident lane. It checks arguments and dimensions before replay and updates
  changed nodes. Other geometries and variable work retain ordinary launches.
- The rejected CfL warp experiment is absent from the implementation.
- The bracket baseline now means final defaults plus `--base`; explicit base
  switches stay on in both arms. Explicit spinning remains selectable. A DC
  enable comparison is now a no-op and is rejected. The existing 70-second
  execution budget plus at most five seconds of cleanup remains unchanged.
  No bracket was run on the loaded host, and no new windows are requested.

## Claude's clean results and decision

The authoritative decisions are
phase 2 (satellite repository `codecs/jxl-gpu-hybrid/results/E4/phase2/clean-window.md`)
and phase 3 (satellite repository `codecs/jxl-gpu-hybrid/results/E4/phase3/clean-window.md`).
Phase 2 selected blocking waits. Phase 3 selected DC pipelining after consistent
approximately 8% throughput gains at eight contexts and noisier positive
average results at 12 and 16. DC can cost slightly more CPU per tile. Graph
results changed sign across corpora/context counts, so graphs stay off.

Claude's final 12-context assessment versus satellite is **1.05–1.13×
throughput** and **1.7–1.9× less CPU time per tile**, freeing about 4.5 cores.
**The original ≥1.5× throughput / ≥2× CPU-reduction target was not reached.**
Final default promotion is Claude's explicit decision, not a claim that the
original performance target passed. All performance conclusions come from
Claude's clean windows; phase 4 contains correctness/resource checks only.

## Final focused gate

All encoder checks below left every E4 variable unset. The full phase-2 switch
matrix was not repeated.

| Check | Result | Lock hold |
| --- | --- | ---: |
| Real option-parser probes | 30/30 fresh processes; unset, exact values, malformed values, eight masks | 0 s |
| poc120 plus edges against frozen E3 | 381/381 files identical | 10 s |
| dev plus edges against frozen E3 | 1,221/1,221 files identical | 13 s |
| Stock djxl sample | 69/69 decoded, zero failures | 0 s |
| ASan/UBSan | One run, exit 0, leak detection on, empty stderr | 28 s |
| Memory/endurance at 12 contexts | One run, 10,000/10,000 encodes identical after 800 warmup encodes | 30 s |

The **1,602 frozen comparisons** cover three presets (0, 7, 8), legacy and
resident host input, device HWC and CHW, seven edge dimensions, four edge
stride/layout cases, concurrent callers and producer/consumed event lifetime.
Stock decoding sampled eight evenly spaced tiles from each corpus/preset and
all 21 edge outputs. The sanitizer run covered all three presets, seven edges,
four device layouts, six concurrent callers, producer waits and early reuse.

The 12-context memory run passed the existing phase-2 plateau criteria:

| Memory measurement | Observed | Gate |
| --- | ---: | ---: |
| Peak encoder VRAM (caller input excluded) | **1,564 MiB** | ≤2,048 MiB |
| Tail encoder VRAM range | 0 bytes | 0 |
| Tail managed-live range | 0 bytes | 0 |
| Tail malloc-live range | 40,768 bytes | ≤262,144 bytes |
| RSS upper-envelope growth | 61,440 bytes (60 KiB) | ≤1,048,576 bytes |
| Full post-warmup RSS range | 106,496 bytes (104 KiB) | Reported |

RSS uses `/proc/self/smaps_rollup`. The tail starts at encode 5,200; its upper
envelope is compared with the first 12 measured batches. All 25 samples are
preserved. This run used **12 encoder workers** and 400 MiB of caller-owned
input backing, reported separately. No threshold changes or repeat memory
runs were needed.

Release and ASan/UBSan builds both passed, sequentially, with `nice -n 10`,
eight CPUs and `-j8`. The E4 harness check passed **120 fake processes / 30
comparisons / 240 rows**, including environment isolation, shared-base
forwarding, explicit spinning, invalid/no-op rejection, mixed/incomplete
logs, and three cleanup/deadline paths. E3's harness check passed **32 fake
processes / eight comparisons**. These checks performed no real encoding.
Python compilation, shell syntax and `git diff --check` passed.

All GPU checks held the timing lock and required ≥6 GiB free VRAM. Maximum
functional lock hold was **30 seconds**, below the five-minute limit. No E4
containers remain. Total remote E4 storage is **8.4 GiB**, below 50 GiB.

## Commands and evidence

Executed on sat-5090, in order:

```sh
bash /root/jxl-hybrid/e4/gjxl/tools/e4/prepare.sh release
bash /root/jxl-hybrid/e4/gjxl/tools/e4/prepare.sh asan
bash /root/jxl-hybrid/e4/gjxl/tools/e4/focus.sh
```

`focus.sh` runs `focus.py options`, `validate.py unset poc120`,
`validate.py unset dev`, `focus.py decode`, `focus.py asan`, and
`focus.py memory`, each under `run_locked.sh`, then collects the result.
The single sanitizer command was
`/w/e4/phase4/asan/gjxl_transfer_gate test 2 1`; the single memory command was
`/w/e4/phase4/release/gjxl_transfer_gate endurance 12 25 /w/corpus/dev`.
The helper strips inherited E4/token overrides and fixes E3 to its selected
defaults. ASan used leak detection and halt-on-error; UBSan used halt-on-error
and stack traces. `protect_shadow_gap=0` retains the established CUDA-compatible
ASan configuration. These are qualification commands, not throughput runs.

Local harness checks:

```sh
python3 tools/e4/check_bracket.py
python3 tools/e3/check_bracket.py
python3 -m py_compile tools/e4/focus.py tools/e4/validate.py tools/e4/variants.py tools/e3/variants.py
bash -n tools/e4/prepare.sh tools/e4/run_locked.sh tools/e4/focus.sh
git diff --check
```

The final collector reports `focused_gate_passed=true` in
phase4/gate.json (satellite repository `codecs/jxl-gpu-hybrid/results/E4/phase4/gate.json`).
Adjacent files contain stdout/stderr, exit codes, lock durations, build logs,
option cases, decode selections and all memory samples. Remote originals are
under `/root/jxl-hybrid/e4/phase4/results/`; complete codestreams/manifests and
identity coverage logs are under `/root/jxl-hybrid/e4/phase4/codestreams/`.

Final release gate SHA-256:
`7398c5560dc4c038fbc0de399226c8c3979fa95f72c16470c75c560250d902dd`.
Final release library SHA-256:
`ed0b820b4a1bf12801573d842658cd4c481c39dc4274c63af5d6988614b709b2`.
The collector records the ASan and option-probe hashes. Source option/helper
hashes matched between the worktree and remote build source.

Prior binaries/results are preserved under remote `e4/phase1/`, `e4/phase2/`
and `e4/phase3/`. Phase-3 helpers were archived in `phase3/tools/` before the
final sync, and its measured gate/library hashes remain unchanged. The frozen
E3 gate hash is also unchanged. The earlier full qualification passed 14,418
frozen comparisons, 1,581 stock decodes and 77 sanitizer executions, with all
eight masks qualified for memory and a maximum of 1,920 MiB at 16 contexts.
See the phase-3 report with prior history (satellite repository `codecs/jxl-gpu-hybrid/results/E4/phase3/REPORT.md`)
and [e4-profile.md](e4-profile.md) for attribution,
prior deviations and raw trace paths. Large traces remain remote.

## Deviations and blockers

No phase-4 deviations or blockers remain. The requested focused gate passed
without repeating the full matrix. The original performance target remains
unmet as documented above; Claude explicitly finalized E4 with the selected
defaults. No further timing or implementation work is pending.

## Intended commits

Claude can make these commits with plain messages; the worker has left every
change uncommitted. These supersede the earlier proposed commit lists.

1. **Enable blocking waits and DC pipelining and retain optional Butteraugli graphs**
   — `src/core/e4_gpu_options.h`, `src/c_api/resident_encoder.cpp`,
   `src/gpu/cuda/cuda_backend.cpp`, `cuda_backend_internal.h`,
   `cuda_host_wait.h`, `cuda_reusable_graph.h`, `cuda_butteraugli.cpp`,
   `cuda_butteraugli_kernels.cu`, `cuda_butteraugli_kernels.h`,
   `cuda_dc_processing_kernels.cu`, `tests/cuda_backend_test.cpp`,
   `tests/cuda_dc_processing_test.cpp` (the CUDA basenames share
   `src/gpu/cuda/`).
2. **Add E4 profiling and bounded comparison tools** — `tools/e3/variants.py`
   and `tools/e4/{variants.py,bracket.py,summarize_bracket.py,check_bracket.py,
   clean-windows.txt,api_audit.py,capture.py,host_profile.py,profile.py,
   check.py,collect.py,finish.sh}`. The clean-window list records completion;
   it requests no new windows.
3. **Qualify the final E4 defaults** — `tools/e1/resident_gate.cpp`,
   `tools/e4/{prepare.sh,run_locked.sh,validate.py,focus.py,focus.sh}`,
   `docs/satellite/e4-gpu-efficiency-report.md`, `docs/satellite/e4-profile.md`.
