#include "field_continuous.hpp"
#include "continuous/xy_fitpack.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <new>
#include <stdexcept>

namespace tpmshx::fields {
std::size_t field_extent(std::size_t first, std::size_t second) {
    const auto limit = static_cast<std::size_t>(std::numeric_limits<std::ptrdiff_t>::max()) / sizeof(double);
    if (!first || !second || first > limit / second)
        throw std::invalid_argument("invalid or excessive field extent");
    return first * second;
}

void sample_axis(const double* axis, std::size_t count) {
    if (!axis || !count) throw std::invalid_argument("missing field sampling axis");
    for (std::size_t i = 0; i < count; ++i)
        if (!std::isfinite(axis[i]) || (i && !(axis[i] > axis[i - 1])))
            throw std::invalid_argument("field sampling axes must be finite and strictly increasing");
}

bool constant_values(const double* values, std::size_t count) {
    if (!values || !count) throw std::invalid_argument("missing field controls");
    return std::all_of(values, values + count, [values](double value) { return value == values[0]; });
}

void clip_field(Values& values, double lower, double upper) {
    if (!std::isfinite(lower) || !std::isfinite(upper) || !(0. < lower && lower <= upper))
        throw std::invalid_argument("field bounds must be finite, positive and ordered");
    for (double& value : values) {
        if (value < lower) value = lower;
        if (value > upper) value = upper;
    }
}

namespace {
void xy_status(int status) {
    if (status == XY_FITPACK_OK) return;
    if (status == XY_FITPACK_INVALID_INPUT) throw std::invalid_argument("invalid XY FITPACK input");
    if (status == XY_FITPACK_ALLOCATION_FAILED) throw std::bad_alloc();
    throw std::runtime_error("XY FITPACK numerical failure");
}
}

struct XYFit::State {
    xy_fitpack_owner* owner = nullptr;
    std::size_t count;
    explicit State(std::size_t value_count) : count(value_count) {}
    ~State() { xy_fitpack_release(owner); }
};

XYFit::XYFit(const double* x, std::size_t nx, const double* y, std::size_t ny,
             const double* values, std::size_t count, int degree_x, int degree_y)
    : state_(std::make_unique<State>(count)) {
    xy_status(xy_fitpack_create(x, nx, y, ny, values, count, degree_x, degree_y, &state_->owner));
}
XYFit::~XYFit() = default;

Values XYFit::sample(const double* current_values, std::size_t current_count,
                     const double* x, std::size_t nx, const double* y, std::size_t ny,
                     double lower, double upper) const {
    const auto count = field_extent(nx, ny);
    if (current_count != state_->count) throw std::invalid_argument("XY control count changed");
    sample_axis(x, nx); sample_axis(y, ny);
    Values result(count);
    if (constant_values(current_values, current_count))
        std::fill(result.begin(), result.end(), current_values[0]);
    else
        xy_status(xy_fitpack_evaluate(state_->owner, x, nx, y, ny, result.data(), result.size()));
    clip_field(result, lower, upper);
    return result;
}
}  // namespace tpmshx::fields
