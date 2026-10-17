#!/bin/bash
# Functional tests only. Each mask releases the lock before the next job.
set -euo pipefail
root=/root/jxl-hybrid/e3
start=${1:-0}
end=${2:-127}
for ((mask=start; mask<=end; mask++)); do
  printf -v label 'toggles-identity-%03d' "$mask"
  # GPU-capacity retries happen only after the child has released the lock.
  for attempt in {1..10}; do
    if bash "$root/run_locked.sh" "$label" python3 \
        /w/e3/gjxl/tools/e3/validate_toggles.py "$mask"; then
      cat "$root/results/$label.jsonl"
      break
    else
      result=$?
      if [[ $result != 75 || $attempt == 10 ]]; then exit "$result"; fi
      sleep 20
    fi
  done
done
