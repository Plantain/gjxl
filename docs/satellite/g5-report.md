# G5 raw-quant readback fix

**Gate: PASS (2026-10-19).** Source base `33e1734`, branch `g5-rawquant`.
The reviewed fix and regression test were unchanged during final qualification.
No deployment, operational container changes, commits, or sub-agents.

Evidence is in `satellite repository codecs/jxl-gpu-hybrid/results/G5/`.
`gate.json` records the aggregate result and hashes of 113 supporting artifacts;
`REPORT.md` records the investigation, commands and deviations. Large artifacts
remain at `root@sat-5090:/root/jxl-hybrid/g5/`.

## Cause and compatibility

The sparse-Y AC heuristic inherited from pinned libjxl can increment initial
raw quant 256 to 257 in a larger transform. Its later saturation branches need
not execute. The native quantizer initialization is bounded at 256, the one
uncapped increment adds one, and activity subtraction cannot raise the value:
257 is the sole additional legitimate value. CUDA's scalar and cooperative
selectors agree. The final frame validator rejected this content edge case.

Pinned libjxl (`e8ff0976`) permits this encoder decision in `enc_group.cc`, then
clamps decoded AC metadata to [1,256] in `dec_modular.cc:552`. G5 canonicalizes
exactly 257 to 256 at final CUDA frame publication. Other invalid values still
fail. AQ iterations, quantized coefficients, thresholds, and every valid final
field remain unchanged. This preserves the decoder's effective quant field
without changing AQ scores or the bytes of previously encodable tiles.

The reproducer is derived from the published 2026-10-18 22:45 UTC SEVIRI rapid
COG associated with the reported fallback. Its decoded 4× overview block (2,0),
zero-padded and multiplied by 1.4, fails deterministically at e8-balanced d1.19.
Diagnostic raw min/max are 5/257. It fails even in a fresh single-context encoder
without releases. The original decoded COG re-encodes; its unavailable
precompression input is not claimed as reproduced. Provenance and fixture hash
are in `testdata/satellite/README.md` and `published-sources.json`.

## Gate results

| Check | Result | Evidence |
| --- | --- | --- |
| poc120 + dev | 520 cases, 1,560 identical layout outputs | `matrix-*-{baseline,candidate}.json` |
| Edge/constant/padded cases | 14 cases, 42 identical outputs | Same matrix reports |
| Captured production base/4×/16× levels | 11,274 cases, 33,822 identical outputs | Same matrix reports; `manifest-exact.json` |
| Published rapid COG | 87 cases, 261 identical outputs | `published-{baseline,candidate}.json` |
| Published-tile mutation sweep | 1,301 previously successful cases, 3,903 identical outputs; one failing case now passes all layouts | `mutations-{baseline,candidate}.json` |
| Reproducer, waits off/on | Baseline fails 3/3 layouts in each mode; candidate fails 0/3 in each mode | `repro-{base,fix}-{0,1}.json` |
| Fresh baseline, no release | 3/3 failures with one context | `repro-baseline-fresh.json` |
| Native regression | 30/30 encodes; strided device layouts, release before each; identical 20,383-byte streams | `regression-native.log` |
| CTest `cuda_raw_quant_readback` | 1/1 pass, 0.69 s | `ctest-attempt1.log` |
| memcheck / initcheck / racecheck | Zero errors; racecheck zero hazards/warnings; full RGB repro, all kernels | `sanitize-*.receipt.json` and referenced logs |
| Stock djxl sample | 128/128 decode; 37 strata, every edge and formerly failing case included | `decode.json`, `stock-decode.log` |

Total: **13,197 tile cases, 39,588 byte-identical previously successful
host/HWC/CHW outputs, three newly encodable outputs, zero candidate failures
or mismatches**. The identity sweep uses 12 contexts, release/reacquire between
batches, route distances 1.19 (SEVIRI/MTG), 1.195 (GOES), 1.275 (AHI), and 1.2
for poc120/dev. Production overview sampling uses the actual global phase zero.
The nine captured images cover four rapid dates, SEVIRI full, MTG full, GOES full,
and Himawari primary/east. `*.receipt.json` selects each successful attempt;
`*.guard.json` records its exact command, memory floor, duration and exit status.

| Release stress | Waits off | Waits on |
| --- | ---: | ---: |
| Encodes / release cycles | 10,000 / 1,000 | 10,000 / 1,000 |
| Contexts / concurrent callers | 12 / 4 | 12 / 4 |
| Steady RSS span | 20,889,600 B | 24,977,408 B |
| Steady process VRAM span | 0 B | 0 B |
| Peak process VRAM | 1,648,361,472 B | 1,648,361,472 B |
| Guarded duration | 33.911 s | 36.389 s |
| Minimum physical free VRAM | 25,131,024,384 B | 19,388,301,312 B |

Both stress runs leave zero live arena bytes after every idle release; a release
during an active call defers freeing until completion. Limits are 32 MiB RSS
span, 16 MiB VRAM span, and 2,048 MiB peak. Overall candidate peak across the
identity and stress gates is **1,588 MiB**. Minimum free among successful guarded
runs is **12.54 GiB**; the longest is **116.620 s** (racecheck).

