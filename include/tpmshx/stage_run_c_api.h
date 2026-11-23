#ifndef TPMSHX_STAGE_RUN_C_API_H
#define TPMSHX_STAGE_RUN_C_API_H
#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/grid_c_api.h"
#include "tpmshx/full_2d_c_api.h"
#include "tpmshx/full_2d_run_c_api.h"
#include "tpmshx/result_balance_c_api.h"
#include "tpmshx/result_stage_c_api.h"

#define TPMSHX_STAGE_RUN_ABI_VERSION 1u
#define TPMSHX_STAGE_RUN_ABI_VERSION_V4 4u
#define TPMSHX_STAGE_RUN_ABI_VERSION_V5 5u

typedef struct {
    const char *relation,*provider,*state_update,*eos_fluid;
    uint32_t solved;
} tpmshx_stage_energy_relation_v1;
/* These views remain valid while the completed stage result owns its storage.
 * Temperature uses the main and optional fine grid. Energy and SIMPLE use sides A and B.
 * The 3D drag summaries use permeability first and the Forchheimer coefficient second. */
typedef struct {
    tpmshx_property_sampling_v1 sampling;
    const tpmshx_stage_range_record_v1 *observations,*last;
    size_t observation_count,last_count;
    const tpmshx_model_enthalpy_evidence_v1* temperature[2];
    const char* simple_stop[2];
    tpmshx_stage_energy_relation_v1 energy[2];
    const char *const *transient_failures,*const *final_failures;
    size_t transient_count,final_count;
    tpmshx_preparation_df_summary_v1 base_drag[2],applied_drag[2][2];
    uint32_t thermal_history_converged;
} tpmshx_stage_run_records_v1;

/* Execution views remain valid until stage result release. Model-h settings
 * refer to the last main call. The index equals count when it is absent.
 * Acceleration, when present, has one entry per model-h record. */
typedef struct {
    const tpmshx_stage_run_records_v1* records;
    tpmshx_energy_update_scale_v1 update_scale;
    tpmshx_model_h_iteration_records_v1 model_h;
    const tpmshx_model_h_acceleration_v1* acceleration;
    size_t last_main_model_h;
    const char *unknown,*algorithm;
    const char* sco2_notices[2];
    uint32_t red_black;
} tpmshx_stage_execution_v1;
typedef struct {
    tpmshx_stage_execution_v1 execution;
    tpmshx_full_2d_energy_effective_settings_v1 settings;
    tpmshx_full_2d_energy_evidence_v1 energy;
} tpmshx_stage_run_2d_execution_v1;

typedef struct { uint32_t present; size_t value; } tpmshx_stage_size_option_v1;
typedef struct { uint32_t present; double value; } tpmshx_stage_double_option_v1;
/* Flat 2D stage run request (abi_version=4, struct_size=sizeof(*)).
 * Active model_h controls (any nonzero field) cannot be combined with a
 * non-null energy pointer, a non-null explicit_energy pointer, or any partial
 * energy override (any energy_* field with present=1, or
 * require_enthalpy_update_on_temperature=1).
 * A non-null explicit_energy pointer cannot be combined with any partial
 * energy override.
 * A null energy pointer selects temperature_sou with a 1e-8 K temperature
 * update tolerance. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_stage_size_option_v1 max_iter_simple,max_outer_ltne;
    tpmshx_stage_double_option_v1 outer_tol_K,simple_velocity_relaxation;
    tpmshx_stage_double_option_v1 mom_tol,mass_local_tol,mass_global_tol,solid_seed_K;
    uint32_t have_pressure_shooting,pressure_shooting;
    const char* convergence_mode;
    const char* envelope_mode;
    tpmshx_model_h_iteration_options_v1 model_h;
    /* NULL selects temperature_sou with a 1e-8 K temperature update tolerance. */
    const tpmshx_energy_options_v1* energy;
    const tpmshx_full_2d_energy_control_v4* explicit_energy;
    tpmshx_stage_size_option_v1 energy_iterations,energy_sweeps;
    tpmshx_stage_double_option_v1 energy_omega,energy_update_tolerance;
    tpmshx_stage_double_option_v1 energy_coupled_tolerance,energy_equation_tolerance;
    uint32_t require_enthalpy_update_on_temperature;
} tpmshx_stage_run_request_2d_v4;
typedef struct {
    const char* result_id;
    const char* table_directory;
    size_t cpu_threads;
    tpmshx_full_2d_callbacks_v2 callbacks;
} tpmshx_stage_run_control_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    void* owner;
    tpmshx_full_2d_result_v2 raw;
    tpmshx_result_evidence_v1 evidence;
    tpmshx_full_2d_config_v2 resolved;
} tpmshx_stage_run_result_2d_v1;

