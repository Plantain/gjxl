# E3 transfer and synchronization inventory

Baseline: `c3c82fb`, device CHW input, e8-balanced, d1.2, poc120 (120 tiles).
Nsight Systems 2025.6.3 / CUPTI capture with memory and synchronization backtraces.
Single-context attribution run; baseline E1 twelve-context totals agree.

| Direction | Bytes/tile | Calls/tile | Call sites (baseline lines) |
| --- | ---: | ---: | --- |
| D2H | 16.0 | 1.000 | src/gpu/cuda/cuda_input_preparation.cpp:239; src/gpu/cuda/cuda_input_preparation.cpp:367 |
| H2D | 47616.0 | 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:602; src/gpu/cuda/cuda_aq_resident.cpp:3878 |
| H2D | 292.0 | 5.000 | src/gpu/cuda/cuda_butteraugli.cpp:246; src/gpu/cuda/cuda_butteraugli.cpp:446 |
| D2H | 4.0 | 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:3455; src/gpu/cuda/cuda_aq_resident.cpp:1605 |
| H2D | 396288.0 | 7.000 | src/gpu/ops/ac_strategy_search.cpp:520; src/gpu/ops/ac_strategy_search.cpp:842 |
| H2D | 62976.0 | 7.000 | src/gpu/ops/ac_strategy_search.cpp:526; src/gpu/ops/ac_strategy_search.cpp:842 |
| D2H | 66048.0 | 7.000 | src/gpu/ops/ac_strategy_search.cpp:711; src/gpu/ops/ac_strategy_search.cpp:842 |
| H2D | 57243.0 | 5.000 | src/gpu/cuda/cuda_aq_resident.cpp:2451; src/gpu/ops/adaptive_quantization.cpp:612 |
| D2D | 16384.0 | 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:795; src/gpu/ops/adaptive_quantization.cpp:696 |
| D2H | 12.0 | 2.000 | src/gpu/cuda/cuda_aq_resident.cpp:805; src/gpu/ops/adaptive_quantization.cpp:696 |
| D2H | 4.0 | 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:3455; src/gpu/cuda/cuda_aq_resident.cpp:1232 |
| D2H | 24588.0 | 2.000 | src/gpu/cuda/cuda_aq_resident.cpp:1261; src/gpu/ops/adaptive_quantization.cpp:868 |
| D2H | 8.0 | 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:1299; src/gpu/ops/adaptive_quantization.cpp:868 |
| D2D | 3145728.0 | 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:2616; src/gpu/cuda/cuda_aq_resident.cpp:1311 |
| D2H | 334041.6 | 7.908 | src/gpu/cuda/cuda_aq_resident.cpp:2768; src/gpu/cuda/cuda_aq_resident.cpp:2638 |
| H2D | 53826.8 | 5.000 | src/gpu/cuda/cuda_ac_tokenization.cpp:211; src/codestream/vardct/encoder.cpp:2081 |
| D2H | 320.0 | 2.000 | src/gpu/cuda/cuda_ac_tokenization.cpp:242; src/codestream/vardct/encoder.cpp:2175 |
| D2H | 1165044.4 | 3.000 | src/gpu/cuda/cuda_ac_tokenization.cpp:276; src/codestream/vardct/encoder.cpp:2175 |
| D2H | 26761.6 | 0.042 | src/gpu/cuda/cuda_aq_resident.cpp:2687; src/gpu/cuda/cuda_aq_resident.cpp:2628 |

## Host synchronization sites

| Syncs/tile | Call sites (baseline lines) |
| ---: | --- |
| 1.000 | src/gpu/cuda/cuda_input_preparation.cpp:239; src/gpu/cuda/cuda_input_preparation.cpp:367 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:602; src/gpu/cuda/cuda_aq_resident.cpp:3878 |
| 5.000 | src/gpu/cuda/cuda_butteraugli.cpp:246; src/gpu/cuda/cuda_butteraugli.cpp:446 |
| 1.000 | src/gpu/cuda/cuda_butteraugli.cpp:264; src/gpu/cuda/cuda_butteraugli.cpp:468 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:1603; src/gpu/cuda/cuda_aq_resident.cpp:730 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:3455; src/gpu/cuda/cuda_aq_resident.cpp:1605 |
| 7.000 | src/gpu/ops/ac_strategy_search.cpp:520; src/gpu/ops/ac_strategy_search.cpp:842 |
| 7.000 | src/gpu/ops/ac_strategy_search.cpp:526; src/gpu/ops/ac_strategy_search.cpp:842 |
| 1.000 | src/gpu/ops/ac_strategy_search.cpp:633; src/gpu/ops/ac_strategy_search.cpp:842 |
| 7.000 | src/gpu/ops/ac_strategy_search.cpp:711; src/gpu/ops/ac_strategy_search.cpp:842 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:2451; src/gpu/ops/adaptive_quantization.cpp:612 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:795; src/gpu/ops/adaptive_quantization.cpp:696 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:805; src/gpu/ops/adaptive_quantization.cpp:696 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:1230; src/gpu/ops/adaptive_quantization.cpp:868 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:3455; src/gpu/cuda/cuda_aq_resident.cpp:1232 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:1261; src/gpu/ops/adaptive_quantization.cpp:868 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:1299; src/gpu/ops/adaptive_quantization.cpp:868 |
| 1.000 | src/gpu/cuda/cuda_aq_resident.cpp:2616; src/gpu/cuda/cuda_aq_resident.cpp:1311 |
| 0.992 | src/gpu/cuda/cuda_aq_resident.cpp:2743; src/gpu/cuda/cuda_aq_resident.cpp:2638 |
| 0.992 | src/gpu/cuda/cuda_aq_resident.cpp:2768; src/gpu/cuda/cuda_aq_resident.cpp:2638 |
| 1.000 | src/gpu/cuda/cuda_ac_tokenization.cpp:211; src/codestream/vardct/encoder.cpp:2081 |
| 1.000 | src/gpu/cuda/cuda_ac_tokenization.cpp:236; src/codestream/vardct/encoder.cpp:2175 |
| 1.000 | src/gpu/cuda/cuda_ac_tokenization.cpp:242; src/codestream/vardct/encoder.cpp:2175 |
| 1.000 | src/gpu/cuda/cuda_ac_tokenization.cpp:276; src/codestream/vardct/encoder.cpp:2175 |
| 0.008 | src/gpu/cuda/cuda_aq_resident.cpp:2687; src/gpu/cuda/cuda_aq_resident.cpp:2628 |

