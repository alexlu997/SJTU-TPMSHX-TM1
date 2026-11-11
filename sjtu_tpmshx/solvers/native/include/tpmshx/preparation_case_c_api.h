#ifndef TPMSHX_PREPARATION_CASE_C_API_H
#define TPMSHX_PREPARATION_CASE_C_API_H

#include "tpmshx/preparation_c_api.h"
#include "tpmshx/preparation_df_c_api.h"

#define TPMSHX_PREPARATION_CASE_ABI_VERSION 1u

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

#ifdef __cplusplus
}
#endif
#endif
