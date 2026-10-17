// SPDX-License-Identifier: Apache-2.0
// Satellite tile throughput and byte-identity benchmark (Linux/CUDA).
// Run with the host PID namespace so NVML can identify this process.
#include <gjxl/gjxl.h>
#include <cuda_profiler_api.h>
#include <nvml.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <barrier>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <dlfcn.h>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>
#include <sys/resource.h>
#include <unistd.h>

namespace {
using Clock = std::chrono::steady_clock;
constexpr size_t kTileBytes = 512 * 512 * 3;

void Check(GJXLResult result) {
  if (result != GJXL_OK) throw std::runtime_error(gjxl_get_last_error());
}

std::string Json(const std::string& value) {
  std::ostringstream out;
  out << '"';
  for (unsigned char c : value) {
    if (c == '"' || c == '\\') out << '\\' << c;
    else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c);
    else out << c;
  }
  return out.str() + '"';
}

double CpuSeconds() {
  rusage usage{};
  if (getrusage(RUSAGE_SELF, &usage) != 0) throw std::runtime_error("getrusage failed");
  return usage.ru_utime.tv_sec + usage.ru_stime.tv_sec +
      (usage.ru_utime.tv_usec + usage.ru_stime.tv_usec) * 1e-6;
}

template <typename T> T Symbol(void* library, const char* name) {
  auto symbol = reinterpret_cast<T>(dlsym(library, name));
  if (!symbol) throw std::runtime_error(std::string("Missing symbol: ") + name);
  return symbol;
}

class DeviceMemory {
 public:
  DeviceMemory() {
    library_ = dlopen("libnvidia-ml.so.1", RTLD_NOW);
    if (!library_) throw std::runtime_error("NVML unavailable");
    auto init = Symbol<decltype(&nvmlInit_v2)>(library_, "nvmlInit_v2");
    auto device = Symbol<decltype(&nvmlDeviceGetHandleByIndex_v2)>(library_, "nvmlDeviceGetHandleByIndex_v2");
    processes_ = Symbol<decltype(&nvmlDeviceGetComputeRunningProcesses_v3)>(library_, "nvmlDeviceGetComputeRunningProcesses_v3");
    shutdown_ = Symbol<decltype(&nvmlShutdown)>(library_, "nvmlShutdown");
    if (init() != NVML_SUCCESS || device(0, &device_) != NVML_SUCCESS)
      throw std::runtime_error("NVML initialization failed");
  }
  ~DeviceMemory() { if (shutdown_) shutdown_(); if (library_) dlclose(library_); }
  void Sample() {
    std::array<nvmlProcessInfo_t, 256> entries{};
    unsigned count = entries.size();
    const auto status = processes_(device_, &count, entries.data());
    if (status != NVML_SUCCESS) throw std::runtime_error("NVML process query failed");
    for (unsigned i = 0; i < count; ++i) {
      if (entries[i].pid != static_cast<unsigned>(getpid()) ||
          entries[i].usedGpuMemory == NVML_VALUE_NOT_AVAILABLE) continue;
      peak = std::max<uint64_t>(peak, entries[i].usedGpuMemory);
      ++samples;
    }
  }
  uint64_t peak = 0;
  size_t samples = 0;
 private:
  void* library_ = nullptr;
  nvmlDevice_t device_{};
  decltype(&nvmlDeviceGetComputeRunningProcesses_v3) processes_ = nullptr;
  decltype(&nvmlShutdown) shutdown_ = nullptr;
};

class Hash {
 public:
  Hash() {
    library_ = dlopen("libcrypto.so.3", RTLD_NOW);
    if (!library_) throw std::runtime_error("libcrypto.so.3 required for SHA-256");
    sha_ = Symbol<Function>(library_, "SHA256");
  }
  ~Hash() { dlclose(library_); }
  std::string operator()(const uint8_t* data, size_t size) const {
    std::array<unsigned char, 32> digest{};
    if (!sha_(data, size, digest.data())) throw std::runtime_error("SHA256 failed");
    std::ostringstream out;
    for (auto byte : digest) out << std::hex << std::setw(2) << std::setfill('0') << unsigned(byte);
    return out.str();
  }
 private:
  using Function = unsigned char* (*)(const unsigned char*, size_t, unsigned char*);
  void* library_ = nullptr;
  Function sha_ = nullptr;
};

