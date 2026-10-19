#!/bin/bash
# Per-task reruns on sat-5090. run.sh acquires/releases the timing lock.
set -euo pipefail
root=/root/jxl-hybrid/g5
run="$root/gjxl/tools/g5/run.sh"
gate=/w/g5/gjxl/tools/g5/gate.py
candidate=/w/g5/gjxl/build/g5/libgjxl.so
task=$1
case "$task" in
  identity-[0-3])
    part=${task##*-}
    args=(--manifest /w/g5/manifest-exact.json --start "$((part*3000))" --count 3000)
    ;;
  mutations|published|synthetic|mixtures)
    args=(--manifest "/w/g5/$task.json")
    ;;
  plateau-[01])
    export GJXL_E4_BLOCKING_WAITS=${task##*-}
    exec bash "$run" "$task" python3 "$gate" endurance --library "$candidate" \
      --manifest /w/g5/repro.json --output "/w/g5/results/$task.json"
    ;;
  sanitize-memcheck|sanitize-initcheck|sanitize-racecheck)
    export G5_IMAGE=satellite-cujpegxl-build:cuda12.8
    exec bash "$run" "$task" /usr/local/cuda/bin/compute-sanitizer \
      --tool "${task#sanitize-}" --error-exitcode 91 \
      /w/g5/gjxl/build/g5/gjxl_cuda_raw_quant_readback_test \
      /w/g5/gjxl/testdata/satellite/raw-quant-257.rgb 1 1
    ;;
  *) echo "Unknown G5 task: $task" >&2; exit 2 ;;
esac
bash "$run" "$task-baseline" python3 "$gate" scan "${args[@]}" --release \
  --output "/w/g5/results/$task-baseline.json"
bash "$run" "$task-candidate" python3 "$gate" scan "${args[@]}" --release \
  --library "$candidate" --baseline "/w/g5/results/$task-baseline.json" \
  --save /w/g5/codestreams --output "/w/g5/results/$task-candidate.json"
