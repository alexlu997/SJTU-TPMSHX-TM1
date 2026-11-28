#ifndef TPMSHX_PREPARATION_FLOW_C_API_H
#define TPMSHX_PREPARATION_FLOW_C_API_H

#include "tpmshx/preparation_c_api.h"

typedef struct {
    const double* data;
    size_t count;
} tpmshx_preparation_flow_values_v1;

#ifdef __cplusplus
extern "C" {
#endif

/* Values and outputs use float64. A zero scalar divisor returns TPMSHX_PREPARATION_SCALAR_DIVISION.
 * Empty 2D buffers are valid numerical inputs; their zero capacity remains
 * available to the existing application guard.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_capacity_2d_v1(
    tpmshx_preparation_flow_values_v1 epsilon_total, tpmshx_preparation_flow_values_v1 opening,
    tpmshx_preparation_flow_values_v1 geometric, tpmshx_preparation_flow_values_v1 widths,
    double density, double depth,
    double* output, size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_capacity_3d_v1(
    tpmshx_preparation_flow_values_v1 epsilon_side, const size_t* shape, size_t shape_count,
    int32_t direction, tpmshx_preparation_flow_values_v1 widths1,
    tpmshx_preparation_flow_values_v1 widths2, tpmshx_preparation_flow_values_v1 opening,
    double density, double* output,
    size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_speeds_v1(
    const double* targets, const double* capacities, size_t count,
    double* output, size_t output_count, char* error, size_t error_capacity);
/* Sections are area_A, length_A, area_B, length_B. Flow is mass_flux, pore_speed;
 * pore_speed is unused and zero for air, which does not divide by density.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_quick_design_sections_v1(
    double epsilon_side, double width,
    double length, double height, uint32_t cross,
    double* output, size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_quick_design_flow_v1(
    double mass_flow, double area,
    double density, uint32_t air,
    double* output, size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_relative_pressure_v1(
    double pressure_drop, double inlet_pressure,
    double* output, size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_design_temperature_target_v1(
    double temperature, uint32_t has_delta, double delta,
    double duty, double mass_flow, double heat_capacity,
    double* output, size_t output_count, char* error, size_t error_capacity);
/* The proxy outputs score, target_required. The second value preserves the
 * original lazy property query at a zero or nonfinite temperature span.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_design_cooling_proxy_v1(
    double hot, double cold, double target,
    double mass_flow, double* output,
    size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_design_volume_v1(
    double width, double height, double length,
    double* output, size_t output_count, char* error, size_t error_capacity);
/* Preserve the original (D_h_m * 1000.) / L_mm steps before SI packing. */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_closure_geometry_ratio_v1(
    tpmshx_preparation_flow_values_v1 hydraulic_diameter_m,
    tpmshx_preparation_flow_values_v1 cell_length_mm,
    double* output, size_t output_count, char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
