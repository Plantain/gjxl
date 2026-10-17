#!/bin/bash
# Functional gate for the frozen toggle builds. Does not invoke timing modes.
set -euo pipefail
root=/root/jxl-hybrid/e3
run() {
  for attempt in {1..10}; do
    if bash "$root/run_locked.sh" "$@"; then return 0; else result=$?; fi
    if [[ $result != 75 || $attempt == 10 ]]; then return "$result"; fi
    # The child has released its lock before any capacity retry wait.
    sleep 20
  done
}
case ${1:-all} in
  all)
    run toggles-regression python3 /w/e3/gjxl/tools/e3/regress_toggles.py
    run toggles-identity-unset python3 /w/e3/gjxl/tools/e3/validate_toggles.py --unset --default-mask 0
    bash "$root/gjxl/tools/e3/validate_matrix.sh" 0 127 > "$root/results/toggles-matrix.log"
    ;;
  remaining) ;;
  *) echo 'Usage: finish_toggles.sh [all|remaining]' >&2; exit 2 ;;
esac
E3_CPU_ONLY=1 run toggles-conformance python3 /w/e3/gjxl/tools/e1/decode_gate.py \
  /w/e3/toggle-codestreams/unset /w/wp0/libjxl/build/tools/djxl
for section in providers backend resident; do
  run "toggles-asan-$section" python3 /w/e3/gjxl/tools/e3/sanitize_toggles.py \
    asan --section "$section"
done
for tool in memcheck initcheck; do
  run "toggles-$tool" python3 /w/e3/gjxl/tools/e3/sanitize_toggles.py "$tool"
done
for mask in 0 127; do
  run "toggles-dev-$mask" python3 /w/e3/gjxl/tools/e3/validate_toggles.py "$mask" \
    --corpus /w/corpus/dev --output-root /w/e3/toggle-dev
done
python3 "$root/gjxl/tools/e3/toggle_inventory.py" "$root/profiles" \
  > "$root/results/toggles-inventory.json"
python3 "$root/gjxl/tools/e3/check_bracket.py" > "$root/results/toggles-bracket-check.json"
python3 "$root/gjxl/tools/e3/collect_toggles.py" "$root" > "$root/results/toggles-gate.json"
