#!/bin/bash
# Run on sat-5090 after the external timing-lock deadlock is resolved.
# Requires the frozen baseline, final Release/ASan builds and identity dumps.
set -euo pipefail
root=/root/jxl-hybrid/e3
run() {
  for attempt in {1..10}; do
    if bash "$root/run_locked.sh" "$@"; then return 0; else result=$?; fi
    if [[ $result != 75 ]]; then return "$result"; fi
    # The child wrapper has exited and released its lock before this wait.
    sleep 20
  done
  return 75
}

run asan-final env \
  ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:protect_shadow_gap=0 \
  UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  bash -c 'set -e
    /w/e3/gjxl/build/asan/gjxl_transfer_gate test 2 1
    /w/e3/gjxl/build/asan/gjxl_c_api_test
    /w/e3/gjxl/build/asan/gjxl_cuda_token_provider_test
    /w/e3/gjxl/build/asan/gjxl_cuda_backend_test'

for entry in corpus:codestreams edges:edges; do
  E3_CPU_ONLY=1 run "conformance-${entry%%:*}" python3 \
    /w/e3/gjxl/tools/e1/decode_gate.py "/w/e3/final-${entry#*:}" \
    /w/wp0/libjxl/build/tools/djxl
done

run endurance /w/e3/gjxl/build/e3/gjxl_transfer_gate leak 16 25 /w/corpus/dev
run endurance-heap /w/e3/gjxl/build/e3/gjxl_transfer_gate heap 16 50 /w/corpus/dev
run asan-endurance env \
  ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:protect_shadow_gap=0 \
  UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  /w/e3/gjxl/build/asan/gjxl_transfer_gate leak 16 25 /w/corpus/dev
for corpus in poc120 dev; do
  run "bracket-$corpus" python3 /w/e3/gjxl/tools/e3/bracket.py "/w/corpus/$corpus" 8
done
# Longer measurements retain the initial samples and release the lock between
# ABBA blocks. No build or other-job wait occurs inside a lock hold.
for block in 0 1 2; do
  run "bracket-confirm-poc120-$block" python3 /w/e3/gjxl/tools/e3/bracket.py \
    /w/corpus/poc120 40 --blocks 1 --block-start "$block"
  run "bracket-confirm-dev-$block" python3 /w/e3/gjxl/tools/e3/bracket.py \
    /w/corpus/dev 12 --blocks 1 --block-start "$block"
done

run trace-baseline-poc120 \
  /w/g3/nsys/opt/nvidia/nsight-systems/2025.6.3/bin/nsys profile \
  --trace=cuda,nvtx --sample=none --cpuctxsw=none \
  --capture-range=cudaProfilerApi --capture-range-end=stop \
  --force-overwrite=true --export=sqlite -o /w/e3/profiles/baseline-poc120 \
  /w/e3/baseline/gjxl_transfer_gate trace 12 1 /w/corpus/poc120
python3 "$root/gjxl/tools/e1/summarize_profile.py" \
  "$root/profiles/baseline-poc120.sqlite" --tiles 120 \
  > "$root/results/profile-baseline-poc120.json"

for tool in memcheck initcheck; do
  options=(--tool "$tool" --error-exitcode 99)
  if [[ $tool == memcheck ]]; then options+=(--leak-check full); fi
  run "$tool-provider" /usr/local/cuda/bin/compute-sanitizer "${options[@]}" \
    /w/e3/gjxl/build/e3/gjxl_cuda_token_provider_test
  run "$tool-resident" /usr/local/cuda/bin/compute-sanitizer "${options[@]}" \
    /w/e3/gjxl/build/e3/gjxl_transfer_gate devicebench 1 1 \
    /w/corpus/poc120/ahi-022-001.rgb
done

python3 "$root/gjxl/tools/e3/collect_results.py" "$root/results" > "$root/results/gate.json"
