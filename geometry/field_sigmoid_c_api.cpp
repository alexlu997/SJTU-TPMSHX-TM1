#include "tpmshx/field_sigmoid_c_api.h"
#include "field_sigmoid.hpp"
#include "field_c_boundary.hpp"
#include <algorithm>
#include <array>
#include <stdexcept>
#include <vector>

namespace {
namespace f = tpmshx::fields;
using f::c_api::boundary;
using f::c_api::product;
using f::c_api::require_buffer;
using f::c_api::require_output;
void outputs(size_t count, size_t output_count, double* output,
             size_t flags, size_t flag_count, uint32_t* overflow) {
    require_output(output, output_count, count);
    require_output(overflow, flag_count, flags);
}
void publish(const f::SigmoidResult& value, size_t count, size_t flags,
             double* output, uint32_t* overflow) {
    if (value.values.size() != count || value.exp_overflow.size() != flags)
        throw std::runtime_error("native sigmoid result extent is incorrect");
    if (!value.values.empty()) std::copy(value.values.begin(), value.values.end(), output);
    if (!value.exp_overflow.empty()) std::copy(value.exp_overflow.begin(), value.exp_overflow.end(), overflow);
}
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_values_v2(
    const double* values, size_t count, double center, double width,
    double* output, size_t output_count, uint32_t* exp_overflow, size_t exp_count,
    char* error, size_t size) {
    return boundary(error, size, [&] {
        require_buffer(values, count);
        outputs(count, output_count, output, 1, exp_count, exp_overflow);
        const auto result = f::sigmoid_values(values, count, center, width);
        publish(result, count, 1, output, exp_overflow);
    });
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_blend_v2(
    const double* x, size_t count, const double* boundaries, size_t boundary_count,
    const double* layers, size_t layer_value_count, size_t layer_count,
    double width, double* output, size_t output_count,
    uint32_t* exp_overflow, size_t exp_count, char* error, size_t size) {
    return boundary(error, size, [&] {
        if (!layer_count || boundary_count != layer_count - 1)
            throw std::invalid_argument("incorrect sigmoid layer count");
        outputs(count, output_count, output, boundary_count, exp_count, exp_overflow);
        if (layer_value_count != product(count, layer_count))
            throw std::invalid_argument("incorrect sigmoid layer buffer");
        require_buffer(x, boundary_count ? count : 0);
        require_buffer(layers, layer_value_count);
        require_buffer(boundaries, boundary_count);
        const auto result = f::sigmoid_blend(x, count, boundaries, boundary_count, layers, layer_count, width);
        publish(result, count, boundary_count, output, exp_overflow);
    });
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_field_v2(
    const double* x, const double* y, size_t count,
    const double* inlet, size_t inlet_count, const double* outlet, size_t outlet_count,
    double uniform, const double* boundaries, size_t boundary_count, double width_x, double width_y,
    double* output, size_t output_count, uint32_t* exp_overflow, size_t exp_count,
    char* error, size_t size) {
    return boundary(error, size, [&] {
        outputs(count, output_count, output, 8, exp_count, exp_overflow);
        if (inlet_count != 9 || outlet_count != 9 || boundary_count != 6)
            throw std::invalid_argument("incorrect sigmoid control counts");
        require_buffer(x, count);
        require_buffer(y, count);
        require_buffer(inlet, inlet_count);
        require_buffer(outlet, outlet_count);
        require_buffer(boundaries, boundary_count);
        std::array<double, 9> input{}, output_values{};
        std::array<double, 6> bounds{};
        std::copy(inlet, inlet + 9, input.begin());
        std::copy(outlet, outlet + 9, output_values.begin());
        std::copy(boundaries, boundaries + 6, bounds.begin());
        const auto result = f::sigmoid_field(x, y, count, input, output_values, uniform, bounds, width_x, width_y);
        publish(result, count, 8, output, exp_overflow);
    });
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_clip_v1(
    const double* values, size_t count, double lower, double upper,
    double* output, size_t output_count, char* error, size_t size) {
    return boundary(error, size, [&] {
        require_buffer(values, count);
        outputs(count, output_count, output, 0, 0, nullptr);
        const auto result = f::clip_values(values, count, lower, upper);
        publish(result, count, 0, output, nullptr);
    });
}