struct Options {
  size_t contexts = 8, reps = 1, warmups = 2;
  int effort = 8;
  float distance = 1.2f;
  int32_t aq_updates = -1;
  GJXLEntropyBehavior entropy_behavior = GJXL_ENTROPY_AUTOMATIC;
  bool profile_range = false;
  std::string output_dir;
  std::vector<std::string> paths;
};

size_t Count(const std::string& value, bool zero = false) {
  size_t end = 0;
  if (value.empty() || value[0] < '0' || value[0] > '9') throw std::runtime_error("Invalid count");
  auto n = std::stoull(value, &end);
  if (end != value.size() || (!zero && n == 0) || n > std::numeric_limits<size_t>::max())
    throw std::runtime_error("Invalid count");
  return n;
}

Options Parse(int argc, char** argv) {
  Options o;
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--help") {
      std::cout << "satellite_tile_bench [--contexts 1..16] [--reps N] [--warmups N]\n"
                   "  [--effort 1..10] [--distance D] [--list FILE] [--output-dir DIR]\n"
                   "  [--aq-updates 0..4] [--entropy-behavior balanced|rate-optimized]\n"
                   "  [--profile-range] tile.rgb...\n"
                   "JSON on stdout; SHA-256 per tile, repeated-output checks outside timing.\n"
                   "NVML peak sampled at context-0 tile boundaries (including warmup).\n";
      std::exit(0);
    }
    if (arg == "--profile-range") { o.profile_range = true; continue; }
    if (!arg.starts_with("--")) { o.paths.push_back(arg); continue; }
    if (++i == argc) throw std::runtime_error("Missing option value");
    std::string value = argv[i];
    if (arg == "--contexts") o.contexts = Count(value);
    else if (arg == "--reps") o.reps = Count(value);
    else if (arg == "--warmups") o.warmups = Count(value, true);
    else if (arg == "--effort") {
      const auto effort = Count(value);
      if (effort > 10) throw std::runtime_error("Effort must be 1..10");
      o.effort = static_cast<int>(effort);
    } else if (arg == "--aq-updates") {
      const auto updates = Count(value, true);
      if (updates > 4) throw std::runtime_error("AQ updates must be 0..4");
      o.aq_updates = static_cast<int32_t>(updates);
    } else if (arg == "--entropy-behavior") {
      if (value == "balanced") o.entropy_behavior = GJXL_ENTROPY_BALANCED;
      else if (value == "rate-optimized") o.entropy_behavior = GJXL_ENTROPY_RATE_OPTIMIZED;
      else throw std::runtime_error("Entropy behavior must be balanced or rate-optimized");
    } else if (arg == "--distance") {
      size_t end = 0;
      o.distance = std::stof(value, &end);
      if (end != value.size() || !std::isfinite(o.distance) || o.distance <= 0)
        throw std::runtime_error("Invalid distance");
    } else if (arg == "--output-dir") o.output_dir = value;
    else if (arg == "--list") {
      std::ifstream list(value);
      if (!list) throw std::runtime_error("Cannot read tile list");
      std::string path;
      while (std::getline(list, path)) if (!path.empty()) o.paths.push_back(path);
    } else throw std::runtime_error("Unknown option: " + arg);
  }
  if (o.contexts > 16 || o.paths.empty() || o.reps > std::numeric_limits<size_t>::max() / o.paths.size())
    throw std::runtime_error("Need tiles, contexts 1..16 and a valid repetition count");
  return o;
}

struct Buffer {
  GJXLBuffer value{};
  ~Buffer() { gjxl_buffer_free(&value); }
};

