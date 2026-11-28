#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace tpmshx::fields {
struct SigmoidResult {
    std::vector<double> values;
    std::vector<std::uint32_t> exp_overflow;
};
SigmoidResult sigmoid_values(const double* values, std::size_t count, double center, double width);
SigmoidResult sigmoid_blend(const double* x, std::size_t count,
    const double* boundaries, std::size_t boundary_count,
    const double* layers, std::size_t layer_count, double width);
SigmoidResult sigmoid_field(const double* x, const double* y, std::size_t count,
    const std::array<double, 9>& inlet, const std::array<double, 9>& outlet, double uniform,
    const std::array<double, 6>& boundaries, double width_x, double width_y);
SigmoidResult clip_values(const double* values, std::size_t count, double lower, double upper);
}  // namespace tpmshx::fields
