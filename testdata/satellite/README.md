# Raw quant 257 regression

`raw-quant-257.rgb` is 512×512 interleaved RGB8, no header. It is a deterministic
derivative of the published SEVIRI rapid product for 2026-10-18 22:45 UTC,
whose production encoding reported the raw-quant readback failure. Decode its
4× overview tile at block row 2, column 0; zero-pad to 512×512; multiply RGB
by 1.4, round to nearest even, and clamp to [0, 255]. `tools/g5/published.py`
and the `mutations` mode of `tools/g5/gate.py` reproduce this derivation.

SHA256: `1102a4cac308ad835083334e9b117e382b4eeda0a27440c5818588ddc5b8bc34`.

The unmodified `33e1734` encoder fails at e8-balanced, distance 1.19. Diagnostic
readback shows minimum 5, maximum 257. The original decoded tile itself
re-encodes successfully; this fixture is a derivative, not a capture of the
uncompressed production input. Small evidence and source hashes are recorded
in satellite `results/G5/`; the source COG remains on sat-5090 under `g5/published/`.
