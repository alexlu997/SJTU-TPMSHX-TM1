#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace tpmshx::fields {
struct LUTView {
    const double *x, *y, *epsilon, *area;
    std::size_t nx, ny, table_count;
    std::uint32_t epsilon_fast, area_fast;
};
void validate_lut_axes(const double* x, std::size_t nx, const double* y, std::size_t ny);
std::array<std::vector<double>, 2> sample_lut(const LUTView& view,
    const double* x, const double* y, std::size_t count);
}  // namespace tpmshx::fields
