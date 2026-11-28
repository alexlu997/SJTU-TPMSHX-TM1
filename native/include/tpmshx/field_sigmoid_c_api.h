#pragma once
#include "field_continuous_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif
/* All scalars and arrays use float64. Exponents use std::exp after a [-50,50] clip.
 * Exp flags follow original ufunc-array calls, not individual elements.
 * Counts are exact. Output buffers cannot overlap any input or each other.
 * Failure leaves every output unchanged. Empty point arrays are valid.
 */
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_values_v2(
    const double* values, size_t count, double center, double width,
    double* output, size_t output_count, uint32_t* exp_overflow, size_t exp_count,
    char* error, size_t error_capacity);
/* Layers are packed in C order [layer][point], after Python shape broadcasting. */
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_blend_v2(
    const double* x, size_t count, const double* boundaries, size_t boundary_count,
    const double* layers, size_t layer_value_count, size_t layer_count,
    double width, double* output, size_t output_count,
    uint32_t* exp_overflow, size_t exp_count, char* error, size_t error_capacity);
/* Controls contain three rows of three scalar values. Boundaries contain the
 * six configuration scalars. Exp flags: x1, x2, then y0..y5.
 */
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_sigmoid_field_v2(
    const double* x, const double* y, size_t count,
    const double* inlet, size_t inlet_count, const double* outlet, size_t outlet_count,
    double uniform, const double* boundaries, size_t boundary_count,
    double width_x, double width_y, double* output, size_t output_count,
    uint32_t* exp_overflow, size_t exp_count, char* error, size_t error_capacity);
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_clip_v1(
    const double* values, size_t count, double lower, double upper,
    double* output, size_t output_count, char* error, size_t error_capacity);
#ifdef __cplusplus
}
#endif
