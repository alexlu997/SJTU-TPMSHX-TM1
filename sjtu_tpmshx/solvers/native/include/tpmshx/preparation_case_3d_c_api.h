#ifndef TPMSHX_PREPARATION_CASE_3D_C_API_H
#define TPMSHX_PREPARATION_CASE_3D_C_API_H

#include "tpmshx/preparation_case_c_api.h"

#define TPMSHX_PREPARATION_CASE_3D_ABI_VERSION 1u
#define TPMSHX_PREPARATION_FLOW_3D_ABI_VERSION 2u
#define TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION 3u

typedef struct {
    uint32_t fluid;
    double velocity_m_s,temperature_K,pressure_Pa;
    tpmshx_grid_port_v1 port;
    uint32_t have_mass_flow;
    double mass_flow_kg_s;
} tpmshx_preparation_inlet_3d_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_grid_scalar_v1 lengths_m[3];
    size_t counts[3],max_cells;
    uint32_t port_wall_refine,topology;
    double cell_length_mm,wall_thickness_mm,solid_conductivity_W_mK,delta_levelset;
    tpmshx_preparation_inlet_3d_v1 sides[2];
    uint32_t geometry_mode,df_mode;
    tpmshx_preparation_case_kinds_v2 kinds;
    tpmshx_preparation_sco2_nu_v2 sco2_nu;
} tpmshx_preparation_case_input_3d_v1;
typedef struct {
    /* cross1, stream, cross2, solver-to-real permutation[3], reverse. */
    int32_t axes[7];
    tpmshx_preparation_array_v1 inlet_opening,outlet_opening;
    double rho,mu,cp,k_f;
    uint32_t have_drag_application;
    tpmshx_preparation_drag_evidence_v1 drag_evidence;
    tpmshx_preparation_drag_selection_v2 drag_selection;
} tpmshx_preparation_side_3d_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_3d_v1 input;
    tpmshx_preparation_case_options_v1 options;
    tpmshx_preparation_array_v1 widths[3],edges[3];
    tpmshx_preparation_geometry_cache_v3 geometry;
    double uniform_solid_conductivity;
    tpmshx_preparation_array_v1 cell_length,wall_thickness,total_porosity,side_porosity;
    tpmshx_preparation_array_v1 permeability,forchheimer,solid_conductivity;
    tpmshx_preparation_scalar_kind_v2 length_kinds[2];
    tpmshx_preparation_side_3d_v1 sides[2];
    tpmshx_preparation_model_ref_v1 models[4];
    tpmshx_preparation_flow_evidence_v3 evidence;
    tpmshx_preparation_text_v1 sco2_nu_model_version,sco2_nu_interpretation;
    double sco2_nu_coefficients[2][3];
    tpmshx_preparation_co2_model_v2 co2;
    const tpmshx_preparation_text_v1* notices;
    size_t notice_count;
    void* owner;
} tpmshx_preparation_case_3d_v1;

typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_3d_v1 input;
    tpmshx_preparation_scalar_kind_v2 target_kinds[2];
    uint32_t have_explicit_targets;
    double explicit_targets_kg_s[2];
} tpmshx_preparation_flow_input_3d_v2;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_3d_v1 input;
    uint32_t have_capacities;
    tpmshx_grid_scalar_v1 capacities[2],speeds[2];
    tpmshx_preparation_flow_evidence_v3 evidence;
    void* owner;
} tpmshx_preparation_flow_3d_v2;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_3d_v1 prepared;
    tpmshx_preparation_flow_3d_v2 flow;
    void* owner;
} tpmshx_preparation_flow_case_3d_v2;