int Run(const Options& o) {
  Hash hash;
  DeviceMemory memory;
  std::vector<std::vector<uint8_t>> tiles;
  for (const auto& path : o.paths) {
    if (std::filesystem::file_size(path) != kTileBytes) throw std::runtime_error("Not a 512x512 RGB8 tile: " + path);
    std::ifstream file(path, std::ios::binary);
    tiles.emplace_back(kTileBytes);
    if (!file.read(reinterpret_cast<char*>(tiles.back().data()), kTileBytes)) throw std::runtime_error("Read failed: " + path);
  }
  GJXLExecutionDomainOptions domain_options;
  Check(gjxl_execution_domain_options_init(&domain_options, sizeof(domain_options)));
  domain_options.cpu_participant_limit = o.contexts;
  GJXLExecutionDomain* raw_domain = nullptr;
  Check(gjxl_execution_domain_create(&domain_options, &raw_domain));
  std::unique_ptr<GJXLExecutionDomain, decltype(&gjxl_execution_domain_destroy)> domain(raw_domain, gjxl_execution_domain_destroy);
  using Context = std::unique_ptr<GJXLContext, decltype(&gjxl_context_destroy)>;
  std::vector<Context> contexts;
  for (size_t i = 0; i < o.contexts; ++i) {
    GJXLContextOptions options;
    Check(gjxl_context_options_init(&options, sizeof(options)));
    options.backend = GJXL_BACKEND_CUDA;
    options.num_cpu_threads = 1;
    options.execution_domain = domain.get();
    GJXLContext* context = nullptr;
    Check(gjxl_context_create(&options, &context));
    contexts.emplace_back(context, gjxl_context_destroy);
  }
  GJXLEncoderOptions encode_options;
  Check(gjxl_encoder_options_init(&encode_options, sizeof(encode_options)));
  encode_options.effort = o.effort;
  encode_options.distance = o.distance;
  encode_options.aq_updates = o.aq_updates;
  encode_options.entropy_behavior = o.entropy_behavior;
  auto encode = [&](size_t context, size_t tile, Buffer& output) {
    GJXLImageView image{};
    image.struct_size = sizeof(image);
    image.width = image.height = 512;
    image.pixel_format = GJXL_PIXEL_FORMAT_RGB8_SRGB;
    image.pixels = tiles[tile].data();
    image.pixels_size = kTileBytes;
    image.row_stride_bytes = 512 * 3;
    Check(gjxl_encode(contexts[context].get(), &image, &encode_options, &output.value));
  };
  const size_t total = tiles.size() * o.reps;
  std::vector<Buffer> outputs(total);
  std::vector<double> latency(total);
  std::vector<std::string> errors(o.contexts);
  std::atomic<size_t> next{0};
  std::atomic<bool> failed{false};
  std::barrier ready(static_cast<ptrdiff_t>(o.contexts));
  std::barrier start(static_cast<ptrdiff_t>(o.contexts));
  std::barrier finished(static_cast<ptrdiff_t>(o.contexts));
  Clock::time_point begin, end;
  double cpu_begin = 0, cpu_end = 0;
  auto worker = [&](size_t t) {
    try {
      for (size_t i = 0; i < o.warmups; ++i) {
        Buffer output;
        encode(t, (t + i * o.contexts) % tiles.size(), output);
        if (t == 0) memory.Sample();
      }
    } catch (const std::exception& e) { errors[t] = e.what(); failed = true; }
    ready.arrive_and_wait();
    if (t == 0) {
      if (o.profile_range) cudaProfilerStart();
      cpu_begin = CpuSeconds();
      begin = Clock::now();
    }
    start.arrive_and_wait();
    try {
      while (!failed.load()) {
        const size_t job = next.fetch_add(1);
        if (job >= total) break;
        const auto before = Clock::now();
        encode(t, job % tiles.size(), outputs[job]);
        latency[job] = std::chrono::duration<double, std::milli>(Clock::now() - before).count();
        if (t == 0) memory.Sample();
      }
    } catch (const std::exception& e) { errors[t] = e.what(); failed = true; }
    finished.arrive_and_wait();
    if (t == 0) {
      end = Clock::now();
      cpu_end = CpuSeconds();
      if (o.profile_range) cudaProfilerStop();
    }
  };
  std::vector<std::thread> workers;
  for (size_t t = 1; t < o.contexts; ++t) workers.emplace_back(worker, t);
  worker(0);
  for (auto& thread : workers) thread.join();
  for (const auto& error : errors) if (!error.empty()) throw std::runtime_error(error);
  memory.Sample();
  if (memory.samples == 0) throw std::runtime_error("No process VRAM samples; run docker with --pid=host");

  std::vector<std::string> hashes;
  uint64_t bytes = 0;
  std::string aggregate;
  if (!o.output_dir.empty()) std::filesystem::create_directories(o.output_dir);
  for (size_t i = 0; i < total; ++i) {
    const auto& output = outputs[i].value;
    if (output.size < 2 || output.data[0] != 0xff || output.data[1] != 0x0a) throw std::runtime_error("Not a bare codestream");
    if (i >= tiles.size()) {
      const auto& first = outputs[i % tiles.size()].value;
      if (output.size != first.size || std::memcmp(output.data, first.data, output.size) != 0)
        throw std::runtime_error("Repeated output differs");
      continue;
    }
    bytes += output.size;
    hashes.push_back(hash(output.data, output.size));
    aggregate += hashes.back() + '\n';
    if (!o.output_dir.empty()) {
      const auto path = std::filesystem::path(o.output_dir) / (std::to_string(i) + ".jxl");
      std::ofstream file(path, std::ios::binary);
      file.write(reinterpret_cast<const char*>(output.data), output.size);
      if (!file) throw std::runtime_error("Codestream write failed");
    }
  }
  GJXLExecutionDomainSnapshot snapshot{};
  Check(gjxl_execution_domain_snapshot(domain.get(), &snapshot, sizeof(snapshot)));
  std::sort(latency.begin(), latency.end());
  const auto percentile = [&](double p) { return latency[static_cast<size_t>(std::ceil(p * total)) - 1]; };
  const double seconds = std::chrono::duration<double>(end - begin).count();
  std::cout << std::setprecision(10)
      << "{\"schema\":1,\"encoder\":\"gjxl-cuda\",\"effort\":" << o.effort
      << ",\"aq_updates\":" << o.aq_updates
      << ",\"entropy_behavior\":" << o.entropy_behavior
      << ",\"distance\":" << o.distance << ",\"contexts\":" << o.contexts
      << ",\"warmups_per_context\":" << o.warmups << ",\"tiles\":" << tiles.size()
      << ",\"reps\":" << o.reps << ",\"encodes\":" << total
      << ",\"seconds\":" << seconds << ",\"tiles_per_s\":" << total / seconds
      << ",\"cpu_seconds\":" << cpu_end - cpu_begin << ",\"cpu_cores_busy\":" << (cpu_end - cpu_begin) / seconds
      << ",\"peak_cpu_participants\":" << snapshot.peak_cpu_participants
      << ",\"peak_device_bytes_sampled\":" << memory.peak << ",\"device_memory_samples\":" << memory.samples
      << ",\"device_memory_method\":\"NVML current PID, context-0 tile boundaries including warmup\""
      << ",\"latency_ms\":{\"p50\":" << percentile(.50) << ",\"p95\":" << percentile(.95)
      << ",\"p99\":" << percentile(.99) << ",\"max\":" << latency.back() << "}"
      << ",\"bytes\":" << bytes << ",\"aggregate_sha256\":"
      << Json(hash(reinterpret_cast<const uint8_t*>(aggregate.data()), aggregate.size()))
      << ",\"repeat_byte_identity\":true,\"outputs\":[";
  for (size_t i = 0; i < tiles.size(); ++i) {
    if (i) std::cout << ',';
    std::cout << "{\"path\":" << Json(o.paths[i]) << ",\"bytes\":" << outputs[i].value.size
              << ",\"sha256\":" << Json(hashes[i]) << '}';
  }
  std::cout << "]}\n";
  return 0;
}
}  // namespace

int main(int argc, char** argv) {
  try { return Run(Parse(argc, argv)); }
  catch (const std::exception& e) { std::cerr << "satellite_tile_bench: " << e.what() << '\n'; return 1; }
}
