#include "tpmshx/field_lut_c_api.h"
#include "field_lut.hpp"
#include "field_c_boundary.hpp"
#include <algorithm>
#include <stdexcept>

namespace {
using tpmshx::fields::c_api::boundary;
using tpmshx::fields::c_api::product;
using tpmshx::fields::c_api::require_buffer;
using tpmshx::fields::c_api::require_output;
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_lut_validate_v1(
    const double* x, size_t nx, const double* y, size_t ny, char* error, size_t size) {
    return boundary(error, size, [&] {
        require_buffer(x, nx);
        require_buffer(y, ny);
        tpmshx::fields::validate_lut_axes(x, nx, y, ny);
    });
}
extern "C" int TPMSHX_FIELD_CALL tpmshx_field_lut_query_v1(
    const double* axis_x, size_t nx, const double* axis_y, size_t ny,
    const double* epsilon, const double* area, size_t table_count,
    uint32_t epsilon_fast, uint32_t area_fast,
    const double* x, const double* y, size_t count,
    double* epsilon_output, double* area_output, size_t output_count, char* error, size_t size) {
    return boundary(error, size, [&] {
        if (table_count != product(nx, ny))
            throw std::invalid_argument("incorrect LUT table extent");
        require_buffer(axis_x, nx);
        require_buffer(axis_y, ny);
        require_buffer(epsilon, table_count);
        require_buffer(area, table_count);
        require_buffer(x, count);
        require_buffer(y, count);
        require_output(epsilon_output, output_count, count);
        require_output(area_output, output_count, count);
        const tpmshx::fields::LUTView view{axis_x, axis_y, epsilon, area, nx, ny,
                                         table_count, epsilon_fast, area_fast};
        const auto result = tpmshx::fields::sample_lut(view, x, y, count);
        if (result[0].size() != count || result[1].size() != count)
            throw std::runtime_error("native LUT result extent is incorrect");
        if (count) {
            std::copy(result[0].begin(), result[0].end(), epsilon_output);
            std::copy(result[1].begin(), result[1].end(), area_output);
        }
    });
}
