// SPDX-License-Identifier: Apache-2.0
#include "c_api/resident_encoder.h"

#if defined(GJXL_ENABLE_CUDA)
#include <cuda.h>
#include <cuda_runtime_api.h>

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <cstring>
#include <limits>
#include <mutex>
#include <thread>
#include <vector>

#include "c_api/image_conversion.h"
#include "codestream/workflow_internal.h"
#include "gpu/cuda/cuda_backend.h"
#include "gpu/cuda/cuda_backend_internal.h"
#include "gpu/cuda/cuda_host_wait.h"
#include "gpu/cuda/cuda_rgb8_input.h"

namespace gjxl::c_api_internal {
namespace {
using namespace cuda_internal;
constexpr size_t kTileBytes = 512 * 512 * 3;
// Include a conservative allowance for the primary context, loaded kernel
// modules and their static tables, in addition to every cudaMalloc arena.
// NVML on SM120 reports about 504 MiB before lane backing. It is shared with
// the caller, but charging it here keeps a standalone encoder under the cap.
constexpr uint64_t kStaticDeviceAllowance = uint64_t{640} * 1024 * 1024;
constexpr size_t kMaximumLaneBytes = 88 * 1024 * 1024;

template <class F> Status CatchStatus(F&& f) {
  try { return f(); }
  catch (const resource_budget_internal::ManagedAllocationFailure& e) { return e.status(); }
  catch (const std::bad_alloc&) { return Status::OutOfMemory("Resident encoder host allocation"); }
  catch (const std::exception& e) { return Status::Internal(e.what()); }
  catch (...) { return Status::Internal("Resident encoder worker exception"); }
}

Status ValidateOutputs(size_t count, GJXLBuffer* outputs) {
  if (count > SIZE_MAX / sizeof(GJXLDeviceTileRGB8) || (count != 0 && outputs == nullptr))
    return Status::InvalidArgument("Invalid resident batch count or outputs");
  for (size_t i = 0; i < count; ++i)
    if (outputs[i].data != nullptr || outputs[i].size != 0)
      return Status::InvalidArgument("Resident outputs must be empty");
  return Status::Ok();
}

Status ValidateExtent(uint32_t extent) {
  if (extent < 64 || extent > 512 || extent % 64 != 0)
    return Status::InvalidArgument("Resident coding extent must be a multiple of 64 up to 512");
  return Status::Ok();
}

Status ValidateTile(const GJXLDeviceTileRGB8& tile, int device, uint32_t extent) {
  if (tile.struct_size < sizeof(tile) || tile.device_pixels == nullptr ||
      tile.width == 0 || tile.width > extent || tile.height == 0 || tile.height > extent ||
      tile.channel_stride <= 0 || tile.pixel_stride <= 0 || tile.row_stride <= 0)
    return Status::InvalidArgument("Invalid device RGB8 tile dimensions or strides");
  // Bound every multiply and sum used by the kernel's signed address math.
  uint64_t last = 0;
  for (auto [stride, steps] : {
         std::pair{tile.channel_stride, uint64_t{2}},
         std::pair{tile.pixel_stride, uint64_t{tile.width - 1}},
         std::pair{tile.row_stride, uint64_t{tile.height - 1}}}) {
    if (steps != 0 && static_cast<uint64_t>(stride) > (INT64_MAX - last) / steps)
      return Status::InvalidArgument("Device RGB8 address range overflows");
    last += static_cast<uint64_t>(stride) * steps;
  }
  if (last > UINTPTR_MAX - reinterpret_cast<uintptr_t>(tile.device_pixels))
    return Status::InvalidArgument("Device RGB8 pointer range overflows");
  cudaPointerAttributes attributes{};
  const cudaError_t error = cudaPointerGetAttributes(&attributes, tile.device_pixels);
  if (error != cudaSuccess) {
    (void)cudaGetLastError();
    return Status::InvalidArgument("RGB8 source is not a CUDA device allocation");
  }
  if (attributes.type != cudaMemoryTypeDevice || attributes.device != device)
    return Status::InvalidArgument("RGB8 source must be on the encoder CUDA device");
  return Status::Ok();
}

class CudaResidentEncoder final : public ResidentEncoder {
  struct Lane {
    int device = 0;
    std::unique_ptr<GpuBackend> backend;
    std::unique_ptr<DeviceBuffer> table, upload;
    cudaEvent_t input_done = nullptr;
    ~Lane() {
      ScopedCudaDevice selected(device);
      if (input_done != nullptr) (void)cudaEventDestroy(input_done);
    }
  };
  struct Batch {
    CudaResidentEncoder* encoder = nullptr;
    Batch* queued_next = nullptr;
    const GJXLDeviceTileRGB8* device_tiles = nullptr;
    const GJXLImageView* host_tiles = nullptr;
    size_t count = 0, next = 0, completed = 0, inputs_remaining = 0;
    uint32_t extent = 512;
    cudaEvent_t producer = nullptr, consumed = nullptr;
    VarDctEncodingOptions options;
    std::vector<GJXLBuffer> results;
    Status status;
    std::condition_variable ready;
    ~Batch() { for (auto& buffer : results) delete[] buffer.data; }
  };

