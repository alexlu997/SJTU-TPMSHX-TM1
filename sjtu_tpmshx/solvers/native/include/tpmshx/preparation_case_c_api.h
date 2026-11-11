#ifndef TPMSHX_PREPARATION_CASE_C_API_H
#define TPMSHX_PREPARATION_CASE_C_API_H

#include "tpmshx/preparation_c_api.h"
#include "tpmshx/preparation_df_c_api.h"

#define TPMSHX_PREPARATION_CASE_ABI_VERSION 1u
#define TPMSHX_PREPARATION_CASE_ABI_VERSION_V2 2u

typedef struct {
    int32_t direction;
    double inlet_center_m,inlet_width_m,outlet_center_m,outlet_width_m;
    uint32_t uniform_inlet;
} tpmshx_preparation_port_2d_v1;
typedef struct {
    uint32_t fluid;
    double velocity_m_s,temperature_K,pressure_Pa;
    tpmshx_preparation_port_2d_v1 port;
    uint32_t have_mass_flow;
    double mass_flow_kg_s;
} tpmshx_preparation_inlet_2d_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    double length_m,height_m;
    size_t requested_nx,requested_ny;
    uint32_t port_wall_refine,topology;
    double cell_length_mm,wall_thickness_mm,solid_conductivity_W_mK,delta_levelset;
    tpmshx_preparation_inlet_2d_v1 sides[2];
    uint32_t have_physical_depth,geometry_mode,df_mode;
    double physical_depth_m;
} tpmshx_preparation_case_input_2d_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    uint32_t have_chi,allow_extrapolation;
    double chi;
} tpmshx_preparation_case_options_v1;
typedef struct {const double* data;size_t size;} tpmshx_preparation_array_v1;
typedef struct {const char* data;size_t size;} tpmshx_preparation_text_v1;
typedef struct {
    uint32_t kind;
    tpmshx_preparation_text_v1 logger,message;
    uint32_t floating_event;
} tpmshx_preparation_event_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    int (TPMSHX_PREPARATION_CALL *event)(void*,const tpmshx_preparation_event_v1*);
    void* context;
} tpmshx_preparation_case_callbacks_v1;
typedef struct {
    double rho,mu,k_f,cp,pr,re,nu;
    double permeability_m2,forchheimer_per_m,pressure_gradient_Pa_m;
    double surface_transfer_W_m2K,fluid_conductivity_W_mK,solid_conductivity_W_mK;
} tpmshx_preparation_inlet_properties_v1;
typedef struct {
    tpmshx_preparation_df_summary_v1 base_permeability,base_forchheimer,applied_permeability,applied_forchheimer;
    double scale_permeability,scale_forchheimer;
    tpmshx_preparation_text_v1 campaign,scope;
} tpmshx_preparation_drag_evidence_v1;
typedef struct {
    tpmshx_preparation_inlet_2d_v1 inlet;
    tpmshx_preparation_inlet_properties_v1 properties;
    double seed_permeability_m2,seed_forchheimer_per_m;
    tpmshx_preparation_array_v1 cross_widths,stream_widths,row_permeability,row_forchheimer;
    tpmshx_preparation_array_v1 permeability,forchheimer;
    tpmshx_preparation_array_v1 inlet_geometry,outlet_geometry,inlet_profile,outlet_profile,outlet_u_fraction;
    double inlet_bounds[2],outlet_bounds[2];
    tpmshx_preparation_drag_evidence_v1 drag_evidence;
} tpmshx_preparation_side_2d_v1;
typedef struct {
    uint32_t have_finite;
    double minimum,maximum;
    size_t minimum_index,maximum_index,low,high,size,nonfinite;
} tpmshx_preparation_range_sample_v1;
typedef struct {
    const tpmshx_preparation_text_v1* source;
    size_t source_count;
    tpmshx_preparation_text_v1 side,stage,layout,label,quantity,unit;
    double bounds[2];
    const size_t* shape;
    size_t rank;
    tpmshx_preparation_range_sample_v1 sample,last;
} tpmshx_preparation_range_v1;
typedef struct {
    tpmshx_preparation_text_v1 name,version,side;
} tpmshx_preparation_model_ref_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_2d_v1 input;
    tpmshx_preparation_case_options_v1 options;
    size_t nx,ny;
    tpmshx_preparation_array_v1 dx,dy,x_edges,y_edges,x_breaks,y_breaks;
    double epsilon,epsilon_a,epsilon_b,area_density_per_m,hydraulic_diameter_m;
    double uniform_solid_conductivity,hydraulic_radius_m,cell_length_m,wall_thickness_m,split_a;
    tpmshx_preparation_array_v1 cell_length,wall_thickness,total_porosity,solid_conductivity,hydraulic_radius;
    tpmshx_preparation_side_2d_v1 sides[2];
    tpmshx_preparation_model_ref_v1 models[4];
    const tpmshx_preparation_range_v1* ranges;
    size_t range_count;
    const tpmshx_preparation_text_v1* warnings;
    size_t warning_count;
    const tpmshx_preparation_event_v1* events;
    size_t event_count;
    void* owner;
} tpmshx_preparation_case_2d_v1;

/* The value buffers use double transport. Tags retain the existing property
 * precision, strong-scalar and layout rules. They do not change the units.
 */
