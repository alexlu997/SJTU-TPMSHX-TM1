#ifndef TPMSHX_PREPARATION_CASE_C_API_H
#define TPMSHX_PREPARATION_CASE_C_API_H

#include "tpmshx/preparation_c_api.h"
#include "tpmshx/preparation_df_c_api.h"

#define TPMSHX_PREPARATION_CASE_ABI_VERSION 1u
#define TPMSHX_PREPARATION_CALLBACK_ABI_VERSION 3u
#define TPMSHX_PREPARATION_FAILURE_ABI_VERSION 2u

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
typedef struct {const double* data;size_t size;} tpmshx_preparation_array_v1;
typedef struct {const char* data;size_t size;} tpmshx_preparation_text_v1;
typedef struct {tpmshx_preparation_text_v1 key,value;} tpmshx_preparation_text_field_v2;
typedef struct {
    uint32_t mode,have_alpha[2];
    double alpha[2];
    tpmshx_preparation_text_v1 parameter_version,source,applicability;
} tpmshx_preparation_sco2_nu_v2;
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
    tpmshx_preparation_sco2_nu_v2 sco2_nu;
} tpmshx_preparation_case_input_2d_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    /* have_chi: 0=fitted, 1=explicit value, 2=failed host conversion. */
    uint32_t have_chi,allow_extrapolation;
    double chi;
} tpmshx_preparation_case_options_v1;
typedef struct {
    uint32_t kind;
    tpmshx_preparation_text_v1 logger,message;
    uint32_t floating_event;
} tpmshx_preparation_event_v1;
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
/* Flat prepared 2D sub-record. All views are borrowed from the outer result owner. */
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
    const uint32_t* range_bounds_list;
    const tpmshx_preparation_text_v1* warnings;
    size_t warning_count;
    const tpmshx_preparation_event_v1* events;
    size_t event_count;
    tpmshx_preparation_sco2_nu_v2 sco2_nu;
    tpmshx_preparation_text_v1 sco2_nu_model_version,sco2_nu_interpretation;
    double sco2_nu_coefficients[2][3];
    tpmshx_preparation_drag_selection_v2 drag[2];
    tpmshx_preparation_co2_model_v2 co2;
    const tpmshx_preparation_text_v1* notices;
    size_t notice_count;
} tpmshx_preparation_case_2d_v1;
typedef struct {uint32_t kind;char message[4096];} tpmshx_preparation_failure_cause_v2;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    uint32_t kind,side,have_property,cause_count;
    tpmshx_property_failure_v1 property;
    tpmshx_preparation_failure_cause_v2 causes[2];
} tpmshx_preparation_case_failure_v2;

typedef struct {
    const tpmshx_preparation_range_v1* ranges;
    size_t range_count;
    const uint32_t* range_bounds_list;
    const tpmshx_preparation_text_v1* warnings;
    size_t warning_count;
    const tpmshx_preparation_event_v1* events;
    size_t event_count;
} tpmshx_preparation_flow_evidence_v3;
typedef struct {
    double epsilon,epsilon_a,epsilon_b,area_density_per_m,hydraulic_diameter_m;
} tpmshx_preparation_geometry_cache_v3;
typedef struct {
    uint32_t topology;
    double cell_length_mm,wall_thickness_mm;
} tpmshx_preparation_geometry_key_v9;
typedef struct {
    tpmshx_preparation_geometry_key_v9 geometry;
    uint32_t fluid;
    double velocity_m_s,temperature_K,pressure_Pa;
    uint32_t have_sco2_nu;
    tpmshx_preparation_sco2_nu_v2 sco2_nu;
    uint32_t co2_geometry;
} tpmshx_preparation_inlet_key_v9;
typedef struct {
    tpmshx_preparation_array_v1 cell_mm,wall_mm,porosity,area_density_per_m;
    uint32_t porosity_fast,area_fast;
} tpmshx_preparation_sigmoid_lut_view_v6;

