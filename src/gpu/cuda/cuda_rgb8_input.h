// SPDX-License-Identifier: Apache-2.0
#pragma once

#include "gpu/cuda/cuda_aq_exact_kernels.h"
#include "gpu/ops/resident_input.h"

namespace gjxl::cuda_internal {
class CudaBackend;

struct Rgb8Preparation {
  CudaRgb8Input input;
  // Square coding extent: the codestream size, zero-padded beyond the input.
  uint32_t extent = 512;
  // Non-null selects the host adapter; staging belongs to the resident lane.
  const uint8_t* host_pixels = nullptr;
  size_t host_row_stride = 0;
  cudaEvent_t producer = nullptr;
  cudaEvent_t input_done = nullptr;
  // Called immediately after input_done is recorded, before any CPU wait.
  cudaError_t (*consumed)(void*, cudaEvent_t) = nullptr;
  void* consumed_context = nullptr;
  bool compute_matrix_scale_stats = true;
};

Status PrepareCudaRgb8Input(CudaBackend& backend, const Rgb8Preparation& input,
                           std::unique_ptr<PreparedResidentInput>* prepared);
}  // namespace gjxl::cuda_internal
