#include "field_sigmoid.hpp"
#include "tpmshx/scalar_precision.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx::fields {
namespace {
namespace g = tpmshx::grid;
namespace precision = tpmshx::geometry::detail;
using Scalar = FieldScalar;
std::size_t product(std::size_t first, std::size_t second) {
    const auto limit = static_cast<std::size_t>(std::numeric_limits<std::ptrdiff_t>::max()) / sizeof(double);
    if (second && first > limit / second) throw std::invalid_argument("sigmoid extent is too large");
    return first * second;
}
void buffer(const void* values, std::size_t count) {
    product(count, 1);
    if (count && !values) throw std::invalid_argument("nonempty sigmoid buffer is null");
}
Scalar kind(Scalar first, Scalar second) {
    return {0., g::result_precision(first, second), first.strong || second.strong ? 1u : 0u};
}
Scalar point(double value, Scalar type) { type.value = value; return g::checked(type); }
Scalar array_point(double value, Scalar type) {
    return {precision::round_scalar(value, type.precision), type.precision, 1};
}
Scalar sigmoid_kind(Scalar x, Scalar center, Scalar width) {
    auto output = kind(kind(x, center), width);
    output.strong = 1;
    return output;
}
Scalar sigmoid(Scalar x, Scalar center, Scalar width, std::uint32_t& overflow) {
    auto exponent = g::subtract(x, center);
    exponent.value = -exponent.value;
    exponent = g::divide(exponent, width);
    if (exponent.value < -50.) exponent.value = -50.;
    if (exponent.value > 50.) exponent.value = 50.;
    exponent.strong = 1;
    const double value = exponent.precision == 64 ? std::exp(exponent.value)
        : static_cast<double>(std::exp(static_cast<float>(exponent.value)));
    const auto exponential = array_point(value, exponent);
    if (std::isfinite(exponent.value) && std::isinf(exponential.value)) overflow = 1;
    return g::divide(g::weak(1.), g::add(g::weak(1.), exponential));
}
Scalar xblend_kind(Scalar coordinate, const Scalar* row, Scalar alpha) {
    auto value = Scalar{0., coordinate.precision, 1};
    value = kind(value, kind(kind(row[1], value), alpha));
    return kind(value, kind(kind(row[2], value), alpha));
}
Scalar xblend(Scalar coordinate, const Scalar* row, Scalar first, Scalar second) {
    auto value = array_point(row[0].value, coordinate);
    value = g::add(value, g::multiply(g::subtract(row[1], value), first));
    return g::add(value, g::multiply(g::subtract(row[2], value), second));
}
}  // namespace

SigmoidResult sigmoid_values(const double* values, std::size_t count,
    FieldScalar type, FieldScalar center, FieldScalar width) {
    buffer(values, count);
    type = g::checked(type); center = g::checked(center); width = g::checked(width);
    SigmoidResult result{std::vector<double>(count), sigmoid_kind(type, center, width).precision, {0}};
    for (std::size_t i = 0; i < count; ++i)
        result.values[i] = sigmoid(point(values[i], type), center, width, result.exp_overflow[0]).value;
    return result;
}

SigmoidResult sigmoid_blend(const double* x, std::size_t count, FieldScalar x_kind,
    const FieldScalar* boundaries, std::size_t boundary_count, const double* layers,
    const FieldScalar* layer_kinds, std::size_t layer_count, FieldScalar width) {
    if (!layer_count || boundary_count != layer_count - 1)
        throw std::invalid_argument("incorrect sigmoid layer count");
    buffer(x, boundary_count ? count : 0); buffer(layers, product(layer_count, count));
    buffer(boundaries, boundary_count); buffer(layer_kinds, layer_count);
    x_kind = g::checked(x_kind); width = g::checked(width);
    auto output_kind = g::checked(layer_kinds[0]);
    for (std::size_t i = 0; i < boundary_count; ++i) {
        const auto alpha = sigmoid_kind(x_kind, g::checked(boundaries[i]), width);
        output_kind = kind(kind(output_kind, alpha), kind(g::checked(layer_kinds[i + 1]), alpha));
    }
    SigmoidResult result{std::vector<double>(count), output_kind.precision,
                          std::vector<std::uint32_t>(boundary_count, 0)};
    for (std::size_t p = 0; p < count; ++p) {
        auto value = point(layers[p], layer_kinds[0]);
        for (std::size_t i = 0; i < boundary_count; ++i) {
            const auto alpha = sigmoid(point(x[p], x_kind), g::checked(boundaries[i]), width, result.exp_overflow[i]);
            value = g::add(g::multiply(value, g::subtract(g::weak(1.), alpha)),
                          g::multiply(point(layers[(i + 1) * count + p], layer_kinds[i + 1]), alpha));
        }
        result.values[p] = value.value;
    }
    return result;
}

