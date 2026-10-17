# G4 integration report

**Scoped fixture checks pass; complete production wiring is blocked by the
brief's existing-file allowance.** Final report, 2026-10-17. Base:
`1e4c83542604dbfcc731caaac3aa6879458012dc` on `g4-integration`.
No commits or production service changes. The two remaining caller changes
are described below; the passing fixture results do not establish that every
production path is fully wired.

## Scope and sequence

1. Correct RGB8/opaque RGBA8 sRGB image metadata without changing encoded
   frame data; compare pre/post-fix codestreams and forced-sRGB decodes.
2. Add the ctypes context pool, bounded execution domain, route table, COG
   sink and logged CPU fallback. Keep CPU selection as the default.
3. Run mocked unit tests, the flag-off satellite suite, and full-scene
   GDAL/COG/quality/timing gates on sat-5090.

## Environment and evidence

- Required documents read in order: COMMON, PLAN, GJXL-EVALUATION, G4 brief;
  then STATUS. Current integration preset is e8-balanced.
- Remote access verified. Initial GPU free memory: 8262 MiB.
- Remote base checkout is `2c7c725`; the G4 copy was overlaid from this
  worktree to use `1e4c835`. Builds use nice 10 and at most 8 CPUs.
- Initial satellite dirty-file inventory saved at
  `/tmp/g4-satellite-initial-status.txt`; unrelated files were left alone.
- Results live in satellite `codecs/jxl-gpu-hybrid/results/G4/` and
  remote `/root/jxl-hybrid/g4/`.
- Compact result index: `results/G4/summary.json`; overview images and review:
  `results/G4/visual/`. Full COGs remain in remote `g4/scenes/`.
- Final resource cleanup check: no G4 processes or containers remain;
  remote footprint is approximately 2 GiB (50 GiB allowance).

## Gate status

1. Header and consumer checks: native metadata fix implemented. Regression
   compares complete frame payloads under both metadata formats. Remote full
   build succeeded; initial targeted ctest was 6/7 (publication fixture still
   expected the old C API metadata; updated its source provenance). Rerun: 7/7
   PASS (`header-ctest2.log`).
   408-image before/after check PASS: 400 dev tiles plus 8 RGB/RGBA edge
   cases. All frame payloads and forced-sRGB float pixels identical; new default
   and forced-sRGB 8-bit PPM pixels identical; GDAL exact for all 400 tiles.
   Total header delta -1222 bytes (512x512: -3 bytes/tile).
2. Full-scene COGs, levels, georeferencing and quality: **6/6 scene pairs
   PASS** structural checks at base, 4x and 16x. All **12,222 tiles per backend**
   decode; inventories and georeferencing match. No normal gjxl scene used
   CPU fallback. GDAL recognizes all 12 files as `LAYOUT=COG`
   (`cog-layout.json`). PSNR compares every valid decoded pixel;
   SSIMULACRA2 covers every tile, with mean/p5/min in `scenes/*-comparison.json`.
   The six worst-scoring 16x crops were compared against source and reviewed
   visually; no obvious color-transfer or alignment error was seen. This is
   a spot review, with low-score edge cases preserved for G5/reviewer scrutiny.
3. Flag-off satellite suite: **PASS on local Python 3.14.8: 547 tests, 27
   environment-dependent skips** (`suite-python314.log`). The Python 3.12
   qualification image has two pre-existing annotation-evaluation failures. Original
   hook files: 536 tests, 2 errors, 4 skips. G4 hook files: 546 tests, the SAME
   2 errors, 4 skips. Commands: `SATELLITE_JXL_BACKEND=cpu-libjxl
   SATELLITE_CPU_SPOOL=0 python -m unittest discover -s tests -t .` in remote
   `satellite-baseline` and `satellite` respectively, qualification image.
   Errors are `GEOSOutputOwnershipTest.test_validation_failure_removes_the_persistent_run_directory`
   (`TypeError: type 'object' is not subscriptable`) and
   `GoesConusSupportTests.test_goes_backfill_sends_timestamp_without_fabricated_record`
   (`NameError: SatelliteConfig`). Evidence: `suite-baseline.log`,
   `suite-current.log`, reconstructed original hook files, `satellite-hooks.patch`.
   Python 3.14's deferred annotations resolve both without source/test changes.
   No unrelated tests/source have been edited. Current targeted local suite:
   35/35 PASS (11 new binding/sink tests + existing CPU/cuJPEGXL sink tests).
