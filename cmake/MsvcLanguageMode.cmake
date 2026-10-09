# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Yunho Cho

# CMake versions mapping C++23 to /std:c++latest would select post-C++23
# behavior on this compiler. Use the explicit audited language mode.
if(CMAKE_CXX_COMPILER_ID STREQUAL "MSVC" AND MSVC_VERSION EQUAL 1944)
  set(CMAKE_CXX23_STANDARD_COMPILE_OPTION "/std:c++23preview")
  set(CMAKE_CXX23_EXTENSION_COMPILE_OPTION "/std:c++23preview")
endif()
