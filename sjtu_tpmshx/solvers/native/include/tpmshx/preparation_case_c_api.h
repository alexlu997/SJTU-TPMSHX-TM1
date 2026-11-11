#ifndef TPMSHX_PREPARATION_CASE_C_API_H
#define TPMSHX_PREPARATION_CASE_C_API_H

#include "tpmshx/preparation_c_api.h"
#include "tpmshx/preparation_df_c_api.h"
#include "tpmshx/grid_c_api.h"

#define TPMSHX_PREPARATION_CASE_ABI_VERSION 1u
#define TPMSHX_PREPARATION_CASE_ABI_VERSION_V2 2u
#define TPMSHX_PREPARATION_CASE_ABI_VERSION_V3 3u
#define TPMSHX_PREPARATION_CASE_ABI_VERSION_V4 4u

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
/* V3/v4 entries also accept this descriptor through &values.
 * Set values.abi_version=2 and values.struct_size=sizeof(this descriptor).
 * Host stages: 0=begin final preparation, 1=nominal geometry, 2=inlet properties.
 * Side: 0=A, 1=B, 2=shared. The hook validates host objects and supplies no
 * numerical value. It must not throw. Nonzero status stops the operation.
 * Its storage is borrowed until the call returns. Stored events are unchanged.
 */
typedef struct {
    tpmshx_preparation_case_callbacks_v1 values;
    int (TPMSHX_PREPARATION_CALL *validate_host_input)(void*,uint32_t,uint32_t);
} tpmshx_preparation_case_callbacks_v2;
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

typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_2d_v2 values;
    tpmshx_preparation_scalar_kind_v2 physical_depth_kind,target_kinds[2];
    uint32_t have_explicit_targets;
    double explicit_targets_kg_s[2];
} tpmshx_preparation_flow_input_2d_v3;
typedef struct {
    const tpmshx_preparation_range_v1* ranges;
    size_t range_count;
    const uint32_t* range_bounds_list;
    const tpmshx_preparation_text_v1* warnings;
    size_t warning_count;
    const tpmshx_preparation_event_v1* events;
    size_t event_count;
} tpmshx_preparation_flow_evidence_v3;
/* Cache lookup (action=0) sets hit to 0 or 1. Publication (action=1)
 * receives completed values and must not change them. A callback return of
 * nonzero stops the operation. No callback calculates physical values.
 * Lookup storage belongs to the host and stays valid until the stage returns.
 * Publication views stay valid only during the callback. Copy them before return.
 * Nested views must not overlap the stage result, failure or error storage.
 * Invalid borrowed storage leaves all three output buffers unchanged.
 */
typedef struct {
    double epsilon,epsilon_a,epsilon_b,area_density_per_m,hydraulic_diameter_m;
} tpmshx_preparation_geometry_cache_v3;
typedef struct {
    tpmshx_preparation_geometry_cache_v3 geometry;
    tpmshx_preparation_inlet_properties_v1 properties;
    tpmshx_preparation_scalar_kind_v2 kinds[13];
    tpmshx_preparation_flow_evidence_v3 evidence;
} tpmshx_preparation_inlet_cache_v3;
typedef struct {
    tpmshx_preparation_case_callbacks_v2 values;
    int (TPMSHX_PREPARATION_CALL *geometry_cache)(void*,uint32_t,tpmshx_preparation_geometry_cache_v3*,uint32_t*);
    int (TPMSHX_PREPARATION_CALL *inlet_cache)(void*,uint32_t,uint32_t,
        const tpmshx_preparation_inlet_2d_v1*,tpmshx_preparation_scalar_kind_v2,
        tpmshx_preparation_inlet_cache_v3*,uint32_t*);
} tpmshx_preparation_case_callbacks_v3;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_2d_v2 input;
    uint32_t have_capacities;
    tpmshx_grid_scalar_v1 capacities[2],speeds[2];
    tpmshx_preparation_flow_evidence_v3 evidence;
    void* owner;
} tpmshx_preparation_flow_2d_v3;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_2d_v2 prepared;
    tpmshx_preparation_flow_2d_v3 flow;
    void* owner;
} tpmshx_preparation_flow_case_2d_v3;

typedef struct {
    size_t n_ctrl_x,n_ctrl_y;
    uint32_t spline_order,symmetric_y;
    double L_bounds_mm[2],t_bounds_mm[2];
    tpmshx_preparation_array_v1 decision_mm;
} tpmshx_preparation_continuous_controls_2d_v4;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_input_2d_v3 values;
    tpmshx_preparation_continuous_controls_2d_v4 controls;
} tpmshx_preparation_continuous_input_2d_v4;
typedef struct {
    tpmshx_preparation_text_v1 transfer_policy,geometry_application;
    uint32_t have_reference_geometry;
    double reference_geometry_mm[2];
} tpmshx_preparation_continuous_drag_v4;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_2d_v3 flow;
    tpmshx_preparation_continuous_controls_2d_v4 controls;
    void* owner;
} tpmshx_preparation_continuous_flow_2d_v4;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_2d_v2 prepared;
    tpmshx_preparation_flow_2d_v3 flow;
    tpmshx_preparation_continuous_controls_2d_v4 controls;
    tpmshx_preparation_array_v1 area_density_per_m,hydraulic_diameter_m,fluid_conductivity[2];
    tpmshx_preparation_continuous_drag_v4 drag[2];
    void* owner;
} tpmshx_preparation_continuous_case_2d_v4;

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
 * The result is accepted by tpmshx_run_case_2d_v2. Nonzero delta, zones and
 * prescribed mass flow are not supported by this preparation entry.
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

