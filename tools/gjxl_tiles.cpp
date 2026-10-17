// gjxl evaluation driver for 512x512 RGB8 sRGB tiles via the public C API.
//   gjxl_tiles one IN.ppm OUT.jxl DISTANCE EFFORT
//   gjxl_tiles bench THREADS REPS DISTANCE EFFORT tile.rgb...
// bench: THREADS workers, each with its own CUDA context, encode the tiles
// REPS times (dynamic scheduling) and report sustained tiles/s.
#include <gjxl/gjxl.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <filesystem>
#include <ctime>
#include <string>
#include <thread>
#include <vector>

namespace {
constexpr uint32_t kDim = 512;
GJXLEncoderOptions preset;
std::string preset_flags;

bool ParseFlags(int argc, char** argv, int* index) {
  for (; *index < argc && std::string(argv[*index]).starts_with("--"); *index += 2) {
    if (*index + 1 >= argc) return false;
    const std::string flag = argv[*index], value = argv[*index + 1];
    preset_flags += (preset_flags.empty() ? "" : " ") + flag + " " + value;
    char* end = nullptr;
    const long number = strtol(value.c_str(), &end, 10);
    const bool numeric = end != value.c_str() && *end == '\0';
    if (flag == "--aq-updates" || flag == "--final-cfl-iterations" || flag == "--ac-search-spacing") {
      const int maximum = flag == "--aq-updates" ? 4 : flag == "--final-cfl-iterations" ? 20 : 2;
      if (value != "auto" && (!numeric || number < 0 || number > maximum ||
          (flag == "--ac-search-spacing" && number == 0))) return false;
      if (flag == "--aq-updates") preset.aq_updates = value == "auto" ? -1 : number;
      if (flag == "--final-cfl-iterations") preset.final_cfl_iterations = value == "auto" ? -1 : number;
      if (flag == "--ac-search-spacing") preset.ac_search_spacing = value == "auto" ? 0 : number;
    } else if (flag == "--entropy-behavior") {
      if (value == "auto") preset.entropy_behavior = GJXL_ENTROPY_AUTOMATIC;
      else if (value == "balanced") preset.entropy_behavior = GJXL_ENTROPY_BALANCED;
      else if (value == "rate-optimized") preset.entropy_behavior = GJXL_ENTROPY_RATE_OPTIMIZED;
      else return false;
    } else if (flag == "--coefficient-orders") {
      if (value == "auto") preset.coefficient_order_behavior = GJXL_COEFFICIENT_ORDER_AUTOMATIC;
      else if (value == "sampled") preset.coefficient_order_behavior = GJXL_COEFFICIENT_ORDER_SAMPLED;
      else if (value == "full") preset.coefficient_order_behavior = GJXL_COEFFICIENT_ORDER_FULL;
      else return false;
    } else {
      GJXLFeatureOverride* field = nullptr;
      if (flag == "--epf-sharpness-search") field = &preset.epf_sharpness_search;
      if (flag == "--fixed-dct8") field = &preset.fixed_dct8;
      if (flag == "--uniform-initial-quantization") field = &preset.uniform_initial_quantization;
      if (flag == "--gaborish") field = &preset.gaborish;
      if (flag == "--adjusted-ac-quantization") field = &preset.adjusted_ac_quantization;
      if (flag == "--adaptive-quantization-matrices") field = &preset.adaptive_quantization_matrices;
      if (flag == "--dc-uint-search") field = &preset.dc_uint_search;
      if (!field) return false;
      if (value == "auto") *field = GJXL_FEATURE_AUTOMATIC;
      else if (value == "off") *field = GJXL_FEATURE_DISABLED;
      else if (value == "on") *field = GJXL_FEATURE_ENABLED;
      else return false;
    }
  }
  return true;
}

bool Write(const std::filesystem::path& path, const std::vector<uint8_t>& data) {
  FILE* f = fopen(path.c_str(), "wb");
  if (!f) return false;
  const bool ok = fwrite(data.data(), 1, data.size(), f) == data.size();
  return fclose(f) == 0 && ok;
}

double CpuSeconds() {
  return static_cast<double>(std::clock()) / CLOCKS_PER_SEC;
}

GJXLContext* MakeContext() {
  GJXLContextOptions o;
  gjxl_context_options_init(&o, sizeof(o));
  o.backend = GJXL_BACKEND_CUDA;
  o.num_cpu_threads = 1;
  GJXLContext* c = nullptr;
  if (gjxl_context_create(&o, &c) != GJXL_OK) {
    fprintf(stderr, "context: %s\n", gjxl_get_last_error());
    exit(1);
  }
  return c;
}

bool Encode(GJXLContext* c, const uint8_t* rgb, float d, int effort,
            std::vector<uint8_t>* out) {
  GJXLImageView v;
  memset(&v, 0, sizeof(v));
  v.struct_size = sizeof(v);
  v.width = kDim;
  v.height = kDim;
  v.pixel_format = GJXL_PIXEL_FORMAT_RGB8_SRGB;
  v.pixels = rgb;
  v.pixels_size = kDim * kDim * 3;
  v.row_stride_bytes = kDim * 3;
  GJXLEncoderOptions o = preset;
  o.distance = d;
  o.effort = effort;
  GJXLBuffer b{nullptr, 0};
  if (gjxl_encode(c, &v, &o, &b) != GJXL_OK) {
    fprintf(stderr, "encode: %s\n", gjxl_get_last_error());
    return false;
  }
  out->assign(b.data, b.data + b.size);
  gjxl_buffer_free(&b);
  return true;
}

std::vector<uint8_t> ReadRgb(const char* path) {
  FILE* f = fopen(path, "rb");
  std::vector<uint8_t> v(kDim * kDim * 3);
  if (!f || fread(v.data(), 1, v.size(), f) != v.size()) {
    fprintf(stderr, "read %s\n", path);
    exit(1);
  }
  fclose(f);
  return v;
}

std::vector<uint8_t> ReadPpm(const char* path) {
  FILE* f = fopen(path, "rb");
  int w, h, m;
  if (!f || fscanf(f, "P6 %d %d %d", &w, &h, &m) != 3 || w != 512 || h != 512 || m != 255) {
    fprintf(stderr, "bad ppm %s\n", path);
    exit(1);
  }
  fgetc(f);
  std::vector<uint8_t> v(kDim * kDim * 3);
  if (fread(v.data(), 1, v.size(), f) != v.size()) exit(1);
  fclose(f);
  return v;
}
}  // namespace

