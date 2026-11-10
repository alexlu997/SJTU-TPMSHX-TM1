/* Basis and band-solve steps follow the fixed SciPy source.
 * Copyright (c) 2001-2002 Enthought, Inc. 2003, SciPy Developers.
 * All rights reserved. See ../../licenses/scipy-LICENSE.txt.
 * Source details are in ../../geometry/fields-sources.md.
 */
#include "../field_continuous.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

namespace tpmshx::fields {
namespace {
size_t extent(size_t a, size_t b) {
    const auto limit = static_cast<size_t>(std::numeric_limits<std::ptrdiff_t>::max()) / sizeof(double);
    if (!a || !b || a > limit / b) throw std::invalid_argument("invalid or excessive extent");
    return a * b;
}

void finite_values(const double *values, size_t count) {
    if (!values || !count) throw std::invalid_argument("missing values");
    for (size_t i = 0; i < count; ++i)
        if (!std::isfinite(values[i])) throw std::invalid_argument("values must be finite");
}

void increasing(const double *axis, size_t count) {
    finite_values(axis, count);
    for (size_t i = 1; i < count; ++i)
        if (!(axis[i] > axis[i - 1])) throw std::invalid_argument("axis must increase strictly");
}

std::vector<double> knots(const double *x, size_t n, int degree) {
    const size_t k = static_cast<size_t>(degree);
    std::vector<double> result;
    result.reserve(n + k + 1);
    result.insert(result.end(), k + 1, x[0]);
    if (degree == 1) {
        for (size_t i = 1; i + 1 < n; ++i) result.push_back(x[i]);
    } else if (degree == 2) {
        for (size_t i = 1; i + 2 < n; ++i) result.push_back((x[i + 1] + x[i]) / 2.0);
    } else {
        for (size_t i = 2; i + 2 < n; ++i) result.push_back(x[i]);
    }
    result.insert(result.end(), k + 1, x[n - 1]);
    finite_values(result.data(), result.size());
    return result;
}

/* SciPy v1.18.1 _find_interval: project samples stay within the domain. */
size_t interval(const std::vector<double>& t, size_t k, double x, size_t previous) {
    const size_t n = t.size() - k - 1;
    size_t left = (k < previous && previous < n) ? previous : k;
    while (x < t[left] && left != k) --left;
    ++left;
    while (x >= t[left] && left != n) ++left;
    return left - 1;
}

/* SciPy v1.18.1 _deBoor_D, restricted to derivative order zero. */
std::array<double, 4> basis(const std::vector<double>& t, size_t k, double x, size_t left) {
    std::array<double, 4> h{}, previous{};
    h[0] = 1.0;
    for (size_t j = 1; j <= k; ++j) {
        std::copy_n(h.begin(), j, previous.begin());
        h[0] = 0.0;
        for (size_t a = 1; a <= j; ++a) {
            const size_t index = left + a;
            const double high = t[index], low = t[index - j];
            if (high == low) {
                h[a] = 0.0;
                continue;
            }
            const double weight = previous[a - 1] / (high - low);
            h[a - 1] += weight * (high - x);
            h[a] = weight * (x - low);
        }
    }
    return h;
}

class Band {
public:
    Band(size_t count, size_t degree) : n(count), k(degree), stride(3 * degree + 1),
        values(extent(count, stride), 0.0) {}

    double& at(size_t row, size_t column) {
        if (row >= n || column >= n || column + k < row || column > row + 2 * k)
            throw std::logic_error("band index outside storage");
        return values[row * stride + column + k - row];
    }

    size_t n, k, stride;
    std::vector<double> values;
};

/* Scalar band elimination. LAPACK/BLAS arithmetic parity is not established. */
void band_solve(Band& matrix, std::vector<double>& rhs, size_t channels) {
    size_t last_upper = 0;
    for (size_t column = 0; column < matrix.n; ++column) {
        const size_t last_row = column + std::min(matrix.k, matrix.n - column - 1);
        size_t pivot = column;
        for (size_t row = column + 1; row <= last_row; ++row)
            if (std::abs(matrix.at(row, column)) > std::abs(matrix.at(pivot, column))) pivot = row;
        if (matrix.at(pivot, column) == 0.0) throw std::runtime_error("collocation matrix is singular");
        last_upper = std::max(last_upper, std::min(matrix.n - 1, pivot + matrix.k));
        if (pivot != column) {
            for (size_t j = column; j <= last_upper; ++j)
                std::swap(matrix.at(pivot, j), matrix.at(column, j));
            for (size_t channel = 0; channel < channels; ++channel)
                std::swap(rhs[pivot * channels + channel], rhs[column * channels + channel]);
        }
        if (last_row == column) continue;
        const double inverse = 1.0 / matrix.at(column, column);
        for (size_t row = column + 1; row <= last_row; ++row) matrix.at(row, column) *= inverse;
        for (size_t j = column + 1; j <= last_upper; ++j) {
            const double negative = -matrix.at(column, j);
            if (negative != 0.0)
                for (size_t row = column + 1; row <= last_row; ++row)
                    matrix.at(row, j) += matrix.at(row, column) * negative;
        }
        for (size_t channel = 0; channel < channels; ++channel) {
            const double negative = -rhs[column * channels + channel];
            if (negative != 0.0)
                for (size_t row = column + 1; row <= last_row; ++row)
                    rhs[row * channels + channel] += matrix.at(row, column) * negative;
        }
    }
    for (size_t channel = 0; channel < channels; ++channel) {
        for (size_t column = matrix.n; column-- > 0;) {
            double& value = rhs[column * channels + channel];
            if (value == 0.0) continue;
            value /= matrix.at(column, column);
            const size_t distance = std::min(2 * matrix.k, column);
            for (size_t step = 1; step <= distance; ++step) {
                const size_t row = column - step;
                rhs[row * channels + channel] -= value * matrix.at(row, column);
            }
        }
    }
}

}  // namespace
struct AxisSpline {
    int degree;
    size_t count, channels;
    std::vector<double> t, coefficients;

