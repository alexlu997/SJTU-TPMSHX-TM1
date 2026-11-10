#pragma once
#include "field_continuous_c_api.h"
#include "tpmshx/grid_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Scalar precision and strong type use the grid contract. Transport buffers use
 * doubles; the core rounds each original operation at its actual precision.
 * Exp flags follow original ufunc-array calls, not individual elements.
 * Counts are exact. Output buffers cannot overlap any input or each other.
 * Failure leaves every output unchanged. Empty point arrays are valid.
 */
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_values_v1(
    const double* values, size_t count, tpmshx_grid_scalar_v1 kind,
    tpmshx_grid_scalar_v1 center, tpmshx_grid_scalar_v1 width,
    double* output, size_t output_count, uint32_t* precision,
    uint32_t* exp_overflow, size_t exp_count, char* error, size_t error_capacity);
/* Layers are packed in C order [layer][point], after Python shape broadcasting.
 * The wrapper retains copy/full_like type selection before buffer conversion.
 */
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_blend_v1(
    const double* x, size_t count, tpmshx_grid_scalar_v1 x_kind,
    const tpmshx_grid_scalar_v1* boundaries, size_t boundary_count,
    const double* layers, size_t layer_value_count,
    const tpmshx_grid_scalar_v1* layer_kinds, size_t layer_count,
    tpmshx_grid_scalar_v1 width, double* output, size_t output_count,
    uint32_t* precision, uint32_t* exp_overflow, size_t exp_count,
    char* error, size_t error_capacity);
/* Controls contain three rows of three scalar values. Boundaries contain the
 * six original Python configuration scalars. Exp flags: x1, x2, then y0..y5.
 */
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_field_v1(
    const double* x, const double* y, size_t count,
    tpmshx_grid_scalar_v1 x_kind, tpmshx_grid_scalar_v1 y_kind,
    const tpmshx_grid_scalar_v1* inlet, size_t inlet_count,
    const tpmshx_grid_scalar_v1* outlet, size_t outlet_count,
    tpmshx_grid_scalar_v1 uniform,
    const tpmshx_grid_scalar_v1* boundaries, size_t boundary_count,
    tpmshx_grid_scalar_v1 width_x, tpmshx_grid_scalar_v1 width_y,
    double* output, size_t output_count, uint32_t* precision,
    uint32_t* exp_overflow, size_t exp_count, char* error, size_t error_capacity);
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_clip_v1(
    const double* values, size_t count, tpmshx_grid_scalar_v1 kind,
    tpmshx_grid_scalar_v1 lower, tpmshx_grid_scalar_v1 upper,
    double* output, size_t output_count, uint32_t* precision,
    char* error, size_t error_capacity);
#ifdef __cplusplus
}
#endif
