#ifndef TPMSHX_RESULT_BALANCE_C_API_H
#define TPMSHX_RESULT_BALANCE_C_API_H

#include "result_c_api.h"

typedef struct {
    double signed_sum, l1, cell_max;
    size_t cell_count;
} tpmshx_result_norm_values_v1;

typedef struct {
    tpmshx_result_norm_values_v1 residual;
    double inflow, outflow, scale, relative_net, relative_l1;
    double boundary_out[6], telescoping_error;
    uint32_t has_scale, reserved;
} tpmshx_result_mass_values_v1;

typedef struct {
    double values[6], total;
} tpmshx_result_plane_values_v1;

typedef struct {
    tpmshx_result_norm_values_v1 residual;
    double source_integral, advective_out_sum, diffusive_out_sum;
} tpmshx_result_energy_phase_v1;

typedef struct {
    double boundary_out, source_integral, prescribed_b_power;
    double net_external_in, residual_sum, telescoping_error;
    double scale, relative_external_imbalance;
    double l1_relative[3], cell_max_relative[3];
} tpmshx_result_energy_values_v1;

#ifdef __cplusplus
extern "C" {
#endif

TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_balance_norms_v1(
    const tpmshx_result_array_v1* residual, tpmshx_result_norm_values_v1* output,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_balance_mass_v1(
    const tpmshx_result_array_v1* faces, size_t dimension,
    tpmshx_result_mass_values_v1* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_balance_planes_v1(
    const tpmshx_result_array_v1* planes, size_t plane_count,
    tpmshx_result_plane_values_v1* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_balance_energy_v1(
    const tpmshx_result_energy_phase_v1* phases, size_t phase_count, double reservoir,
    tpmshx_result_energy_values_v1* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);

/* Zone calls retain each original Python float-conversion boundary. Weights
 * are read only when weighted is one. All scalar outputs retain their dtype.
 * square_fused selects separate (0) or fused (1) complex array products.
 */
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_mean_v1(
    const tpmshx_result_array_v1* values, const tpmshx_result_array_v1* weights, uint32_t weighted,
    tpmshx_result_scalar_v1* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_std_v1(
    const tpmshx_result_array_v1* values, const tpmshx_result_array_v1* weights, uint32_t weighted,
    uint32_t square_fused, tpmshx_result_scalar_v1* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_minimum_v1(
    const tpmshx_result_array_v1* values, tpmshx_result_scalar_v1* output,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_maximum_v1(
    const tpmshx_result_array_v1* values, tpmshx_result_scalar_v1* output,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_spread_v1(
    const tpmshx_result_array_v1* values, tpmshx_result_scalar_v1* output,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);

/* Speed has the selected one-dimensional extent. The byte buffer has the
 * exact result dtype size; output_type identifies that native dtype.
 */
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_power_two_v1(
    const tpmshx_result_array_v1* values, uint32_t square_fused, unsigned char* output, size_t output_capacity,
    tpmshx_result_scalar_v1* output_type, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_speed_from_squared_v1(
    const tpmshx_result_array_v1* u_squared, const tpmshx_result_array_v1* v_squared,
    unsigned char* output, size_t output_capacity, tpmshx_result_scalar_v1* output_type,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_cv_v1(
    double deviation, double mean, double* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
