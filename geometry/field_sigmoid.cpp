#include "field_sigmoid.hpp"
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx::fields {
namespace {
std::size_t product(std::size_t first, std::size_t second) {
    const auto limit = static_cast<std::size_t>(std::numeric_limits<std::ptrdiff_t>::max()) / sizeof(double);
    if (second && first > limit / second) throw std::invalid_argument("sigmoid extent is too large");
    return first * second;
}
void buffer(const void* values, std::size_t count) {
    product(count, 1);
    if (count && !values) throw std::invalid_argument("nonempty sigmoid buffer is null");
}
// Array arithmetic keeps IEEE results; a zero width gives the clipped exponent or NaN.
double sigmoid(double x, double center, double width, std::uint32_t& overflow) {
    double exponent = -(x - center) / width;
    if (exponent < -50.) exponent = -50.;
    if (exponent > 50.) exponent = 50.;
    const double exponential = std::exp(exponent);
    if (std::isfinite(exponent) && std::isinf(exponential)) overflow = 1;
    return 1. / (1. + exponential);
}
double xblend(const double* row, double first, double second) {
    double value = row[0];
    value = value + (row[1] - value) * first;
    return value + (row[2] - value) * second;
}
}  // namespace

SigmoidResult sigmoid_values(const double* values, std::size_t count, double center, double width) {
    buffer(values, count);
    SigmoidResult result{std::vector<double>(count), {0}};
    for (std::size_t i = 0; i < count; ++i)
        result.values[i] = sigmoid(values[i], center, width, result.exp_overflow[0]);
    return result;
}

SigmoidResult sigmoid_blend(const double* x, std::size_t count,
    const double* boundaries, std::size_t boundary_count, const double* layers,
    std::size_t layer_count, double width) {
    if (!layer_count || boundary_count != layer_count - 1)
        throw std::invalid_argument("incorrect sigmoid layer count");
    buffer(x, boundary_count ? count : 0); buffer(layers, product(layer_count, count));
    buffer(boundaries, boundary_count);
    SigmoidResult result{std::vector<double>(count), std::vector<std::uint32_t>(boundary_count, 0)};
    for (std::size_t p = 0; p < count; ++p) {
        double value = layers[p];
        for (std::size_t i = 0; i < boundary_count; ++i) {
            const double alpha = sigmoid(x[p], boundaries[i], width, result.exp_overflow[i]);
            value = value * (1. - alpha) + layers[(i + 1) * count + p] * alpha;
        }
        result.values[p] = value;
    }
    return result;
}

SigmoidResult sigmoid_field(const double* x, const double* y, std::size_t count,
    const std::array<double, 9>& inlet, const std::array<double, 9>& outlet, double uniform,
    const std::array<double, 6>& boundaries, double width_x, double width_y) {
    buffer(x, count); buffer(y, count);
    SigmoidResult result{std::vector<double>(count), std::vector<std::uint32_t>(8, 0)};
    for (std::size_t p = 0; p < count; ++p) {
        const double first = sigmoid(x[p], 1. / 3., width_x, result.exp_overflow[0]);
        const double second = sigmoid(x[p], 2. / 3., width_x, result.exp_overflow[1]);
        const std::array<double, 7> layers{
            xblend(inlet.data(), first, second), xblend(inlet.data() + 3, first, second),
            xblend(inlet.data() + 6, first, second), uniform,
            xblend(outlet.data(), first, second), xblend(outlet.data() + 3, first, second),
            xblend(outlet.data() + 6, first, second)};
        double value = layers[0];
        for (std::size_t i = 0; i < 6; ++i) {
            const double alpha = sigmoid(y[p], boundaries[i], width_y, result.exp_overflow[i + 2]);
            value = value * (1. - alpha) + layers[i + 1] * alpha;
        }
        result.values[p] = value;
    }
    return result;
}

SigmoidResult clip_values(const double* values, std::size_t count, double lower, double upper) {
    buffer(values, count);
    SigmoidResult result{std::vector<double>(count), {}};
    for (std::size_t p = 0; p < count; ++p) {
        // np.clip propagates NaN from the value and from either bound.
        double value = values[p];
        if (std::isnan(lower)) value = lower;
        if (std::isnan(upper)) value = upper;
        if (!std::isnan(value)) {
            if (value < lower) value = lower;
            if (value > upper || lower > upper) value = upper;
        }
        result.values[p] = value;
    }
    return result;
}
}  // namespace tpmshx::fields
