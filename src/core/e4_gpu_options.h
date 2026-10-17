// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cstdlib>
#include <cstring>

namespace gjxl::e4_internal {

struct GpuOptions {
  bool dc_pipeline;
  bool blocking_waits;
  bool butteraugli_graph;
};

// Read once, before encoder workers start. DC pipelining and blocking waits
// default on; only the exact value "0" disables them. Butteraugli graphs
// default off; only the exact value "1" enables them.
inline const GpuOptions& Options() {
  static const GpuOptions options = [] {
    const auto enabled = [](const char* name) {
      const char* value = std::getenv(name);
      return value != nullptr && std::strcmp(value, "1") == 0;
    };
    const auto default_on = [](const char* name) {
      const char* value = std::getenv(name);
      return value == nullptr || std::strcmp(value, "0") != 0;
    };
    return GpuOptions{default_on("GJXL_E4_DC_PIPELINE"),
                      default_on("GJXL_E4_BLOCKING_WAITS"),
                      enabled("GJXL_E4_BUTTERAUGLI_GRAPH")};
  }();
  return options;
}

}  // namespace gjxl::e4_internal