typedef struct {
    size_t n_ctrl_x,n_ctrl_y,n_ctrl_z;
    uint32_t have_ctrl_z,spline_order,symmetric_y;
    double L_bounds_mm[2],t_bounds_mm[2];
    tpmshx_preparation_array_v1 decision_mm;
} tpmshx_preparation_continuous_controls_3d_v3;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_input_3d_v2 values;
    tpmshx_preparation_continuous_controls_3d_v3 controls;
} tpmshx_preparation_continuous_input_3d_v3;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_3d_v2 flow;
    tpmshx_preparation_continuous_controls_3d_v3 controls;
    void* owner;
} tpmshx_preparation_continuous_flow_3d_v3;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_3d_v1 prepared;
    tpmshx_preparation_flow_3d_v2 flow;
    tpmshx_preparation_continuous_controls_3d_v3 controls;
    tpmshx_preparation_array_v1 area_density_per_m,hydraulic_diameter_m,thermal_porosity;
    tpmshx_preparation_continuous_drag_v4 drag[2];
    void* owner;
} tpmshx_preparation_continuous_case_3d_v3;

#ifdef __cplusplus
extern "C" {
#endif
/* Supports symmetric uniform cases at prescribed inlet velocity. Both sides
 * require active ports. Missing first-axis values mean zero-width full faces.
 * Depth is explicit. max_cells is the resolved host limit, not an environment read.
 * Input buffers and v1 event callbacks are borrowed until return. The result
 * owns every returned view. Keep it unchanged and release it with this library.
 * Fields use physical C order (x,y,z). Masks use physical (cross1,cross2).
 * Side porosity already includes the symmetric split. K/cF fields are unscaled;
 * side drag evidence records the corrections for the later run stage.
 * Failure preserves the result. Invalid overlapping output storage preserves
 * the result, failure and error buffers. No run or property table is created.
 */
TPMSHX_PREPARATION_API uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_3d_abi_version_v1(void);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_case_3d_v1(
    const tpmshx_preparation_case_input_3d_v1*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_case_3d_v1*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_case_3d_release_v1(
    tpmshx_preparation_case_3d_v1*);
/* Capacity queries ignore old speeds and do not evaluate Nu or velocity windows.
 * Explicit targets replace both configured mass inputs. Resolution without a
 * target copies the input without physical preparation. Complete preparation
 * reuses the same geometry and records static evidence before speed checks.
 * Nested views in the combined result are borrowed and have NULL owners.
 * All calls retain the v1 storage, callback and same-library release rules.
 */
TPMSHX_PREPARATION_API uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_flow_3d_abi_version_v2(void);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_inlet_mass_capacities_3d_v2(
    const tpmshx_preparation_flow_input_3d_v2*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_flow_3d_v2*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_resolve_inlet_flow_3d_v2(
    const tpmshx_preparation_flow_input_3d_v2*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_flow_3d_v2*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_flow_case_3d_v2(
    const tpmshx_preparation_flow_input_3d_v2*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_flow_case_3d_v2*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_flow_3d_release_v2(tpmshx_preparation_flow_3d_v2*);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_flow_case_3d_release_v2(tpmshx_preparation_flow_case_3d_v2*);
/* V3 accepts canonical XY extrusion or XYZ controls with geometry_mode=1.
 * have_ctrl_z selects XYZ even when n_ctrl_z is one. Decisions store all L,
 * then all t, with z fastest. Thermal fields retain the SI round trip.
 * Nested views are borrowed from the outer owner. Release that owner once.
 * Existing v1/v2 storage and callback rules remain in force.
 */
TPMSHX_PREPARATION_API uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_continuous_3d_abi_version_v3(void);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_inlet_mass_capacities_3d_v3(
    const tpmshx_preparation_continuous_input_3d_v3*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_continuous_flow_3d_v3*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_resolve_inlet_flow_3d_v3(
    const tpmshx_preparation_continuous_input_3d_v3*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_continuous_flow_3d_v3*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_flow_case_3d_v3(
    const tpmshx_preparation_continuous_input_3d_v3*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_continuous_case_3d_v3*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_continuous_flow_3d_release_v3(
    tpmshx_preparation_continuous_flow_3d_v3*);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_continuous_case_3d_release_v3(
    tpmshx_preparation_continuous_case_3d_v3*);
#ifdef __cplusplus
}
#endif
#endif