 public:
  ~CudaResidentEncoder() override {
    {
      std::lock_guard lock(mutex_);
      stopping_ = true;
    }
    work_.notify_all();
    for (auto& thread : workers_) if (thread.joinable()) thread.join();
    ScopedCudaDevice selected(device_);
    if (event_stream_ != nullptr) {
      (void)cuda_internal::SynchronizeCudaStream(event_stream_, host_wait_);
      if (host_wait_ != nullptr) (void)cudaEventDestroy(host_wait_);
      (void)cudaStreamDestroy(event_stream_);
    }
  }

  Status Initialize(const GJXLEncoderCreateOptions& options) {
    device_ = options.device;
    ScopedCudaDevice selected(device_);
    if (selected.status() != cudaSuccess)
      return CudaRuntimeStatus(selected.status(), "Select resident encoder device");
    const cudaError_t initialization = cudaFree(nullptr);
    if (initialization != cudaSuccess)
      return CudaRuntimeStatus(initialization, "Initialize CUDA primary context");
    // Runtime allocations, external pointers/events, and worker threads must
    // all refer to the caller's primary context (the CuPy interoperability ABI).
    CUcontext primary = nullptr, current = nullptr;
    CUresult driver = cuDevicePrimaryCtxRetain(&primary, device_);
    if (driver != CUDA_SUCCESS) return Status::Unavailable("CUDA primary context unavailable");
    driver = cuCtxGetCurrent(&current);
    (void)cuDevicePrimaryCtxRelease(device_);
    if (driver != CUDA_SUCCESS || current != primary)
      return Status::InvalidArgument("Resident encoding requires the CUDA primary context");
    if (options.device_memory_bytes <= kStaticDeviceAllowance)
      return Status::ResourcePlanExceeded("Resident device cap is too small");
    arena_bytes_ = static_cast<size_t>(std::min<uint64_t>(kMaximumLaneBytes,
      (options.device_memory_bytes - kStaticDeviceAllowance) / options.contexts)) & ~size_t{255};
    if (arena_bytes_ == 0) return Status::ResourcePlanExceeded("Resident lane cap is too small");
    cudaError_t error = cudaStreamCreateWithFlags(&event_stream_, cudaStreamNonBlocking);
    if (error != cudaSuccess) return CudaRuntimeStatus(error, "Create input-consumption stream");
    error = cuda_internal::CreateCudaHostWait(&host_wait_);
    if (error != cudaSuccess) return CudaRuntimeStatus(error, "Create input-consumption wait");
    lanes_.reserve(options.contexts);
    for (size_t i = 0; i < options.contexts; ++i) {
      auto lane = std::make_unique<Lane>();
      lane->device = device_;
      error = cudaEventCreateWithFlags(
          &lane->input_done, cuda_internal::CudaCompletionEventFlags());
      if (error != cudaSuccess) return CudaRuntimeStatus(error, "Create input-consumption event");
      lanes_.push_back(std::move(lane));
    }
    Status backing = AcquireLanes();
    if (!backing.ok()) return backing;
    // Exercise the low-effort and resident AQ/token paths before publishing the
    // encoder. Scratch is suballocated from each already-fixed arena. This also
    // rejects an insufficient cap at creation instead of on the first batch.
    std::vector<uint8_t> pixels(kTileBytes);
    for (size_t i = 0; i < pixels.size(); ++i)
      pixels[i] = static_cast<uint8_t>((i * 13 + (i / 1536) * 17) & 255);
    GJXLImageView tile{sizeof(GJXLImageView), 512, 512, GJXL_PIXEL_FORMAT_RGB8_SRGB,
                       pixels.data(), pixels.size(), 1536};
    for (auto& lane : lanes_) {
      for (int effort : {1, 7, 8, 10}) {
        Batch warm;
        warm.host_tiles = &tile;
        warm.options.effort = effort;
        warm.options.butteraugli_target = 1.2f;
        GJXLBuffer output{};
        Status status = RunOne(*lane, warm, 0, &output);
        delete[] output.data;
        if (!status.ok()) return status;
      }
    }
    const size_t worker_count = std::min(options.contexts, options.cpu_threads);
    workers_.reserve(worker_count);
    // Lanes are exclusively assigned to persistent workers. If CPU capacity
    // is smaller than context count, each worker rotates over its own lanes.
    for (size_t i = 0; i < worker_count; ++i)
      workers_.emplace_back([this, i, worker_count] { Worker(i, worker_count); });
    return Status::Ok();
  }