/* V3 adds uniform symmetric 2D total mass flow. Existing v1/v2 inputs stay
 * unchanged. values and its nested values retain their v2/v1 versions.
 * Configured targets come from values.values.sides. Explicit targets replace
 * both stored targets and clear them in the resolved input. Flag is 0 or 1.
 * Target/depth kinds also permit strong=2 with precision 8/16/32/64 for the
 * existing integer scalar arithmetic. A zero-dimensional value uses its
 * extracted scalar kind. These numeric tags do not encode Python objects.
 * Capacity-only rejects have_explicit_targets=1. It ignores old speeds and
 * does not evaluate Nu. Resolve without targets returns a copied input and
 * have_capacities=0. Otherwise both capacities are evaluated before division.
 * Callback order includes preliminary flow work followed by final prepare.
 * flow.evidence is separate from prepared.values ranges/warnings/events.
 * Failure uses the v2 contract. All output storage is preserved on failure.
 * Query outputs own copied text and evidence. Initialize owner to NULL.
 * In a flow-case result, prepared and flow are borrowed, with NULL owners.
 * Release only the complete result with its matching release function.
 */
TPMSHX_PREPARATION_API uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v3(void);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_inlet_mass_capacities_2d_v3(
    const tpmshx_preparation_flow_input_2d_v3* input,
    const tpmshx_preparation_case_options_v1* options,
    const tpmshx_preparation_case_callbacks_v1* callbacks,
    tpmshx_preparation_flow_2d_v3* result,tpmshx_preparation_case_failure_v2* failure,
    char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_resolve_inlet_flow_2d_v3(
    const tpmshx_preparation_flow_input_2d_v3* input,
    const tpmshx_preparation_case_options_v1* options,
    const tpmshx_preparation_case_callbacks_v1* callbacks,
    tpmshx_preparation_flow_2d_v3* result,tpmshx_preparation_case_failure_v2* failure,
    char* error,size_t error_capacity);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_flow_case_2d_v3(
    const tpmshx_preparation_flow_input_2d_v3* input,
    const tpmshx_preparation_case_options_v1* options,
    const tpmshx_preparation_case_callbacks_v1* callbacks,
    tpmshx_preparation_flow_case_2d_v3* result,tpmshx_preparation_case_failure_v2* failure,
    char* error,size_t error_capacity);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_flow_2d_release_v3(
    tpmshx_preparation_flow_2d_v3* result);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_flow_case_2d_release_v3(
    tpmshx_preparation_flow_case_2d_v3* result);

/* V4 accepts canonical continuous XY controls. Nested versions remain v3/v2/v1.
 * geometry_mode is 1. Decisions contain L controls then t controls in mm.
 * Each field uses C order (x,y). A symmetric field stores the lower half of y,
 * including the central row for an odd count. Controls and bounds must stay
 * within the current CFD geometry domain. spline_order is 1, 2 or 3.
 * Capacity and resolution retain the v3 target and static-input contracts.
 * The complete result adds four C-order physical fields. Its existing local
 * drag views use (cross,stream), with the stream reversed for directions 1/3.
 * All nested owners are NULL. Controls, arrays and text are copied or borrowed
 * from the outer owner. Release that owner once with the matching v4 release.
 * Complete preparation supports CFD for all pairs, Shanghai Gyroid air/water
 * experimental transfer at nominal 7/0.6, and the existing CO2/CO2 bypass.
 * All failure, alias, callback and ownership rules from v3 remain in effect.
 */
TPMSHX_PREPARATION_API uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v4(void);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_inlet_mass_capacities_2d_v4(
    const tpmshx_preparation_continuous_input_2d_v4*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_continuous_flow_2d_v4*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_resolve_inlet_flow_2d_v4(
    const tpmshx_preparation_continuous_input_2d_v4*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_continuous_flow_2d_v4*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_flow_case_2d_v4(
    const tpmshx_preparation_continuous_input_2d_v4*,const tpmshx_preparation_case_options_v1*,
    const tpmshx_preparation_case_callbacks_v1*,tpmshx_preparation_continuous_case_2d_v4*,
    tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_continuous_flow_2d_release_v4(
    tpmshx_preparation_continuous_flow_2d_v4*);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_continuous_case_2d_release_v4(
    tpmshx_preparation_continuous_case_2d_v4*);

#ifdef __cplusplus
}
#endif
#endif
