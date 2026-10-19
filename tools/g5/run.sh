#!/bin/bash
# Run on sat-5090; all files and containers belong to G5.
set -euo pipefail
label=$1
shift
root=/root/jxl-hybrid/g5
mkdir -p "$root/results"
exec 9>/root/jxl-hybrid/locks/timing.lock
flock 9
name="g5-$label"
trap 'rc=$?; docker rm -f "$name" >/dev/null 2>&1 || true; echo "$rc" > "$root/results/$label.exitcode"' EXIT
timeout --signal=TERM --kill-after=2s 270s docker run --rm --name "$name" \
  --gpus device=0 --pid=host --cpus=16 \
  -v /root/jxl-hybrid:/w \
  -v /root/migration/cujpegxl-qualification/corpus-captures:/captures:ro \
  -e PYTHONPATH=/opt/satellite-gpu-service \
  -e GJXL_E4_BLOCKING_WAITS="${GJXL_E4_BLOCKING_WAITS:-1}" \
  -e G5_EXPECTED_PEAK_MIB="${G5_EXPECTED_PEAK_MIB:-2048}" \
  -e G5_LIMIT_SECONDS="${G5_LIMIT_SECONDS:-250}" \
  --entrypoint python3 "${G5_IMAGE:-satellite-sat5090-gpu:gjxl-e5-4813fa9e044eb4210588}" \
  /w/g5/gjxl/tools/g5/guard.py "/w/g5/results/$label.guard.json" "$@" \
  > "$root/results/$label.log" 2>&1
