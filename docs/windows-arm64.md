# Native Windows ARM64

GJXL's CPU encoder, command-line tools, C/C++ interfaces and Rust bindings can
build and run natively on Windows ARM64. The existing NEON color-conversion and
workflow analysis paths recognize MSVC's `_M_ARM64` macro. Metal and CUDA must
be disabled; there is no Adreno GPU backend.

## Toolchain and build

Install Visual Studio 2022 Build Tools with the Windows SDK and these components:

- MSVC v143 ARM64/ARM64EC tools, toolset **14.44.35207**
  (`Microsoft.VisualStudio.Component.VC.14.44.17.14.ARM64`).
- C++ Clang tools for Windows, for native ARM64 `libclang.dll` (Rust bindgen)
  and `clang-cl.exe` (the independent pinned decoder).
- CMake 3.25 or later, Ninja and Python 3 on `PATH`.
- For Rust, the native `aarch64-pc-windows-msvc` Rust toolchain.

From a PowerShell terminal at the repository root:

```powershell
& ./.github/actions/setup-native-toolchain/setup-msvc.ps1 -Architecture Arm64
cmake -S . -B build/windows-arm64 -G Ninja `
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_STANDARD=20 `
  -DGJXL_ENABLE_METAL=OFF -DGJXL_ENABLE_CUDA=OFF `
  -DGJXL_BUILD_TESTS=ON -DGJXL_BUILD_BENCHMARKS=ON `
  -DGJXL_ENABLE_LIBJXL_REFERENCE=OFF
cmake --build build/windows-arm64 --parallel 8
ctest --test-dir build/windows-arm64 --output-on-failure --parallel 4
```

The setup script selects `HostARM64/ARM64/cl.exe` and the matching libraries,
and sets `LIBCLANG_PATH` to Visual Studio's ARM64 LLVM directory when installed.
It changes only the current process environment. Outside GitHub Actions it
reports missing components without invoking the installer. In Actions it also
exports the environment for later steps and installs missing pinned MSVC tools.
The x64 CI jobs continue to select toolset 14.37.32822.

Use a separate build directory with `-DCMAKE_CXX_STANDARD=23` for C++23. GJXL
selects `/std:c++23preview` for MSVC 19.44, including installed C++ consumers
and the configure-time storage probe. `/std:c++latest` on this compiler enables
post-C++23 behavior and is intentionally rejected. Debug iterator mode, unknown
compiler/STL versions and mismatched recognized version pairs remain rejected.

The native encoder is `build/windows-arm64/gjxl_encode.exe`; run it with
`--help` for its VarDCT and lossless Modular input options.

```powershell
$env:CMAKE_GENERATOR = 'Ninja'
cargo test --manifest-path rust/Cargo.toml --workspace
cargo clippy --manifest-path rust/Cargo.toml --workspace --all-targets -- -D warnings
python rust/check_native_rebuild.py
```

Rust's native build remains host-equals-target: native ARM64 does not require
removing the cross-compilation guard. CUDA is not enabled for this configuration.

## Independent decoder verification

```powershell
git submodule update --init --recursive third_party/libjxl
cmake --build build/windows-arm64 --target codestream-conformance --parallel 4
```

