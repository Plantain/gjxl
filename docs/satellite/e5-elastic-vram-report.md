# E5 elastic encoder VRAM

Status: **PASS — collector writes `passed=true`; no remaining blockers.**
All 13 tasks in Claude's production-paused window exited zero on 2026-10-18,
09:22:39–09:27:13 UTC. The worker then reran CPU scene identity, native stock
decode and the cleanup audit, refreshed the evidence, and reran the collector.
Changes remain uncommitted for Claude. Bases are gjxl `7df5950` and satellite
rollout `37d6eb5`. No sub-agents or E5-worker production changes.

Evidence is in `codecs/jxl-gpu-hybrid/results/E5/`: `gate.json`,
`window-sequence.txt`, `window-TASK.log`, guard receipts and JSON measurements.
`before-12gib/` is unchanged and retains the earlier complete pass. The resolved
blocker is retained under `history/resource-blocked/` and `deferred/`.
Large COGs/codestreams remain on `root@sat-5090:/root/jxl-hybrid/e5/`.
R1's proposed pins, report, runbook and gate pointer/hash are refreshed in
`results/R1/`; its original artifacts remain under `before-E5/`.

## Candidate and implementation

- Image: `satellite-sat5090-gpu:gjxl-e5-4813fa9e044eb4210588`.
- Image ID: `sha256:93b88b61dc1a1791c23850fc925e63368cb29f7ad7016b695b7c55d1d880db3c`.
- Installed native library SHA256: `e39c22195e7ea23f30ee31175790211550c400cce66eae62ee5de4fa7f62745f`.
- Native patch SHA256: `8a1a0f0e49c3213ceaf76ff071c1bb74d52b502fdb96492145399cd349945c93`.
- Proposed qualification SHA256: `4d8fbcb41918c29b1fe8164951b1cb66a0c6c12e531aff2d15839e444d22f323`.

The build applies a SHA256-checked patch to native revision
`7df59506fa91895eaedfde95018a549b380e1919`. The patch equals the four-file native diff;
encoder/service source, image and deployment pins stayed unchanged during
this completion turn. Worker image inputs
are unchanged. If the patch is replaced with a committed source revision,
rebuild and requalify the resulting image/library.

The new idle-release API frees lane backends, fixed arenas, upload buffers and
static-table backing while retaining workers, input-consumption events and
calibration. The next nonempty batch recreates backing without repeating the
48 effort-1/7/8/10 calibration encodes. Live arena bytes are exposed separately
from the configured cap. Busy release is nonblocking and completes after the
last active batch; failed reacquisition clears partial backing.

The service releases after `drain_gpu` and abort, credits only actual live
backing, and checks physical headroom again under its operation lock. A pending
release is also checked after unlock to cover the final race window. TensorRT
uses the small optional reclaim hook on short admission and idle release.
Its 3.5 GiB margin remains unchanged; V1 owns that separate work. The hook does
not import gjxl or initialize CUDA just to reclaim it. Defaults remain
12 contexts, 2,048 MiB cap and effort 8 balanced.

## Gate results

| Check | Final result |
| --- | --- |
| Native byte identity | 527 poc120/dev/edge host outputs match R1; 1,054 HWC/CHW comparisons match after release; efforts 1/7/8/10 match |
| Stock decode | All 527 native streams decode with stock `djxl` |
| Six scene routes | Six complete COGs and 12,222 codestreams equal frozen E2; stock GDAL/libjxl decode; zero CPU fallback or explicit RGB transfers |
| Idle memory | 0 private arena bytes; 10 MiB incremental overhead above an initialized caller CUDA primary context |
| TensorRT reclaim | 2.834 ms; same physical-free bound stalls with hook disabled and admits with it enabled |
| 1,000 cycles | Zero live arenas after every cycle; RSS span 10.539 MiB; VRAM span 0 B; maximum release 2.908 ms |
| 20 broker scenes | One singleton, 20 releases; final backing zero; RSS span 4.559 MiB and VRAM span 4.000 MiB |
| Recovery | Missing library, post-consumption error and real fourth-arena `cudaMalloc` fault all recover CPU pixels with exactly-once slot release |
| Installed renderer/adapters | Real `DeviceCUDAMTGRenderer`, synthetic radiance, all 878 streams/geometry match G4; zero RGB D2H |
| Local checks | 61 focused tests; 282 flag-off tests with 26 skips; Ansible syntax/local rendering and all eight deployment-verifier cases pass |

The unchanged Ansible raw-worktree suite has one inherited allowlist-fixture
mismatch. All nine tests pass in the documented temporary stage-1 fixture;
`ansible-current-host.log` preserves the original failure. This is not reported
as a pass of the unmodified current host-vars suite.

