#include "tpmshx/field_continuous_c_api.h"
#include "field_continuous.hpp"
#include "field_c_boundary.hpp"
#include <algorithm>
#include <cstdint>
#include <limits>
#include <memory>

struct tpmshx_field_xy_v1 {
    tpmshx::fields::XYFit fit;
    tpmshx_field_xy_v1(const double* x, size_t nx, const double* y, size_t ny,
                      const double* values, size_t count, int kx, int ky)
        : fit(x, nx, y, ny, values, count, kx, ky) {}
};
namespace {
using tpmshx::fields::c_api::boundary;
using tpmshx::fields::c_api::require_buffer;
using tpmshx::fields::c_api::require_output;
}

extern "C" uint32_t TPMSHX_FIELD_CALL tpmshx_field_abi_version_v1(void) { return 1; }
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_xy_create_v1(
    const double* x, size_t nx, const double* y, size_t ny, const double* values,
    size_t count, int kx, int ky, tpmshx_field_xy_v1** output, char* error, size_t size) {
    return boundary(error, size, [&] {
        require_buffer(output, 1);
        const auto required = tpmshx::fields::field_extent(nx, ny);
        if (count != required) throw std::invalid_argument("incorrect XY field control extent");
        require_buffer(x, nx);
        require_buffer(y, ny);
        require_buffer(values, count);
        auto owner = std::make_unique<tpmshx_field_xy_v1>(x, nx, y, ny, values, count, kx, ky);
        *output = owner.release();
    });
}
extern "C" void TPMSHX_FIELD_CALL tpmshx_field_xy_release_v1(tpmshx_field_xy_v1* owner) {
    if (!owner) return;
    const auto address = reinterpret_cast<std::uintptr_t>(owner);
    if (address % alignof(tpmshx_field_xy_v1)
        || sizeof(tpmshx_field_xy_v1) - 1 > std::numeric_limits<std::uintptr_t>::max() - address)
        return;
    delete owner;
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_xy_sample_v1(
    const tpmshx_field_xy_v1* owner, const double* values, size_t value_count,
    const double* x, size_t nx, const double* y, size_t ny, double lower, double upper,
    double* output, size_t output_count, char* error, size_t size) {
    return boundary(error, size, [&] {
        require_buffer(owner, 1);
        const auto required = tpmshx::fields::field_extent(nx, ny);
        require_output(output, output_count, required);
        require_buffer(values, value_count);
        require_buffer(x, nx);
        require_buffer(y, ny);
        const auto result = owner->fit.sample(values, value_count, x, nx, y, ny, lower, upper);
        if (result.size() != output_count)
            throw std::runtime_error("native XY field result extent is incorrect");
        std::copy(result.begin(), result.end(), output);
    });
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_tensor_sample_v1(
    size_t dimension, const size_t* counts, const double* const* axes,
    const double* values, size_t value_count, int order, const size_t* samples,
    const double* const* points, double lower, double upper,
    double* output, size_t output_count, char* error, size_t size) {
    return boundary(error, size, [&] {
        if (dimension != 2 && dimension != 3)
            throw std::invalid_argument("invalid tensor field dimension");
        require_buffer(counts, dimension);
        require_buffer(samples, dimension);
        require_buffer(axes, dimension);
        require_buffer(points, dimension);
        size_t controls_required = 1, samples_required = 1;
        for (size_t axis = 0; axis < dimension; ++axis) {
            controls_required = tpmshx::fields::field_extent(controls_required, counts[axis]);
            samples_required = tpmshx::fields::field_extent(samples_required, samples[axis]);
        }
        if (value_count != controls_required)
            throw std::invalid_argument("incorrect tensor field control extent");
        require_buffer(values, value_count);
        require_output(output, output_count, samples_required);
        for (size_t axis = 0; axis < dimension; ++axis) {
            require_buffer(axes[axis], counts[axis]);
            require_buffer(points[axis], samples[axis]);
        }
        const auto result = tpmshx::fields::sample_tensor(dimension, counts, axes, values, value_count,
            order, samples, points, lower, upper);
        if (result.size() != output_count)
            throw std::runtime_error("native tensor field result extent is incorrect");
        std::copy(result.begin(), result.end(), output);
    });
}
