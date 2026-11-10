#ifndef TPMSHX_PREPARATION_FLOW_C_API_H
#define TPMSHX_PREPARATION_FLOW_C_API_H

#include "tpmshx/preparation_c_api.h"
#include "tpmshx/grid_c_api.h"

typedef struct {
    const double* data;
    size_t count;
    uint32_t precision, strong;
} tpmshx_preparation_flow_values_v1;

#ifdef __cplusplus
extern "C" {
#endif

/* Values use double storage with original real arithmetic tags. Integer tags
 * cover non-overflowing physical inputs, as in the grid arithmetic contract.
 * Outputs keep
 * scalar precision/kind. Empty 2D buffers are valid numerical inputs; their
 * zero capacity remains available to the existing application guard.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_capacity_2d_v1(
    tpmshx_preparation_flow_values_v1 epsilon_total, tpmshx_preparation_flow_values_v1 opening,
    tpmshx_preparation_flow_values_v1 geometric, tpmshx_preparation_flow_values_v1 widths,
    tpmshx_grid_scalar_v1 density, tpmshx_grid_scalar_v1 depth,
    tpmshx_grid_scalar_v1* output, size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_capacity_3d_v1(
    tpmshx_preparation_flow_values_v1 epsilon_side, const size_t* shape, size_t shape_count,
    int32_t direction, tpmshx_preparation_flow_values_v1 widths1,
    tpmshx_preparation_flow_values_v1 widths2, tpmshx_preparation_flow_values_v1 opening,
    tpmshx_grid_scalar_v1 density, tpmshx_grid_scalar_v1* output,
    size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_speeds_v1(
    const tpmshx_grid_scalar_v1* targets, const tpmshx_grid_scalar_v1* capacities, size_t count,
    tpmshx_grid_scalar_v1* output, size_t output_count, char* error, size_t error_capacity);
/* Sections are area_A, length_A, area_B, length_B. Flow is mass_flux, pore_speed;
 * pore_speed is unused and zero for air, which does not divide by density.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_quick_design_sections_v1(
    tpmshx_grid_scalar_v1 epsilon_side, tpmshx_grid_scalar_v1 width,
    tpmshx_grid_scalar_v1 length, tpmshx_grid_scalar_v1 height, uint32_t cross,
    tpmshx_grid_scalar_v1* output, size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_quick_design_flow_v1(
    tpmshx_grid_scalar_v1 mass_flow, tpmshx_grid_scalar_v1 area,
    tpmshx_grid_scalar_v1 density, uint32_t air,
    tpmshx_grid_scalar_v1* output, size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_relative_pressure_v1(
    tpmshx_grid_scalar_v1 pressure_drop, tpmshx_grid_scalar_v1 inlet_pressure,
    tpmshx_grid_scalar_v1* output, size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_design_temperature_target_v1(
    tpmshx_grid_scalar_v1 temperature, uint32_t has_delta, tpmshx_grid_scalar_v1 delta,
    tpmshx_grid_scalar_v1 duty, tpmshx_grid_scalar_v1 mass_flow, tpmshx_grid_scalar_v1 heat_capacity,
    tpmshx_grid_scalar_v1* output, size_t output_count, char* error, size_t error_capacity);
/* The proxy outputs score, target_required. The second value preserves the
 * original lazy property query at a zero or nonfinite temperature span.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_design_cooling_proxy_v1(
    tpmshx_grid_scalar_v1 hot, tpmshx_grid_scalar_v1 cold, tpmshx_grid_scalar_v1 target,
    tpmshx_grid_scalar_v1 mass_flow, tpmshx_grid_scalar_v1* output,
    size_t output_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_design_volume_v1(
    tpmshx_grid_scalar_v1 width, tpmshx_grid_scalar_v1 height, tpmshx_grid_scalar_v1 length,
    tpmshx_grid_scalar_v1* output, size_t output_count, char* error, size_t error_capacity);
/* Preserve the original (D_h_m * 1000.) / L_mm steps before SI packing.
 * Kind describes each output, including an empty output array.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_closure_geometry_ratio_v1(
    tpmshx_preparation_flow_values_v1 hydraulic_diameter_m,
    tpmshx_preparation_flow_values_v1 cell_length_mm,
    double* output, size_t output_count, tpmshx_grid_scalar_v1* kind,
    char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
