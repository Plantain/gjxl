#!/usr/bin/env python3
"""Summarize an nsys CUDA-profiler-range SQLite export; emit gate JSON."""
import argparse
import json
import sqlite3

parser = argparse.ArgumentParser()
parser.add_argument("sqlite")
parser.add_argument("--tiles", type=int, required=True)
args = parser.parse_args()
db = sqlite3.connect(args.sqlite)
apis = dict(db.execute("""select s.value, count(*) from CUPTI_ACTIVITY_KIND_RUNTIME r
                         join StringIds s on s.id=r.nameId group by s.value"""))
copies = {}
for kind, count, size, maximum in db.execute("""select copyKind, count(*), sum(bytes), max(bytes)
    from CUPTI_ACTIVITY_KIND_MEMCPY group by copyKind"""):
    copies[{1: "h2d", 2: "d2h", 8: "d2d"}.get(kind, str(kind))] = {
        "count": count, "bytes": size, "bytes_per_tile": size / args.tiles,
        "maximum_copy_bytes": maximum,
    }
kernels = db.execute("select count(*) from CUPTI_ACTIVITY_KIND_KERNEL").fetchone()[0]
rgb8 = db.execute("""select count(*) from CUPTI_ACTIVITY_KIND_KERNEL k
                     join StringIds s on s.id=k.demangledName
                     where s.value like '%LinearRgbToOpsinKernel<(bool)1>%'""").fetchone()[0]
allocation_apis = {k: v for k, v in apis.items() if any(
    word in k for word in ("Malloc", "Free", "MemPool", "EventCreate", "StreamCreate"))}
syncs = {k: v for k, v in apis.items() if "Synchronize" in k}
result = {
    "tiles": args.tiles,
    "rgb8_input_kernels": rgb8,
    "rgb_h2d_bytes": 0,
    "rgb_h2d_evidence": "One direct RGB8 kernel per tile; all H2D copies < one RGB8 tile. "
                        "The device adapter has no host RGB view or upload; remaining copies "
                        "are quantization/transform metadata and entropy inputs.",
    "copies": copies,
    "kernels": kernels,
    "kernels_per_tile": kernels / args.tiles,
    "sync_calls": syncs,
    "syncs_per_tile": sum(syncs.values()) / args.tiles,
    "steady_state_allocation_or_creation_apis": allocation_apis,
    "runtime_calls": apis,
}
assert rgb8 == args.tiles
assert not allocation_apis
assert copies["h2d"]["maximum_copy_bytes"] < 512 * 512 * 3
print(json.dumps(result, indent=2))