typedef struct {uint32_t precision,strong,layout;} tpmshx_preparation_scalar_kind_v2;
typedef struct {
    tpmshx_preparation_scalar_kind_v2 velocity,temperature,pressure;
} tpmshx_preparation_inlet_kinds_v2;
typedef struct {
    tpmshx_preparation_scalar_kind_v2 cell_length,wall_thickness,solid_conductivity;
    tpmshx_preparation_inlet_kinds_v2 sides[2];
} tpmshx_preparation_case_kinds_v2;
typedef struct {
    uint32_t mode,have_alpha[2];
    double alpha[2];
    tpmshx_preparation_text_v1 parameter_version,source,applicability;
} tpmshx_preparation_sco2_nu_v2;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_2d_v1 values;
    tpmshx_preparation_sco2_nu_v2 sco2_nu;
    tpmshx_preparation_case_kinds_v2 kinds;
} tpmshx_preparation_case_input_2d_v2;
typedef struct {tpmshx_preparation_text_v1 key,value;} tpmshx_preparation_text_field_v2;
typedef struct {
    uint32_t have_selection;
    tpmshx_preparation_df_selection_v1 selection;
    tpmshx_preparation_text_v1 application_scope,fluid;
    const tpmshx_preparation_text_field_v2* calibration;
    size_t calibration_count;
} tpmshx_preparation_drag_selection_v2;
typedef struct {
    uint32_t active,sides[2];
    tpmshx_preparation_text_v1 version,application_version,pressure_model;
    double pressure_multiplier,scale_K,scale_F,nu_multiplier,nu_floor_multiplier;
    tpmshx_preparation_text_v1 correction_source,property_model,common_geometry;
    double re_range[2],pr_range[2];
} tpmshx_preparation_co2_model_v2;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_2d_v1 values;
    tpmshx_preparation_case_kinds_v2 input_kinds;
    tpmshx_preparation_scalar_kind_v2 field_kinds[5],property_kinds[2][13];
    tpmshx_preparation_sco2_nu_v2 sco2_nu;
    tpmshx_preparation_text_v1 sco2_nu_model_version,sco2_nu_interpretation;
    double sco2_nu_coefficients[2][3];
    tpmshx_preparation_drag_selection_v2 drag[2];
    tpmshx_preparation_co2_model_v2 co2;
    const tpmshx_preparation_text_v1* notices;
    size_t notice_count;
    const uint32_t* range_bounds_list;
} tpmshx_preparation_case_2d_v2;
typedef struct {uint32_t kind;char message[4096];} tpmshx_preparation_failure_cause_v2;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    uint32_t kind,side,have_property,cause_count;
    tpmshx_property_failure_v1 property;
    tpmshx_preparation_failure_cause_v2 causes[2];
} tpmshx_preparation_case_failure_v2;

#ifdef __cplusplus
extern "C" {
#endif

TPMSHX_PREPARATION_API uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v1(void);
/* Units are explicit in field names. Fluid: air=0,water=1,sco2=2,co2=3.
 * Topology: Diamond=0,Gyroid=1. Geometry mode and DF mode are currently 0.
 * This entry accepts uniform symmetric air/air at prescribed velocity.
 * Initialize result.abi_version/struct_size and set result.owner to NULL.
 * Options/callbacks may be NULL. Their flags must be 0/1 when supplied.
 * Result owns all const array/text views. No input is retained. Release with
 * this same library. Physical fields use C order (nx,ny); side row fields use
 * the stream axis. A nonzero return preserves result. Do not copy owners.
 * Callbacks run on the caller thread. Event views live only during callback.
 * They must not throw; nonzero callback status stops preparation. No C++
 * exception crosses this boundary. No numerical callback is required.
 * Input/result/error/callback storage must be disjoint. No pointer can prove
 * allocation size. Error requires a nonempty writable buffer.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_case_2d_v1(
    const tpmshx_preparation_case_input_2d_v1* input,
    const tpmshx_preparation_case_options_v1* options,
    const tpmshx_preparation_case_callbacks_v1* callbacks,
    tpmshx_preparation_case_2d_v1* result,char* error,size_t error_capacity);
/* Clear the result. NULL and an already cleared result are accepted. */
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_case_2d_release_v1(
    tpmshx_preparation_case_2d_v1* result);

/* V2 adds four fluids and existing uniform experimental DF/Nu choices.
 * values keeps its v1 layout/version; df_mode=0/1 selects CFD/experimental.
 * It does not enable nonzero delta, zones, prescribed mass flow or run_case.
 * Scalar tags use precision 16/32/64, strong 0/1 and layout 0/1/2.
 * A weak scalar uses precision=64 and layout=0. A strong scalar uses 1/2.
 * Nu mode 0=CFD, 1=experimental. Both experimental alphas and provenance
 * texts are required. Texts are borrowed for this call and then copied.
 * field_kinds order: cell_length,wall_thickness,porosity,solid,radius.
 * property_kinds follows inlet_properties_v1 declaration order. It describes
 * the original property scalars before the host freezes metadata values.
 * range_bounds_list has values.range_count flags. Each flag retains the
 * original range bound container: 0=tuple, 1=list, before DTO freezing.
 * failure is required, versioned, writable and disjoint from all inputs,
 * result and error. Kind: 0=none, 1=ValueError, 2=WaterStateError, 3=RuntimeError;
 * side: 0=A, 1=B, 2=shared. Cause messages are bounded and NUL-terminated.
 * A failed call writes only error/failure. Success clears failure details.
 * Release the complete v2 result once; values and all other views are borrowed.
 */
TPMSHX_PREPARATION_API uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v2(void);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_case_2d_v2(
    const tpmshx_preparation_case_input_2d_v2* input,
    const tpmshx_preparation_case_options_v1* options,
    const tpmshx_preparation_case_callbacks_v1* callbacks,
    tpmshx_preparation_case_2d_v2* result,tpmshx_preparation_case_failure_v2* failure,
    char* error,size_t error_capacity);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_case_2d_release_v2(
    tpmshx_preparation_case_2d_v2* result);

#ifdef __cplusplus
}
#endif
#endif
