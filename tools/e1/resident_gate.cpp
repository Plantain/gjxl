// SPDX-License-Identifier: Apache-2.0
// Reproducible E1 gate. JSONL stdout; use the timing-lock wrapper on sat-5090.
#include <gjxl/gjxl.h>
#include <cuda.h>
#include <cuda_runtime_api.h>
#include <cuda_profiler_api.h>
#include <nvml.h>
#include <dlfcn.h>
#include <unistd.h>
#include <sys/resource.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <future>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;
constexpr size_t kBytes = 512 * 512 * 3;
void Check(GJXLResult s) {
  if (s != GJXL_OK) throw std::runtime_error(std::to_string(s) + ": " + gjxl_get_last_error());
}
void Cuda(cudaError_t s) {
  if (s != cudaSuccess) throw std::runtime_error(cudaGetErrorString(s));
}
void Require(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
double Seconds(Clock::time_point t) { return std::chrono::duration<double>(Clock::now() - t).count(); }
double Cpu() {
  rusage u{}; getrusage(RUSAGE_SELF, &u);
  return u.ru_utime.tv_sec + u.ru_stime.tv_sec + (u.ru_utime.tv_usec + u.ru_stime.tv_usec) * 1e-6;
}
size_t Rss() {
  std::ifstream file("/proc/self/statm"); size_t pages = 0, resident = 0;
  file >> pages >> resident; return resident * static_cast<size_t>(sysconf(_SC_PAGESIZE));
}
size_t Vram() {
  static void* lib = dlopen("libnvidia-ml.so.1", RTLD_NOW);
  Require(lib != nullptr, "NVML unavailable");
  auto init = reinterpret_cast<decltype(&nvmlInit_v2)>(dlsym(lib, "nvmlInit_v2"));
  auto get = reinterpret_cast<decltype(&nvmlDeviceGetHandleByIndex_v2)>(dlsym(lib, "nvmlDeviceGetHandleByIndex_v2"));
  auto query = reinterpret_cast<decltype(&nvmlDeviceGetComputeRunningProcesses_v3)>(dlsym(lib, "nvmlDeviceGetComputeRunningProcesses_v3"));
  static bool initialized = init() == NVML_SUCCESS;
  Require(initialized, "NVML initialization failed");
  nvmlDevice_t device{}; Require(get(0, &device) == NVML_SUCCESS, "NVML device failed");
  std::array<nvmlProcessInfo_t, 128> processes{}; unsigned count = processes.size();
  Require(query(device, &count, processes.data()) == NVML_SUCCESS, "NVML processes failed");
  for (unsigned i = 0; i < count; ++i)
    if (processes[i].pid == static_cast<unsigned>(getpid())) return processes[i].usedGpuMemory;
  throw std::runtime_error("NVML cannot find PID: run with --pid=host");
}
struct Outputs {
  explicit Outputs(size_t n) : values(n) {}
  ~Outputs() { for (auto& v : values) gjxl_buffer_free(&v); }
  std::vector<GJXLBuffer> values;
  uint64_t Bytes() const { uint64_t n = 0; for (auto& v : values) n += v.size; return n; }
};
struct Tile {
  unsigned width = 512, height = 512;
  std::vector<uint8_t> pixels = std::vector<uint8_t>(kBytes);
  std::string name;
  GJXLImageView View() const {
    return {sizeof(GJXLImageView), width, height, GJXL_PIXEL_FORMAT_RGB8_SRGB,
            pixels.data(), pixels.size(), width * 3};
  }
};
struct DeviceTiles {
  std::vector<void*> allocations;
  std::vector<GJXLDeviceTileRGB8> views;
  size_t bytes = 0;
  DeviceTiles(const std::vector<Tile>& tiles, int layout) {
    for (const auto& t : tiles) {
      const bool chw = layout >= 2;
      const size_t pixel = chw ? 1 : (layout == 1 ? 4 : 3);
      const size_t row = t.width * pixel + (layout == 2 ? 0 : 17);
      const size_t channel = chw ? row * t.height : 1;
      std::vector<uint8_t> packed(chw ? 3 * channel : row * t.height, 0xDA);
      for (size_t y = 0; y < t.height; ++y)
        for (size_t x = 0; x < t.width; ++x)
          for (size_t c = 0; c < 3; ++c)
            packed[y * row + x * pixel + c * channel] = t.pixels[(y * t.width + x) * 3 + c];
      void* p = nullptr; Cuda(cudaMalloc(&p, packed.size())); allocations.push_back(p);
      Cuda(cudaMemcpy(p, packed.data(), packed.size(), cudaMemcpyHostToDevice));
      bytes += packed.size();
      views.push_back({sizeof(GJXLDeviceTileRGB8), static_cast<const uint8_t*>(p),
        static_cast<int64_t>(channel), static_cast<int64_t>(pixel), static_cast<int64_t>(row),
        t.width, t.height});
    }
  }
  ~DeviceTiles() { for (auto p : allocations) (void)cudaFree(p); }
  GJXLDeviceBatch Batch(size_t begin = 0, size_t count = SIZE_MAX) const {
    return {sizeof(GJXLDeviceBatch), views.data() + begin,
            count == SIZE_MAX ? views.size() - begin : count, 0, 0};
  }
};
struct Encoder {
  GJXLEncoder* value = nullptr;
  explicit Encoder(unsigned contexts) {
    const GJXLEncoderCreateOptions o{sizeof(o), 0, contexts, uint64_t{2048} << 20, contexts};
    auto begin = Clock::now(); Check(gjxl_encoder_create(&o, &value));
    Require(Vram() <= o.device_memory_bytes, "Encoder exceeded device cap");
    std::cout << "{\"create_seconds\":" << Seconds(begin) << ",\"contexts\":" << contexts
              << ",\"vram_bytes\":" << Vram() << ",\"rss_bytes\":" << Rss() << "}" << std::endl;
  }
  ~Encoder() { if (value) gjxl_encoder_destroy(value); }
  void Destroy() {
    auto begin = Clock::now(); gjxl_encoder_destroy(value); value = nullptr;
    std::cout << "{\"destroy_seconds\":" << Seconds(begin) << ",\"vram_bytes\":" << Vram()
              << ",\"rss_bytes\":" << Rss() << "}" << std::endl;
  }
};
GJXLEncoderOptions Options(int preset) {
  GJXLEncoderOptions o; Check(gjxl_encoder_options_init(&o, sizeof(o)));
  o.distance = 1.2f; o.effort = preset == 7 ? 7 : 8;
  if (preset == 0) o.entropy_behavior = GJXL_ENTROPY_BALANCED;
  return o;
}
std::vector<GJXLImageView> HostViews(const std::vector<Tile>& tiles) {
  std::vector<GJXLImageView> result; for (auto& t : tiles) result.push_back(t.View()); return result;
}
void Compare(const Outputs& a, const Outputs& b) {
  Require(a.values.size() == b.values.size(), "Output count mismatch");
  for (size_t i = 0; i < a.values.size(); ++i)
    if (a.values[i].size != b.values[i].size ||
        std::memcmp(a.values[i].data, b.values[i].data, a.values[i].size) != 0)
      throw std::runtime_error("Byte mismatch at tile " + std::to_string(i));
}
void Legacy(const std::vector<Tile>& tiles, unsigned threads,
            const GJXLEncoderOptions& options, Outputs& output) {
  std::atomic<size_t> next{0};
  std::vector<std::future<void>> jobs;
  for (unsigned i = 0; i < threads; ++i) jobs.push_back(std::async(std::launch::async, [&] {
    GJXLContextOptions co; Check(gjxl_context_options_init(&co, sizeof(co)));
    co.backend = GJXL_BACKEND_CUDA; co.num_cpu_threads = 1;
    GJXLContext* context = nullptr; Check(gjxl_context_create(&co, &context));
    std::unique_ptr<GJXLContext, decltype(&gjxl_context_destroy)> owner(context, gjxl_context_destroy);
    for (;;) {
      size_t i = next++; if (i == tiles.size() || i > tiles.size()) break;
      std::vector<uint8_t> padded(kBytes, 0);
      for (size_t y = 0; y < tiles[i].height; ++y)
        std::memcpy(padded.data() + y * 1536,
          tiles[i].pixels.data() + y * tiles[i].width * 3, tiles[i].width * 3);
      GJXLImageView view{sizeof(view), 512, 512, GJXL_PIXEL_FORMAT_RGB8_SRGB,
                         padded.data(), padded.size(), 1536};
      Check(gjxl_encode(context, &view, &options, &output.values[i]));
    }
  }));
  for (auto& job : jobs) job.get();
}
void Identity(Encoder& encoder, unsigned contexts, const std::vector<Tile>& tiles,
              const std::string& outdir, bool edges) {
  auto host = HostViews(tiles);
  for (int preset : {0, 7, 8}) {
    auto options = Options(preset);
    Outputs reference(tiles.size()), from_host(tiles.size());
    Legacy(tiles, contexts, options, reference);
    Check(gjxl_encoder_encode_host(encoder.value, host.data(), host.size(), &options, from_host.values.data()));
    Compare(reference, from_host);
    for (int layout : (edges ? std::vector<int>{0, 1, 2, 3} : std::vector<int>{0, 2})) {
      DeviceTiles device(tiles, layout); auto batch = device.Batch(); Outputs result(tiles.size());
      Check(gjxl_encoder_encode_device(encoder.value, &batch, &options, result.values.data()));
      Compare(reference, result);
    }
    if (!outdir.empty()) {
      std::filesystem::create_directories(outdir + "/" + std::to_string(preset));
      for (size_t i = 0; i < tiles.size(); ++i) {
        std::ofstream f(outdir + "/" + std::to_string(preset) + "/" + tiles[i].name + ".jxl", std::ios::binary);
        f.write(reinterpret_cast<const char*>(reference.values[i].data), reference.values[i].size);
        Require(bool(f), "Write codestream failed");
      }
    }
    std::cout << "{\"identity\":true,\"preset\":" << preset << ",\"tiles\":" << tiles.size()
              << ",\"device_layouts\":" << (edges ? 4 : 2) << ",\"bytes\":" << reference.Bytes() << "}" << std::endl;
  }
}
void Concurrency(Encoder& encoder, const std::vector<Tile>& tiles) {
  DeviceTiles device(tiles, 2); auto options = Options(8);
  Outputs reference(tiles.size()); auto batch = device.Batch();
  Check(gjxl_encoder_encode_device(encoder.value, &batch, &options, reference.values.data()));
  std::vector<std::future<void>> callers;
  for (int c = 0; c < 6; ++c) callers.push_back(std::async(std::launch::async, [&] {
    for (int r = 0; r < 3; ++r) {
      Outputs result(tiles.size()); auto b = device.Batch();
      Check(gjxl_encoder_encode_device(encoder.value, &b, &options, result.values.data()));
      Compare(reference, result);
    }
  }));
  for (auto& caller : callers) caller.get();
  std::cout << "{\"concurrent_callers\":6,\"batches_per_caller\":3,\"identity\":true}" << std::endl;
}
void Events(Encoder& encoder) {
  // Mimics a CuPy renderer: primary-context allocation, a non-default producer
  // stream and external events passed through uintptr_t from another thread.
  constexpr size_t count = 24;
  constexpr size_t bytes = count * kBytes;
  std::vector<Tile> tiles(count);
  for (size_t t = 0; t < count; ++t)
    for (size_t i = 0; i < kBytes; ++i)
      tiles[t].pixels[i] = static_cast<uint8_t>(i * 7 + i / 1536 + t * 17);
  auto views = HostViews(tiles); auto options = Options(8); Outputs reference(count), actual(count);
  Check(gjxl_encoder_encode_host(encoder.value, views.data(), count, &options, reference.values.data()));
  void* pixels = nullptr; Cuda(cudaMalloc(&pixels, bytes)); Cuda(cudaMemset(pixels, 0, bytes));
  uint8_t* pinned = nullptr; Cuda(cudaMallocHost(reinterpret_cast<void**>(&pinned), bytes));
  for (size_t t = 0; t < count; ++t) std::memcpy(pinned + t * kBytes, tiles[t].pixels.data(), kBytes);
  cudaStream_t producer, pending; cudaEvent_t ready, consumed;
  Cuda(cudaStreamCreateWithFlags(&producer, cudaStreamNonBlocking));
  Cuda(cudaStreamCreateWithFlags(&pending, cudaStreamNonBlocking));
  Cuda(cudaEventCreateWithFlags(&ready, cudaEventDisableTiming));
  Cuda(cudaEventCreateWithFlags(&consumed, cudaEventDisableTiming));
  // Pre-arm consumption with an unfinished GPU semaphore. Querying an event
  // before its first record would otherwise return success by CUDA definition.
  CUdeviceptr flag = 0; Require(cuMemAlloc(&flag, 4) == CUDA_SUCCESS, "Allocate semaphore");
  Require(cuMemsetD32(flag, 0, 1) == CUDA_SUCCESS, "Clear semaphore");
  Require(cuStreamWaitValue32(reinterpret_cast<CUstream>(pending), flag, 1, CU_STREAM_WAIT_VALUE_EQ) == CUDA_SUCCESS, "Arm semaphore");
  Cuda(cudaEventRecord(consumed, pending));
  std::atomic<bool> release{false};
  Cuda(cudaLaunchHostFunc(producer, [](void* p) {
    while (!static_cast<std::atomic<bool>*>(p)->load()) std::this_thread::yield();
  }, &release));
  Cuda(cudaMemcpyAsync(pixels, pinned, bytes, cudaMemcpyHostToDevice, producer));
  Cuda(cudaEventRecord(ready, producer));
  std::vector<GJXLDeviceTileRGB8> descriptors;
  for (size_t t = 0; t < count; ++t)
    descriptors.push_back({sizeof(GJXLDeviceTileRGB8), static_cast<uint8_t*>(pixels) + t * kBytes,
                            1, 3, 1536, 512, 512});
  GJXLDeviceBatch batch{sizeof(batch), descriptors.data(), count,
                        reinterpret_cast<uintptr_t>(ready), reinterpret_cast<uintptr_t>(consumed)};
  auto encode = std::async(std::launch::async, [&] {
    Check(gjxl_encoder_encode_device(encoder.value, &batch, &options, actual.values.data()));
  });
  const bool waited = encode.wait_for(std::chrono::milliseconds(30)) == std::future_status::timeout;
  release = true;
  bool early = false;
  auto deadline = Clock::now();
  while (Seconds(deadline) < 10) {
    auto state = cudaEventQuery(consumed);
    if (state == cudaSuccess) {
      early = encode.wait_for(std::chrono::milliseconds(0)) == std::future_status::timeout;
      // Overwrite immediately: output must still match the original RGB.
      Cuda(cudaMemsetAsync(pixels, 0xAD, bytes, producer)); break;
    }
    Cuda(state == cudaErrorNotReady ? cudaSuccess : state);
    std::this_thread::yield();
  }
  Require(cuStreamWriteValue32(reinterpret_cast<CUstream>(producer), flag, 1, 0) == CUDA_SUCCESS, "Release semaphore");
  encode.get(); Cuda(cudaStreamSynchronize(producer)); Cuda(cudaStreamSynchronize(pending));
  Compare(reference, actual); Require(waited, "Encoder did not wait for producer");
  Require(early, "Consumed event was not visible before encoding completed");
  Cuda(cudaEventDestroy(ready)); Cuda(cudaEventDestroy(consumed));
  Cuda(cudaStreamDestroy(producer)); Cuda(cudaStreamDestroy(pending));
  Cuda(cudaFreeHost(pinned)); Cuda(cudaFree(pixels)); Require(cuMemFree(flag) == CUDA_SUCCESS, "Free semaphore");
  std::cout << "{\"primary_context_events\":true,\"producer_wait\":true,\"early_recycle\":true,\"tiles\":24}" << std::endl;
}
void Invalid(Encoder& encoder) {
  GJXLEncoder* output = nullptr;
  GJXLEncoderCreateOptions tiny{sizeof(tiny), 0, 1, 1024, 1};
  Require(gjxl_encoder_create(&tiny, &output) == GJXL_ERROR_RESOURCE_PLAN_EXCEEDED && !output, "Tiny cap accepted");
  auto options = Options(0); GJXLBuffer buffer{};
  GJXLDeviceTileRGB8 tile{sizeof(tile), nullptr, 1, 3, 1536, 512, 512};
  GJXLDeviceBatch batch{sizeof(batch), &tile, 1, 0, 0};
  Require(gjxl_encoder_encode_device(encoder.value, &batch, &options, &buffer) == GJXL_ERROR_INVALID_ARGUMENT, "Null device pointer accepted");
  batch.count = 0; Check(gjxl_encoder_encode_device(encoder.value, &batch, &options, nullptr));
  std::cout << "{\"invalid_arguments\":true,\"tiny_cap_rejected\":true}" << std::endl;
}
void Measure(Encoder& encoder, const std::vector<Tile>& tiles, size_t reps,
             bool leak, bool trace) {
  const size_t before_input = Vram();
  DeviceTiles device(tiles, 2);
  const size_t input_backing = Vram() - before_input;
  auto batch = device.Batch(); auto host = HostViews(tiles); auto options = Options(0);
  for (int i = 0; i < 2; ++i) {
    Outputs warm(tiles.size()); Check(gjxl_encoder_encode_device(encoder.value, &batch, &options, warm.values.data()));
  }
  if (trace) Cuda(cudaProfilerStart());
  size_t done = 0;
  for (size_t r = 0; r < reps; ++r) {
    for (int path : (leak || trace ? std::vector<int>{1} : std::vector<int>{0, 1, 1, 0})) {
      Outputs out(tiles.size()); const double cpu = Cpu(); auto begin = Clock::now();
      if (path) Check(gjxl_encoder_encode_device(encoder.value, &batch, &options, out.values.data()));
      else Check(gjxl_encoder_encode_host(encoder.value, host.data(), host.size(), &options, out.values.data()));
      const double seconds = Seconds(begin); done += tiles.size();
      const size_t encoder_vram = Vram() - input_backing;
      Require(encoder_vram <= (uint64_t{2048} << 20), "Steady encoder exceeded cap");
      if (!trace) std::cout << "{\"path\":\"" << (path ? "device" : "host") << "\",\"repetition\":" << r
        << ",\"tiles\":" << tiles.size() << ",\"encodes\":" << done << ",\"seconds\":" << seconds
        << ",\"tiles_per_second\":" << tiles.size() / seconds << ",\"cpu_seconds\":" << Cpu() - cpu
        << ",\"bytes\":" << out.Bytes() << ",\"rss_bytes\":" << Rss() << ",\"vram_bytes\":" << Vram()
        << ",\"caller_device_bytes\":" << device.bytes << ",\"caller_device_backing_bytes\":" << input_backing
        << ",\"encoder_vram_bytes\":" << encoder_vram << "}" << std::endl;
    }
  }
  if (trace) { Cuda(cudaProfilerStop()); std::cout << "{\"profile_tiles\":" << done << "}" << std::endl; }
}
}  // namespace

