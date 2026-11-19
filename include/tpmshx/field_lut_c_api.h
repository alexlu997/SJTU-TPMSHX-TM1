#pragma once
#include "field_continuous_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif
/* Axes and table states are normalized and retained by the Python DTO.
 * This block borrows their current buffers only during a call. Field ABI status
 * and output/error ownership follow field_continuous_c_api.h.
 * Each table has its own current fast64 flag. No table finite check runs here.
 */
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_lut_validate_v1(
    const double* x, size_t nx, const double* y, size_t ny,
    char* error, size_t error_capacity);
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_lut_query_v1(
    const double* axis_x, size_t nx, const double* axis_y, size_t ny,
    const double* epsilon, const double* area, size_t table_count,
    uint32_t epsilon_fast, uint32_t area_fast,
    const double* x, const double* y, size_t count,
    double* epsilon_output, double* area_output, size_t output_count,
    char* error, size_t error_capacity);
#ifdef __cplusplus
}
#endif
