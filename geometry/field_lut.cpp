/* Linear LUT arithmetic follows SciPy v1.18.1 _rgi.py/_rgi_cython.pyx.
 * Copyright (c) 2001-2002 Enthought, Inc. 2003, SciPy Developers.
 * All rights reserved. See ../licenses/scipy-LICENSE.txt.
 * Source details are in ../geometry/fields-sources.md.
 */
#include "field_lut.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx::fields {
namespace {
std::size_t product(std::size_t first, std::size_t second) {
    const auto limit = static_cast<std::size_t>(std::numeric_limits<std::ptrdiff_t>::max()) / sizeof(double);
    if (second && first > limit / second) throw std::invalid_argument("LUT extent is too large");
    return first * second;
}
void buffer(const double* values, std::size_t count) {
    product(count, 1);
    if (count && !values) throw std::invalid_argument("nonempty LUT buffer is null");
}
void ascending(const double* axis, std::size_t count) {
    buffer(axis, count);
    for (std::size_t i = 0; i < count; ++i)
        if (!std::isfinite(axis[i]) || (i && !(axis[i] > axis[i - 1])))
            throw std::invalid_argument("normalized LUT axes must increase strictly");
}
struct Location { std::size_t lo, hi; double distance; };
Location locate(const double* axis, std::size_t count, double point) {
    if (count == 1) return {0, 0, 0.};
    std::size_t lo;
    if (point < axis[0]) lo = 0;
    else if (point >= axis[count - 1]) lo = count - 2;
    else lo = static_cast<std::size_t>(std::upper_bound(axis, axis + count, point) - axis - 1);
    return {lo, lo + 1, (point - axis[lo]) / (axis[lo + 1] - axis[lo])};
}
double interpolate(const double* values, std::size_t nx, std::size_t ny,
                   Location x, Location y, std::uint32_t fast) {
    const double a = 1. - x.distance, b = 1. - y.distance;
    if (fast) {
        if (nx == 1 && ny == 1) return values[0];
        if (ny == 1) return values[x.lo] * a + values[x.hi] * x.distance;
        if (nx == 1) return values[y.lo] * b + values[y.hi] * y.distance;
        double result = 0.;
        result = result + values[x.lo * ny + y.lo] * a * b;
        result = result + values[x.lo * ny + y.hi] * a * y.distance;
        result = result + values[x.hi * ny + y.lo] * x.distance * b;
        result = result + values[x.hi * ny + y.hi] * x.distance * y.distance;
        return result;
    }
    double result = 0.;
    const std::array<std::size_t, 2> ix{x.lo, x.hi}, iy{y.lo, y.hi};
    const std::array<double, 2> wx{a, x.distance}, wy{b, y.distance};
    for (std::size_t i = 0; i < 2; ++i)
        for (std::size_t j = 0; j < 2; ++j) {
            double weight = 1.;
            weight = weight * wx[i];
            weight = weight * wy[j];
            const double term = values[ix[i] * ny + iy[j]] * weight;
            result = result + term;
        }
    return result;
}
}  // namespace

void validate_lut_axes(const double* x, std::size_t nx, const double* y, std::size_t ny) {
    product(nx, ny);
    ascending(x, nx); ascending(y, ny);
}
std::array<std::vector<double>, 2> sample_lut(const LUTView& view,
    const double* x, const double* y, std::size_t count) {
    if (view.table_count != product(view.nx, view.ny) || view.epsilon_fast > 1 || view.area_fast > 1)
        throw std::invalid_argument("incorrect LUT extent or path");
    buffer(view.x, view.nx); buffer(view.y, view.ny);
    buffer(view.epsilon, view.table_count); buffer(view.area, view.table_count);
    buffer(x, count); buffer(y, count);
    std::array<std::vector<double>, 2> result{std::vector<double>(count), std::vector<double>(count)};
    if (!count) return result;
    if (!view.nx || !view.ny) throw std::invalid_argument("cannot query an empty LUT axis");
    // The captured arrays can change in place. Do not reject new table NaNs.
    for (std::size_t i = 0; i < count; ++i) {
        if (std::isnan(x[i]) || std::isnan(y[i])) {
            result[0][i] = result[1][i] = std::numeric_limits<double>::quiet_NaN();
        } else {
            const auto ix = locate(view.x, view.nx, x[i]), iy = locate(view.y, view.ny, y[i]);
            result[0][i] = interpolate(view.epsilon, view.nx, view.ny, ix, iy, view.epsilon_fast);
            result[1][i] = interpolate(view.area, view.nx, view.ny, ix, iy, view.area_fast);
        }
    }
    return result;
}
}  // namespace tpmshx::fields