At 12 contexts the arenas occupy 12 × 88 MiB = 1,056 MiB. Peak without caller
RGB is 1564 MiB, below the 2 GiB encoder budget.
The native microbenchmark peaks at 1,566 MiB including its caller tile.
An initialized CUDA primary context uses 498
MiB; after release the process uses 508 MiB.
Destroy also leaves that shared context/module storage. Explicit arena release
takes 2.589 ms; create after primary initialization
takes 1.891908 s including calibration. VmLck/VmPin remain zero;
source has no cuFFT or explicit CUDA host-pinning calls. Driver-internal staging
is not measured by those Linux counters (`memory-breakdown.json`).

The concurrency gate uses the installed admission loop, real CUDA free memory
and a scaled bound of 23,505,666,048 B. With reclaim
disabled, 22,968,795,136 B free produces the expected
accelerated 0.506198 s timeout. Reclaim raises free memory
to 24,067,702,784 B and admits in 2.834 ms.
Busy release returns in 2.385 microseconds and
completes after the batch; four broker scenes interleave successfully.
The activation allocation is stubbed to 256 B and the 300 s timeout accelerated
to 0.5 s. This is an admission reproduction, not live MTG inference/publication.

## Reacquisition costs — Claude's paused window

Two interleaved warm/released pairs use each complete captured scene. The
first-batch measurement includes actual encoding and arena recreation, excludes
fixture upload, and does not isolate allocator latency. The full fixture has
3,106 tiles including overviews, exceeding the brief's approximate 1,170.
Both added costs and complete released first-batch times are below 0.3 s.

| Scene | Tiles | Warm first batch ms | Released first batch ms | Added ms | Maximum released ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| CONUS | 204 | 20.730 | 26.242 | 5.513 | 26.689 |
| GOES full disk | 3,106 | 30.856 | 38.817 | 7.961 | 40.883 |

These are medians of two measurements per state; the raw pairs, batch sizes,
complete-scene times and output hashes are in `scene-reacquisition.json`.
Do not attribute differences in whole-scene timing solely to reacquisition.

## 6/8/12-context benchmarks — Claude's paused window

Median throughput in tiles/s, using one repeated real CONUS corpus tile.
Each original-R1 baseline is followed by E5 at the same context count.
Warm retains arenas; released starts with freed arenas and includes
reacquisition in the measured run.
These microbenchmarks are separate from the complete-scene measurements above.

| Tiles | Contexts | R1 warm tiles/s | E5 warm tiles/s | E5 released tiles/s | Peak MiB |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 204 | 6 | 524.5 | 529.9 | 524.4 | 1036 |
| 204 | 8 | 630.4 | 632.6 | 621.1 | 1212 |
| 204 | 12 | 767.6 | 800.1 | 772.5 | 1566 |
| 1,170 | 6 | 524.3 | 529.4 | 526.7 | 1036 |
| 1,170 | 8 | 638.6 | 639.7 | 640.1 | 1212 |
| 1,170 | 12 | 793.2 | 812.2 | 806.3 | 1566 |

Twelve contexts is fastest in this repeated-tile comparison and has the largest
peak. The configurable default remains 12; this does not establish an optimum
for every production scene. See `benchmark-summary.json` and all six raw
`benchmark-{baseline,candidate}-{6,8,12}.json` files.

Current six-route captured-RGB-to-COG measurements follow. CPU measurements and
three smaller device routes come from earlier runs with varying host load;
GOES full/thermal and AHI device measurements come from Claude's paused window.
These columns are **not paired speedup measurements**. They exclude source
rendering/inference, download and publication; fixture allocations are excluded
from the separate encoder-budget measurement.

| Route | Tiles | Earlier CPU s | Current E5 s | E5 timing phase |
| --- | ---: | ---: | ---: | --- |
| native | 878 | 39.010 | 6.887 | Earlier guarded run |
| gk2a | 1,652 | 85.762 | 9.471 | Earlier guarded run |
| goesfd | 3,106 | 160.103 | 5.482 | Claude paused window |
| thermal | 3,106 | 157.766 | 4.937 | Claude paused window |
| conus | 204 | 11.366 | 5.266 | Earlier guarded run |
| ahi | 3,276 | 169.612 | 4.842 | Claude paused window |

## Commands, evidence and resource controls

Claude ran the 13 `run_window.sh TASK` commands listed in `CLAUDE-WINDOW.md`.
`window-sequence.txt` records zero exit codes for all tasks, from 09:22:39 to
09:27:13 UTC, with the longest task taking 60 s.
The worker then ran:

