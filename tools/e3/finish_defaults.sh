#!/bin/bash
# Functional checks only, with all E3 and legacy token variables unset.
# Requires prepare_defaults.sh release and prepare_defaults.sh asan first.
set -euo pipefail
root=/root/jxl-hybrid/e3
phase=${1:-all}
case "$phase" in
  all|identity|checks) ;;
  *) echo 'Usage: finish_defaults.sh [all|identity|checks]' >&2; exit 2 ;;
esac
run() {
  for attempt in {1..10}; do
    if bash "$root/run_locked.sh" "$@"; then return 0; else result=$?; fi
    if [[ $result != 75 || $attempt == 10 ]]; then return "$result"; fi
    # The child has released its lock before any capacity retry wait.
    sleep 20
  done
}
if [[ $phase != checks ]]; then
  for corpus in poc120 dev; do
    run "defaults-identity-$corpus" python3 /w/e3/gjxl/tools/e3/validate_toggles.py \
      --unset --executable /w/e3/defaults/gjxl_transfer_gate \
      --corpus "/w/corpus/$corpus" --output-root "/w/e3/default-codestreams/$corpus"
  done
  # Decode one copy of each corpus/edge output: 381 + 1200 = 1581 files.
  E3_CPU_ONLY=1 run defaults-decode-poc120-edges python3 /w/e3/gjxl/tools/e1/decode_gate.py \
    /w/e3/default-codestreams/poc120/unset /w/wp0/libjxl/build/tools/djxl
  E3_CPU_ONLY=1 run defaults-decode-dev python3 /w/e3/gjxl/tools/e1/decode_gate.py \
    /w/e3/default-codestreams/dev/unset/identity /w/wp0/libjxl/build/tools/djxl
fi
if [[ $phase == identity ]]; then exit 0; fi
for section in providers coefficients backend resident; do
  run "defaults-asan-$section" python3 /w/e3/gjxl/tools/e3/sanitize_toggles.py \
    asan --defaults --build /w/e3/defaults-asan --section "$section"
done
for tool in memcheck initcheck; do
  for section in providers coefficients resident; do
    run "defaults-$tool-$section" python3 /w/e3/gjxl/tools/e3/sanitize_toggles.py \
      "$tool" --defaults --build /w/e3/defaults --section "$section"
  done
done
python3 "$root/gjxl/tools/e3/toggle_inventory.py" "$root/profiles" \
  > "$root/results/defaults-inventory.json"
python3 "$root/gjxl/tools/e3/check_bracket.py" > "$root/results/defaults-bracket-check.json"
if python3 "$root/gjxl/tools/e3/collect_defaults.py" "$root" > "$root/results/defaults-gate.json"; then
  echo 0 > "$root/results/defaults-collection.exitcode"
else
  result=$?
  echo "$result" > "$root/results/defaults-collection.exitcode"
  exit "$result"
fi
