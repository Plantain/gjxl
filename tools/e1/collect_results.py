#!/usr/bin/env python3
"""Aggregate the saved E1 gate logs. No third-party Python packages needed."""
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])


def rows(name):
    return [json.loads(line) for line in (root / f"{name}.jsonl").read_text().splitlines()]


def rates(name):
    records = rows(name)
    result = {}
    for path in ("host", "device"):
        samples = [r for r in records if r.get("path") == path]
        result[path] = sum(r["tiles"] for r in samples) / sum(r["seconds"] for r in samples)
    baseline = [r for r in records if r.get("encoder") == "gjxl-cuda"]
    if baseline:
        result["g4_host"] = sum(r["encodes"] for r in baseline) / sum(r["seconds"] for r in baseline)
        result["device_vs_g4"] = result["device"] / result["g4_host"]
    result["device_vs_resident_host"] = result["device"] / result["host"]
    return result


timing = {name: rates(name) for name in (
    "bench-poc120-c12", "bench-dev-c12", "bench-poc120-c16", "bench-dev-c16",
    "bracket-poc120-c12", "bracket-dev-c12")}
profile = json.loads((root / "profile-summary.json").read_text())
identity = json.loads((root / "g4-byte-identity.json").read_text())
decode = json.loads((root / "conformance.jsonl").read_text())
endurance = [r for r in rows("endurance") if "encodes" in r]
tail = endurance[len(endurance) // 2:]
functional = rows("functional-final")
exit_codes = {name: int((root / f"{name}.exitcode").read_text()) for name in
              ("functional-final", "asan-final", "c-api-final")}
encoder_vram = max(r["encoder_vram_bytes"] for name in ("bench-dev-c12", "bench-dev-c16")
                   for r in rows(name) if "encoder_vram_bytes" in r)
gates = {
    "byte_identity": identity["files"] == 1560 and identity["mismatches"] == 0
                     and sum(r.get("identity", False) for r in functional) == 4,
    "stock_decode": decode["decoded"] == 1560 and decode["failed"] == 0,
    "zero_rgb_h2d": profile["rgb_h2d_bytes"] == 0 and profile["rgb8_input_kernels"] == 120,
    "no_steady_device_allocations": not profile["steady_state_allocation_or_creation_apis"],
    "throughput_at_least_host": all(timing[n]["device"] >= timing[n]["host"]
                                    and timing[n]["device"] >= timing[n]["g4_host"]
                                    for n in ("bracket-poc120-c12", "bracket-dev-c12")),
    "target_900": all(timing[n]["device"] >= 900
                      for n in ("bench-poc120-c12", "bench-dev-c12")),
    "vram_cap": encoder_vram <= 2048 * 1024**2,
    "asan_ubsan": all(code == 0 for code in exit_codes.values())
                  and all((root / f"{name}.stderr").stat().st_size == 0 for name in exit_codes),
    "endurance": endurance[-1]["encodes"] == 10000
                 and len({r["vram_bytes"] for r in endurance}) == 1
                 and len({r["rss_bytes"] for r in tail}) == 1,
}
result = {
    "work_package": "E1", "passed": all(gates.values()), "gates": gates,
    "timing_tiles_per_second": timing,
    "timing_note": "Production stayed running. The bracket runs were under heavier load; "
                   "the separate 12-context runs demonstrate the absolute target. "
                   "Claude still confirms a clean window.",
    "encoder_peak_vram_bytes": encoder_vram, "device_cap_bytes": 2048 * 1024**2,
    "endurance_encodes": endurance[-1]["encodes"],
    "endurance_final_rss_bytes": tail[-1]["rss_bytes"],
    "endurance_tail_rss_growth_bytes": max(r["rss_bytes"] for r in tail) - min(r["rss_bytes"] for r in tail),
    "identity_codestreams": identity["files"], "decoded_codestreams": decode["decoded"],
    "exit_codes": exit_codes,
    "profile": {k: profile[k] for k in ("copies", "kernels_per_tile", "syncs_per_tile")},
}
print(json.dumps(result, indent=2))
assert result["passed"], gates
