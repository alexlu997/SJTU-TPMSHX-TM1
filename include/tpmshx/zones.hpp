#pragma once

#include "tpmshx/grid.hpp"
#include <array>
#include <cstdint>
#include <vector>

namespace tpmshx::zones {
using Values = std::vector<double>;
using Bounds = std::array<grid::Scalar, 4>;

// Stripe rows are already sorted and validated by the configuration owner.
std::vector<std::int32_t> assign(std::uint32_t kind, std::size_t nx, std::size_t ny,
    int axis, grid::Scalar domain, const std::vector<Bounds>& rows,
    const Values* dx, const Values* dy);
Values gaussian_sigma2(const Values& input, std::size_t nx, std::size_t ny);
}  // namespace tpmshx::zones
