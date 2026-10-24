// SPDX-License-Identifier: Apache-2.0
// Resident encoding at a coding extent below 512 (satellite z8 delivery uses
// 320): host, HWC and CHW inputs must match the CUDA context encode of the
// same zero-padded image, the header must carry the extent, and 512 output
// must not change when batches of both extents share the encoder's lanes.
#include <gjxl/gjxl.h>
#include <cuda_runtime_api.h>

#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void Check(GJXLResult result) {
  if (result != GJXL_OK) throw std::runtime_error(gjxl_get_last_error());
}
void CheckCuda(cudaError_t result) {
  if (result != cudaSuccess) throw std::runtime_error(cudaGetErrorString(result));
}
void Require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}
struct Encoder {
  GJXLEncoder* value = nullptr;
  ~Encoder() { if (value) gjxl_encoder_destroy(value); }
};
struct Buffer {
  GJXLBuffer value{};
  ~Buffer() { gjxl_buffer_free(&value); }
  std::vector<uint8_t> Bytes() const { return {value.data, value.data + value.size}; }
};
struct DeviceBuffer {
  void* value = nullptr;
  ~DeviceBuffer() { if (value) (void)cudaFree(value); }
};

// Real satellite content: synthetic periodic patterns create exact cost ties
// that the encoder does not promise to break identically across inputs.
std::vector<uint8_t> Fixture(const std::string& path) {
  std::vector<uint8_t> pixels(512 * 512 * 3);
  std::ifstream input(path, std::ios::binary);
  if (!input.read(reinterpret_cast<char*>(pixels.data()), pixels.size()) ||
      input.peek() != std::ifstream::traits_type::eof())
    throw std::runtime_error("Invalid satellite fixture");
  return pixels;
}

std::vector<uint8_t> Crop(const std::vector<uint8_t>& tile, uint32_t width, uint32_t height,
                          uint32_t left, uint32_t top) {
  std::vector<uint8_t> pixels(size_t{width} * height * 3);
  for (uint32_t y = 0; y < height; ++y)
    std::memcpy(pixels.data() + size_t{y} * width * 3,
                tile.data() + (size_t{top + y} * 512 + left) * 3, size_t{width} * 3);
  return pixels;
}

// The oracle: the CUDA context encoder on a host image zero-padded to extent.
std::vector<uint8_t> Reference(const std::vector<uint8_t>& pixels, uint32_t width, uint32_t height,
                               uint32_t extent, const GJXLEncoderOptions& options) {
  GJXLContextOptions context_options;
  Check(gjxl_context_options_init(&context_options, sizeof(context_options)));
  context_options.backend = GJXL_BACKEND_CUDA;
  context_options.num_cpu_threads = 1;
  GJXLContext* context = nullptr;
  Check(gjxl_context_create(&context_options, &context));
  std::unique_ptr<GJXLContext, decltype(&gjxl_context_destroy)> owner(context, gjxl_context_destroy);
  std::vector<uint8_t> padded(size_t{extent} * extent * 3, 0);
  for (uint32_t y = 0; y < height; ++y)
    std::memcpy(padded.data() + size_t{y} * extent * 3, pixels.data() + size_t{y} * width * 3, width * 3);
  const GJXLImageView view{sizeof(view), extent, extent, GJXL_PIXEL_FORMAT_RGB8_SRGB,
                           padded.data(), padded.size(), size_t{extent} * 3};
  Buffer output;
  Check(gjxl_encode(context, &view, &options, &output.value));
  return output.Bytes();
}

std::vector<uint8_t> Resident(Encoder& encoder, const std::vector<uint8_t>& pixels, uint32_t width,
                              uint32_t height, uint32_t extent, int layout,
                              const GJXLEncoderOptions& options) {
  Buffer output;
  if (layout == 0) {
    const GJXLImageView host{sizeof(host), width, height, GJXL_PIXEL_FORMAT_RGB8_SRGB,
                             pixels.data(), pixels.size(), size_t{width} * 3};
    Check(gjxl_encoder_encode_host_extent(encoder.value, &host, 1, extent, &options, &output.value));
    return output.Bytes();
  }
  // Padded rows and pixels exercise both strided device layouts.
  const size_t pixel_stride = layout == 1 ? 4 : 1;
  const size_t row_stride = width * pixel_stride + 17;
  const size_t channel_stride = layout == 1 ? 1 : row_stride * height;
  std::vector<uint8_t> packed(row_stride * height * (layout == 1 ? 1 : 3), 0xDA);
  for (size_t y = 0; y < height; ++y)
    for (size_t x = 0; x < width; ++x)
      for (size_t c = 0; c < 3; ++c)
        packed[y * row_stride + x * pixel_stride + c * channel_stride] = pixels[(y * width + x) * 3 + c];
  DeviceBuffer device;
  CheckCuda(cudaMalloc(&device.value, packed.size()));
  CheckCuda(cudaMemcpy(device.value, packed.data(), packed.size(), cudaMemcpyHostToDevice));
  const GJXLDeviceTileRGB8 tile{sizeof(tile), static_cast<uint8_t*>(device.value),
                                static_cast<int64_t>(channel_stride), static_cast<int64_t>(pixel_stride),
                                static_cast<int64_t>(row_stride), width, height};
  const GJXLDeviceBatch batch{sizeof(batch), &tile, 1, 0, 0};
  Check(gjxl_encoder_encode_device_extent(encoder.value, &batch, extent, &options, &output.value));
  return output.Bytes();
}