  Status ReleaseDeviceMemory(uint64_t* released_bytes) override {
    *released_bytes = 0;
    release_requested_.store(true, std::memory_order_release);
    std::unique_lock lock(mutex_, std::try_to_lock);
    if (!lock.owns_lock() || active_batches_ != 0) {
      work_.notify_one();
      return Status::Ok();
    }
    ScopedCudaDevice selected(device_);
    if (selected.status() != cudaSuccess)
      return CudaRuntimeStatus(selected.status(), "Select resident release device");
    *released_bytes = live_bytes_.load(std::memory_order_acquire);
    ReleaseLanes();
    return Status::Ok();
  }

  uint64_t DeviceMemoryBytes() const override {
    return live_bytes_.load(std::memory_order_acquire);
  }

  Status EncodeDevice(const GJXLDeviceBatch& input, uint32_t extent,
                       VarDctEncodingOptions options, GJXLBuffer* outputs) override {
    Status status = ValidateOutputs(input.count, outputs);
    if (!status.ok()) return status;
    status = ValidateExtent(extent);
    if (!status.ok()) return status;
    if (input.count != 0 && input.tiles == nullptr)
      return Status::InvalidArgument("Device batch tiles must not be null");
    ScopedCudaDevice selected(device_);
    if (selected.status() != cudaSuccess)
      return CudaRuntimeStatus(selected.status(), "Select resident batch device");
    for (size_t i = 0; i < input.count; ++i) {
      status = ValidateTile(input.tiles[i], device_, extent);
      if (!status.ok()) return status;
    }
    Batch batch;
    batch.encoder = this;
    batch.device_tiles = input.tiles;
    batch.extent = extent;
    batch.count = batch.inputs_remaining = input.count;
    batch.producer = reinterpret_cast<cudaEvent_t>(input.producer_event);
    batch.consumed = reinterpret_cast<cudaEvent_t>(input.consumed_event);
    batch.options = std::move(options);
    if (batch.count == 0) {
      std::lock_guard lock(event_mutex_);
      cudaError_t error = cudaSuccess;
      if (batch.producer != nullptr)
        error = cudaStreamWaitEvent(event_stream_, batch.producer, 0);
      if (error == cudaSuccess && batch.consumed != nullptr)
        error = cudaEventRecord(batch.consumed, event_stream_);
      return CudaRuntimeStatus(error, "Record empty batch consumption");
    }
    return Run(batch, outputs);
  }

  Status EncodeHost(const GJXLImageView* tiles, size_t count, uint32_t extent,
                     VarDctEncodingOptions options, GJXLBuffer* outputs) override {
    Status status = ValidateOutputs(count, outputs);
    if (!status.ok()) return status;
    status = ValidateExtent(extent);
    if (!status.ok()) return status;
    if (count != 0 && tiles == nullptr)
      return Status::InvalidArgument("Host batch tiles must not be null");
    for (size_t i = 0; i < count; ++i) {
      const auto& t = tiles[i];
      if (t.struct_size < sizeof(t) || t.width > extent || t.height > extent ||
          t.pixel_format != GJXL_PIXEL_FORMAT_RGB8_SRGB)
        return Status::InvalidArgument("Resident host input requires RGB8 tiles within the extent");
      status = ValidatePackedSrgbImage({static_cast<const uint8_t*>(t.pixels),
        t.pixels_size, t.width, t.height, t.row_stride_bytes, PackedPixelFormat::kRgb8Srgb});
      if (!status.ok()) return status;
    }
    if (count == 0) return Status::Ok();
    Batch batch;
    batch.encoder = this;
    batch.host_tiles = tiles;
    batch.extent = extent;
    batch.count = count;
    batch.options = std::move(options);
    return Run(batch, outputs);
  }

