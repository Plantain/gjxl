// SPDX-License-Identifier: Apache-2.0
#pragma once

#include <cuda_runtime_api.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <tuple>

namespace gjxl::cuda_internal {

class CudaReusableGraph;
inline thread_local CudaReusableGraph* cuda_reusable_graph = nullptr;

// One bounded, linear kernel graph per lane. Build its topology once; update
// every argument and launch dimension before replay. CUDA copies parameter
// values during Add/SetParams, so host argument temporaries need not survive.
class CudaReusableGraph {
 public:
  CudaReusableGraph() = default;
  CudaReusableGraph(const CudaReusableGraph&) = delete;
  CudaReusableGraph& operator=(const CudaReusableGraph&) = delete;
  ~CudaReusableGraph() { Reset(); }

  void Reset() {
    if (graph_ == nullptr) return;
    int previous = -1;
    (void)cudaGetDevice(&previous);
    if (previous != device_) (void)cudaSetDevice(device_);
    if (exec_ != nullptr) (void)cudaGraphExecDestroy(exec_);
    (void)cudaGraphDestroy(graph_);
    if (previous >= 0 && previous != device_) (void)cudaSetDevice(previous);
    graph_ = nullptr;
    exec_ = nullptr;
    count_ = 0;
  }

  cudaError_t Begin() {
    cursor_ = 0;
    error_ = cudaSuccess;
    if (graph_ == nullptr) {
      error_ = cudaGetDevice(&device_);
      if (error_ == cudaSuccess) error_ = cudaGraphCreate(&graph_, 0);
    }
    return error_;
  }

  template <class... Params, class... Args>
  void Kernel(void (*kernel)(Params...), dim3 grid, dim3 block,
              size_t shared, Args... args) {
    if (error_ != cudaSuccess) return;
    if (cursor_ >= nodes_.size() || (exec_ != nullptr && cursor_ >= count_)) {
      error_ = cudaErrorInvalidValue;
      return;
    }
    // Conversions match the kernel signature, including structs passed by value.
    std::tuple<Params...> values(args...);
    std::apply([&](auto&... value) {
      void* pointers[] = {static_cast<void*>(&value)...};
      cudaKernelNodeParams parameters{};
      parameters.func = reinterpret_cast<void*>(kernel);
      parameters.gridDim = grid;
      parameters.blockDim = block;
      parameters.sharedMemBytes = static_cast<unsigned int>(shared);
      parameters.kernelParams = pointers;
      constexpr size_t bytes = (sizeof(Params) + ...);
      static_assert(bytes <= kArgumentBytes);
      std::array<uint8_t, bytes> packed;
      size_t offset = 0;
      const auto append = [&](const auto& argument) {
        std::memcpy(packed.data() + offset, &argument, sizeof(argument));
        offset += sizeof(argument);
      };
      (append(value), ...);
      auto& node = nodes_[cursor_];
      if (exec_ == nullptr) {
        error_ = cudaGraphAddKernelNode(&node.handle, graph_,
            cursor_ == 0 ? nullptr : &nodes_[cursor_ - 1].handle,
            cursor_ == 0 ? 0 : 1, &parameters);
      } else {
        const auto same_dim = [](dim3 a, dim3 b) {
          return a.x == b.x && a.y == b.y && a.z == b.z;
        };
        if (node.function == parameters.func && same_dim(node.grid, grid) &&
            same_dim(node.block, block) && node.shared == shared &&
            node.bytes == bytes && std::memcmp(node.arguments.data(), packed.data(), bytes) == 0)
          return;
        error_ = cudaGraphExecKernelNodeSetParams(exec_, node.handle, &parameters);
      }
      if (error_ == cudaSuccess) {
        node.function = parameters.func;
        node.grid = grid;
        node.block = block;
        node.shared = shared;
        node.bytes = bytes;
        std::memcpy(node.arguments.data(), packed.data(), bytes);
      }
    }, values);
    ++cursor_;
  }

  cudaError_t status() const { return error_; }
  cudaError_t Launch(cudaStream_t stream) {
    if (error_ == cudaSuccess && exec_ != nullptr && cursor_ != count_)
      error_ = cudaErrorInvalidValue;
    if (error_ == cudaSuccess && exec_ == nullptr) {
      count_ = cursor_;
      error_ = cudaGraphInstantiate(&exec_, graph_, 0);
    }
    if (error_ == cudaSuccess) error_ = cudaGraphLaunch(exec_, stream);
    return error_;
  }

 private:
  cudaGraph_t graph_ = nullptr;
  cudaGraphExec_t exec_ = nullptr;
  static constexpr size_t kArgumentBytes = 1024;
  struct Node {
    cudaGraphNode_t handle = nullptr;
    void* function = nullptr;
    dim3 grid{}, block{};
    size_t shared = 0, bytes = 0;
    std::array<uint8_t, kArgumentBytes> arguments;
  };
  std::array<Node, 128> nodes_{};
  size_t cursor_ = 0, count_ = 0;
  int device_ = 0;
  cudaError_t error_ = cudaSuccess;
};

// Only the fixed Butteraugli prefix installs this scope. Variable anchor
// composition/reduction remains ordinary launches after Launch(). A failed
// prefix never replays a partially updated graph; its caller drains prior work.
class CudaGraphScope {
 public:
  explicit CudaGraphScope(CudaReusableGraph* graph) : graph_(graph) {
    if (graph_ != nullptr) {
      (void)graph_->Begin();
      cuda_reusable_graph = graph_;
    }
  }
  ~CudaGraphScope() {
    if (graph_ != nullptr) {
      cuda_reusable_graph = nullptr;
      graph_->Reset();
    }
  }
  cudaError_t Launch(cudaStream_t stream) {
    if (graph_ == nullptr) return cudaSuccess;
    cuda_reusable_graph = nullptr;
    const auto error = graph_->Launch(stream);
    if (error == cudaSuccess) graph_ = nullptr;
    return error;
  }
 private:
  CudaReusableGraph* graph_;
};

inline cudaError_t CudaGraphLaunchStatus() {
  return cuda_reusable_graph != nullptr ? cuda_reusable_graph->status() : cudaGetLastError();
}

}  // namespace gjxl::cuda_internal

// The ordinary path retains the exact CUDA launch expression. Parenthesizing
// the kernel name allows template arguments containing commas.
#define GJXL_E4_KERNEL_NAME(...) __VA_ARGS__
#define GJXL_E4_BA_LAUNCH(kernel, grid, block, shared, stream, ...) do { \
  if (::gjxl::cuda_internal::cuda_reusable_graph != nullptr) { \
    ::gjxl::cuda_internal::cuda_reusable_graph->Kernel( \
        GJXL_E4_KERNEL_NAME kernel, grid, block, shared, __VA_ARGS__); \
  } else { \
    GJXL_E4_KERNEL_NAME kernel<<<grid, block, shared, stream>>>(__VA_ARGS__); \
  } \
} while (false)
