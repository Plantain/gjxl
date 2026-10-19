#!/bin/bash
# CPU-only stock decoder qualification on sat-5090.
set -euo pipefail
root=/root/jxl-hybrid/g5
name=g5-stock-decode
exec 9>/root/jxl-hybrid/locks/timing.lock
flock 9
trap 'rc=$?; docker rm -f "$name" >/dev/null 2>&1 || true; echo "$rc" > "$root/results/stock-decode.exitcode"' EXIT
timeout --signal=TERM --kill-after=2s 270s docker run --rm --name "$name" \
  --cpus=8 -v /root/jxl-hybrid:/w --entrypoint nice \
  satellite-cujpegxl-build:cuda12.8 -n 10 python3 /w/g5/gjxl/tools/g5/decode.py \
  > "$root/results/stock-decode.log" 2>&1