 private:
  // Called with mutex_ held (or before publishing the encoder). Backends own
  // their constant caches and fixed arenas. No caller input/output is retained.
  void ReleaseLanes() {
    for (auto& lane : lanes_) {
      lane->upload.reset();
      lane->table.reset();
      lane->backend.reset();
    }
    live_bytes_.store(0, std::memory_order_release);
    release_requested_.store(false, std::memory_order_release);
  }

  Status AcquireLanes() {
    if (live_bytes_.load(std::memory_order_acquire) != 0) return Status::Ok();
    Status status = CatchStatus([&]() -> Status {
      for (auto& lane : lanes_) {
        CudaBackendOptions options;
        options.device_ordinal = device_;
        options.fixed_arena_bytes = arena_bytes_;
        Status result = CreateCudaBackend(options, &lane->backend);
        if (!result.ok()) return result;
        result = lane->backend->Allocate(256 * sizeof(float), &lane->table);
        if (!result.ok()) return result;
        result = lane->backend->CopyHostToDevice(*lane->table,
            SrgbToLinearTable().data(), 256 * sizeof(float), 0);
        if (!result.ok()) return result;
        result = lane->backend->Allocate(kTileBytes, &lane->upload);
        if (!result.ok()) return result;
      }
      return Status::Ok();
    });
    if (!status.ok()) {
      ReleaseLanes();  // Allocation failure must not leave partial backing.
      return status;
    }
    live_bytes_.store(arena_bytes_ * lanes_.size(), std::memory_order_release);
    return Status::Ok();
  }

  static cudaError_t InputsConsumed(void* opaque, cudaEvent_t event) {
    auto& batch = *static_cast<Batch*>(opaque);
    auto& encoder = *batch.encoder;
    std::lock_guard lock(encoder.event_mutex_);
    cudaError_t error = cudaStreamWaitEvent(encoder.event_stream_, event, 0);
    if (error == cudaSuccess && --batch.inputs_remaining == 0)
      error = cudaEventRecord(batch.consumed, encoder.event_stream_);
    return error;
  }

  Status RunOne(Lane& lane, Batch& batch, size_t index, GJXLBuffer* output) {
    return CatchStatus([&]() -> Status {
      Rgb8Preparation preparation;
      preparation.extent = batch.extent;
      preparation.input.srgb_to_linear = static_cast<const float*>(
        static_cast<CudaBuffer*>(lane.table.get())->pointer());
      if (batch.host_tiles != nullptr) {
        const auto& t = batch.host_tiles[index];
        preparation.input.pixels = static_cast<const uint8_t*>(
          static_cast<CudaBuffer*>(lane.upload.get())->pointer());
        preparation.input.channel_stride = 1;
        preparation.input.pixel_stride = 3;
        preparation.input.row_stride = 1536;
        preparation.input.width = t.width;
        preparation.input.height = t.height;
        preparation.host_pixels = static_cast<const uint8_t*>(t.pixels);
        preparation.host_row_stride = t.row_stride_bytes;
      } else {
        const auto& t = batch.device_tiles[index];
        preparation.input.pixels = t.device_pixels;
        preparation.input.channel_stride = t.channel_stride;
        preparation.input.pixel_stride = t.pixel_stride;
        preparation.input.row_stride = t.row_stride;
        preparation.input.width = t.width;
        preparation.input.height = t.height;
        preparation.producer = batch.producer;
        if (batch.consumed != nullptr) {
          preparation.input_done = lane.input_done;
          preparation.consumed = &InputsConsumed;
          preparation.consumed_context = &batch;
        }
      }
      auto options = batch.options;
      options.backend = VarDctBackendPreference::kCuda;
      options.cpu_thread_count = 1;
      options.source_is_srgb8 = true;
      preparation.compute_matrix_scale_stats =
        codestream_internal::ShouldComputeQuantizationMatrixScaleStats(options);
      codestream_internal::ResidentEncodingInput input;
      input.backend = lane.backend.get();
      // Only geometry is passed to host-side resident-policy validation. No
      // host RGB storage exists and no CPU operation may dereference this view.
      for (auto& plane : input.linear_rgb.plane)
        plane = {nullptr, {batch.extent, batch.extent}, batch.extent};
      Status status = PrepareCudaRgb8Input(static_cast<CudaBackend&>(*lane.backend),
                                            preparation, &input.owner);
      if (!status.ok()) return status;
      codestream_internal::CodestreamBuffer codestream;
      status = codestream_internal::EncodeResidentLinearRgbVarDctCodestreamOwned(
        std::move(input), options, &codestream);
      if (!status.ok()) return status;
      if (codestream.empty()) return Status::Internal("Resident encoder returned no bytes");
      auto bytes = std::make_unique<uint8_t[]>(codestream.size());
      std::memcpy(bytes.get(), codestream.data(), codestream.size());
      *output = {bytes.release(), codestream.size()};
      return Status::Ok();
    });
  }

