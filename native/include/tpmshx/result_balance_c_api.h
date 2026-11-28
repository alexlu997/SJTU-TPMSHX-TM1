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
    const tpmshx_result_array_v2* residual, tpmshx_result_norm_values_v1* output,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_balance_mass_v1(
    const tpmshx_result_array_v2* faces, size_t dimension,
    tpmshx_result_mass_values_v1* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_balance_planes_v1(
    const tpmshx_result_array_v2* planes, size_t plane_count,
    tpmshx_result_plane_values_v1* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_balance_energy_v1(
    const tpmshx_result_energy_phase_v1* phases, size_t phase_count, double reservoir,
    tpmshx_result_energy_values_v1* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);

/* Zone calls retain each original Python float-conversion boundary. Weights
 * are read only when weighted is one. Scalar outputs are binary64 values.
 */
typedef struct {
    size_t cells;
    double mean[3], deviation[3], minimum[2], maximum[2];
} tpmshx_result_zone_temperatures_v1;

/* Temperatures and widths use float64. int32 labels select zones in
 * physical cell order. Empty zones have zero cells. Other labels are ignored.
 * Boundary fractions use the same physical axes as length and height. */
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_temperatures_2d_v1(
    const tpmshx_result_array_v2 widths[2], const tpmshx_result_labels_v1* labels,
    const tpmshx_result_array_v2 temperatures[3], size_t zone_count,
    tpmshx_result_zone_temperatures_v1* output, double length_m, double height_m,
    const double* x_fractions, size_t nx, double* x_positions,
    const double* y_fractions, size_t ny, double* y_positions,
    tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);

TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_mean_v1(
    const tpmshx_result_array_v2* values, const tpmshx_result_array_v2* weights, uint32_t weighted,
    double* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_std_v1(
    const tpmshx_result_array_v2* values, const tpmshx_result_array_v2* weights, uint32_t weighted,
    double* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_minimum_v1(
    const tpmshx_result_array_v2* values, double* output,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_maximum_v1(
    const tpmshx_result_array_v2* values, double* output,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_spread_v1(
    const tpmshx_result_array_v2* values, double* output,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);

/* Outputs have the selected one-dimensional extent. output_count must equal it.
 */
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_power_two_v1(
    const tpmshx_result_array_v2* values, double* output, size_t output_count,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_speed_from_squared_v1(
    const tpmshx_result_array_v2* u_squared, const tpmshx_result_array_v2* v_squared,
    double* output, size_t output_count,
    tpmshx_result_diagnostics_v1* diagnostics, char* error, size_t error_capacity);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_zone_cv_v1(
    double deviation, double mean, double* output, tpmshx_result_diagnostics_v1* diagnostics,
    char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