/* Callbacks run on the calling thread. A nonzero return stops the operation.
 * A planar stage can request host validation immediately before grid construction.
 * Inlet queries and volume stages require validate_grid_stage=0. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    void* context;
    uint32_t validate_grid_stage;
    int (TPMSHX_PREPARATION_CALL *event)(void*,const tpmshx_preparation_event_v1*);
    int (TPMSHX_PREPARATION_CALL *validate_host_input)(void*,uint32_t,uint32_t);
    int (TPMSHX_PREPARATION_CALL *observe_range)(void*,uint32_t,const tpmshx_preparation_range_v1*,uint32_t,uint32_t,double);
    int (TPMSHX_PREPARATION_CALL *observe_notice)(void*,uint32_t,uint32_t,double,tpmshx_preparation_text_v1);
} tpmshx_preparation_callbacks_v3;

/* Non-owning flat flow sub-record embedded in 2D flow and complete-case results. */
typedef struct {
    tpmshx_preparation_case_input_2d_v1 input;
    uint32_t have_capacities;
    double capacities[2],speeds[2];
    tpmshx_preparation_flow_evidence_v3 evidence;
} tpmshx_preparation_flow_2d_v1;

/* Nominal asymmetric thermal sides: area, diameter, reference area and diameter.
 * The split fraction remains in the prepared sub-record. */
typedef struct {
    uint32_t have_side_geometry;
    double side_geometry[2][4];
} tpmshx_preparation_thermal_sides_2d_v10;

typedef struct {
    size_t n_ctrl_x,n_ctrl_y;
    uint32_t spline_order,symmetric_y;
    double L_bounds_mm[2],t_bounds_mm[2];
    tpmshx_preparation_array_v1 decision_mm;
} tpmshx_preparation_continuous_controls_2d_v4;
typedef struct {
    tpmshx_preparation_text_v1 transfer_policy,geometry_application;
    uint32_t have_reference_geometry;
    double reference_geometry_mm[2];
} tpmshx_preparation_continuous_drag_v4;

typedef struct {
    tpmshx_preparation_text_v1 name;
    double bounds[4];
    double cell_length_mm,wall_thickness_mm;
} tpmshx_preparation_zone_region_v5;
typedef struct {
    tpmshx_preparation_zone_region_v5 region;
    tpmshx_preparation_geometry_cache_v3 geometry,property_geometry[2];
    double solid_conductivity;
    tpmshx_preparation_inlet_properties_v1 properties[2];
} tpmshx_preparation_zone_values_v5;
typedef struct {
    tpmshx_preparation_array_v1 decision_mm;
    double inlet_transition,outlet_transition;
} tpmshx_preparation_sigmoid_controls_2d_v6;
typedef struct {
    double solid_conductivity_W_mK;
    uint32_t allow_geometry_extrapolation,load_default_lut;
} tpmshx_preparation_spatial_model_2d_v9;

/* Optional original file representation for one field. The numerical view contains its float64 conversion.
 * Use an empty field for a native float64 array. File bytes keep the order of the input axes. */
typedef struct {
    tpmshx_preparation_text_v1 dtype;
    const unsigned char* data;
    size_t size;
} tpmshx_preparation_lut_file_field_v1;