SigmoidResult sigmoid_field(const double* x, const double* y, std::size_t count,
    FieldScalar x_kind, FieldScalar y_kind, const std::array<FieldScalar, 9>& inlet,
    const std::array<FieldScalar, 9>& outlet, FieldScalar uniform,
    const std::array<FieldScalar, 6>& boundaries, FieldScalar width_x, FieldScalar width_y) {
    buffer(x, count); buffer(y, count);
    x_kind = g::checked(x_kind); y_kind = g::checked(y_kind);
    width_x = g::checked(width_x); width_y = g::checked(width_y);
    const auto alpha_x = sigmoid_kind(x_kind, g::weak(1. / 3.), width_x);
    std::array<Scalar, 7> layer_types{
        xblend_kind(x_kind, inlet.data(), alpha_x), xblend_kind(x_kind, inlet.data() + 3, alpha_x),
        xblend_kind(x_kind, inlet.data() + 6, alpha_x), Scalar{0., x_kind.precision, 1},
        xblend_kind(x_kind, outlet.data(), alpha_x), xblend_kind(x_kind, outlet.data() + 3, alpha_x),
        xblend_kind(x_kind, outlet.data() + 6, alpha_x)};
    auto output_kind = layer_types[0];
    for (std::size_t i = 0; i < 6; ++i) {
        const auto alpha = sigmoid_kind(y_kind, g::checked(boundaries[i]), width_y);
        output_kind = kind(kind(output_kind, alpha), kind(layer_types[i + 1], alpha));
    }
    SigmoidResult result{std::vector<double>(count), output_kind.precision, std::vector<std::uint32_t>(8, 0)};
    for (std::size_t p = 0; p < count; ++p) {
        const auto px = point(x[p], x_kind), py = point(y[p], y_kind);
        const auto first = sigmoid(px, g::weak(1. / 3.), width_x, result.exp_overflow[0]);
        const auto second = sigmoid(px, g::weak(2. / 3.), width_x, result.exp_overflow[1]);
        const std::array<Scalar, 7> layers{
            xblend(px, inlet.data(), first, second), xblend(px, inlet.data() + 3, first, second),
            xblend(px, inlet.data() + 6, first, second), array_point(uniform.value, px),
            xblend(px, outlet.data(), first, second), xblend(px, outlet.data() + 3, first, second),
            xblend(px, outlet.data() + 6, first, second)};
        auto value = layers[0];
        for (std::size_t i = 0; i < 6; ++i) {
            const auto alpha = sigmoid(py, g::checked(boundaries[i]), width_y, result.exp_overflow[i + 2]);
            value = g::add(g::multiply(value, g::subtract(g::weak(1.), alpha)), g::multiply(layers[i + 1], alpha));
        }
        result.values[p] = value.value;
    }
    return result;
}
}  // namespace tpmshx::fields

namespace tpmshx::fields {
SigmoidResult clip_values(const double* values, std::size_t count,
    FieldScalar type, FieldScalar lower, FieldScalar upper) {
    buffer(values, count);
    type = g::checked(type); lower = g::checked(lower); upper = g::checked(upper);
    auto output_kind = kind(kind(type, lower), upper);
    output_kind.strong = 1;
    const auto low = array_point(lower.value, output_kind);
    const auto high = array_point(upper.value, output_kind);
    SigmoidResult result{std::vector<double>(count), output_kind.precision, {}};
    for (std::size_t p = 0; p < count; ++p) {
        auto value = array_point(values[p], output_kind);
        if (std::isnan(low.value)) value = low;
        if (std::isnan(high.value)) value = high;
        if (!std::isnan(value.value)) {
            if (value.value < low.value) value = low;
            if (value.value > high.value || low.value > high.value) value = high;
        }
        result.values[p] = value.value;
    }
    return result;
}
}  // namespace tpmshx::fields
