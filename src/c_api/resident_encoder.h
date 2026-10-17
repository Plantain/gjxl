// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <memory>
#include "gjxl/gjxl.h"
#include "codestream/workflow.h"

namespace gjxl::c_api_internal {
class ResidentEncoder {
 public:
  virtual ~ResidentEncoder() = default;
  virtual Status EncodeDevice(const GJXLDeviceBatch&, VarDctEncodingOptions,
                              GJXLBuffer*) = 0;
  virtual Status EncodeHost(const GJXLImageView*, size_t, VarDctEncodingOptions,
                            GJXLBuffer*) = 0;
};
Status CreateResidentEncoder(const GJXLEncoderCreateOptions& options,
                             std::unique_ptr<ResidentEncoder>* out);
}  // namespace gjxl::c_api_internal