/* Scalar values derived from recorded thermal states.
 * model_h_* and red_black use level indices: 0=main, 1=fine.
 * nu_*, pressure_*, absolute_duty and application_hv use side indices: 0=A, 1=B.
 * Pressure limits use the main thermal state. Unavailable entries are zero. */
typedef struct {
    uint32_t model_h_available[2],nu_available[2],pressure_available;
    size_t model_h_cell_count[2];
    double model_h_area_m2[2],nu_floor[2],nu_floor_fraction[2];
    double pressure_min_Pa[2],pressure_max_Pa[2];
    double q_net,absolute_duty[2],application_hv[2];
    size_t pressure_clip_hits;
    uint32_t have_finite_duty,red_black[2];
} tpmshx_stage_capture_2d_v1;
/* Saved application properties, separate from thermal geometry.
 * Both arrays use side indices: 0=A, 1=B. */
typedef struct {
    double area_density_per_m[2],surface_htc_W_m2K[2];
} tpmshx_stage_application_2d_v1;

/* Each side supplies cross and stream widths. Bounds are inlet lower/upper,
 * then outlet lower/upper in float64.
 * The stage computes the staggered outlet opening. Leave outlet_u_fraction empty. */
typedef struct {
    tpmshx_preparation_array_v1 cross,stream;
    uint32_t direction;
    double bounds[4];
} tpmshx_stage_saved_flow_grid_2d_v3;
typedef struct {
    tpmshx_preparation_text_v1 name;
    tpmshx_preparation_array_v1 values;
} tpmshx_stage_design_field_2d_v3;
/* Use the original saved domain for the experiment check. Create and
 * restore also check the prepared model, nominal geometry and resolved
 * velocities. The host query defers a side with a configured total flow. */
typedef struct {
    uint32_t topology,geometry_mode,domain_count;
    uint32_t fluids[2],configured_flow[2];
    double domain_m[3],cell_length_mm,wall_thickness_mm,delta_levelset,velocity_m_s[2];
} tpmshx_stage_experiment_2d_v4;

/* Flat validated saved 2D descriptor (abi_version=5, struct_size=sizeof(*)).
 * No preparation operation is performed. prepared->input.geometry_mode selects
 * uniform (0), continuous (1), or discrete spatial (2).
 * Spatial cases supply cell_length and all four cell arrays with nx*ny values.
 * Uniform cases can supply both thermal geometry arrays, with nx*ny values,
 * or leave both empty to use the prepared scalars. Their conductivity arrays
 * must be empty; the saved inlet properties supply the uniform values.
 * inlet_recorded is 0 for absent inlet range evidence and 1 for a recorded set.
 * range_captured has prepared->range_count flags (0 or 1); NULL means all
 * ranges were captured. When have_side_geometry is 1, each row is area,
 * diameter, reference area, reference diameter.
 * experiment is required when prepared->input.df_mode selects experimental D-F. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    const tpmshx_preparation_case_2d_v1* prepared;
    tpmshx_preparation_array_v1 area_density_per_m,hydraulic_diameter_m,fluid_conductivity[2];
    uint32_t inlet_recorded;
    const uint32_t* range_captured;
    uint32_t have_side_geometry;
    double side_geometry[2][4];
    double lengths_m[2];
    tpmshx_stage_saved_flow_grid_2d_v3 flow_grid[2];
    /* Models in the prepared view are in role order: fluid A, fluid B, geometry, drag. */
    tpmshx_preparation_text_v1 resource_fluids[2],resource_topology;
    tpmshx_preparation_sco2_nu_v2 resource_nu[2];
    const tpmshx_stage_design_field_2d_v3* additional_fields;
    size_t additional_count;
    tpmshx_stage_experiment_2d_v4 experiment;
} tpmshx_stage_saved_case_2d_v5;

