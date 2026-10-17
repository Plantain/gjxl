#!/bin/bash
# Claude only: invoke after establishing a clean window, without an outer flock.
# Each corpus/block owns its lock for at most 260 seconds and releases it before
# the next invocation. No builds, service controls, or quiet-host waits here.
set -euo pipefail
root=/root/jxl-hybrid/e3
blocks=${1:-1}
reps=${2:-6}
if (( blocks < 1 || blocks > 3 || reps < 1 )); then
  echo 'Usage: run_variants.sh [BLOCKS=1 (1..3)] [REPS=6 (>0)]' >&2
  exit 2
fi
run_id=$(date -u +%Y%m%dT%H%M%SZ)
for ((block=0; block<blocks; block++)); do
  for corpus in poc120 dev; do
    bash "$root/run_locked.sh" "toggles-abba-$run_id-$corpus-$block" \
      python3 /w/e3/gjxl/tools/e3/bracket.py "/w/corpus/$corpus" "$reps" \
      --variants --blocks 1 --block-start "$block"
  done
done
