// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Yunho Cho

#pragma once

#include <cstdlib>
#include <stdexcept>

namespace gjxl_test {

// Call between encodes, when no worker is reading the process environment.
// A null value removes the variable on both platforms.
inline void SetEnvironment(const char* name, const char* value) {
#ifdef _WIN32
  const int result = _putenv_s(name, value == nullptr ? "" : value);
#else
  const int result = value == nullptr ? unsetenv(name) : setenv(name, value, 1);
#endif
  if (result != 0) throw std::runtime_error("Could not set test environment");
}

}  // namespace gjxl_test