## Consumption and implemented treatment

- RGB: device input reads in place; only the 16-byte input validation/matrix statistics result reaches the host.
- Search descriptors/matrices (459,264 bytes H2D), AQ matrices (47,616 bytes H2D), and Butteraugli filters (292 bytes H2D) are immutable for a lane/settings pair. Cache exact contents in the fixed arena.
- The seven AC candidate cost arrays (66,048 bytes D2H) are consumed by the CPU selector. Batch their reads into one completion; preserve CPU placement/tie breaking.
- Transform metadata (57,243 bytes H2D average) is built from the selected strategy grid and consumed by AQ kernels. Kept for this iteration.
- AQ score/population/error/quantizer readbacks are consumed by validation and CPU coefficient-order construction. Batch scalar readbacks.
- Sparse/dense AC coefficients, raw quantizers, DC coefficients and CfL maps supply the CPU frame representation. Preserve them; narrow exact AC integer values with overflow fallback.
- `GJXL_E3_CPU_TOKENS=1` selects CPU tokenization, consuming coefficients already needed by the CPU. It removes token descriptors (53,827 bytes H2D average), token/histogram readbacks, and the duplicate 3 MiB D2D coefficient handoff. Unset retains E1 GPU-token selection. The earlier unconditional batch-scheduling marker has been removed.
- CPU entropy consumes compact token values/contexts plus histogram counts. Dense histogram is 760,320 bytes/tile: return only nonzero (index, count) pairs. Narrow token values with exact overflow flags.
- D2D copies initialize AQ state. With explicit GPU tokenization, the coefficient-owner copy is chained to frame readback.
- Event waits immediately followed by blocking copies are redundant: readbacks on the same stream prove prior submissions complete. Track successful stream completion serials, preserving error injection and failure draining.

Full machine-readable inventory, including resolved stacks: satellite `results/E3/inventory.json`.
The backtrace capture emits both wrapper and versioned API records for each
synchronization. The inventory counts each thread/correlation ID once, with
the resolved wrapper stack: 37 stream + 8.9917 event waits per tile.
The nsys PID-namespace export did not resolve executable symbols. `inventory.py` resolves addresses using the preserved executable; base `0x55d8dfab5000` was recovered from the exact return address of `cudaStreamSynchronize` in `CopyHostToDeviceBatch` (object offset `0x15206d`).
After numbers and gate evidence: see REPORT.md.

## Previous all-on steady-state profile (before toggle revision)

Twelve resident contexts, 120 device CHW poc120 tiles, e8-balanced, d1.2.

| Measure | E1 baseline | E3 | Reduction |
| --- | ---: | ---: | ---: |
| H2D bytes/tile | 618,241.8 | 57,243.0 | 10.80× |
| D2H bytes/tile | 1,616,847.6 | 340,062.1 | 4.75× |
| Total PCIe bytes/tile | 2,235,089.4 | 397,305.1 | 5.63× |
| Host synchronizations/tile | 45.9917 | 8.0000 | 5.75× |
| Kernels/tile | 432.2167 | 429.2167 | 0.69% fewer |
| D2D bytes/tile | 3,162,112 | 16,384 | 193× |

RGB H2D remains zero. No steady device allocation/free, event-create or
stream-create calls occur. The remaining H2D is selected transform metadata;
the remaining D2H supplies CPU placement, validation, and entropy coding.
Raw final trace: `/root/jxl-hybrid/e3/profiles/final-poc120.{nsys-rep,sqlite}`.

## Selected defaults and independent switches

