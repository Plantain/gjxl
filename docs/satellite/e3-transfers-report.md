# E3: selected compact-transfer defaults

**Selected-default correctness gate passed.**
All 1,581 distinct outputs match E1 and decode with stock djxl. Default-only
ASan/UBSan, CUDA memcheck and initcheck are clean. No throughput timing was
run. No correctness blocker remains.

Base: `c3c82fbb71adff6e3565c4d98f1e44fee5f6b15b`, branch `e3-transfers`.
Changes remain uncommitted; intended commits are listed below.

## Claude's clean-window decision

Claude ran the production-paused measurements. The worker did not run timing
or a new profiler capture for this revision. These findings supersede the
old loaded-host throughput conclusions and the original all-on proposal.

| Configuration versus all off | Claude's reported speed change | Decision |
| --- | --- | --- |
| Sync removal alone | −10..−16% | Default off |
| Resident tables alone | −2..−8% | Default off |
| CPU tokens alone | Mixed | Default off |
| Narrow coefficients alone | +2% poc120, −2.6% dev | Default on |
| Narrow coefficients + compact histograms | 0% poc120, −2% dev; within noise | Both default on |
| Four-feature combination (`keep4`) | −6% dev | Do not use as default |

Batched readbacks and narrow tokens also remain default off. All seven
switches remain available for experiments. This decision favors the selected
pair's transfer reduction with throughput within noise; it is not a claim
of a measured speedup or of meeting the brief's original 4× reduction goal.

Authoritative remote evidence:

- `/root/jxl-hybrid/e3/results/toggles-abba-20261017T105843Z-{poc120,dev}-0.*`
- `/root/jxl-hybrid/gjxl-eval/results/cw11-{poc120,dev}.jsonl`
- `/root/jxl-hybrid/gjxl-eval/results/cw12-{poc120,dev}.jsonl`

The six raw JSONL files and `defaults-clean-window-decision.json` (reported
findings, selection, source-file hashes) accompany the small E3 evidence.
Earlier cw8/cw9 showed the original CPU/GPU-token candidates 13–17% slower
than E1; that rejected proposal and its measurements remain historical.

## Current implementation

New Release executable and library:
`root@sat-5090:/root/jxl-hybrid/e3/defaults/{gjxl_transfer_gate,libgjxl.so}`.
ASan/UBSan artifacts use `e3/defaults-asan/`. Claude's measured `e3/toggles/`
and `e3/toggles-asan/` builds and their evidence are preserved unchanged.

| Variable | Unset default | Enabled behavior |
| --- | --- | --- |
| `GJXL_E3_COMPACT_HISTOGRAMS` | **On** | Return nonzero histogram index/count pairs. |
| `GJXL_E3_NARROW_COEFFICIENTS` | **On** | Resident int8/int16 AC readback with exact int32 fallback. |
| `GJXL_E3_RESIDENT_TABLES` | Off | Cache exact search/AQ/filter tables in fixed-arena lanes. |
| `GJXL_E3_BATCHED_READBACKS` | Off | Batch seven search reads and AQ error/quantizer reads. |
| `GJXL_E3_SYNC_REMOVAL` | Off | Reorder waits after blocking reads; track proven stream completion. |
| `GJXL_E3_CPU_TOKENS` | Off | Select CPU tokenization, overriding legacy GPU selectors. |
| `GJXL_E3_NARROW_TOKENS` | Off | Transfer uint8/uint16 token values with uint32 fallback. |

Variables are read once per process, before encoder use. Unset selects the
default above; exact `1` enables, and any other explicit value (including
`0`) disables. Explicitly setting all seven to `0` restores E1 behavior.
The old compile-time `GJXL_CUDA_COMPACT_AC` option remains supported and is
OFF in both new builds, so runtime defaults control narrowing.

Only the two default arguments in `src/core/e3_transfer_options.h` change
production behavior in this revision. No further tuning was performed.
Validation tools now record the effective unset mask as 6, clear all E3 and
legacy token variables, and support separate default-only sanitizer runs.
`bracket.py --variants` still explicitly sets all seven flags for every
subprocess, so its baseline remains all off after this default change.

The independently switchable implementation retains separate histogram and
token narrowing allocations/kernel work. CPU tokens bypasses both GPU-token
compaction features. Batching and sync removal are independent; completion
serial atomics are inactive with sync removal off. The earlier unconditional
entropy batch marker is gone. A prior cache-fallback status bug on non-fixed,
evaluation-free host input was corrected and is covered by low-effort tests.

## Selected-default correctness gate

All new checks run with the seven E3 variables absent. They compare against
the frozen E1 codestreams, not against another configuration of the new build.
Presets: e8-balanced, e7 + aq3, and e8, each at distance 1.2.

- Poc120: **381/381** frozen E1 matches (360 corpus + 21 edges).
- Dev: **1,221/1,221** frozen E1 matches (1,200 corpus + 21 edges).
- Total: **1,602 comparisons**, **1,581 distinct codestreams**, zero mismatches.
  The 21 edge outputs are intentionally checked in both invocations.