#ifdef __cplusplus
extern "C" {
#endif
/* Returns TPMSHX_STAGE_RUN_ABI_VERSION_V5 (5). Check at load time before any
 * typed 2D stage run call. */
TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_abi_version(void);
/* A null return indicates an invalid or incomplete result. */
TPMSHX_THERMAL_API const tpmshx_stage_run_records_v1* TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_records_v1(
    const tpmshx_stage_run_result_2d_v1* result);
TPMSHX_THERMAL_API const tpmshx_stage_run_2d_execution_v1* TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_execution_view_v1(
    const tpmshx_stage_run_result_2d_v1* result);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_get_capture_v1(
    const tpmshx_stage_run_result_2d_v1*,const tpmshx_stage_application_2d_v1*,
    tpmshx_stage_capture_2d_v1*);
/* Summarize completed main-grid temperatures by saved zone. Borrow the
 * arrays through this call. Use the result zone query's data and status rules. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_zone_temperatures_v1(
    const tpmshx_result_array_v2 widths[2],const tpmshx_result_labels_v1* labels,
    const tpmshx_result_array_v2 temperatures[3],size_t zone_count,
    tpmshx_result_zone_temperatures_v1* output,double length_m,double height_m,
    const double* x_fractions,size_t nx,double* x_positions,
    const double* y_fractions,size_t ny,double* y_positions,
    tpmshx_result_diagnostics_v1* diagnostics,char* error,size_t error_capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_release_v1(
    tpmshx_stage_run_result_2d_v1*);
/* Produce borrowed solver views for an aligned double mesh. Keep this record
 * and its inputs alive through the solve. On success, uniform thermal views
 * have one value. Spatial views have one value per cell. A zero return leaves
 * the outputs unused. Axis maps contain the physical axes and their inverse. */
typedef struct {
    size_t dimension;
    tpmshx_result_array_v2 widths[3], edges[3];
    double area_density, hydraulic_diameter, porosity, split_a;
    tpmshx_result_array_v2 fields[3], side_geometry[2];
    uint32_t axis_present[2];
    int32_t axes[2][6];
    tpmshx_preparation_array_v1 solver_widths[3], solver_area, solver_diameter;
} tpmshx_stage_mesh_v1;
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_borrow_mesh_v1(tpmshx_stage_mesh_v1* mesh);
/* Return one if both normalized windows fit the physical cross axis. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_port_windows_fit_2d_v1(
    double cross_length_m,double inlet_center_m,double inlet_width_m,double outlet_center_m,double outlet_width_m);
/* Experiment checks return 7 for an unavailable calibration or 8 for a
 * velocity outside its application window. Layout and domain failures return 1. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_check_experiment_v4(
    const tpmshx_stage_experiment_2d_v4*,char*,size_t);
/* Run a saved case. A null request selects current 2D defaults.
 * Control is required. cpu_threads must be positive and result_id must point
 * to a caller-selected label. Keep the descriptor and all borrowed storage
 * unchanged until transfer or release.
 * Status 6 means cancelled. Status 1/2/3/4/5 means invalid input/water state/
 * arithmetic/envelope/native failure. Status 7/8 matches the experiment check.
 * All input, string, result and error storage must be disjoint.
 * Error text is written only after all input storage checks complete.
 * Callback lifetime and exception rules match the existing full 2D API.
 * run_saved_case_2d_v5 runs to completion and transfers the result. Initialize
 * result.abi_version=1, struct_size and owner=NULL. Failure preserves result.
 * The raw result is borrowed. Use its existing evidence queries, but do not
 * release it separately. Release the stage owner through this same library.
 * Create and restore return a run handle. Initialize *run=NULL. Failure
 * preserves it. Callback context must remain valid until release. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_run_saved_case_2d_v5(
    const tpmshx_stage_saved_case_2d_v5*,const tpmshx_stage_run_request_2d_v4*,
    const tpmshx_stage_run_control_v1*,tpmshx_stage_run_result_2d_v1*,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_create_saved_v5(
    const tpmshx_stage_saved_case_2d_v5*,const tpmshx_stage_run_request_2d_v4*,
    const tpmshx_stage_run_control_v1*,void**,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_restore_saved_v5(
    const tpmshx_stage_saved_case_2d_v5*,const tpmshx_stage_run_request_2d_v4*,
    const tpmshx_stage_run_control_v1*,const tpmshx_run_state_field_v1*,size_t,void**,char*,size_t);
/* Phases and safe snapshot boundaries match full_2d_run_c_api.h.
 * Snapshots own independent storage; use tpmshx_run_state_release_v1. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_advance_step_v1(void*,uint32_t*,char*,size_t);
/* Advance to completion or cancellation with the registered callbacks. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_finish_v1(void*,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_phase_v1(const void*,uint32_t*);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_snapshot_v1(
    const void*,tpmshx_run_state_v1*,char*,size_t);
/* Transfer one completed result. A cancelled run returns 6 without output.
 * Initialize the output as for run_saved_case. Release it with stage_run_2d_release.
 * All raw queries and releases must use this same library. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_take_result_v1(
    void*,tpmshx_stage_run_result_2d_v1*,char*,size_t);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_release_run_v1(void**);
/* Borrow the scalar execution report until result release. Cell and face arrays
 * stay in their typed views. NULL means that no report is available. */
TPMSHX_THERMAL_API const char* TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_report_v1(
    const tpmshx_stage_run_result_2d_v1*, char* error, size_t capacity);
#ifdef __cplusplus
}
#endif
#endif
