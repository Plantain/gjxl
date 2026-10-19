// SPDX-License-Identifier: Apache-2.0
#include <gjxl/gjxl.h>
#include <cuda_runtime_api.h>

#include <cstring>
#include <fstream>
#include <iostream>
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
struct Encoder {
  GJXLEncoder* value = nullptr;
  ~Encoder() { if (value) gjxl_encoder_destroy(value); }
};
struct Buffer {
  GJXLBuffer value{};
  ~Buffer() { gjxl_buffer_free(&value); }
};
struct DeviceBuffer {
  void* value = nullptr;
  ~DeviceBuffer() { if (value) (void)cudaFree(value); }
};
}  // namespace

int main(int argc, char** argv) {
  int devices = 0;
  if (cudaGetDeviceCount(&devices) != cudaSuccess || devices == 0) return 77;
  try {
    if (argc < 2) throw std::runtime_error("Expected raw-quant-257.rgb path");
    const unsigned repeats = argc > 2 ? std::stoul(argv[2]) : 2;
    const unsigned contexts = argc > 3 ? std::stoul(argv[3]) : 1;
    constexpr size_t kBytes = 512 * 512 * 3;
    std::vector<uint8_t> pixels(kBytes);
    std::ifstream input(argv[1], std::ios::binary);
    if (!input.read(reinterpret_cast<char*>(pixels.data()), pixels.size()) ||
        input.peek() != std::ifstream::traits_type::eof())
      throw std::runtime_error("Invalid regression fixture");
    CheckCuda(cudaSetDevice(0));
    Encoder encoder;
    const GJXLEncoderCreateOptions create{
        sizeof(create), 0, contexts, uint64_t{2048} << 20, contexts};
    Check(gjxl_encoder_create(&create, &encoder.value));
    GJXLEncoderOptions options;
    Check(gjxl_encoder_options_init(&options, sizeof(options)));
    options.distance = 1.19f;
    options.effort = 8;
    options.entropy_behavior = GJXL_ENTROPY_BALANCED;
    const GJXLImageView host{sizeof(host), 512, 512, GJXL_PIXEL_FORMAT_RGB8_SRGB,
                             pixels.data(), pixels.size(), 1536};
    std::vector<uint8_t> expected;
    for (unsigned repeat = 0; repeat < repeats; ++repeat) {
      for (unsigned layout = 0; layout < 3; ++layout) {
        uint64_t released = 0, live = 1;
        Check(gjxl_encoder_release_device_memory(encoder.value, &released));
        Check(gjxl_encoder_device_memory_bytes(encoder.value, &live));
        if (live != 0) throw std::runtime_error("Idle arenas were not released");
        Buffer output;
        if (layout == 0) {
          Check(gjxl_encoder_encode_host(encoder.value, &host, 1, &options, &output.value));
        } else {
          // Deliberately padded rows and pixels exercise both strided layouts.
          const size_t pixel_stride = layout == 1 ? 4 : 1;
          const size_t row_stride = 512 * pixel_stride + 17;
          const size_t channel_stride = layout == 1 ? 1 : row_stride * 512;
          std::vector<uint8_t> packed(row_stride * 512 * (layout == 1 ? 1 : 3), 0xDA);
          for (size_t y = 0; y < 512; ++y)
            for (size_t x = 0; x < 512; ++x)
              for (size_t c = 0; c < 3; ++c)
                packed[y * row_stride + x * pixel_stride + c * channel_stride] =
                    pixels[(y * 512 + x) * 3 + c];
          DeviceBuffer device;
          CheckCuda(cudaMalloc(&device.value, packed.size()));
          CheckCuda(cudaMemcpy(device.value, packed.data(), packed.size(), cudaMemcpyHostToDevice));
          const GJXLDeviceTileRGB8 tile{
              sizeof(tile), static_cast<uint8_t*>(device.value),
              static_cast<int64_t>(channel_stride), static_cast<int64_t>(pixel_stride),
              static_cast<int64_t>(row_stride), 512, 512};
          const GJXLDeviceBatch batch{sizeof(batch), &tile, 1, 0, 0};
          Check(gjxl_encoder_encode_device(encoder.value, &batch, &options, &output.value));
        }
        if (expected.empty()) {
          expected.assign(output.value.data, output.value.data + output.value.size);
        } else if (output.value.size != expected.size() ||
                   std::memcmp(output.value.data, expected.data(), expected.size()) != 0) {
          throw std::runtime_error("Reproduction changed bytes across layouts/releases");
        }
      }
    }
    if (argc > 4) {
      std::ofstream output(argv[4], std::ios::binary);
      if (!output.write(reinterpret_cast<const char*>(expected.data()), expected.size()))
        throw std::runtime_error("Cannot save regression codestream");
    }
    std::cout << "Raw-quant regression passed: " << repeats * 3
              << " encodes, host/HWC/CHW, " << contexts << " contexts, "
              << expected.size() << " bytes\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
  return 0;
}
