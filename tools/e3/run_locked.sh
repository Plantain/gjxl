#!/bin/bash
# Copy to /root/jxl-hybrid/e3/run_locked.sh and invoke on sat-5090.
set -euo pipefail
label=$1
shift
mkdir -p /root/jxl-hybrid/e3/results
exec 9>/root/jxl-hybrid/locks/timing.lock
flock 9
gpu=()
if [[ ${E3_CPU_ONLY:-0} != 1 ]]; then
  free=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
  if (( free < 6144 )); then
    echo "GPU launch deferred: only $free MiB free" >&2
    exit 75
  fi
  gpu=(--gpus device=0)
fi
date -u +%FT%TZ > "/root/jxl-hybrid/e3/results/$label.meta"
nvidia-smi --query-gpu=memory.free,utilization.gpu --format=csv >> "/root/jxl-hybrid/e3/results/$label.meta"
name="e3-$label"
trap 'result=$?; docker rm -f "$name" >/dev/null 2>&1 || true; echo "$result" > "/root/jxl-hybrid/e3/results/$label.exitcode"' EXIT
timeout --signal=TERM --kill-after=10 260 docker run --rm --name "$name" \
  --pid=host --cpus=16 "${gpu[@]}" --entrypoint /bin/bash \
  -v /root/jxl-hybrid:/w satellite-cujpegxl-build:cuda12.8 \
  -c 'exec "$@"' bash "$@" \
  > "/root/jxl-hybrid/e3/results/$label.jsonl" \
  2> "/root/jxl-hybrid/e3/results/$label.stderr"
