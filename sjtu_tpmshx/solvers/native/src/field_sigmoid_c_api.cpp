#include "tpmshx/field_sigmoid_c_api.h"
#include "field_sigmoid.hpp"
#include "field_c_boundary.hpp"
#include <algorithm>
#include <array>
#include <stdexcept>
#include <vector>

namespace {
namespace f = tpmshx::fields;
namespace g = tpmshx::grid;
using CScalar = tpmshx_grid_scalar_v1;
using f::c_api::boundary;
using f::c_api::product;
using f::c_api::require_buffer;
using f::c_api::require_output;
g::Scalar scalar(CScalar value) { return g::checked({value.value, value.precision, value.strong}); }
std::vector<g::Scalar> scalars(const CScalar* values, size_t count) {
    std::vector<g::Scalar> result;
    result.reserve(count);
    for (size_t i = 0; i < count; ++i) result.push_back(scalar(values[i]));
    return result;
}
void outputs(size_t count, size_t output_count, double* output, uint32_t* precision,
             size_t flags, size_t flag_count, uint32_t* overflow) {
    require_output(output, output_count, count);
    require_buffer(precision, 1);
    require_output(overflow, flag_count, flags);
}
void publish(const f::SigmoidResult& value, size_t count, size_t flags,
             double* output, uint32_t* precision, uint32_t* overflow) {
    if (value.values.size() != count || value.exp_overflow.size() != flags)
        throw std::runtime_error("native sigmoid result extent is incorrect");
    if (!value.values.empty()) std::copy(value.values.begin(), value.values.end(), output);
    if (!value.exp_overflow.empty()) std::copy(value.exp_overflow.begin(), value.exp_overflow.end(), overflow);
    *precision = value.precision;
}
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_values_v1(
    const double* values, size_t count, CScalar kind, CScalar center, CScalar width,
    double* output, size_t output_count, uint32_t* precision,
    uint32_t* exp_overflow, size_t exp_count, char* error, size_t size) {
    return boundary(error, size, [&] {
        require_buffer(values, count);
        outputs(count, output_count, output, precision, 1, exp_count, exp_overflow);
        const auto result = f::sigmoid_values(values, count, scalar(kind), scalar(center), scalar(width));
        publish(result, count, 1, output, precision, exp_overflow);
    });
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_blend_v1(
    const double* x, size_t count, CScalar x_kind, const CScalar* boundaries, size_t boundary_count,
    const double* layers, size_t layer_value_count, const CScalar* layer_kinds, size_t layer_count,
    CScalar width, double* output, size_t output_count, uint32_t* precision,
    uint32_t* exp_overflow, size_t exp_count, char* error, size_t size) {
    return boundary(error, size, [&] {
        if (!layer_count || boundary_count != layer_count - 1)
            throw std::invalid_argument("incorrect sigmoid layer count");
        outputs(count, output_count, output, precision, boundary_count, exp_count, exp_overflow);
        if (layer_value_count != product(count, layer_count))
            throw std::invalid_argument("incorrect sigmoid layer buffer");
        require_buffer(x, boundary_count ? count : 0);
        require_buffer(layers, layer_value_count);
        require_buffer(boundaries, boundary_count);
        require_buffer(layer_kinds, layer_count);
        const auto bounds = scalars(boundaries, boundary_count), kinds = scalars(layer_kinds, layer_count);
        const auto result = f::sigmoid_blend(x, count, scalar(x_kind), bounds.data(), bounds.size(),
                                            layers, kinds.data(), kinds.size(), scalar(width));
        publish(result, count, boundary_count, output, precision, exp_overflow);
    });
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_field_v1(
    const double* x, const double* y, size_t count, CScalar x_kind, CScalar y_kind,
    const CScalar* inlet, size_t inlet_count, const CScalar* outlet, size_t outlet_count,
    CScalar uniform, const CScalar* boundaries, size_t boundary_count, CScalar width_x, CScalar width_y,
    double* output, size_t output_count, uint32_t* precision,
    uint32_t* exp_overflow, size_t exp_count, char* error, size_t size) {
    return boundary(error, size, [&] {
        outputs(count, output_count, output, precision, 8, exp_count, exp_overflow);
        if (inlet_count != 9 || outlet_count != 9 || boundary_count != 6)
            throw std::invalid_argument("incorrect sigmoid control counts");
        require_buffer(x, count);
        require_buffer(y, count);
        require_buffer(inlet, inlet_count);
        require_buffer(outlet, outlet_count);
        require_buffer(boundaries, boundary_count);
        const auto a = scalars(inlet, inlet_count), b = scalars(outlet, outlet_count), c = scalars(boundaries, boundary_count);
        std::array<g::Scalar, 9> input{}, output_values{};
        std::array<g::Scalar, 6> bounds{};
        std::copy(a.begin(), a.end(), input.begin());
        std::copy(b.begin(), b.end(), output_values.begin());
        std::copy(c.begin(), c.end(), bounds.begin());
        const auto result = f::sigmoid_field(x, y, count, scalar(x_kind), scalar(y_kind), input, output_values,
                                            scalar(uniform), bounds, scalar(width_x), scalar(width_y));
        publish(result, count, 8, output, precision, exp_overflow);
    });
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_clip_v1(
    const double* values, size_t count, CScalar kind, CScalar lower, CScalar upper,
    double* output, size_t output_count, uint32_t* precision, char* error, size_t size) {
    return boundary(error, size, [&] {
        require_buffer(values, count);
        outputs(count, output_count, output, precision, 0, 0, nullptr);
        const auto result = f::clip_values(values, count, scalar(kind), scalar(lower), scalar(upper));
        publish(result, count, 0, output, precision, nullptr);
    });
}