// SizeHeader, read LSB first: div8 flag, ysize, ratio, then xsize when ratio is 0.
void RequireHeaderExtent(const std::vector<uint8_t>& codestream, uint32_t extent) {
  Require(codestream.size() > 8 && codestream[0] == 0xFF && codestream[1] == 0x0A,
          "Output is not a bare JPEG XL codestream");
  uint64_t bits = 0;
  for (int i = 7; i >= 2; --i) bits = bits << 8 | codestream[i];
  size_t position = 0;
  auto read = [&](int count) {
    const uint32_t value = static_cast<uint32_t>(bits >> position) & ((1u << count) - 1);
    position += count;
    return value;
  };
  const bool div8 = read(1) == 1;
  const int selector_bits[4] = {9, 13, 18, 30};
  auto size = [&] { return div8 ? (read(5) + 1) * 8 : read(selector_bits[read(2)]) + 1; };
  const uint32_t height = size();
  const uint32_t ratio = read(3);  // 0: explicit xsize follows; 1: square
  const uint32_t width = ratio == 0 ? size() : ratio == 1 ? height : 0;
  Require(height == extent && width == extent,
          "Header extent mismatch: " + std::to_string(width) + "x" + std::to_string(height));
}
}  // namespace

int main(int argc, char** argv) {
  int devices = 0;
  if (cudaGetDeviceCount(&devices) != cudaSuccess || devices == 0) return 77;
  try {
    if (argc < 2) throw std::runtime_error("Expected a 512x512 RGB satellite fixture");
    const auto tile = Fixture(argv[1]);
    CheckCuda(cudaSetDevice(0));
    Encoder encoder;
    const GJXLEncoderCreateOptions create{sizeof(create), 0, 2, uint64_t{2048} << 20, 2};
    Check(gjxl_encoder_create(&create, &encoder.value));
    std::vector<GJXLEncoderOptions> presets;
    for (int effort : {1, 7, 8, 10}) {
      GJXLEncoderOptions options;
      Check(gjxl_encoder_options_init(&options, sizeof(options)));
      options.distance = 1.2f;
      options.effort = effort;
      presets.push_back(options);
    }
    presets.push_back(presets[2]);
    presets.back().distance = 1.275f;  // satellite's e8-balanced AHI route
    presets.back().entropy_behavior = GJXL_ENTROPY_BALANCED;

    const auto& full512 = tile;
    std::vector<uint8_t> before512;
    {
      Buffer output;
      const GJXLImageView host{sizeof(host), 512, 512, GJXL_PIXEL_FORMAT_RGB8_SRGB,
                               full512.data(), full512.size(), 1536};
      Check(gjxl_encoder_encode_host(encoder.value, &host, 1, &presets.back(), &output.value));
      before512 = output.Bytes();
      Require(before512 == Resident(encoder, full512, 512, 512, 512, 2, presets.back()),
              "The 512 extent entry point differs from the original call");
    }
    size_t encodes = 0;
    const std::pair<uint32_t, uint32_t> sizes[] = {
        {320, 320}, {1, 1}, {1, 320}, {320, 1}, {319, 317}, {257, 199}, {64, 64}};
    for (const auto& options : presets) {
      for (auto [width, height] : sizes) {
        const auto pixels = Crop(tile, width, height, (512 - width) / 2, (512 - height) / 3);
        const auto expected = Reference(pixels, width, height, 320, options);
        RequireHeaderExtent(expected, 320);
        for (int layout = 0; layout < 3; ++layout, ++encodes)
          Require(Resident(encoder, pixels, width, height, 320, layout, options) == expected,
                  "320 resident encode differs from the context oracle at " +
                  std::to_string(width) + "x" + std::to_string(height) + " layout " +
                  std::to_string(layout));
      }
    }
    // Interleave extents on the same lanes; 512 must stay byte-identical.
    Require(Resident(encoder, full512, 512, 512, 512, 1, presets.back()) == before512,
            "512 output changed after 320 batches");
    Buffer rejected;
    const auto large = Crop(tile, 321, 320, 0, 0);
    const GJXLImageView host{sizeof(host), 321, 320, GJXL_PIXEL_FORMAT_RGB8_SRGB,
                             large.data(), large.size(), 321 * 3};
    Require(gjxl_encoder_encode_host_extent(encoder.value, &host, 1, 320, &presets[0], &rejected.value)
                == GJXL_ERROR_INVALID_ARGUMENT, "A tile larger than the extent was accepted");
    Require(gjxl_encoder_encode_host_extent(encoder.value, &host, 1, 300, &presets[0], &rejected.value)
                == GJXL_ERROR_INVALID_ARGUMENT, "An extent that is not a multiple of 64 was accepted");
    std::cout << "Resident extent test passed: " << encodes << " 320 encodes, 512 unchanged\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
  return 0;
}
