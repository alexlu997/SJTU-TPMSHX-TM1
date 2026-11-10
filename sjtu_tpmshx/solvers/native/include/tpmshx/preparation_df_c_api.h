#ifndef TPMSHX_PREPARATION_DF_C_API_H
#define TPMSHX_PREPARATION_DF_C_API_H

#include "tpmshx/preparation_c_api.h"
#include "tpmshx/grid_c_api.h"
#include "tpmshx/property_c_api.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    double dP_Pa, outlet_squared_Pa;
    uint32_t no_positive_outlet;
    uint32_t precision, strong;
    uint32_t floating_events[TPMSHX_PREPARATION_FP_EVENT_COUNT];
} tpmshx_preparation_df_pressure_v1;

typedef struct {
    uint32_t branch, campaign, scope, flags;
    double scale_K, scale_F;
    double application_u[2], calibration_u[2], runtime_u[2];
} tpmshx_preparation_df_selection_v1;

typedef struct {
    double minimum, maximum;
    uint32_t scalar;
} tpmshx_preparation_df_summary_v1;

/* Topology is 0=Diamond, 1=Gyroid. L/t use mm; K uses m2; cF uses 1/m.
 * Paired arrays are C-order double buffers. Each output count is exact.
 * The fixed model ignores epsilon; Python retains its public shape contract.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_fixed_v1(
    uint32_t topology, const double* L_mm, const double* t_mm, size_t count,
    double* permeability, size_t permeability_count, double* forchheimer, size_t forchheimer_count,
    char* error, size_t error_capacity);

/* Pressure operands retain weak Python or strong NumPy scalar metadata.
 * Result precision/strong describe dP. Events use the preparation property's
 * ordered scalar-operation flags. The nonpositive-outlet policy is separate.
 * The failure POD is mandatory disjoint error data. It can publish earlier
 * FP events and a terminal cause while the numerical result stays unchanged.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_incompressible_v1(
    uint32_t topology, double L_mm, double t_mm, tpmshx_grid_scalar_v1 speed,
    tpmshx_grid_scalar_v1 density, tpmshx_grid_scalar_v1 viscosity,
    tpmshx_grid_scalar_v1 length_m, tpmshx_preparation_df_pressure_v1* result,
    tpmshx_preparation_fp_failure_v1* failure, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_compressible_v1(
    uint32_t topology, double L_mm, double t_mm, tpmshx_grid_scalar_v1 mass_flux,
    tpmshx_grid_scalar_v1 temperature, tpmshx_grid_scalar_v1 inlet_pressure,
    tpmshx_grid_scalar_v1 viscosity, tpmshx_grid_scalar_v1 length_m, uint32_t strict,
    tpmshx_preparation_df_pressure_v1* result, tpmshx_preparation_fp_failure_v1* failure,
    char* error, size_t error_capacity);

/* Use the supplied, already corrected K/cF. The ordered formula is
 * mu*u/K + (((rho*cF)*u)*u). It does not query fixed DF or an outlet state.
 * Inputs have matching broadcast counts; output uses the property data DTO.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_pressure_gradient_v1(
    tpmshx_property_input_v1 density,tpmshx_property_input_v1 viscosity,
    tpmshx_property_input_v1 speed,tpmshx_property_input_v1 permeability,
    tpmshx_property_input_v1 inertial,tpmshx_property_output_v1 result,
    tpmshx_preparation_fp_failure_v1* failure,char* error,size_t error_capacity);

/* Select on the original separate L/t spans before broadcast. A missing u
 * has has_velocity=0. Air specimen selection does not read velocity.
 * Branch 0=air specimen, 1=HX. Flags: windows=1, extrapolated=2, transfer=4.
 * Campaign: 0=air specimen, 1=water/air HX, 2=Gyroid April 1, 3=sCO2 hot HX.
 * Scope: 0=core calibrated, 1=HX effective.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_correction_select_v1(
    uint32_t topology, uint32_t fluid, uint32_t allow_transfer,
    const double* L_mm, size_t L_count, const double* t_mm, size_t t_count,
    const double* velocity, size_t velocity_count, uint32_t has_velocity,
    tpmshx_preparation_df_selection_v1* result, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_correction_scales_v1(
    uint32_t topology, const tpmshx_preparation_df_selection_v1* selection,
    const double* L_mm, const double* t_mm, size_t count,
    double* scale_K, size_t K_count, double* scale_F, size_t F_count,
    char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_apply_scale_v1(
    const double* base, const double* scale, size_t count, uint32_t prepared_scalar_factor,
    double* result, size_t result_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_summarize_v1(
    const double* values, size_t count, uint32_t scalar,
    tpmshx_preparation_df_summary_v1* result, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_co2_factors_v1(
    double* result, size_t result_count, char* error, size_t error_capacity);

/* Optional source widths are present together. Target widths are already
 * float64. Precision tags describe the original floating field/width data.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_project_rows_v1(
    size_t nx, size_t ny, const double* L_mm, const double* t_mm, size_t field_count,
    uint32_t L_precision, uint32_t t_precision, uint32_t direction, size_t target_count,
    const double* source_dx, size_t dx_count, uint32_t dx_precision,
    const double* source_dy, size_t dy_count, uint32_t dy_precision,
    const double* target_widths, size_t target_width_count,
    double* L_rows, size_t L_row_count, double* t_rows, size_t t_row_count,
    int64_t* source_index, size_t index_count, char* error, size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_df_row_means_v1(
    size_t rows, size_t columns, const double* permeability, const double* forchheimer, size_t field_count,
    double* K_rows, size_t K_count, double* cF_rows, size_t cF_count,
    char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