int main(int argc, char** argv) {
  try {
    Require(argc >= 4, "Usage: gjxl_resident_gate test|identity|bench|leak|trace CONTEXTS REPS [OUTDIR for identity] [tile.rgb or directory ...]");
    const std::string mode = argv[1]; const unsigned contexts = std::stoul(argv[2]); const size_t reps = std::stoul(argv[3]);
    Require(contexts >= 1 && contexts <= 16 && reps >= 1, "Invalid contexts/reps");
    Cuda(cudaSetDevice(0));
    std::vector<Tile> tiles;
    int first = mode == "identity" ? 5 : 4;
    for (int i = first; i < argc; ++i) {
      std::vector<std::filesystem::path> files;
      if (std::filesystem::is_directory(argv[i])) {
        for (auto& f : std::filesystem::directory_iterator(argv[i])) if (f.path().extension() == ".rgb") files.push_back(f.path());
      } else files.emplace_back(argv[i]);
      std::sort(files.begin(), files.end());
      for (const auto& path : files) {
        Require(std::filesystem::file_size(path) == kBytes, "Invalid RGB tile size");
        Tile t; t.name = path.stem(); std::ifstream f(path, std::ios::binary);
        Require(bool(f.read(reinterpret_cast<char*>(t.pixels.data()), kBytes)), "Read tile failed"); tiles.push_back(std::move(t));
      }
    }
    if (mode == "test") {
      for (auto [w, h] : {std::pair{1u, 1u}, {1u, 512u}, {512u, 1u}, {511u, 509u}, {31u, 27u}, {257u, 199u}, {512u, 512u}}) {
        Tile t; t.width = w; t.height = h; t.pixels.resize(w * h * 3);
        t.name = "edge-" + std::to_string(w) + "x" + std::to_string(h);
        for (size_t p = 0; p < t.pixels.size(); ++p) t.pixels[p] = static_cast<uint8_t>(p * 37 + p / 67);
        tiles.push_back(std::move(t));
      }
    }
    Require(!tiles.empty(), "No tiles selected");
    Encoder encoder(contexts);
    if (mode == "test") {
      Invalid(encoder); Identity(encoder, contexts, tiles, "", true); Concurrency(encoder, tiles); Events(encoder);
    } else if (mode == "identity") { Identity(encoder, contexts, tiles, argv[4], false); }
    else if (mode == "bench" || mode == "leak" || mode == "trace") Measure(encoder, tiles, reps, mode == "leak", mode == "trace");
    else throw std::runtime_error("Unknown gate mode");
    encoder.Destroy(); return 0;
  } catch (const std::exception& e) { std::cerr << "E1 gate: " << e.what() << std::endl; return 1; }
}