- Stock djxl: **1,581/1,581 decoded**, zero failures (381 poc120/edge +
  1,200 dev outputs; repeated edges not double-counted).
- Release and shared/PIC ASan builds passed.
- ASan/UBSan with leak detection: **5/5 executables passed**, empty stderr,
  in four bounded lock holds (provider, coefficients, backend/low-effort,
  resident). Provider: **512 cases / 2,048 exact groups**, including resize
  retry, integer extremes, failure recovery and destruction. Coefficient
  kernel: **102 cases**, including guards, padding and int32 fallback.
- CUDA memcheck and initcheck: **3/3 executables each passed**, zero errors.
  Every memcheck run reports **0 leaked bytes in 0 allocations**. These cover
  provider, coefficients and the full encoder at all three presets.
- ABBA environment isolation: **8 comparisons / 32 fake processes**, passed,
  with conflicting inherited flags; **zero real encodes**.
- Corpus identity creates 12 resident contexts using **1,639,972,864 bytes
  (1,564 MiB)** of device memory, below the 2,048 MiB cap. This is the recorded
  encoder-creation allocation, not a new throughput/peak-memory profile.

Each corpus check compares legacy host, resident host, pitched device HWC,
and tight device CHW input. Edge checks add HWC4 and pitched CHW at 1×1,
1×512, 512×1, 511×509, 31×27, 257×199 and 512×512. They also check six
concurrent callers, producer waits, early consumed-event recycling, invalid
arguments, and resource-cap rejection. Edge cases are zero-padded as in E1.

Sanitizer checks use ASan/UBSan with leak detection for the token provider,
compact-AC kernel, backend, low-effort path, and resident edge/concurrency
suite. CUDA memcheck (including leak-check full) and initcheck cover the
provider, coefficient kernel, and a full three-preset host/HWC/CHW encode of
`ahi-022-001.rgb`, using functional `identity` mode. No benchmark mode runs.

## Inventory-derived traffic at the selected defaults

Device-input poc120, e8-balanced d1.2, warmed steady state. These are derived
from the existing `baseline-poc120.sqlite` and `candidate2.sqlite`, not new
measurements. Full attribution and call sites are in [transfers.md](transfers.md).

| Measure per tile | E1 / all off | Selected defaults |
| --- | ---: | ---: |
| H2D bytes | 618,241.80 | **618,241.80** |
| D2H bytes | 1,616,847.62 | **764,120.18** |
| Total PCIe bytes | 2,235,089.42 | **1,382,361.98** |
| Host synchronizations | 45.9917 | **45.9917** |
| Kernels | 432.2167 | 434.2167 |
| D2D bytes | 3,162,112 | 3,162,112 |
| RGB H2D bytes | 0 | 0 |

The selected defaults save **852,727.43 D2H bytes/tile**, a **38.15% total
PCIe reduction (1.62×)**. Histogram compaction saves 741,306.33 bytes after
its 8-byte header; coefficient narrowing saves 111,421.10 bytes after its
4-byte width readback. Both headers join existing read batches. Syncs stay
at 37 stream + 8.9917 event waits; no sync savings are claimed. Two added
kernels pack coefficients and compact histograms. These counts do not
include host RGB uploads and are not extrapolated to other presets.

Standalone inventory savings for the retained experiments:

| Toggle | Net PCIe bytes saved/tile alone | Syncs saved alone |
| --- | ---: | ---: |
| Resident tables | 507,172 H2D | 20 stream |
| Compact histograms | 741,306.33 D2H | 0 |
| Narrow coefficients | 111,421.10 D2H | 0 |
| Batched readbacks | 0 | 8 stream |
| Sync removal | 0 | 6.9917 event |
| CPU tokens | 53,826.80 H2D + 1,165,364.45 D2H | 3 stream + 2 event |
| Narrow tokens | 201,816.28 D2H | 0 |

CPU tokens additionally removes 3,145,728 D2D bytes/tile, supersedes both
GPU-token compaction savings, and overlaps sync removal by two event waits.
Histogram and token compaction share an 8-byte header when both are enabled.
First-use capacity retries can add readbacks; the inventory is steady state.

## Reproduction and evidence

Edit locally and sync to `/root/jxl-hybrid/e3/gjxl/`, excluding `.git`,
`build*`, `third_party` and `__pycache__`. Run on sat-5090:

```sh
bash /root/jxl-hybrid/e3/gjxl/tools/e3/prepare_defaults.sh release
bash /root/jxl-hybrid/e3/gjxl/tools/e3/prepare_defaults.sh asan
bash /root/jxl-hybrid/e3/gjxl/tools/e3/finish_defaults.sh
```

`prepare_defaults.sh` records the complete CMake options: CUDA SM120,
shared/PIC, Release `-g1` or RelWithDebInfo with
`-fsanitize=address,undefined -fno-omit-frame-pointer`, compact-AC build
option OFF. The image is `satellite-cujpegxl-build:cuda12.8`, mounted at
`/w`, `--cpus=8`, `nice -n 10`, `-j8`. Targets: shared library, transfer gate,
backend, token-provider, compact-AC, and low-effort tests.