/* Flat owned sigmoid LUT result. Initialize abi_version=1, struct_size and owner=NULL. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_array_v1 cell_mm,wall_mm,porosity,area_density_per_m;
    uint32_t porosity_fast,area_fast;
    void* owner;
    tpmshx_preparation_lut_file_field_v1 file_fields[2];
} tpmshx_preparation_sigmoid_lut_v7;

/* Flat 2D uniform operation family structs. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_2d_v1 input;
    uint32_t have_explicit_targets;
    double explicit_targets_kg_s[2];
} tpmshx_preparation_2d_uniform_input_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_2d_v1 flow;
    void* owner;
} tpmshx_preparation_2d_uniform_flow_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_2d_v1 prepared;
    tpmshx_preparation_geometry_cache_v3 property_geometry[2];
    tpmshx_preparation_flow_2d_v1 flow;
    tpmshx_preparation_thermal_sides_2d_v10 thermal;
    void* owner;
} tpmshx_preparation_2d_uniform_case_v1;

/* Flat 2D continuous operation family structs. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_2d_v1 input;
    uint32_t have_explicit_targets;
    double explicit_targets_kg_s[2];
    tpmshx_preparation_continuous_controls_2d_v4 controls;
} tpmshx_preparation_2d_continuous_input_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_2d_v1 flow;
    tpmshx_preparation_continuous_controls_2d_v4 controls;
    void* owner;
} tpmshx_preparation_2d_continuous_flow_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_2d_v1 prepared;
    tpmshx_preparation_geometry_cache_v3 property_geometry[2];
    tpmshx_preparation_flow_2d_v1 flow;
    tpmshx_preparation_continuous_controls_2d_v4 controls;
    tpmshx_preparation_array_v1 area_density_per_m,hydraulic_diameter_m,fluid_conductivity[2],design_pore_porosity;
    tpmshx_preparation_continuous_drag_v4 drag[2];
    void* owner;
} tpmshx_preparation_2d_continuous_case_v1;

/* Flat 2D zoned, sigmoid and stripe operation family structs. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_2d_v1 input;
    uint32_t have_explicit_targets;
    double explicit_targets_kg_s[2];
    uint32_t kind,axis;
    const tpmshx_preparation_zone_region_v5* regions;
    size_t region_count;
    tpmshx_preparation_spatial_model_2d_v9 model;
} tpmshx_preparation_2d_zoned_input_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_2d_v1 flow;
    uint32_t kind,axis;
    const tpmshx_preparation_zone_region_v5* regions;
    size_t region_count;
    tpmshx_preparation_spatial_model_2d_v9 model;
    void* owner;
} tpmshx_preparation_2d_zoned_flow_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_2d_v1 prepared;
    tpmshx_preparation_geometry_cache_v3 property_geometry[2];
    tpmshx_preparation_flow_2d_v1 flow;
    uint32_t kind,axis;
    const tpmshx_preparation_zone_values_v5* regions;
    size_t region_count;
    const int32_t* zone_id;
    size_t cell_count;
    tpmshx_preparation_array_v1 thermal_porosity,area_density_per_m,hydraulic_diameter_m;
    tpmshx_preparation_array_v1 design_area_density_per_m,design_pore_porosity;
    tpmshx_preparation_array_v1 fluid_conductivity[2],volumetric_transfer[2];
    tpmshx_preparation_spatial_model_2d_v9 model;
    tpmshx_preparation_thermal_sides_2d_v10 thermal;
    void* owner;
} tpmshx_preparation_2d_zoned_case_v1;

typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_input_2d_v1 input;
    uint32_t have_explicit_targets;
    double explicit_targets_kg_s[2];
    uint32_t kind,axis;
    const tpmshx_preparation_zone_region_v5* regions;
    size_t region_count;
    tpmshx_preparation_sigmoid_controls_2d_v6 controls;
    tpmshx_preparation_sigmoid_lut_view_v6 lut;
    tpmshx_preparation_spatial_model_2d_v9 model;
    /* Set defer_default_lut to request disk I/O on a default-table miss.
     * Initialize both input headers for resume. Pass the live prefix and selected table to the same entry.
     * Pass NULL for resume options. The entry validates any supplied options and uses the values from the prefix.
     * Use a new result. Release the prefix result after resume or an I/O error. */
    uint32_t defer_default_lut;
    struct tpmshx_preparation_sigmoid_prefix_v1* prefix;
    const tpmshx_preparation_sigmoid_lut_v7* table;
} tpmshx_preparation_2d_sigmoid_input_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_flow_2d_v1 flow;
    uint32_t kind,axis;
    const tpmshx_preparation_zone_region_v5* regions;
    size_t region_count;
    tpmshx_preparation_sigmoid_controls_2d_v6 controls;
    tpmshx_preparation_sigmoid_lut_view_v6 lut;
    tpmshx_preparation_spatial_model_2d_v9 model;
    void* owner;
    struct tpmshx_preparation_sigmoid_prefix_v1* prefix;
    size_t lut_resolution;
} tpmshx_preparation_2d_sigmoid_flow_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_2d_v1 prepared;
    tpmshx_preparation_geometry_cache_v3 property_geometry[2];
    tpmshx_preparation_flow_2d_v1 flow;
    uint32_t kind,axis;
    const tpmshx_preparation_zone_values_v5* regions;
    size_t region_count;
    const int32_t* zone_id;
    size_t cell_count;
    tpmshx_preparation_array_v1 thermal_porosity,area_density_per_m,hydraulic_diameter_m;
    tpmshx_preparation_array_v1 design_area_density_per_m,design_pore_porosity;
    tpmshx_preparation_array_v1 fluid_conductivity[2],volumetric_transfer[2];
    tpmshx_preparation_sigmoid_controls_2d_v6 controls;
    tpmshx_preparation_sigmoid_lut_view_v6 lut;
    tpmshx_preparation_spatial_model_2d_v9 model;
    tpmshx_preparation_thermal_sides_2d_v10 thermal;
    void* owner;
    struct tpmshx_preparation_sigmoid_prefix_v1* prefix;
    size_t lut_resolution;
} tpmshx_preparation_2d_sigmoid_case_v1;

typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_case_2d_v1 prepared;
    tpmshx_preparation_geometry_cache_v3 property_geometry[2];
    tpmshx_preparation_flow_2d_v1 flow;
    uint32_t kind,axis;
    const tpmshx_preparation_zone_values_v5* regions;
    size_t region_count;
    const int32_t* zone_id;
    size_t cell_count;
    tpmshx_preparation_array_v1 thermal_porosity,area_density_per_m,hydraulic_diameter_m;
    tpmshx_preparation_array_v1 design_area_density_per_m,design_pore_porosity;
    tpmshx_preparation_array_v1 fluid_conductivity[2],volumetric_transfer[2];
    tpmshx_preparation_array_v1 region_hydraulic_radii_m;
    tpmshx_preparation_spatial_model_2d_v9 model;
    tpmshx_preparation_thermal_sides_2d_v10 thermal;
    void* owner;
} tpmshx_preparation_2d_stripe_case_v1;

typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_inlet_key_v9 inlet;
    double hydraulic_diameter_m,epsilon_a;
    uint32_t exact_co2_drag;
} tpmshx_preparation_inlet_query_input_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    double values[12];
} tpmshx_preparation_inlet_query_result_v1;

#ifdef __cplusplus
extern "C" {
#endif

/* Observe a contiguous double buffer in source order. Indices are zero-based.
 * Ignore nonfinite values when finding extrema and counting bound violations.
 * Keep the caller's floating-point environment.
 * Output, input values and error storage must be disjoint.
 * A failed call preserves output. */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_collect_range_v1(
    tpmshx_preparation_array_v1 values,double lower,double upper,tpmshx_preparation_range_sample_v1* output,
    char* error,size_t capacity);

/* Query inlet properties with the supplied diameter and side porosity.
 * No grid, ports, CaseData or solver is required. Both structures use version 1.
 * Values: rho,mu,k,cp,Pr,Re,Nu,K,cF,dP_per_L,H_sf,K_ff, all float64.
 * Set exact_co2_drag to 1 to apply the fixed CO2 drag factors.
 * The Python inlet query sets this flag for every name that resolves to the CO2 model.
 * Optional callbacks use tpmshx_preparation_callbacks_v3. Set validate_grid_stage to 0. Host validation uses stage 4 and
 * steps: 0=diameter, 1=model, 2=mu, 3=k, 4=rho, 5=cp, 6=Re, 7=Nu, 8=DF, 9=K_ff.
 * FP, range and notice callbacks retain calculation order. Nonzero callback
 * status stops the query. A failed call preserves result. A successful call
 * clears failure. Result, failure and error must be mutually disjoint and must
 * not overlap input, callbacks or borrowed input text. No owner is created.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_query_inlet_properties_v2(
    const tpmshx_preparation_inlet_query_input_v1* input,
    const tpmshx_preparation_callbacks_v3* callbacks,
    tpmshx_preparation_inlet_query_result_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t error_capacity);

/* Query the preparation inlet cache at the model geometry. The result owns its source records.
 * Release the result with this library. Each cold calculation reports its own live events. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_inlet_key_v9 inlet;
} tpmshx_preparation_cached_inlet_input_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_preparation_geometry_cache_v3 geometry;
    double values[12];
    tpmshx_preparation_flow_evidence_v3 evidence;
    void* owner;
} tpmshx_preparation_cached_inlet_result_v1;
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_cached_inlet_v1(
    const tpmshx_preparation_cached_inlet_input_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_cached_inlet_result_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_cached_inlet_release_v1(
    tpmshx_preparation_cached_inlet_result_v1*);

/* Get the shared sigmoid LUT for the training range. Preparation borrows its arrays.
 * The first published table supplies the values. It can come from a file or from the geometry kernel.
 * Initialize result.abi_version=1, struct_size=sizeof(*result) and owner=NULL.
 * Error storage must not overlap any owned LUT array.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_lut_create_v7(
    uint32_t topology,size_t cell_nodes,size_t wall_nodes,size_t resolution,
    tpmshx_preparation_sigmoid_lut_v7* result,char* error,size_t capacity);
/* Find and get/build use the topology, both supplied axes and voxel resolution.
 * Each axis can increase or decrease. The output axes increase.
 * Find returns an empty owner on a miss. Shared import retains the first complete value.
 * Private import owns its values separately. Both import modes use the two interpolation flags.
 * An importer can supply two file fields for lossless file output. Other callers pass NULL.
 * Release each result with tpmshx_preparation_sigmoid_lut_release_v7. */
enum tpmshx_preparation_lut_operation {
    TPMSHX_PREPARATION_LUT_FIND=0, TPMSHX_PREPARATION_LUT_GET_OR_BUILD=1, TPMSHX_PREPARATION_LUT_IMPORT_SHARED=2, TPMSHX_PREPARATION_LUT_IMPORT_PRIVATE=3
};
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_table_v1(
    uint32_t operation,uint32_t topology,size_t resolution,const tpmshx_preparation_sigmoid_lut_view_v6*,
    const tpmshx_preparation_lut_file_field_v1 file_fields[2],tpmshx_preparation_sigmoid_lut_v7*,char*,size_t);
/* Sample the two captured tables. Output arrays have one value per query point. */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_sample_v1(
    const tpmshx_preparation_sigmoid_lut_view_v6*,tpmshx_preparation_array_v1 x,tpmshx_preparation_array_v1 y,
    double* epsilon,double* area,size_t count,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_lut_release_v7(
    tpmshx_preparation_sigmoid_lut_v7* result);

/* Common rules for all 2D preparation entries below.
 * Units are explicit in field names. Fluid: air=0, water=1, sco2=2, co2=3.
 * Topology: Diamond=0, Gyroid=1. df_mode: 0=CFD, 1=experimental.
 * Initialize top-level input/result abi_version=1, struct_size=sizeof(*),
 * input.input.abi_version=1, input.input.struct_size=sizeof(input.input),
 * failure.abi_version=2, failure.struct_size=sizeof(*failure), and result.owner=NULL.
 * Options and callbacks may be NULL. Boolean flags must be 0 or 1.
 * Result owns all const array and text views via its single outer owner.
 * Release each result once with its matching release function from this library.
 * Release functions accept NULL and an already cleared result.
 * Physical fields use C order (nx,ny); side row fields use the stream axis.
 * A nonzero return preserves result. Input, result, failure, error and callback
 * storage must be mutually disjoint. Error requires a nonempty writable buffer.
 * Failure kind: 0=none, 1=ValueError, 2=WaterStateError, 3=RuntimeError, 4=Unsupported, 5=invalid chi.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_capacities_v1(
    const tpmshx_preparation_2d_uniform_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_uniform_flow_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_resolve_flow_v1(
    const tpmshx_preparation_2d_uniform_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_uniform_flow_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_prepare_case_v1(
    const tpmshx_preparation_2d_uniform_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_uniform_case_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_flow_release_v1(
    tpmshx_preparation_2d_uniform_flow_v1*);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_case_release_v1(
    tpmshx_preparation_2d_uniform_case_v1*);

TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_capacities_v1(
    const tpmshx_preparation_2d_continuous_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_continuous_flow_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_resolve_flow_v1(
    const tpmshx_preparation_2d_continuous_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_continuous_flow_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_prepare_case_v1(
    const tpmshx_preparation_2d_continuous_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_continuous_case_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_flow_release_v1(
    tpmshx_preparation_2d_continuous_flow_v1*);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_case_release_v1(
    tpmshx_preparation_2d_continuous_case_v1*);

TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_capacities_v1(
    const tpmshx_preparation_2d_zoned_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_zoned_flow_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_resolve_flow_v1(
    const tpmshx_preparation_2d_zoned_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_zoned_flow_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_prepare_case_v1(
    const tpmshx_preparation_2d_zoned_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_zoned_case_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_flow_release_v1(
    tpmshx_preparation_2d_zoned_flow_v1*);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_case_release_v1(
    tpmshx_preparation_2d_zoned_case_v1*);

TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_capacities_v1(
    const tpmshx_preparation_2d_sigmoid_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_sigmoid_flow_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_resolve_flow_v1(
    const tpmshx_preparation_2d_sigmoid_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_sigmoid_flow_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_prepare_case_v1(
    const tpmshx_preparation_2d_sigmoid_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_sigmoid_case_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_flow_release_v1(
    tpmshx_preparation_2d_sigmoid_flow_v1*);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_case_release_v1(
    tpmshx_preparation_2d_sigmoid_case_v1*);

TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_stripe_prepare_case_v1(
    const tpmshx_preparation_2d_zoned_input_v1*,
    const tpmshx_preparation_case_options_v1*,const tpmshx_preparation_callbacks_v3*,
    tpmshx_preparation_2d_stripe_case_v1*,tpmshx_preparation_case_failure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_stripe_case_release_v1(
    tpmshx_preparation_2d_stripe_case_v1*);

#ifdef __cplusplus
}
#endif
#endif
