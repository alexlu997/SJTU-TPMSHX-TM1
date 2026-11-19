#pragma once
#include <stddef.h>
#include <stdint.h>
#if defined(_WIN32)
#if defined(TPMSHX_FIELD_BUILD_SHARED)
#define TPMSHX_FIELD_API __declspec(dllexport)
#else
#define TPMSHX_FIELD_API
#endif
#define TPMSHX_FIELD_CALL __cdecl
#else
#define TPMSHX_FIELD_API __attribute__((visibility("default")))
#define TPMSHX_FIELD_CALL
#endif
#ifdef __cplusplus
extern "C" {
#endif

typedef struct tpmshx_field_xy_v1 tpmshx_field_xy_v1;
/* Field ABI version is 2. Status: 1 invalid input, 2 allocation, 3 numerical/runtime error.
 * This status 2 differs from geometry ABI status 2. Do not share its mapper.
 * Data is borrowed for the call. Counts are exact. Outputs cannot overlap input.
 * Failure leaves caller outputs unchanged and writes a bounded error string.
 * Release only after the last query; NULL release is valid.
 */
TPMSHX_FIELD_API uint32_t TPMSHX_FIELD_CALL tpmshx_field_abi_version_v1(void);
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_xy_create_v1(
    const double* x, size_t nx, const double* y, size_t ny,
    const double* values, size_t value_count, int degree_x, int degree_y,
    tpmshx_field_xy_v1** output, char* error, size_t error_capacity);
TPMSHX_FIELD_API void TPMSHX_FIELD_CALL tpmshx_field_xy_release_v1(tpmshx_field_xy_v1* owner);
/* Current controls determine the original exact-constant branch. Other XY
 * queries use the fit captured at construction, as RectBivariateSpline did.
 * Bounds are applied once after all interpolation operations.
 */
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_xy_sample_v1(
    const tpmshx_field_xy_v1* owner, const double* current_values, size_t current_count,
    const double* x, size_t nx, const double* y, size_t ny,
    double lower, double upper, double* output, size_t output_count,
    char* error, size_t error_capacity);
/* XYZ and XY singleton axes only. Each axis is fitted and sampled before the
 * next axis. Python retains physical-domain and singleton-midpoint validation;
 * this boundary validates buffers, actual axes and spline constraints.
 */
TPMSHX_FIELD_API int TPMSHX_FIELD_CALL tpmshx_field_tensor_sample_v1(
    size_t dimension, const size_t* control_counts, const double* const* control_axes,
    const double* values, size_t value_count, int order,
    const size_t* sample_counts, const double* const* sample_axes,
    double lower, double upper, double* output, size_t output_count,
    char* error, size_t error_capacity);
#ifdef __cplusplus
}
#endif