The current run uses `finish_defaults.sh identity` followed by
`finish_defaults.sh checks`, allowing the sanitizer build to finish outside
the lock. The first phase runs corpus/edge checks and stock decoding; the
second runs sanitizers, derives the inventory, checks ABBA environment
isolation with a fake executable, and collects `defaults-gate.json`. All
encode, decode and sanitizer commands exited 0. The first collection attempt
exited 1 because it searched only stderr for Compute Sanitizer's summaries;
CUDA 12.8 here writes them to stdout. The collector now checks both streams.
Only collection was rerun after that reporting fix; binaries and completed
functional evidence were unchanged.

Each functional job uses `run_locked.sh`, checks ≥6144 MiB free before GPU
work, and holds the timing lock for at most 260 seconds plus bounded cleanup.
Capacity retries wait only after the child releases the lock. Encoder workers
are ≤12 for corpus identity and ≤2 for sanitizers. Stock djxl uses eight CPU
jobs. No wait for builds or other jobs occurs while holding the lock.

Runtime sanitizer options:

```sh
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:protect_shadow_gap=0
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1
```

`sanitize_toggles.py --defaults --build ...` records each command, unset
flags, effective feature list, stdout/stderr and exit code. CUDA tools use
`--error-exitcode 99`; memcheck adds `--leak-check full`.

`defaults-gate.json` reports `passed: true`, all 1,602 frozen comparisons,
1,581 stock decodes, 11 successful sanitizer executions, effective unset
configuration, inventory-derived totals, and binary/library hashes.
Collection exited 0. Release SHA-256:

- `gjxl_transfer_gate`: `189f4f0e9e7c503c3ba0715f959bf973ca62a823a197b873b9dc6048ac7c4ce9`
- `libgjxl.so`: `d71b85a555266187e58f0ed58a3b1251471105af1a6c560b2d121da81fa32c1c`

Small evidence destination:
`/Users/plantain/src/satellite/codecs/jxl-gpu-hybrid/results/E3/`.
Report copy: `status/E3-REPORT.md`. Current evidence uses `defaults-*` names;
large builds, traces and codestream trees remain on sat-5090:

- `e3/results/defaults-*`: build logs/status, identity, decode, sanitizer,
  inventory, environment check, aggregate gate and hashes.
- `e3/default-codestreams/{poc120,dev}/unset/`: outputs, SHA-256 manifests,
  per-mode stdout/stderr. Dev repeats the same 21 edges; decode only one copy.
- `e3/default-sanitized/{memcheck,initcheck}/`: full-encoder sanitizer outputs.
- `e3/profiles/{baseline-inventory,baseline-poc120,candidate2,final-poc120}.*`:
  historical captures; never copied to the Mac.

## Historical evidence and deviations

The previous all-off-default toggle build passed all 128 explicit on/off
masks on poc120/edges: **48,768** frozen E1 matches, plus **381** unset and
**2,442** dev endpoint comparisons; zero mismatches. Regression 26/26,
ASan/UBSan 15/15, CUDA memcheck/initcheck 8/8 configurations each, and stock
decode 381/381 passed. `toggles-gate.json` and its binary hashes remain intact.
Those historical binaries are not rebuilt by this revision.

The prior original implementation also passed all 1,581 corpus/edge matches
and stock decodes, 10,000 ASan encodes, and 20,000 regular encodes with stable
live managed ownership. These are historical endurance results; this task
requests new-default identity, decode and sanitizers, not another endurance
or throughput run. Old performance claims are superseded by Claude's clean
windows. The original 4× traffic/sync reduction aim is not met by the selected
defaults; this is the explicitly authorized revised decision.

No operational service controls, commits, pushes, sub-agents, or held-out
corpus access. No throughput timing or fresh Nsight capture. E3 disk use is
**7.5 GiB**, below 50 GB. Both Release and sanitizer builds are kept separate
from Claude's measured build; its executable/library SHA-256 hashes match
the prior gate. All worker containers have exited. `git diff --check`, Python
compilation and shell syntax checks pass. No blockers remain. Small evidence
and this report are copied to the project result/status directories.

## Intended commits (Claude commits after review)

1. **Add switchable CUDA transfers with compact data defaults**
   - `src/core/e3_transfer_options.h`, `src/codestream/cuda_tokenization_policy.h`
   - `src/gpu/ops/host_transfer.h`, `src/gpu/ops/ac_strategy_search.cpp`
   - `src/gpu/cuda/cuda_backend.cpp`, `cuda_backend_internal.h`,
     `cuda_aq_resident.cpp`, `cuda_butteraugli.cpp`
   - `src/gpu/cuda/cuda_ac_tokenization.cpp`, `cuda_ac_tokenization_kernels.{cu,h}`
   - `tests/cuda_backend_test.cpp`
2. **Add E3 identity, sanitizer and clean-window variant gates**
   - `CMakeLists.txt`, `tools/e1/resident_gate.cpp`, `tools/e3/*`
   - `REPORT.md`, `transfers.md`
   - Small evidence in satellite `results/E3/` and `status/E3-REPORT.md`;
     Claude commits those separately with the project status updates.