4. Scene timing and <=2048 MB VRAM: **6/6 PASS**, **1.33--4.82x** scene encode
   speedup, peak process NVML **970,981,376 bytes (926 MiB)**. No 10x end-to-end
   claim is made; the brief requires reporting scene times, and G3's in-process
   throughput excludes this integration's startup, spooling and packaging.

Additional lifecycle gate: **PASS** (`lifecycle-gate.json`). A missing
library falls back to CPU for all eight tiles and is pixel-identical to the
CPU reference at all three levels. An injected second-batch failure produces
three gjxl tiles plus five CPU tiles, with all levels readable, admission
released, and managed live/idle/reserved bytes zero. Peak VRAM is 702 MiB.
Both errors are logged. The test scene is 1025x519, with 257x130 and 65x33
overviews, exercising physical-edge padding and recovery.

Optional shared-library install: **PASS** (`install.log`), including
`install/lib/libgjxl.so` and the exported CMake targets.

## Deviations / blockers

- The shared library is now an optional additional CMake target
  (`GJXL_BUILD_SHARED_LIBRARY=ON`), preserving the static test linkage.
  Changing the existing target to shared exposed private-symbol test linkage;
  corrected before acceptance tests.
- First incremental remote build saw stale object timestamps because the
  baseline compiled after the local edits. Touched the overlaid changed files
  and rebuilt. Saved all build logs under remote G4.
- Harness setup corrections: corpus stores `.rgb`, not PPM; unittest needs
  `-t .` because existing root and tests/ modules share names.
- Existing GOES reflective and thermal-only calls supply identical product
  names and output basenames. The new sink supports explicit `route='thermal'`
  and `SATELLITE_GJXL_ROUTE`; automatic thermal identification at that call site
  is not available from the authorized factory inputs. The shared thermal service needs a route hint from its call site
  (`geos_thermal_service.py`), outside the two existing files permitted by the brief.
- The legacy native raster service owns external overviews and result metadata
  outside the sink factory. Its base-TIFF path selects gjxl behind the flag,
  but its externally constructed overviews still use CPU libjxl. The complete
  GjxlCogSink tested here encodes all levels with gjxl. Finishing the legacy
  service wiring requires changes to `raster_gpu.py`/its caller, beyond the
  brief's existing-file allowance. No protocol or caller was silently changed.
- Scene metric harness: CONUS overview edge strips can be 1--3 pixels wide,
  below SSIMULACRA2's 8-pixel minimum. Replicate edge samples to 8 pixels only
  for SSIMULACRA2; PSNR counts each original valid pixel once. The encode,
  inventory and GDAL checks had passed before this harness adjustment.
- The reused `RawJXLWriter` leaves GDAL creation metadata at its defaults:
  `COMPRESSION_REVERSIBILITY=LOSSLESS`, `JXL_EFFORT=5`. These do not describe
  the actual lossy gjxl payloads. Scene JSON `encoder` records hold the
  actual route, distance, preset and library SHA256. This inherited raw-writer
  metadata issue is recorded for integration follow-up; that existing file
  is outside the brief's edit allowance.

## Implementation and measurements

- ctypes pool defaults to 12 thread-affine CUDA contexts, one CPU participant
  per tile, shared bounded execution domain; both requested presets supported.
- Managed-memory cap is 1536 MiB (host plus device), leaving 512 MiB of the
  2048 MiB device budget for CUDA runtime/modules. Native caches are trimmed
  after all batch futures settle, before GPU admission is released.
- First real 12-tile smoke: 12 valid 170-byte codestreams; peak native backing
  418,730,925 bytes, peak committed 1,570,174,434 bytes, peak CPU participants 7.
  Full-scene NVML measurements below include runtime/module residency.
- Native scene pilot NVML peak: 937,426,944 bytes (894 MiB), including the
  process CUDA context. All 878 tiles decoded. Pilot timings (51.79 s CPU,
  10.48 s gjxl) overlap development checks and are excluded from final timing
  claims; the final six-route run has no other G4 compute jobs overlapping.
- CPU fallback uses the deployed GDAL/libjxl tile encoder at the original
  profile's distance/effort and logs the failure. Base/overview batches share
  the same gjxl route distance and preset. Reuses RawJXLWriter, physical edge
  padding, progressive overview writers and host spooling.