```sh
ssh root@sat-5090 'bash /root/jxl-hybrid/e5/run_gate.sh identity'
ssh root@sat-5090 'bash /root/jxl-hybrid/e5/run_gate.sh decode'
ssh root@sat-5090 'E5_AUDIT_SUFFIX=-12gib python3 /root/jxl-hybrid/e5/gates/cleanup.py'
```

All three passed. The cleanup audit reports no E5 containers or partial files
and 1,491,575,533 B under the remote work root. Shared Docker
base layers are reused. Only small JSON/logs were copied to the Mac.

The collector was run from `results/E5/`:

```sh
python3 collect_results.py --evidence . \
  --satellite satellite branch gjxl-rollout \
  --gjxl gjxl branch e5-elastic-vram
```

It validates the source patch, installed image/library, final-image receipts,
12 GiB guard hashes, window sequence, correctness, local tests and qualification
pin. It also checks each scene JSON against the seconds recorded by the fresh
CPU identity gate, preventing stale staged metadata. Authoritative JSON source
paths/hashes are recorded in `artifact-sources.json`. `gate.json` is PASS.

GPU preflight reserves expected peak plus 12 GiB: 14 GiB for native-only work,
17 GiB for complete scene fixtures. Physical free is sampled every 20 ms and a
floor breach immediately exits the test. Minimum sampled free across accepted
final-image checks is 16.780 GiB. Normal timing
holds have a 270 s OS alarm; Claude's window commands additionally cap each
invocation at 75 s plus 2 s forced-exit grace, with 65 s timing alarms.
The longest retained timing hold, including earlier CPU runs, is
169.704 s. Builds used nice 10 and at most eight CPUs;
test containers used at most 16 CPUs. E5 never operated production containers;
Claude controlled the documented pause.

`README.md` retains build, local test, Ansible fixture/rehearsal and rerun
commands. Local results remain 61 focused tests in
0.249 s; 282 flag-off tests
in 0.803 s with 26 skips; nine proposed-fixture
Ansible tests in 0.139 s.

## Retained deviations

- Provider interruption and subsequent sandbox narrowing did not change scope;
  authorized satellite/evidence writes used filesystem escalation.
- The final Python unlock-race fix changed the image but not the native hash.
  Initial evidence is in `revision1/`; current accepted native and service
  receipts identify the final image.
- The new 12 GiB rule caused three worker attempts to abort at the floor.
  Logs remain under `deferred/`; Claude's 13 successful paused tasks resolved
  the blocker. `before-12gib/` and its hash chain remain untouched.
- The first allocation injector could not resolve locally loaded cudart via
  RTLD_NEXT. The test-only injector now resolves cudart explicitly; the native
  implementation required no change for that harness issue.
- An initial timing Mock retained RGB views. The corrected direct wrapper
  records `retains_inputs=false`; the invalid measurement remains in `deferred/`.
- The completion refresh found that some remote `results/` copies predated the
  latest scene/lifecycle/renderer outputs. The actual JSON files in the gate
  output directories were imported, remote staging refreshed, and the collector
  gained a scene-freshness check. No encode was repeated to repair metadata.
- Earlier operational snapshots include one E5 container inheriting a Compose
  label; only that explicitly identified test row is excluded. Subsequent
  snapshots record external production transitions; no worker action caused them.
- R1's runbook still requires MTG FCI full overlapping Himawari or GK2A and zero
  TensorRT admission timeouts at every stage. Qualification is not deployment.

## Intended commits — Claude commits

1. `Release idle resident encoder device arenas` — gjxl
   `include/gjxl/gjxl.h`, `src/c_api/gjxl.cpp`,
   `src/c_api/resident_encoder.cpp`, `src/c_api/resident_encoder.h`, `REPORT.md`.
2. `Reclaim idle gjxl memory for shared GPU admission` — satellite
   `gjxl_resident.py`, `gjxl_device_sink.py`, `cpu_cog_pipeline.py`,
   `standalone_tensorrt.py`, `tests/test_gjxl_device.py`,
   `tests/test_standalone_tensorrt.py`, `Dockerfile.sat-5090-gpu`,
   `runtime/gjxl/build.sh`, `runtime/gjxl/source.json`,
   `runtime/gjxl/elastic-vram.patch`.
3. `Record elastic gjxl qualification and canary requirements` — satellite
   `codecs/jxl-gpu-hybrid/results/E5/`, updated `results/R1/` pins/report/runbook
   with `before-E5/` history, and `status/E5-REPORT.md`. No large remote outputs.
