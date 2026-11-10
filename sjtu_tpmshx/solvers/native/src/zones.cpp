// Copyright (C) 2003-2005 Peter J. Verveer.
// Copyright (c) 2005-2025, NumPy Developers.
// See the SciPy and NumPy source notices in the native license directory.
#include "tpmshx/zones.hpp"
#include "contiguous_sum.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx::zones {
namespace {
using grid::Scalar;
std::size_t extent(std::size_t nx, std::size_t ny) {
    const auto limit = static_cast<std::size_t>(std::numeric_limits<std::int64_t>::max() / 2);
    if (!nx || !ny || nx > limit || ny > limit || nx > std::numeric_limits<std::size_t>::max() / ny)
        throw std::invalid_argument("positive representable zone dimensions are required");
    return nx * ny;
}

double sum(const Values& values) {
    return 0. + detail::contiguous_sum({values.data(), values.size()});
}

std::vector<Scalar> fractions(std::size_t count, std::uint32_t kind,
                              Scalar domain, const Values* widths) {
    std::vector<Scalar> result(count);
    if (widths && widths->size() != count)
        throw std::invalid_argument("zone width count differs from the axis");
    if (!widths) {
        if (kind == 0) {
            const auto spacing = grid::divide(domain, grid::weak(static_cast<double>(count)));
            for (std::size_t i = 0; i < count; ++i) {
                auto value = grid::divide(grid::multiply(grid::weak(static_cast<double>(i) + .5), spacing), domain);
                value.strong = 1; // The original list becomes a NumPy array before comparison.
                result[i] = value;
            }
        } else {
            for (std::size_t i = 0; i < count; ++i)
                result[i] = {(static_cast<double>(i) + .5) / static_cast<double>(count), 64, kind == 1 ? 0u : 1u};
        }
        return result;
    }
    const double total = kind == 0 ? domain.value : sum(*widths);
    double cumulative = 0.;
    for (std::size_t i = 0; i < count; ++i) {
        const double previous = cumulative;
        cumulative += (*widths)[i];
        const double value = kind == 1 ? .5 * (previous + cumulative) / total
            : (cumulative - .5 * (*widths)[i]) / total;
        result[i] = {value, 64, kind == 1 ? 0u : 1u};
    }
    return result;
}

bool inside(Scalar point, Scalar lower, Scalar upper) {
    return !std::isnan(point.value) && !std::isnan(lower.value)
        && !grid::less(point, lower) && grid::less(point, upper);
}

std::size_t reflected(std::int64_t index, std::size_t count) {
    const auto period = 2 * static_cast<std::int64_t>(count);
    auto value = index % period;
    if (value < 0) value += period;
    return static_cast<std::size_t>(value < static_cast<std::int64_t>(count) ? value : period - value - 1);
}

Values correlate(const Values& input, std::size_t nx, std::size_t ny, int axis,
                 const std::array<double, 17>& weights) {
    Values result(input.size());
    for (std::size_t x = 0; x < nx; ++x)
        for (std::size_t y = 0; y < ny; ++y) {
            double value = input[x * ny + y] * weights[8];
            const auto coordinate = static_cast<std::int64_t>(axis == 0 ? x : y);
            const auto count = axis == 0 ? nx : ny;
            for (int offset = -8; offset < 0; ++offset) {
                const auto left = reflected(coordinate + offset, count);
                const auto right = reflected(coordinate - offset, count);
                const double a = input[axis == 0 ? left * ny + y : x * ny + left];
                const double b = input[axis == 0 ? right * ny + y : x * ny + right];
                const double pair = a + b;
#if defined(__APPLE__) && defined(__aarch64__)
                // The locked arm64 ndimage loop fuses this multiply and addition.
                value = std::fma(pair, weights[static_cast<std::size_t>(8 + offset)], value);
#else
                value += pair * weights[static_cast<std::size_t>(8 + offset)];
#endif
            }
            result[x * ny + y] = value;
        }
    return result;
}
}  // namespace

std::vector<std::int32_t> assign(std::uint32_t kind, std::size_t nx, std::size_t ny,
    int axis, Scalar domain, const std::vector<Bounds>& rows, const Values* dx, const Values* dy) {
    const auto count = extent(nx, ny);
    domain = grid::checked(domain);
    if (kind > 2 || (kind == 0 && (axis < 0 || axis > 1 || rows.empty()))
        || rows.size() > static_cast<std::size_t>(std::numeric_limits<std::int32_t>::max()))
        throw std::invalid_argument("invalid zone kind, axis or row count");
    if (kind == 2 && (!dx || !dy)) throw std::invalid_argument("3D zones need physical widths");
    for (const auto& row : rows) for (const auto bound : row) grid::checked(bound);
    std::vector<std::int32_t> result(count, kind == 2 ? -1 : 0);
    const auto x = fractions(nx, kind == 0 && axis != 0 ? 1 : kind, domain, dx);
    const auto y = fractions(ny, kind == 0 && axis != 1 ? 1 : kind, domain, dy);
    for (std::size_t i = 0; i < nx; ++i)
        for (std::size_t j = 0; j < ny; ++j) {
            auto& selected = result[i * ny + j];
            if (kind == 0) selected = static_cast<std::int32_t>(rows.size() - 1);
            for (std::size_t k = 0; k < rows.size(); ++k) {
                const auto& row = rows[k];
                const bool hit = kind == 0 ? inside(axis == 0 ? x[i] : y[j], row[0], row[1])
                    : inside(x[i], row[0], row[1]) && inside(y[j], row[2], row[3]);
                if (hit) {
                    selected = static_cast<std::int32_t>(k);
                    if (kind != 2) break;
                }
            }
        }
    return result;
}

Values gaussian_sigma2(const Values& input, std::size_t nx, std::size_t ny) {
    if (input.size() != extent(nx, ny)) throw std::invalid_argument("Gaussian input shape differs");
    Values kernel(17);
    for (int offset = -8; offset <= 8; ++offset)
        kernel[static_cast<std::size_t>(offset + 8)] = std::exp((-.5 / 4.) * (offset * offset));
    const double total = sum(kernel);
    std::array<double, 17> weights;
    for (std::size_t i = 0; i < 17; ++i) weights[i] = kernel[16 - i] / total;
    return correlate(correlate(input, nx, ny, 0, weights), nx, ny, 1, weights);
}
}  // namespace tpmshx::zones
