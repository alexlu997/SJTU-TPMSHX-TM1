#ifndef TPMSHX_STAGE_RUN_3D_C_API_H
#define TPMSHX_STAGE_RUN_3D_C_API_H
#include "tpmshx/stage_run_c_api.h"
#include "tpmshx/preparation_case_3d_c_api.h"
#include "tpmshx/full_3d_run_c_api.h"

#define TPMSHX_STAGE_RUN_3D_ABI_VERSION 1u

typedef struct { uint32_t present,value; } tpmshx_stage_uint_option_v1;
/* Absent values select the current application defaults, not the low-level
 * Full3DControl defaults. Thermal iterations default to 20000. Supply a saved
 * budget, such as 50000, explicitly. This operation never changes the grid.
 * max_iter_simple overrides both initial (2000) and warm (600) budgets.
 * Null energy selects T-SOU. Model-h overrides and EOS overrides are exclusive.
 * Boolean values are 0/1. roughness_mode is 0/1/2; envelope_mode is 0/1/2.
 * Host environment choices must be resolved before this call. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_stage_size_option_v1 max_iter_simple,max_outer_ltne,thermal_iterations;
    tpmshx_stage_size_option_v1 coarse_iterations,parallel_threshold;
    tpmshx_stage_double_option_v1 outer_tol_K,thermal_relaxation,simple_velocity_relaxation;
    tpmshx_stage_double_option_v1 mom_tol,mass_local_tol,mass_global_tol,solid_seed_K,roughness_height_m;
    tpmshx_stage_uint_option_v1 pressure_shooting,variable_rho_cp,conservative;
    tpmshx_stage_uint_option_v1 strict_mass_balance,force_cell_centered,refined_port_energy;
    tpmshx_stage_uint_option_v1 sco2_local_pressure_a,coarse_bootstrap,adaptive_pressure_tolerance,track_momentum;
    tpmshx_stage_uint_option_v1 roughness_mode,envelope_mode;
    const char* convergence_mode;
    tpmshx_model_h_iteration_options_v1 model_h;
    const tpmshx_energy_options_v1* energy;
    tpmshx_stage_size_option_v1 energy_iterations,energy_sweeps;
    tpmshx_stage_double_option_v1 energy_omega,energy_update_tolerance;
    tpmshx_stage_double_option_v1 energy_coupled_tolerance,energy_equation_tolerance;
    uint32_t require_enthalpy_update_on_temperature;
} tpmshx_stage_run_request_3d_v1;
typedef struct {
    const char* result_id;
    const char* table_directory;
    size_t cpu_threads;
    tpmshx_full3d_callbacks_v1 callbacks;
} tpmshx_stage_run_control_3d_v1;
/* Validated saved inputs in the existing physical XYZ/SI convention.
 * No raw preparation or geometry calculation is performed. The nominal values
 * and wall field supply recorded scope evidence; they do not replace input
 * geometry. inlet_recorded distinguishes absent evidence from a recorded empty
 * set. range_captured has preparation.range_count flags; NULL means all recorded.
 * All referenced storage stays unchanged until result transfer or run release. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    const tpmshx_full3d_input_v1* input;
    double nominal_cell_length_mm,nominal_wall_thickness_mm,nominal_porosity;
    tpmshx_preparation_array_v1 wall_thickness_m;
    tpmshx_preparation_flow_evidence_v3 preparation;
    const tpmshx_preparation_text_v1* notices;
    size_t notice_count;
    uint32_t inlet_recorded;
    const uint32_t* range_captured;
} tpmshx_stage_saved_case_3d_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    void* owner;
    tpmshx_full3d_result_v1 raw;
    tpmshx_result_evidence_v1 evidence;
    tpmshx_full3d_control_v1 resolved;
    tpmshx_stage_input_v2 evaluation;
} tpmshx_stage_run_result_3d_v1;

#ifdef __cplusplus
extern "C" {
#endif
/* Supply exactly one prepared view. Uniform includes the nested prepared view
 * from fixed-flow v2. Continuous v3 and spatial v4 keep their extra geometry.
 * Preparation is borrowed until transfer or release; numerical run inputs and
 * controls are copied. Callback functions/context stay valid until release.
 * Calls on one run must not overlap. Control requires a positive CPU limit and
 * result label. A null request selects defaults. Initialize *run=NULL.
 * Output and error storage must not overlap inputs or each other.
 * Immutable input arrays can share storage.
 * Storage checks precede error writes. Failure preserves caller output.
 * Status 1/2/3/4 means invalid input/water state/arithmetic/native failure. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_create_v1(
    const tpmshx_preparation_case_3d_v1*,const tpmshx_preparation_continuous_case_3d_v3*,
    const tpmshx_preparation_spatial_case_3d_v4*,const tpmshx_stage_run_request_3d_v1*,
    const tpmshx_stage_run_control_3d_v1*,void**,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_restore_v1(
    const tpmshx_preparation_case_3d_v1*,const tpmshx_preparation_continuous_case_3d_v3*,
    const tpmshx_preparation_spatial_case_3d_v4*,const tpmshx_stage_run_request_3d_v1*,
    const tpmshx_stage_run_control_3d_v1*,const tpmshx_run_state_field_v1*,size_t,void**,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_create_saved_v1(
    const tpmshx_stage_saved_case_3d_v1*,const tpmshx_stage_run_request_3d_v1*,
    const tpmshx_stage_run_control_3d_v1*,void**,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_restore_saved_v1(
    const tpmshx_stage_saved_case_3d_v1*,const tpmshx_stage_run_request_3d_v1*,
    const tpmshx_stage_run_control_3d_v1*,const tpmshx_run_state_field_v1*,size_t,void**,char*,size_t);
/* Phases, safe boundaries and archive identity match full_3d_run_c_api.h.
 * Restore can change the positive CPU limit. Snapshots own independent storage;
 * release them with tpmshx_run_state_release_v1. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_advance_step_v1(void*,uint32_t*,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_phase_v1(const void*,uint32_t*);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_snapshot_v1(
    const void*,tpmshx_run_state_v1*,char*,size_t);
/* Transfer a completed or cancelled result once. Initialize abi_version,
 * struct_size and owner=NULL. raw.stop=2 retains cancellation diagnostics but
 * evidence.abi_version=0: no completed evaluation evidence is published.
 * Use evaluation with result_stage_query_v2 for complete status and reasons.
 * The v1 evidence view cannot represent an explicitly absent mass-face record.
 * evaluation and all its views share this result owner.
 * All raw evidence queries use this library. raw is borrowed; never release it
 * separately. The result survives preparation and run release. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_take_result_v1(
    void*,tpmshx_stage_run_result_3d_v1*,char*,size_t);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_release_run_v1(void**);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_release_v1(tpmshx_stage_run_result_3d_v1*);
/* One-shot execution uses create, advance_step and take_result on the same owner.
 * Status 0 reports transfer, not convergence. Check raw.stop and raw.converged. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_run_case_3d_v1(
    const tpmshx_preparation_case_3d_v1*,const tpmshx_preparation_continuous_case_3d_v3*,
    const tpmshx_preparation_spatial_case_3d_v4*,const tpmshx_stage_run_request_3d_v1*,
    const tpmshx_stage_run_control_3d_v1*,tpmshx_stage_run_result_3d_v1*,char*,size_t);
#ifdef __cplusplus
}
#endif
#endif
