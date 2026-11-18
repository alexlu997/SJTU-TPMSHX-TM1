#ifndef TPMSHX_RESULT_CHECKS_C_API_H
#define TPMSHX_RESULT_CHECKS_C_API_H

#include "tpmshx/result_c_api.h"

typedef struct {
    double minimum, maximum;
    size_t minimum_index, maximum_index, low, high, size, nonfinite;
    uint32_t have_finite;
} tpmshx_result_range_sample_v1;
typedef struct {
    size_t indices[8], count;
} tpmshx_result_scalar_sample_indices_v1;
typedef struct {
    double lower, upper, allowance_fraction;
    uint32_t positive;
} tpmshx_result_source_bounds_values_v1;
enum tpmshx_result_range_case_v1 {
    TPMSHX_RESULT_WITHIN_ORIGINAL = 1, TPMSHX_RESULT_DOMAIN_RULE_REQUIRED = 2,
    TPMSHX_RESULT_WITHIN_MARGIN = 3, TPMSHX_RESULT_OUTSIDE_LIMIT = 4
};
typedef struct {
    double relative_extrapolation;
    uint32_t numerical_case, relative_present;
} tpmshx_result_range_decision_v1;
typedef struct {
    uint32_t all_finite, all_zero;
} tpmshx_result_array_check_values_v1;
typedef struct {
    uint32_t strict[4], source_pass;
    double source_residual, source_normalization, epsilon_ltne;
} tpmshx_result_strict_values_v1;

#ifdef __cplusplus
extern "C" {
#endif

/* All numerical outputs are exact extents. Input arrays borrow storage.
 * The common diagnostic and error buffers follow result_c_api.h.
 */
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_collect_range_v1(
    tpmshx_result_array_v1 values, double lower, double upper,
    tpmshx_result_range_sample_v1* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_scalar_samples_v1(
    tpmshx_result_array_v1 values, double lower, double upper,
    tpmshx_result_scalar_sample_indices_v1* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_parameter_bounds_v1(
    double lower, double upper, double* output, size_t output_count,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_source_bounds_v1(
    double lower, double upper, tpmshx_result_source_bounds_values_v1* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_range_values_v1(
    double lower, double upper, double minimum, double maximum, uint32_t hard_bounds,
    tpmshx_result_range_decision_v1* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_array_checks_v1(
    tpmshx_result_array_v1 values, tpmshx_result_array_check_values_v1* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_strict_certificate_v1(
    uint32_t active_b, const double* ratios, size_t ratios_count, double source_a, double source_b,
    tpmshx_result_strict_values_v1* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_energy_ratio_v1(
    tpmshx_result_scalar_v1 ratio, tpmshx_result_scalar_v1 tolerance, uint32_t* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_pressure_square_v1(
    double inlet, double* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_outlet_pressure_squared_v1(
    double square, double gas_constant, double temperature, double drag, double length,
    double* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_sound_speed_v1(
    double gamma, double gas_constant, double temperature,
    double* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_mach_from_sound_v1(
    double speed, double sound, double* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_field_temperature_floor_v1(
    tpmshx_result_array_v1 temperature, double* output, size_t output_count,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_field_sound_speed_v1(
    tpmshx_result_array_v1 temperature, double gamma, double gas_constant,
    double* output, size_t output_count, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_field_mach_max_v1(
    tpmshx_result_array_v1 speed, tpmshx_result_array_v1 sound,
    double* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_pressure_flags_v1(
    tpmshx_result_scalar_v1 pressure, double floor, double allowance, uint32_t* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_mach_limit_flags_v1(
    tpmshx_result_scalar_v1 mach, tpmshx_result_scalar_v1 limit, uint32_t* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_mach_limit_array_flags_v1(
    tpmshx_result_scalar_v1 mach, tpmshx_result_array_v1 limit, uint32_t* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_box_solid_mass_v1(
    tpmshx_result_scalar_v1 bulk_mass, tpmshx_result_scalar_v1 epsilon, tpmshx_result_scalar_v1* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_box_density_length_v1(
    tpmshx_result_scalar_v1 density, tpmshx_result_scalar_v1 length, tpmshx_result_scalar_v1* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_box_bulk_mass_v1(
    tpmshx_result_scalar_v1 density_length, tpmshx_result_scalar_v1 height,
    tpmshx_result_scalar_v1 depth, tpmshx_result_scalar_v1* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_box_density_length_array_v1(
    tpmshx_result_array_v1 density, tpmshx_result_array_v1 length, const tpmshx_result_array_v1* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_box_bulk_mass_array_v1(
    tpmshx_result_array_v1 density_length, tpmshx_result_array_v1 height, tpmshx_result_array_v1 depth,
    const tpmshx_result_array_v1* output, tpmshx_result_diagnostics_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_box_solid_mass_array_v1(
    tpmshx_result_array_v1 bulk_mass, tpmshx_result_array_v1 epsilon, const tpmshx_result_array_v1* output,
    tpmshx_result_diagnostics_v1*, char*, size_t);

#ifdef __cplusplus
}
#endif
#endif
