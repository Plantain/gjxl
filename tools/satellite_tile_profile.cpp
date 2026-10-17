// SPDX-License-Identifier: Apache-2.0
// Diagnostic companion to satellite_tile_bench; timings are instrumented.
#include <atomic>
#include <barrier>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "c_api/image_conversion.h"
#include "codestream/workflow_internal.h"
#include "core/image_buffer.h"
#include "gjxl/execution_domain.hpp"
#include "gpu/cuda/cuda_backend.h"
#include "gpu_profile_json.h"
#include "workflow_profile_json.h"

namespace {
void Check(const gjxl::Status& status) {
  if (!status.ok()) throw std::runtime_error(std::string(status.message()));
}
size_t Count(const char* text, size_t maximum) {
  const std::string value(text);
  size_t end = 0;
  if (value.empty() || value.front() < '1' || value.front() > '9')
    throw std::runtime_error("Invalid count");
  const auto n = std::stoull(value, &end);
  if (end != value.size() || n > maximum) throw std::runtime_error("Invalid count");
  return n;
}
int Run(int argc, char** argv) {
  if (argc != 6 && argc != 7) throw std::runtime_error(
      "Usage: satellite_tile_profile CONTEXTS EFFORT TILE_LIST PREFIX host|stage|dispatch [LANES=2]");
  const size_t contexts = Count(argv[1], 16);
  const int effort = static_cast<int>(Count(argv[2], 10));
  const std::string prefix(argv[4]), mode(argv[5]);
  using Mode = gjxl::gpu_profile_internal::GpuProfilingMode;
  const auto profiling = mode == "host" ? Mode::kDisabled : mode == "stage" ? Mode::kStage : Mode::kDispatch;
  if (mode != "host" && mode != "stage" && mode != "dispatch") throw std::runtime_error("Invalid mode");
  std::ifstream list(argv[3]);
  if (!list) throw std::runtime_error("Cannot open tile list");
  std::vector<gjxl::Image3FBuffer> tiles;
  std::vector<std::string> names;
  std::string path;
  while (std::getline(list, path)) {
    if (path.empty()) continue;
    std::ifstream file(path, std::ios::binary);
    std::vector<uint8_t> rgb(512 * 512 * 3);
    if (!file.read(reinterpret_cast<char*>(rgb.data()), rgb.size()) || file.peek() != EOF)
      throw std::runtime_error("Invalid tile: " + path);
    gjxl::Image3FBuffer image;
    Check(gjxl::c_api_internal::ConvertPackedSrgbToLinearRgb(
        {rgb.data(), rgb.size(), 512, 512, 512 * 3, gjxl::c_api_internal::PackedPixelFormat::kRgb8Srgb}, &image));
    tiles.push_back(std::move(image));
    names.push_back(path);
  }
  if (tiles.empty()) throw std::runtime_error("Empty tile list");
  gjxl::VarDctEncodingOptions options;
  options.backend = gjxl::VarDctBackendPreference::kCuda;
  options.cpu_thread_count = 1;
  options.effort = effort;
  options.butteraugli_target = 1.2f;
  Check(gjxl::ExecutionDomain::Create({.cpu_participant_limit = contexts}, &options.execution_domain));
  const size_t lanes = argc == 7 ? Count(argv[6], 16) : 2;
  std::vector<std::unique_ptr<gjxl::GpuBackend>> backends(lanes);
  for (auto& backend : backends) Check(gjxl::CreateCudaBackend(&backend));
  std::vector<std::vector<uint8_t>> expected(tiles.size());
  std::vector<gjxl::VarDctEncodingSummary> summaries(tiles.size());
  std::vector<gjxl::benchmark::RawWorkflowWorkload> host(tiles.size());
  std::vector<gjxl::benchmark::RawGpuProfileWorkload> gpu(tiles.size());
  std::vector<std::string> errors(contexts);
  std::barrier ready(static_cast<ptrdiff_t>(contexts));
  std::atomic<bool> failed{false};
  auto worker = [&](size_t t) {
    try {
      for (size_t i = t; i < tiles.size(); i += contexts)
        Check(gjxl::codestream_internal::EncodeLinearRgbVarDctCodestreamWithBackendForTesting(
            tiles[i].const_view(), options, backends[t % lanes].get(), false, &expected[i], &summaries[i]));
    } catch (const std::exception& e) { errors[t] = e.what(); failed = true; }
    ready.arrive_and_wait();
    if (failed) return;
    try {
      for (size_t i = t; i < tiles.size(); i += contexts) {
        std::vector<uint8_t> bytes;
        gjxl::VarDctEncodingSummary summary;
        gjxl::codestream_internal::VarDctEncodingProfile hp;
        gjxl::gpu_profile_internal::GpuExecutionProfile gp;
        if (profiling == Mode::kDisabled)
          Check(gjxl::codestream_internal::EncodeLinearRgbVarDctCodestreamProfiledWithBackendForTesting(
              tiles[i].const_view(), options, backends[t % lanes].get(), false, &bytes, &summary, &hp));
        else
          Check(gjxl::codestream_internal::EncodeLinearRgbVarDctCodestreamGpuProfiledWithBackendForTesting(
              tiles[i].const_view(), options, backends[t % lanes].get(), false, profiling, &bytes, &summary, &hp, &gp));
        if (bytes != expected[i] || summary != summaries[i]) throw std::runtime_error("Profile changed output");
        host[i] = {names[i], {512, 512}, {{i, "cuda", "gpu-only", bytes.size(), hp}}};
        gpu[i].workload = names[i];
        gpu[i].source_extent = {512, 512};
        if (profiling != Mode::kDisabled) gpu[i].samples.push_back({i, std::move(gp)});
      }
    } catch (const std::exception& e) { errors[t] = e.what(); failed = true; }
  };
  std::vector<std::thread> threads;
  for (size_t t = 1; t < contexts; ++t) threads.emplace_back(worker, t);
  worker(0);
  for (auto& thread : threads) thread.join();
  for (auto& error : errors) if (!error.empty()) throw std::runtime_error(error);
  const gjxl::benchmark::GpuProfileJsonOptions metadata{
      .scope = "satellite-512-profile", .execution_path = "explicit shared CUDA lanes",
      .gpu_profiling_mode = profiling, .gpu_aq = "fully-resident",
      .butteraugli_target = 1.2f, .warmups = 1, .samples = tiles.size(),
      .effort = effort, .cpu_thread_count = 1, .timestamp_origin = "submission-local",
      .dc_quantization = "auto", .dc_prediction = "weighted"};
  gjxl::benchmark::WriteCudaWorkflowSamples(prefix + "-host.json", metadata, "CUDA", host);
  if (profiling != Mode::kDisabled) gjxl::benchmark::WriteGpuProfileSamples(prefix + "-gpu.json", metadata, gpu);
  std::cout << "{\"contexts\":" << contexts << ",\"tiles\":" << tiles.size()
            << ",\"lanes\":" << lanes
            << ",\"effort\":" << effort << ",\"exact_bytes_and_summaries\":true}\n";
  return 0;
}
}  // namespace
int main(int argc, char** argv) {
  try { return Run(argc, argv); }
  catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
