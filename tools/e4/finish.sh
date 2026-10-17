#!/bin/bash
# Functional qualification only. Builds must have completed before invoking.
set -euo pipefail
root=/root/jxl-hybrid/e4/phase2
phase=${1:-identity}
run() {
  # Resume only with unchanged build artifacts. The caller chooses this
  # explicitly after a capacity deferral; failed jobs are always retried.
  if [[ ${E4_RESUME:-0} == 1 && -f "$root/results/$1.exitcode" ]] &&
      [[ $(cat "$root/results/$1.exitcode") == 0 ]]; then
    return 0
  fi
  for attempt in {1..10}; do
    if bash "/root/jxl-hybrid/e4/gjxl/tools/e4/run_locked.sh" "$@"; then return 0; else result=$?; fi
    if [[ $result != 75 || $attempt == 10 ]]; then return "$result"; fi
    # Capacity waits are outside the wrapper, after its lock has closed.
    sleep 15
  done
}
case "$phase" in
  identity)
    for mask in 0 1 2 3 4 5 6 7 unset; do
      for corpus in poc120 dev; do
        run "identity-$mask-$corpus" python3 /w/e4/gjxl/tools/e4/validate.py "$mask" "$corpus"
      done
    done
    # All variants are identical; decode one complete distinct output set.
    E4_CPU_ONLY=1 run decode-poc120-edges python3 /w/e4/gjxl/tools/e1/decode_gate.py \
      /w/e4/phase2/codestreams/poc120/7 /w/wp0/libjxl/build/tools/djxl
    E4_CPU_ONLY=1 run decode-dev python3 /w/e4/gjxl/tools/e1/decode_gate.py \
      /w/e4/phase2/codestreams/dev/7/identity /w/wp0/libjxl/build/tools/djxl
    ;;
  asan|memcheck|initcheck)
    for mask in 0 1 2 3 4 5 6 7; do
      for section in dc backend resident; do
        run "$phase-$mask-$section" python3 /w/e4/gjxl/tools/e4/check.py "$phase" "$mask" "$section"
      done
    done
    ;;
  sync)
    for tool in racecheck synccheck; do
      for section in dc resident; do
        run "$tool-7-$section" python3 /w/e4/gjxl/tools/e4/check.py "$tool" 7 "$section"
      done
    done
    ;;
  endurance)
    for mask in 0 1 2 3 4 5 6 7; do
      run "endurance-accurate-$mask" python3 /w/e4/gjxl/tools/e4/check.py release "$mask" endurance
    done
    run endurance-accurate-3-extended python3 /w/e4/gjxl/tools/e4/check.py release 3 endurance --reps 75
    run endurance-accurate-6-extended python3 /w/e4/gjxl/tools/e4/check.py release 6 endurance --reps 75
    run endurance-accurate-7-extended50k python3 /w/e4/gjxl/tools/e4/check.py release 7 endurance --reps 125
    run asan-endurance-7 python3 /w/e4/gjxl/tools/e4/check.py asan 7 endurance
    ;;
  *) echo 'Usage: finish.sh identity|asan|memcheck|initcheck|sync|endurance' >&2; exit 2 ;;
esac