  Status Run(Batch& batch, GJXLBuffer* outputs) {
    batch.results.resize(batch.count);
    std::unique_lock lock(mutex_);
    Status status = AcquireLanes();
    if (!status.ok()) return status;
    ++active_batches_;
    Enqueue(&batch);
    work_.notify_all();
    batch.ready.wait(lock, [&] { return batch.completed == batch.count; });
    if (--active_batches_ == 0 && release_requested_.load(std::memory_order_acquire))
      ReleaseLanes();
    if (!batch.status.ok()) return batch.status;
    for (size_t i = 0; i < batch.count; ++i) {
      outputs[i] = batch.results[i];
      batch.results[i] = {};
    }
    return Status::Ok();
  }

  void Enqueue(Batch* batch) noexcept {
    batch->queued_next = nullptr;
    if (queue_tail_ != nullptr) queue_tail_->queued_next = batch;
    else queue_head_ = batch;
    queue_tail_ = batch;
  }

  void Worker(size_t worker, size_t worker_count) {
    ScopedCudaDevice selected(device_);
    size_t lane = worker;
    for (;;) {
      Batch* batch;
      size_t index;
      bool skip;
      {
        std::unique_lock lock(mutex_);
        work_.wait(lock, [&] {
          return stopping_ || queue_head_ != nullptr ||
            (active_batches_ == 0 && release_requested_.load(std::memory_order_acquire));
        });
        if (stopping_) return;
        if (active_batches_ == 0 && release_requested_.load(std::memory_order_acquire)) {
          ReleaseLanes();
          continue;
        }
        batch = queue_head_;
        queue_head_ = batch->queued_next;
        if (queue_head_ == nullptr) queue_tail_ = nullptr;
        index = batch->next++;
        if (batch->next < batch->count) Enqueue(batch);
        skip = !batch->status.ok();
      }
      Status status;
      if (!skip) status = RunOne(*lanes_[lane], *batch, index, &batch->results[index]);
      lane += worker_count;
      if (lane >= lanes_.size()) lane = worker;
      {
        std::lock_guard lock(mutex_);
        if (!status.ok() && batch->status.ok()) batch->status = std::move(status);
        if (++batch->completed == batch->count) batch->ready.notify_one();
      }
    }
  }

  int device_ = 0;
  size_t arena_bytes_ = 0;
  size_t active_batches_ = 0;  // Protected by mutex_. Includes queued batches.
  std::atomic<uint64_t> live_bytes_{0};
  std::atomic<bool> release_requested_{false};
  cudaStream_t event_stream_ = nullptr;
  cudaEvent_t host_wait_ = nullptr;
  std::mutex event_mutex_;
  std::vector<std::unique_ptr<Lane>> lanes_;
  std::vector<std::thread> workers_;
  std::mutex mutex_;
  std::condition_variable work_;
  Batch* queue_head_ = nullptr;
  Batch* queue_tail_ = nullptr;
  bool stopping_ = false;
};
}  // namespace

Status CreateResidentEncoder(const GJXLEncoderCreateOptions& options,
                             std::unique_ptr<ResidentEncoder>* out) {
  auto candidate = std::make_unique<CudaResidentEncoder>();
  Status status = candidate->Initialize(options);
  if (!status.ok()) return status;
  *out = std::move(candidate);
  return Status::Ok();
}
}  // namespace gjxl::c_api_internal
#else
namespace gjxl::c_api_internal {
Status CreateResidentEncoder(const GJXLEncoderCreateOptions&,
                             std::unique_ptr<ResidentEncoder>*) {
  return Status::Unavailable("Resident RGB8 encoding requires a CUDA build");
}
}  // namespace gjxl::c_api_internal
#endif