Final timings include sink construction, host spooling, all level encoding
and COG packaging from captured RGB. Source loading/rendering is outside the
timer. Each candidate starts a new 12-context pool; CPU uses 14 base threads
plus one per overview. Candidate/baseline order alternates; operational
services remain running. No other G4 compute jobs overlapped these timings.
Longest recorded encode was 179.34 seconds; each timing-lock window was
capped at 270 seconds, below five minutes.

| Route | Tiles (base/4x/16x) | CPU seconds | gjxl seconds | Speedup | Peak MiB |
| --- | --- | ---: | ---: | ---: | ---: |
| Native | 817/55/6 | 42.581888 | 11.205786 | 3.800x | 894 |
| GOES CONUS | 187/15/2 | 5.526221 | 4.155209 | 1.330x | 862 |
| GK2A | 1530/110/12 | 88.383976 | 21.441663 | 4.122x | 926 |
| GOES full disk | 2890/198/18 | 85.647740 | 36.552903 | 2.343x | 894 |
| Thermal | 2890/198/18 | 116.665122 | 29.103997 | 4.009x | 894 |
| AHI primary | 3060/198/18 | 179.341032 | 37.191309 | 4.822x | 926 |

Each cell below is PSNR dB / mean SSIMULACRA2 against the decoded CPU COG,
not against original RGB. Full p5/min values and byte sizes are in the JSONs.

| Route | Base | 4x | 16x |
| --- | ---: | ---: | ---: |
| Native | 46.849 / 89.891 | 41.542 / 86.886 | 37.249 / 75.962 |
| GOES CONUS | 44.461 / 87.646 | 38.245 / 83.662 | 36.016 / 85.562 |
| GK2A | 46.823 / 88.558 | 39.945 / 84.636 | 37.616 / 74.513 |
| GOES full disk | 45.405 / 88.042 | 38.827 / 84.259 | 36.827 / 73.839 |
| Thermal | 53.570 / 91.788 | 48.021 / 90.584 | 40.123 / 88.341 |
| AHI primary | 53.273 / 91.837 | 46.881 / 89.656 | 41.030 / 88.681 |

Worst 16x pair scores for native/GK2A/GOES full are 59.66/48.94/25.03,
respectively, in textured strips only 84/45/34 pixels wide. Both encoders
also score poorly against source there. See `visual/REVIEW.md` and the
source/CPU/gjxl PNGs for the qualitative assessment and its limits. These
observations do not replace G5's quality qualification.

Native's first final-run diagnostic snapshot was taken before cache trim;
its reported idle capacity is not a post-drain reading. Trim still ran
before admission release. Later scenes and the lifecycle gate record the
post-trim snapshot. Native CPU participant peaks across scenes were 7--9.

## Intended commits (Claude applies at review)

- `Fix sRGB8 image metadata in the C encoder` — gjxl header/provenance code
  and regression coverage: `src/c_api/gjxl.cpp`, `src/codec/frame_metadata.cpp`,
  `src/codestream/{encoder.h,headers.cpp,headers.h,workflow.cpp,workflow.h}`,
  `src/codestream/vardct/{encoder.cpp,headers.cpp}`,
  `tests/{codestream_encoder_test.cpp,modular_foundation_test.cpp,workflow_publication_test.cpp}`.
- `Build an optional shared C API` — gjxl `CMakeLists.txt`.
- `Add optional gjxl COG encoding with CPU fallback` — satellite: new
  `gjxl_backend.py`, `tests/test_gjxl_backend.py`, minimal sink-factory
  wiring in `cpu_cog_pipeline.py` and `mtg_gpu_renderer.py`, and
  `codecs/jxl-gpu-hybrid/results/G4/` scripts/evidence. Exact hunks are
  saved in `satellite-hooks.patch`. Add this `REPORT.md` with the gjxl review.

## Reproduction commands

All remote paths below are inside `/root/jxl-hybrid/g4`; bind
`/root/jxl-hybrid:/w`. Builds use `satellite-cujpegxl-build:cuda12.8`,
`docker run --rm --cpus=8 ... nice -n 10`:

