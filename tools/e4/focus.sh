#!/bin/bash
# The phase-2 matrix is complete. Run only the requested phase-4 focused gate.
set -euo pipefail
run() {
  for attempt in {1..10}; do
    if bash /root/jxl-hybrid/e4/gjxl/tools/e4/run_locked.sh "$@"; then return 0; else result=$?; fi
    if [[ $result != 75 || $attempt == 10 ]]; then return "$result"; fi
    sleep 15  # Capacity retry outside the timing lock.
  done
}
# The option probe does not encode, but its binary links the CUDA driver.
run defaults-options python3 /w/e4/gjxl/tools/e4/focus.py options
for corpus in poc120 dev; do
  run "defaults-$corpus" python3 /w/e4/gjxl/tools/e4/validate.py unset "$corpus"
done
E4_CPU_ONLY=1 run defaults-decode python3 /w/e4/gjxl/tools/e4/focus.py decode
run defaults-asan python3 /w/e4/gjxl/tools/e4/focus.py asan
run defaults-memory python3 /w/e4/gjxl/tools/e4/focus.py memory
python3 /root/jxl-hybrid/e4/gjxl/tools/e4/focus.py collect --root /root/jxl-hybrid/e4/phase4 \
  > /root/jxl-hybrid/e4/phase4/results/gate.json