The decoder builder finds `clang-cl` through `LIBCLANG_PATH` when necessary.
It builds the pinned libjxl revision, verifies its identity, and exchanges PFM
files with the test encoder. Optional JPEG, PNG and GIF libraries are disabled
for this verification tool to avoid linking unrelated host libraries found on
`PATH` (for example, Strawberry Perl's x64 MinGW libraries).

## Storage audit for MSVC 19.44

The reviewed headers are from toolset 14.44.35207, compiler 19.44.35229, STL
version 143/update 202503. The [storage contract](storage-toolchain.md) still
uses its original pre-allocation bounds; the extension admits this specific
compiler/header family without providing a bypass.

| Header and implementation | Reason the existing bound applies |
| --- | --- |
| `xmemory`: `allocator::allocate_at_least`, `allocator_traits::allocate_at_least`, `_Allocate_at_least_helper` | The standard allocator returns exactly the requested count. The managed allocator has no `allocate_at_least` member; both traits and container helpers fall back to exact `allocate(n)`. The helper also excludes the standard allocator's inherited primary member. |
| `vector`: `_Buy_raw`, `_Calculate_growth`, `_Change_array` | Fresh counted/forward-range construction and reserve allocate the requested capacity. Growth chooses the larger of the request and 1.5 times old capacity, with overflow handling. Old and new backing coexist during replacement, within the existing 2x/3x bounds. |
| `xstring`: `_Calculate_growth`, `_Allocate_for_capacity`, `_Deallocate_for_capacity` | Character capacity rounds with `requested \| 15` and grows by 1.5x. Allocation includes the terminator. The 32-byte slack and existing growth/replacement factors still cover it; inline storage stays inside the string object. |
| `list`: `_List_node`, `_Buyheadnode`; `xhash`: constructor, `_Desired_grow_bucket_count`, `_Forced_rehash` | One allocated sentinel and one concrete rebound list node per entry. Eight initial buckets, each holding two pointer-sized unchecked iterators. Growth uses 8x below 512 buckets where sufficient, then power-of-two rounding. Existing empty, retained and simultaneous replacement bounds apply. |
| `yvals_core.h`, `yvals.h` | STL identity is 143/202503; iterator level 0 excludes debug proxies. C++20 and explicit C++23 are checked separately. |

The allocator test now gates C++23 coverage on `__cpp_lib_allocate_at_least`,
so MSVC's legacy `__cplusplus` value cannot silently skip those assertions.
Unsupported identities, crossed compiler/header pairs, iterator-debug mode,
C++17, C++26 and MSVC 19.44's latest mode are tested for rejection.

## Qualification

Validation is performed on a Snapdragon X2 Elite (X2E84100), Windows ARM64,
using MSVC 19.44.35229, Windows SDK 10.0.26100.0, CMake 3.29 and Rust 1.98.1
(`aarch64-pc-windows-msvc`). Both the compiler and generated encoder execute
natively. PE machine type `0xAA64` is checked for the native executables, Rust
test binaries, and the independent decoder tools.

The native and Rust CI matrices include `windows-11-arm` to repeat the checks
on an ARM64 host. The C++20 ARM64 job also runs the pinned decoder conformance
target. These workflow changes have been validated locally; hosted CI has not
been run for this branch.

Local qualification on 2026-10-08:

| Check | Result |
| --- | --- |
| Release C++20 CPU suite | All 119 tests passed across the full suite and targeted reruns after fixes. |
| Release C++23 CPU suite | 119/119 passed, including installed C/C++ consumers and both allocation modes. |
| Independent VarDCT decoder conformance | All 23 fixtures and four workflow policies passed with pinned ARM64 libjxl tools. |
| Additional lossless Modular checks | 7/7 passed: oracle, conformance, policy, transforms, API, CLI and frozen reference. |
| Native Rust | 12 tests passed; format check, Clippy with warnings denied and native incremental rebuild check passed. |
| x64 regression check | Allocation tests in both language modes and the wide-arithmetic image layout oracle passed using MSVC 19.44 x64 binaries under Windows emulation. This does not replace the existing MSVC 19.37 x64 CI. |

The [qualification record](windows-arm64-qualification.json) contains reviewed
header hashes, commands and results. Detailed local logs are retained under
`build/arm64-evidence/`. The initial suite exposed Unix-only environment calls
in tests, an x64-only wide-arithmetic oracle, and a scheduler-dependent overlap
assertion; these now exercise the same contracts on ARM64. No production memory
limit or codec tolerance was loosened.

To reproduce the additional Modular checks after building the pinned decoder:

```powershell
cmake -S . -B build/windows-arm64 `
  -DGJXL_MODULAR_ORACLE_BUILD="$PWD/build/windows-arm64/pinned-libjxl-clang"
cmake --build build/windows-arm64 --parallel 8
ctest --test-dir build/windows-arm64 --output-on-failure `
  -R '^(modular_oracle|modular_conformance|modular_policy|modular_transform|modular_api|modular_cli|modular_frozen_reference)$'
```