int main(int argc, char** argv) {
  gjxl_encoder_options_init(&preset, sizeof(preset));
  if (argc >= 6 && std::string(argv[1]) == "dump") {
    int first = 5;
    if (!ParseFlags(argc, argv, &first) || first == argc) return 2;
    std::filesystem::create_directories(argv[2]);
    GJXLContext* c = MakeContext();
    for (int i = first; i < argc; ++i) {
      std::vector<uint8_t> out;
      if (!Encode(c, ReadRgb(argv[i]).data(), atof(argv[3]), atoi(argv[4]), &out) ||
          !Write(std::filesystem::path(argv[2]) /
                 (std::filesystem::path(argv[i]).filename().string() + ".jxl"), out)) return 1;
    }
    gjxl_context_destroy(c);
    return 0;
  }
  if (argc >= 6 && std::string(argv[1]) == "one") {
    int first = 6;
    if (!ParseFlags(argc, argv, &first) || first != argc) return 2;
    GJXLContext* c = MakeContext();
    std::vector<uint8_t> out;
    if (!Encode(c, ReadPpm(argv[2]).data(), atof(argv[4]), atoi(argv[5]), &out)) return 1;
    if (!Write(argv[3], out)) return 1;
    gjxl_context_destroy(c);
    return 0;
  }
  if (argc >= 7 && std::string(argv[1]) == "bench") {
    const int threads = atoi(argv[2]), reps = atoi(argv[3]), effort = atoi(argv[5]);
    const float d = atof(argv[4]);
    std::vector<std::vector<uint8_t>> tiles;
    int first = 6;
    if (!ParseFlags(argc, argv, &first) || first == argc || threads < 1 || threads > 16 ||
        reps < 1 || effort < 1 || effort > 10 || !std::isfinite(d) || d <= 0) return 2;
    for (int i = first; i < argc; ++i) tiles.push_back(ReadRgb(argv[i]));
    const size_t n = tiles.size(), total = n * reps;
    std::vector<GJXLContext*> ctx(threads);
    for (auto& c : ctx) c = MakeContext();
    std::atomic<bool> failed{false};
    // Warm up every context once (kernel loading, allocations).
    {
      std::vector<std::thread> w;
      for (int t = 0; t < threads; ++t)
        w.emplace_back([&, t] { std::vector<uint8_t> o; if (!Encode(ctx[t], tiles[t % n].data(), d, effort, &o)) failed = true; });
      for (auto& x : w) x.join();
    }
    std::atomic<size_t> next{0};
    std::atomic<size_t> bytes{0};
    if (failed) return 1;
    const double cpu_start = CpuSeconds();
    auto start = std::chrono::steady_clock::now();
    std::vector<std::thread> w;
    for (int t = 0; t < threads; ++t) {
      w.emplace_back([&, t] {
        std::vector<uint8_t> o;
        for (;;) {
          size_t job = next.fetch_add(1);
          if (job >= total) break;
          if (!Encode(ctx[t], tiles[job % n].data(), d, effort, &o)) { failed = true; break; }
          if (job < n) bytes += o.size();
        }
      });
    }
    for (auto& x : w) x.join();
    double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
    printf("{\"encoder\":\"gjxl-cuda\",\"effort\":%d,\"distance\":%.3f,\"threads\":%d,\"tiles\":%zu,\"encodes\":%zu,\"seconds\":%.3f,\"tiles_per_s\":%.2f,\"bytes\":%zu,\"failed\":%s,\"cpu_seconds\":%.6f,\"cpu_ms_per_tile\":%.6f,\"flags\":\"%s\"}\n",
           effort, d, threads, n, total, s, total / s, bytes.load(), failed ? "true" : "false", CpuSeconds() - cpu_start,
           (CpuSeconds() - cpu_start) * 1000 / total, preset_flags.c_str());
    for (auto c : ctx) gjxl_context_destroy(c);
    return failed ? 1 : 0;
  }
  fprintf(stderr, "usage: gjxl_tiles one IN.ppm OUT.jxl D EFFORT [flags] | bench THREADS REPS D EFFORT [flags] tiles... | dump DIR D EFFORT [flags] tiles...\n");
  return 2;
}