`GJXL_E3_NARROW_COEFFICIENTS` and `GJXL_E3_COMPACT_HISTOGRAMS` default on.
The other five variables default off. Unset uses the selected default; `1`
enables and any other explicit value (including `0`) disables the feature.
Values are read once per process, before creating an encoder. Explicitly
setting all seven to `0` restores E1's transfers, allocations, GPU-token
policy and waits. `GJXL_CUDA_COMPACT_AC` remains OFF in the Release build;
that older compile-time option remains supported.

Claude selected these defaults after production-paused toggle measurements
in `toggles-abba-20261017T105843Z-*`, `cw11-*`, and `cw12-*`. The selected
pair was within throughput noise (0% poc120, −2% dev). The worker ran no new
throughput timing or profiler capture for this default selection.

### Per-tile traffic at the selected defaults

Device-input poc120, e8-balanced d1.2, warmed steady state. **Derived from
the existing inventory**, not newly profiled. The two headers are included
in the net savings, and neither feature changes the steady-state sync count.

| Measure | E1 / all off | Selected defaults | Change |
| --- | ---: | ---: | ---: |
| H2D bytes/tile | 618,241.80 | 618,241.80 | 0 |
| D2H bytes/tile | 1,616,847.62 | 764,120.18 | −852,727.43 |
| Total PCIe bytes/tile | 2,235,089.42 | 1,382,361.98 | −38.15% (1.62× less) |
| Host syncs/tile | 45.9917 | 45.9917 | 0 |
| Kernels/tile | 432.2167 | 434.2167 | +2 |
| D2D bytes/tile | 3,162,112 | 3,162,112 | 0 |
| RGB H2D bytes/tile | 0 | 0 | 0 |

Syncs remain 37 stream plus 8.9917 event waits. The two added kernels pack
coefficients and compact histograms. These totals apply to the device-input
path and preset above, not to host RGB uploads or other presets. Evidence:
`results/E3/defaults-inventory.json`; `tools/e3/toggle_inventory.py` derives
the totals from preserved SQLite captures.

These are **inventory-derived steady-state deltas**, using the existing
`baseline-poc120.sqlite` and GPU-token `candidate2.sqlite`, with 120 tiles,
device input, e8-balanced, d1.2. No new timing or profile run was performed.
`tools/e3/toggle_inventory.py` reproduces the per-payload numbers by selecting
the last token readbacks within each tile/stream in those captures. Small
result: `results/E3/toggles-inventory.json`.

| Environment variable | Bytes moved per tile, off → on | Net PCIe bytes saved | Host syncs saved alone |
| --- | --- | ---: | ---: |
| `GJXL_E3_RESIDENT_TABLES` | Static-table H2D 507,172 → 0 after warm-up | 507,172 | 20 stream |
| `GJXL_E3_COMPACT_HISTOGRAMS` | Histogram D2H 760,320 → 19,005.67, plus 8-byte header | 741,306.33 | 0 |
| `GJXL_E3_NARROW_COEFFICIENTS` | Frame coefficient/metadata D2H 360,803.17 → 249,378.07, plus 4-byte width | 111,421.10 | 0 |
| `GJXL_E3_BATCHED_READBACKS` | Search costs 66,048 and AQ error/quantizer 12 D2H, unchanged | 0 | 8 stream |
| `GJXL_E3_SYNC_REMOVAL` | No transfer-byte change | 0 | 6.9917 event |
| `GJXL_E3_CPU_TOKENS` | H2D 53,826.8 → 0; D2H 1,165,364.45 → 0; D2D 3,145,728 → 0 | 1,219,191.25 | 5 (3 stream, 2 event) |
| `GJXL_E3_NARROW_TOKENS` | Token-value D2H 269,816.3 → 67,992.02, plus 8-byte header; uint16 contexts unchanged | 201,816.28 | 0 |

Resident tables cover 396,288 bytes of search descriptors, 62,976 bytes of
search matrices, 47,616 bytes of AQ matrices, and 292 bytes of Butteraugli
filters. Batched reads save six waits on the seven search arrays, then two
on AQ error/quantizer reads, while preserving the original submission wait
unless sync removal is also enabled. Sync removal defers the initial-quant,
search, policy-prepare, policy, coefficient-owner, sparse-pack (119/120 tiles)
and token-provider waits until a blocking copy proves completion.

The two token-compaction flags share one 8-byte header and one kernel when
both are enabled. Thus combined savings are their standalone sum **plus
8 bytes**, not twice the header. The prior trace used uint8 tokens on 118
tiles and uint16 on two; the provider regression suite covers uint32 overflow
fallback too. Histogram-only mode allocates no narrow-value plane; token-only
mode allocates no sparse histogram plane. Both off run no compacting kernel.
First-use output-capacity retries can add a compact-header read/sync; the
inventory numbers are warmed, non-retry counts.

CPU tokens makes both GPU-token compaction flags inactive, and overlaps sync
removal by **two event waits**. With CPU tokens on, sync removal saves 4.9917
additional event waits. All-on totals therefore remain the historical
397,305.07 PCIe bytes and 8 host syncs per tile by attribution; these are
not a fresh measurement of the toggle binary. CPU tokens now changes only
tokenization, without installing the former entropy batch marker. It takes
precedence over legacy GPU-token selectors when explicitly enabled. The
variant/identity tools clear those legacy selectors before each subprocess.