```sh
cmake -S . -B build/g4 -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DGJXL_BUILD_SHARED_LIBRARY=ON -DGJXL_ENABLE_CUDA=ON \
  -DGJXL_ENABLE_METAL=OFF -DGJXL_ENABLE_LIBJXL_REFERENCE=OFF \
  -DCMAKE_CUDA_ARCHITECTURES=120
cmake --build build/g4 -j8
cmake --install build/g4 --prefix /w/g4/install
ctest --test-dir build/g4 \
  -R '^(codestream_encoder|c_api|c_api_cpp|c_api_image_conversion|modular_foundation|workflow_publication|serializer_storage_plan)$' \
  --output-on-failure -j2
```

Header gate in `satellite-cujpegxl-qualification:dev`, with
`PYTHONPATH=/w/g4/satellite` and `--cpus=8` (add `--gpus device=0` for encode
only, after verifying >=6144 MiB free):

```sh
python /w/g4/results/header_gate.py encode --library /w/g4/libgjxl-before.so \
  --corpus /w/corpus/dev --output /w/g4/before
python /w/g4/results/header_gate.py encode --library /w/g4/gjxl/build/g4/libgjxl.so \
  --corpus /w/corpus/dev --output /w/g4/after
python /w/g4/results/header_gate.py compare --before /w/g4/before --after /w/g4/after \
  --corpus /w/corpus/dev --tools /w/wp0/libjxl/build/tools --output /w/g4/header
```

408/408 passed. Header deltas: 406 images save 3 bytes, 2 save 2 bytes.
All 400 GDAL tiles exactly equal the new stock djxl 8-bit sRGB output.
Against CPU libjxl decoded pixels at d1.2: mean tile PSNR 52.165 dB,
minimum 38.901 dB (a comparison of two lossy encoders, not original RGB).

Native library SHA256:
- Before: `fffc3f535aa418fe8fa5f5c3e1430876cb245829dfd7665f090c01ba6a0b533e`
- Fixed: `ea0ef3f8b461bcbb949ebffa005925b7447da7a7275d60d0b56c73a1b036452f`

Scene gate: `bash /root/jxl-hybrid/g4/results/run_scenes.sh` on sat-5090.
The script records all docker flags, headroom checks, interleaving and scene
IDs. It mounts captures read-only and uses `--pid=host` solely so NVML can
identify the test process. Each Python encode holds the timing lock for its
encode duration only, capped by a 270-second alarm. CPU coding uses 14 base
threads plus 1 per overview; gjxl defaults to 12 context threads. Metrics
run after releasing the lock. The CONUS metric-only rerun used the corrected
minimum-edge handling; `G4_START_INDEX=2` continued the remaining scenes,
without repeating successful encodes.

Recovery gate, with >=6144 MiB GPU free, no timing claim or timing lock:

```sh
docker run --rm --pid=host --gpus device=0 --cpus=8 \
  -v /root/jxl-hybrid:/w -w /w/g4/satellite \
  -e PYTHONPATH=/w/g4/satellite \
  -e SATELLITE_GJXL_LIBRARY=/w/g4/gjxl/build/g4/libgjxl.so \
  satellite-cujpegxl-qualification:dev python /w/g4/results/lifecycle_gate.py
```

Overview review: in the qualification image, mount captures read-only as in
`run_scenes.sh`, then run `python /w/g4/results/review_overviews.py` (CPU only).
COG layout check: `python /w/g4/results/check_cog_layout.py /w/g4/scenes`
in the same image without GPU access. All 12 files report `LAYOUT=COG`.

Mocked binding/sink and existing backend tests, locally:
`python3 -m unittest tests.test_gjxl_backend tests.test_cpu_cog_pipeline tests.test_cujpegxl_backend -v`
(35 tests / PASS, including 11 new tests).

Flag-off local suite:
`SATELLITE_JXL_BACKEND=cpu-libjxl SATELLITE_CPU_SPOOL=0 python3 -m unittest discover -s tests -t .`
(Python 3.14.8, 547 tests / 27 skips / PASS).

Aggregate copied evidence locally:
`python3 codecs/jxl-gpu-hybrid/results/G4/summarize.py`
(6 scenes, 12,222 tiles, 926 MiB peak; overall status explicitly records the
production caller blockers).

Exact existing satellite hunks are in `results/G4/satellite-hooks.patch`:
- `cpu_cog_pipeline.py`: allowed backend, spooling selection, COG factory,
  native base-raster factory (4 hunks).
- `mtg_gpu_renderer.py`: direct Bridge-5 sink selection and actual encoder
  manifest metadata, gated on gjxl (3 hunks).
