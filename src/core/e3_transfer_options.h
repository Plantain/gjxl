// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdlib>
#include <cstring>

namespace gjxl::e3_internal {

struct TransferOptions {
  bool resident_tables;
  bool compact_histograms;
  bool narrow_coefficients;
  bool batched_readbacks;
  bool sync_removal;
  bool cpu_tokens;
  bool narrow_tokens;
};

// Read once per process, before workers start encoding. Unset uses the selected
// default; "1" enables a feature, and any other explicit value disables it.
// Keep allocation plans and execution on the same immutable configuration.
inline const TransferOptions& Options() {
  static const TransferOptions options = [] {
    const auto enabled = [](const char* name, bool default_value = false) {
      const char* value = std::getenv(name);
      return value == nullptr ? default_value : std::strcmp(value, "1") == 0;
    };
    return TransferOptions{
        enabled("GJXL_E3_RESIDENT_TABLES"),
        enabled("GJXL_E3_COMPACT_HISTOGRAMS", true),
        enabled("GJXL_E3_NARROW_COEFFICIENTS", true),
        enabled("GJXL_E3_BATCHED_READBACKS"),
        enabled("GJXL_E3_SYNC_REMOVAL"),
        enabled("GJXL_E3_CPU_TOKENS"),
        enabled("GJXL_E3_NARROW_TOKENS")};
  }();
  return options;
}

}  // namespace gjxl::e3_internal