    AxisSpline(const double *axis, size_t n, const double *values, size_t value_count,
                     size_t channel_count, int requested_degree)
        : degree(requested_degree), count(n), channels(channel_count) {
        if (degree < 1 || degree > 3 || n <= static_cast<size_t>(degree) ||
            value_count != extent(n, channels) ||
            n > static_cast<size_t>(std::numeric_limits<std::ptrdiff_t>::max()) / sizeof(double) - 4)
            throw std::invalid_argument("invalid fit degree or extent");
        extent(n, 3 * static_cast<size_t>(degree) + 1);
        increasing(axis, n);
        finite_values(values, value_count);
        t = knots(axis, n, degree);
        coefficients.assign(values, values + value_count);
        if (degree == 1) return;
        Band collocation(n, static_cast<size_t>(degree));
        size_t left = static_cast<size_t>(degree);
        for (size_t row = 0; row < n; ++row) {
            left = interval(t, static_cast<size_t>(degree), axis[row], left);
            const auto h = basis(t, static_cast<size_t>(degree), axis[row], left);
            for (size_t a = 0; a <= static_cast<size_t>(degree); ++a)
                collocation.at(row, left - static_cast<size_t>(degree) + a) = h[a];
        }
        finite_values(collocation.values.data(), collocation.values.size());
        band_solve(collocation, coefficients, channels);
    }

    std::vector<double> sample(const double *points, size_t n) const {
        const size_t total = extent(n, channels);
        increasing(points, n);
        const size_t k = static_cast<size_t>(degree);
        if (points[0] < t[k] || points[n - 1] > t[count])
            throw std::invalid_argument("samples are outside the control range");
        std::vector<double> output(total, 0.0);
        size_t left = k;
        for (size_t row = 0; row < n; ++row) {
            left = interval(t, k, points[row], left);
            const auto h = basis(t, k, points[row], left);
            for (size_t channel = 0; channel < channels; ++channel)
                for (size_t a = 0; a <= k; ++a)
                    output[row * channels + channel] += coefficients[(left + a - k) * channels + channel] * h[a];
        }
        return output;
    }
};

Values sample_tensor(std::size_t dimension, const std::size_t* counts,
    const double* const* axes, const double* values, std::size_t value_count,
    int order, const std::size_t* samples, const double* const* points,
    double lower, double upper) {
    if ((dimension != 2 && dimension != 3) || !counts || !axes || !values ||
        !samples || !points || order < 1 || order > 3)
        throw std::invalid_argument("invalid tensor field input");
    if (dimension == 2 && counts[0] > 1 && counts[1] > 1)
        throw std::invalid_argument("nondegenerate XY requires FITPACK");
    std::size_t controls_total = 1, samples_total = 1;
    for (std::size_t axis = 0; axis < dimension; ++axis) {
        controls_total = extent(controls_total, counts[axis]);
        samples_total = extent(samples_total, samples[axis]);
        if (!axes[axis]) throw std::invalid_argument("missing tensor control axis");
        sample_axis(points[axis], samples[axis]);
    }
    if (controls_total != value_count) throw std::invalid_argument("incorrect tensor control extent");
    Values result;
    if (constant_values(values, value_count)) {
        result.assign(samples_total, values[0]);
    } else {
        std::vector<std::size_t> shape(counts, counts + dimension);
        result.assign(values, values + value_count);
        for (std::size_t axis = 0; axis < dimension; ++axis) {
            std::size_t outer = 1, inner = 1;
            for (std::size_t a = 0; a < axis; ++a) outer = extent(outer, shape[a]);
            for (std::size_t a = axis + 1; a < dimension; ++a) inner = extent(inner, shape[a]);
            const auto n = counts[axis], p = samples[axis];
            const auto channels = extent(outer, inner);
            Values next(extent(p, channels));
            if (n == 1) {
                for (std::size_t o = 0; o < outer; ++o)
                    for (std::size_t q = 0; q < p; ++q)
                        for (std::size_t r = 0; r < inner; ++r)
                            next[(o * p + q) * inner + r] = result[o * inner + r];
            } else {
                Values packed(extent(n, channels));
                for (std::size_t i = 0; i < n; ++i)
                    for (std::size_t o = 0; o < outer; ++o)
                        for (std::size_t r = 0; r < inner; ++r)
                            packed[i * channels + o * inner + r] = result[(o * n + i) * inner + r];
                const int degree = static_cast<int>(std::min(static_cast<std::size_t>(order), n - 1));
                const AxisSpline fit(axes[axis], n, packed.data(), packed.size(), channels, degree);
                const auto sampled = fit.sample(points[axis], p);
                for (std::size_t o = 0; o < outer; ++o)
                    for (std::size_t q = 0; q < p; ++q)
                        for (std::size_t r = 0; r < inner; ++r)
                            next[(o * p + q) * inner + r] = sampled[q * channels + o * inner + r];
            }
            result = std::move(next);
            shape[axis] = p;
        }
    }
    clip_field(result, lower, upper);
    return result;
}
}  // namespace tpmshx::fields
