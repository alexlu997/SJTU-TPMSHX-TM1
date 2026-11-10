#ifndef TPMSHX_ZONES_C_API_H
#define TPMSHX_ZONES_C_API_H
#include "tpmshx/grid_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif

/* Rows have four typed bounds. Stripe rows use the first two.
 * Kinds: 0=stripe, 1=first rectangle, 2=last rectangle.
 * Stripe rows arrive in configuration order. Output is C-order int32.
 * Absent widths use NULL and count zero. Other lengths are exact.
 * The geometry buffer, error and unchanged-output rules apply.
 */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_zone_ids_v1(
    uint32_t kind, size_t nx, size_t ny, int axis, tpmshx_grid_scalar_v1 domain,
    const tpmshx_grid_scalar_v1* rows, size_t row_count,
    const double* dx, size_t dx_count, const double* dy, size_t dy_count,
    int32_t* output, size_t output_count, char* error, size_t error_capacity);
/* Fixed sigma2/order0/radius8/reflect. Axis 0 is filtered before axis 1. */
TPMSHX_GEOMETRY_API int TPMSHX_GEOMETRY_CALL tpmshx_geometry_zone_gaussian_v1(
    size_t nx, size_t ny, const double* input, size_t input_count,
    double* output, size_t output_count, char* error, size_t error_capacity);
#ifdef __cplusplus
}
#endif
#endif
