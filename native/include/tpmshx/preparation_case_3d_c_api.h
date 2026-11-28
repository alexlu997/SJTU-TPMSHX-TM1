#ifndef TPMSHX_PREPARATION_CASE_3D_C_API_H
#define TPMSHX_PREPARATION_CASE_3D_C_API_H

#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/grid_c_api.h"

#define TPMSHX_PREPARATION_CASE_3D_ABI_VERSION 1u

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
    double lengths_m[3];
    size_t counts[3],max_cells;
    uint32_t port_wall_refine,topology;
    double cell_length_mm,wall_thickness_mm,solid_conductivity_W_mK,delta_levelset;
    tpmshx_preparation_inlet_3d_v1 sides[2];
    uint32_t geometry_mode,df_mode;
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
/* Flat prepared 3D sub-record. All views are borrowed from the outer result owner. */
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
    tpmshx_preparation_side_3d_v1 sides[2];
    tpmshx_preparation_model_ref_v1 models[4];
    tpmshx_preparation_flow_evidence_v3 evidence;
    tpmshx_preparation_text_v1 sco2_nu_model_version,sco2_nu_interpretation;
    double sco2_nu_coefficients[2][3];
    tpmshx_preparation_co2_model_v2 co2;
    const tpmshx_preparation_text_v1* notices;
    size_t notice_count;
} tpmshx_preparation_case_3d_v1;

/* Non-owning flat 3D flow sub-record embedded in 3D flow and complete-case results. */
typedef struct {
    tpmshx_preparation_case_input_3d_v1 input;
    uint32_t have_capacities;
    double capacities[2],speeds[2];
    tpmshx_preparation_flow_evidence_v3 evidence;
} tpmshx_preparation_flow_3d_v1;

typedef struct {
    size_t n_ctrl_x,n_ctrl_y,n_ctrl_z;
    uint32_t have_ctrl_z,spline_order,symmetric_y;
    double L_bounds_mm[2],t_bounds_mm[2];
    tpmshx_preparation_array_v1 decision_mm;
} tpmshx_preparation_continuous_controls_3d_v3;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_3d_v1 input;
    uint32_t have_explicit_targets;
    double explicit_targets_kg_s[2];
    tpmshx_preparation_continuous_controls_3d_v3 controls;
} tpmshx_preparation_3d_continuous_input_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_3d_v1 flow;
    tpmshx_preparation_continuous_controls_3d_v3 controls;
    void* owner;
} tpmshx_preparation_3d_continuous_flow_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_3d_v1 prepared;
    tpmshx_preparation_flow_3d_v1 flow;
    tpmshx_preparation_continuous_controls_3d_v3 controls;
    tpmshx_preparation_array_v1 area_density_per_m,hydraulic_diameter_m,thermal_porosity;
    tpmshx_preparation_continuous_drag_v4 drag[2];
    void* owner;
} tpmshx_preparation_3d_continuous_case_v1;

typedef struct {
    double bounds[4]; /* x0,x1,y0,y1 in domain fractions. */
    double cell_length_mm,wall_thickness_mm;
} tpmshx_preparation_grid_cell_3d_v4;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_3d_v1 input;
    uint32_t have_explicit_targets;
    double explicit_targets_kg_s[2];
    const tpmshx_preparation_grid_cell_3d_v4* cells;
    size_t cell_count;
} tpmshx_preparation_3d_spatial_input_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_3d_v1 flow;
    const tpmshx_preparation_grid_cell_3d_v4* cells;
    size_t cell_count;
    void* owner;
} tpmshx_preparation_3d_spatial_flow_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_3d_v1 prepared;
    tpmshx_preparation_flow_3d_v1 flow;
    const tpmshx_preparation_grid_cell_3d_v4* cells;
    size_t cell_count;
    tpmshx_preparation_array_v1 side_b_porosity;
    tpmshx_preparation_array_v1 area_density_per_m,hydraulic_diameter_m,thermal_porosity;
    double split_a;
    uint32_t have_side_geometry;
    double side_geometry[2][4]; /* area, diameter, reference area, reference diameter. */
    void* owner;
} tpmshx_preparation_3d_spatial_case_v1;

#ifdef __cplusplus
extern "C" {
#endif
/* Common rules for all 3D preparation entries below.
 * Both sides require active ports. Missing first-axis values mean zero-width
 * full faces. Depth is explicit. max_cells is the resolved host limit.
 * Initialize top-level input/result abi_version=1, struct_size=sizeof(*),
 * input.input.abi_version=1, input.input.struct_size=sizeof(input.input),
 * failure.abi_version=2, failure.struct_size=sizeof(*failure), and result.owner=NULL.
 * Input buffers and callbacks are borrowed until return. Callbacks use
 * tpmshx_preparation_callbacks_v2, accept inlet_cache_at only, and reject untyped cache hooks, sigmoid_lut_cache, and
 * validate_grid_stage != 0. Host validation uses stages 10-19 with side=2.
 * Fields use physical C order (x,y,z). Masks use physical (cross1,cross2).
 * Side porosity includes the symmetric split. K/cF fields are unscaled;
 * side drag evidence records corrections for the later run stage.
 * Failure preserves the result. Release each result once with this library.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_capacities_v1(
    const tpmshx_preparation_3d_continuous_input_v1*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_callbacks_v2*,tpmshx_preparation_3d_continuous_flow_v1*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_resolve_flow_v1(
    const tpmshx_preparation_3d_continuous_input_v1*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_callbacks_v2*,tpmshx_preparation_3d_continuous_flow_v1*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_prepare_case_v1(
    const tpmshx_preparation_3d_continuous_input_v1*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_callbacks_v2*,tpmshx_preparation_3d_continuous_case_v1*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_flow_release_v1(
    tpmshx_preparation_3d_continuous_flow_v1*);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_case_release_v1(
    tpmshx_preparation_3d_continuous_case_v1*);

TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_capacities_v1(
    const tpmshx_preparation_3d_spatial_input_v1*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_callbacks_v2*,tpmshx_preparation_3d_spatial_flow_v1*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_resolve_flow_v1(
    const tpmshx_preparation_3d_spatial_input_v1*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_callbacks_v2*,tpmshx_preparation_3d_spatial_flow_v1*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_prepare_case_v1(
    const tpmshx_preparation_3d_spatial_input_v1*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_callbacks_v2*,tpmshx_preparation_3d_spatial_case_v1*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_flow_release_v1(
    tpmshx_preparation_3d_spatial_flow_v1*);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_case_release_v1(
    tpmshx_preparation_3d_spatial_case_v1*);
#ifdef __cplusplus
}
#endif
#endif
