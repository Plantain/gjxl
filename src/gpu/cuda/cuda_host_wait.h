// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cuda_runtime_api.h>

#include "core/e4_gpu_options.h"

namespace gjxl::cuda_internal {

inline unsigned int CudaCompletionEventFlags(bool timing = false) {
  return (timing ? cudaEventDefault : cudaEventDisableTiming) |
    (e4_internal::Options().blocking_waits ? cudaEventBlockingSync : 0u);
}

// Each stream owner keeps one reusable event for synchronous copies/cleanup.
// Its existing stream mutex must cover both Record and Synchronize. Submission
// completion events are separate, since they can outlive the submission lock.
inline cudaError_t CreateCudaHostWait(cudaEvent_t* event) {
  if (!e4_internal::Options().blocking_waits) return cudaSuccess;
  return cudaEventCreateWithFlags(event, CudaCompletionEventFlags());
}

inline cudaError_t SynchronizeCudaStream(cudaStream_t stream, cudaEvent_t event) {
  if (event == nullptr) return cudaStreamSynchronize(stream);
  const cudaError_t error = cudaEventRecord(event, stream);
  if (error != cudaSuccess) {
    // Preserve completion-before-release on a failed event record, and return
    // the original error. Never change the caller's primary-context flags.
    (void)cudaStreamSynchronize(stream);
    return error;
  }
  return cudaEventSynchronize(event);
}

}  // namespace gjxl::cuda_internal
