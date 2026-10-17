#!/bin/bash
# Run on sat-5090. Keep Claude's measured toggles/ artifacts untouched.
set -euo pipefail
kind=${1:-release}
case "$kind" in
  release) build=defaults; config=Release; flags=(-DCMAKE_CXX_FLAGS=-g1) ;;
  asan)
    build=defaults-asan; config=RelWithDebInfo
    flags=(-DCMAKE_CXX_FLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer'
           -DCMAKE_EXE_LINKER_FLAGS=-fsanitize=address,undefined
           -DCMAKE_SHARED_LINKER_FLAGS=-fsanitize=address,undefined)
    ;;
  *) echo 'Usage: prepare_defaults.sh release|asan' >&2; exit 2 ;;
esac
root=/root/jxl-hybrid/e3
mkdir -p "$root/results"
name=e3-build-$build
trap 'result=$?; docker rm -f "$name" >/dev/null 2>&1 || true; echo "$result" > "$root/results/defaults-build-$kind.exitcode"' EXIT
docker run --rm --name "$name" --cpus=8 --entrypoint /bin/bash \
  -v /root/jxl-hybrid:/w -w /w/e3/gjxl satellite-cujpegxl-build:cuda12.8 \
  -c 'set -euo pipefail
      build=$1; config=$2; shift 2
      nice -n 10 cmake -S . -B "/w/e3/$build" -G Ninja \
        -DCMAKE_BUILD_TYPE="$config" "$@" \
        -DGJXL_ENABLE_CUDA=ON -DGJXL_ENABLE_METAL=OFF \
        -DGJXL_ENABLE_LIBJXL_REFERENCE=OFF -DCMAKE_CUDA_ARCHITECTURES=120 \
        -DGJXL_BUILD_SHARED_LIBRARY=ON -DGJXL_BUILD_BENCHMARKS=ON \
        -DGJXL_CUDA_COMPACT_AC=OFF
      nice -n 10 cmake --build "/w/e3/$build" -j8 --target \
        gjxl_shared gjxl_transfer_gate gjxl_cuda_backend_test \
        gjxl_cuda_token_provider_test gjxl_cuda_compact_ac_test \
        gjxl_cuda_low_effort_test' bash "$build" "$config" "${flags[@]}" \
  > "$root/results/defaults-build-$kind.log" 2>&1
tail -12 "$root/results/defaults-build-$kind.log"
