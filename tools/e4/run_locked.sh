#!/bin/bash
# Copy to /root/jxl-hybrid/e4/run_locked.sh and invoke on sat-5090.
set -euo pipefail
label=$1
shift
results=/root/jxl-hybrid/e4/phase4/results
mkdir -p "$results"
exec 9>/root/jxl-hybrid/locks/timing.lock
flock 9
e4_started=$(date +%s)
gpu=()
caps=()
if [[ ${E4_COUNTERS:-0} == 1 ]]; then
  # Only this profiling container gains counter access. Do not alter the
  # driver's system-wide counter policy, clocks, or production services.
  caps=(--cap-add=SYS_ADMIN)
fi
if [[ ${E4_CPU_ONLY:-0} != 1 ]]; then
  free=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -1)
  if (( free < 6144 )); then
    echo "GPU launch deferred: only $free MiB free" >&2
    exit 75
  fi
  gpu=(--gpus device=0)
fi
date -u +%FT%TZ > "$results/$label.meta"
nvidia-smi --query-gpu=memory.free,utilization.gpu --format=csv >> "$results/$label.meta"
name="e4-$label"
cleanup() {
  result=$?
  timeout --kill-after=1 5 docker rm -f "$name" >/dev/null 2>&1 || true
  echo "$result" > "$results/$label.exitcode"
  echo "$(( $(date +%s) - e4_started ))" > "$results/$label.lock_seconds"
}
trap cleanup EXIT
timeout --signal=TERM --kill-after=3 245 docker run --rm --name "$name" \
  --pid=host --cpus=16 --memory=16g "${gpu[@]}" "${caps[@]}" --entrypoint /bin/bash \
  -v /root/jxl-hybrid:/w satellite-cujpegxl-build:cuda12.8 \
  -c 'exec "$@"' bash "$@" \
  > "$results/$label.jsonl" \
  2> "$results/$label.stderr"