The decoder is stock djxl v0.13.0 `e8ff0976`, SHA256
`f37c74f86125eb9ae13cc49df195afb5529886078939e5c1364e3851dff73748`.
The deterministic 128-stream sample decoded in 0.123 s using eight CPU workers
and one decoder thread each. The collector matches every sampled codestream
hash to the qualified candidate output. Sampling follows the continuation
request; the byte-identity sweep covers all cases.

## Satellite build delivery

`results/G5/elastic-vram-rawquant.patch` replaces the existing elastic patch on
source **`7df59506fa91895eaedfde95018a549b380e1919`**. It contains the four existing
elastic-release files plus `src/gpu/cuda/cuda_aq_resident.cpp` with the G5 fix.
`patch-check.json` verifies clean application and equality with the five intended
native files. The final worktree diff has the same hash. Tests, reports and
harnesses stay in this worktree for review rather than in the build patch.

- Patch SHA256: `73ef9bc9a18a9122566f9b648dd2c807eb9db154d48db62ed37605cc63fb674b`.
- Qualified library SHA256: `1eadf15abc87a7dd36e4ff1420674d46145479c26c25d12af33cbb018d150aff`.
- Library: `root@sat-5090:/root/jxl-hybrid/g5/release/libgjxl.so` (11,858,096 bytes).
- Frozen `33e1734` baseline SHA256: `f98f28726b8ce2c9f5f263510e29e830fc6addfa00d512adfa25499632546cb8`.
- Builder: `satellite-cujpegxl-build:cuda12.8`, image ID
  `sha256:94a77edf1419b497038ff0f05494c62c464a7f0c27ec3fcf6cab2f06d1337508`.

`release.json` pins these artifacts. The build used Release/SM120, CUDA and shared
library on, Metal/reference off, tests/benchmarks on, nice 10 and eight CPUs.
The candidate and release-copy hashes were rechecked after qualification.
No library was deployed. Binaries over 5 MB remain remote.

## Re-running the gate

The preserved remote manifests, captures, corpus, published RGB and frozen
baseline are the inputs. Sync source changes over `/root/jxl-hybrid/g5/gjxl`,
excluding `.git`, `build*`, and `third_party`. Re-run the completed gate from
the evidence without GPU work:

```sh
python3 tools/g5/collect.py \
  satellite repository codecs/jxl-gpu-hybrid/results/G5
```

To refresh identity, stress, sanitizers, regression and sample decoding on
sat-5090 (the scripts acquire the timing lock per short command):

```sh
cd /root/jxl-hybrid/g5/gjxl
G5_START_FREE_MIB=24576 python3 tools/g5/qualify.py \
  matrix-0 matrix-1 matrix-2 matrix-3 matrix-4 matrix-5 \
  matrix-6 matrix-7 matrix-8 matrix-9 matrix-10 matrix-11 \
  mutations published plateau-0 plateau-1 regression-native ctest \
  sanitize-memcheck sanitize-initcheck sanitize-racecheck
bash tools/g5/decode.sh
python3 tools/g5/collect.py /root/jxl-hybrid/g5/results
```

Reproducer commands are preserved verbatim in `repro-*.guard.json`. The native
test invocation is `gjxl_cuda_raw_quant_readback_test FIXTURE REPEATS CONTEXTS
[OUTPUT.jxl]`; the gate uses 10 repeats and 12 contexts, and sanitizers use one
repeat/context. The full-image fixture is `testdata/satellite/raw-quant-257.rgb`.

Each GPU run preflights expected peak + 12 GiB free, monitors the physical-free
floor every 20 ms, and has a 250-second internal deadline plus 270-second outer
timeout. The controller waits without holding the lock and retries only resource
deferrals, preserving every attempt. CPU decoding also holds the lock, with a
270-second limit and eight-CPU cap.

## Deviations and cleanup

The fixture is a deterministic derivative, not the unavailable original
precompression RGB. Early exploratory scans used centre sampling / GOES d1.21;
they are excluded from the final gate. Resource-floor stops and preflight
deferrals are retained as incomplete attempts. An early diagnostic-library run
labelled `repro-candidate-w1` is excluded; all passing candidate receipts pin the
qualified hash. `REPORT.md` records the initial link/manifest corrections.

The resumed turn found no leftover G5 containers or controller processes.
The final audit also found none; disk use is approximately 1.06 GB, below the
50 GB limit (`cleanup.json`). No remaining blocker.

## Intended commits — Claude commits

1. `Normalize overflowing CUDA raw quant at frame publication` —
   `src/gpu/cuda/cuda_aq_resident.cpp`, `CMakeLists.txt`,
   `tests/cuda_raw_quant_readback_test.cpp`, `testdata/satellite/`.
2. `Record raw quant regression qualification` — `tools/g5/`, `REPORT.md`,
   `docs/satellite/g5-report.md`; satellite `results/G5/` and `status/G5-REPORT.md`.
