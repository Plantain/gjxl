// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <span>

#include "gpu/image.h"

namespace gjxl {

struct DeviceToHostCopy {
  const DeviceBuffer* source = nullptr;
  void* destination = nullptr;
  size_t size_bytes = 0;
  size_t source_offset_bytes = 0;
  // Active byte width of each row; zero pitches mean packed.
  size_t row_count = 1;
  size_t source_row_stride_bytes = 0;
  size_t destination_row_stride_bytes = 0;
};

// Optional transfer capability. Keeps backend-independent search code free of
// CUDA linkage. Backends without it retain their ordinary synchronous copies.
class GpuHostTransfer {
 public:
  virtual ~GpuHostTransfer() = default;
  virtual Status CopyDeviceToHostBatch(std::span<const DeviceToHostCopy>) = 0;

  // Only exclusively owned resident lanes support constant retention. Slots
  // 0..6 hold search candidates, 7..13 search matrices, 14 AQ matrices and
  // 15..19 Butteraugli filters. Exact contents are compared, never hashes.
  // A borrowed view lasts until replacement of that slot or backend teardown.
  // Unavailable requests must use the ordinary upload path.
  virtual Status ResidentConstant(size_t slot, std::span<const std::byte> contents,
                                  DevicePlaneView* view) = 0;
};

}  // namespace gjxl
