#ifndef TPMSHX_STAGE_RUN_C_API_H
#define TPMSHX_STAGE_RUN_C_API_H
#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/full_2d_c_api.h"
#include "tpmshx/full_2d_run_c_api.h"
#include "tpmshx/result_stage_c_api.h"

#define TPMSHX_STAGE_RUN_ABI_VERSION 1u
#define TPMSHX_STAGE_RUN_ABI_VERSION_V2 2u
#define TPMSHX_STAGE_RUN_ABI_VERSION_V3 3u

typedef struct { uint32_t present; size_t value; } tpmshx_stage_size_option_v1;
typedef struct { uint32_t present; double value; } tpmshx_stage_double_option_v1;
/* For prepared views, active model_h controls and an energy pointer are exclusive.
 * A null energy pointer keeps the defaults for the selected thermal route. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_stage_size_option_v1 max_iter_simple,max_outer_ltne;
    tpmshx_stage_double_option_v1 outer_tol_K,simple_velocity_relaxation;
    tpmshx_stage_double_option_v1 mom_tol,mass_local_tol,mass_global_tol,solid_seed_K;
    uint32_t have_pressure_shooting,pressure_shooting;
    const char* convergence_mode;
    tpmshx_model_h_iteration_options_v1 model_h;
    const tpmshx_energy_options_v1* energy;
    const tpmshx_full_2d_energy_control_v4* explicit_energy;
} tpmshx_stage_run_request_2d_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_stage_run_request_2d_v1 values;
    const char* envelope_mode;
} tpmshx_stage_run_request_2d_v2;
/* Partial controls use defaults from this library. They cannot be combined
 * with values.values.explicit_energy or active model_h controls. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    tpmshx_stage_run_request_2d_v2 values;
    tpmshx_stage_size_option_v1 energy_iterations,energy_sweeps;
    tpmshx_stage_double_option_v1 energy_omega,energy_update_tolerance;
    tpmshx_stage_double_option_v1 energy_coupled_tolerance,energy_equation_tolerance;
    uint32_t require_enthalpy_update_on_temperature;
} tpmshx_stage_run_request_2d_v3;
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
/* Validated saved inputs. No preparation operation is performed.
 * prepared->values.input.geometry_mode selects uniform (0) or continuous (1).
 * Continuous cases supply cell_length and all four arrays with nx*ny values.
 * Uniform cases can supply both thermal geometry arrays, with nx*ny values,
 * or leave both empty to use the prepared scalars. Their conductivity arrays
 * must be empty; the saved inlet properties supply the uniform values.
 * Saved local drag uses the existing full 2D validation. inlet_recorded is 0
 * for absent inlet range evidence and 1 for a recorded set, including empty.
 * range_captured has prepared->values.range_count flags (0 or 1). NULL means
 * all ranges were captured. Uncaptured ranges do not supply sample values.
 * Kinds retain saved SI scalar/array precision through unit conversion and
 * closure-ratio arithmetic. Use precision 16/32/64, strong 0/1 for floating
 * values, or strong 2 with precision 8/16/32/64 for integers. Layout 0/1/2
 * denotes Python scalar, NumPy scalar, or array, as in preparation kinds. */
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    const tpmshx_preparation_case_2d_v2* prepared;
    tpmshx_preparation_array_v1 area_density_per_m,hydraulic_diameter_m,fluid_conductivity[2];
    uint32_t inlet_recorded;
    const uint32_t* range_captured;
    tpmshx_preparation_scalar_kind_v2 reference_cell_kind,cell_field_kind,hydraulic_diameter_kind;
} tpmshx_stage_saved_case_2d_v1;

#ifdef __cplusplus
extern "C" {
#endif
/* The first stage accepts prepared uniform symmetric 2D air/air cases.
 * A null request selects current 2D defaults. Control is required; cpu_threads
 * must be positive and result_id must point to a caller-selected label.
 * The call copies all result storage. The prepared owner can then be released.
 * Initialize result.abi_version, struct_size and owner=NULL. Failure preserves
 * result. Cancellation returns status 4 and does not publish a result.
 * The raw result is borrowed. Use its existing evidence queries, but do not
 * release it separately. Release the stage owner through this same library.
 * Inputs, strings, result and error storage must be disjoint.
 * Error text is written only after all input storage checks complete.
 * Callback lifetime and exception rules match the existing full 2D API.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_run_case_2d_v1(
    const tpmshx_preparation_case_2d_v1*,const tpmshx_stage_run_request_2d_v1*,
    const tpmshx_stage_run_control_v1*,tpmshx_stage_run_result_2d_v1*,char*,size_t);
/* V2 consumes uniform symmetric four-fluid preparation. It uses the current
 * model-h or true-h route and its existing defaults. The optional request
 * retains v1 values and selects envelope_mode; NULL means "raise".
 * Output keeps the v1 layout and release function. Status 6 means cancelled.
 * Status 1/2/3/4/5 means invalid input/water state/arithmetic/envelope/native
 * failure. All input, string, result and error storage must be disjoint.
 * Error text is written only after all input storage checks complete.
 * Failure preserves result. The same lifetime rules apply as for v1. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_run_case_2d_v2(
    const tpmshx_preparation_case_2d_v2*,const tpmshx_stage_run_request_2d_v2*,
    const tpmshx_stage_run_control_v1*,tpmshx_stage_run_result_2d_v1*,char*,size_t);
/* V3 consumes continuous preparation v4, including resolved fixed flow.
 * It uses physical cell geometry and local drag without another preparation.
 * The request, status, output, storage and lifetime rules are the same as v2.
 * Preparation controls and flow-resolution evidence are not used by run. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_run_case_2d_v3(
    const tpmshx_preparation_continuous_case_2d_v4*,const tpmshx_stage_run_request_2d_v2*,
    const tpmshx_stage_run_control_v1*,tpmshx_stage_run_result_2d_v1*,char*,size_t);
/* Copy derived scalars from a live result created by this library.
 * Application inputs retain the existing nonnegative check and IEEE arithmetic.
 * Result, application and output storage must be disjoint. Failure preserves
 * output. Status 1 means invalid input; status 5 means capture failure.
 * No arrays or strings are owned by the copied summary. Existing raw evidence
 * queries still supply the complete fields, histories and numerical ledgers. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_get_capture_v1(
    const tpmshx_stage_run_result_2d_v1*,const tpmshx_stage_application_2d_v1*,
    tpmshx_stage_capture_2d_v1*);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_release_v1(
    tpmshx_stage_run_result_2d_v1*);
/* Supply exactly one preparation view: uniform v2 or continuous v4.
 * The run borrows this view and its storage until take_result or release.
 * Keep that storage unchanged. Controls and numerical inputs are copied.
 * Callback context must remain valid until release. Calls must not overlap.
 * Initialize *run=NULL. Failure preserves it. Create/restore retain the v2
 * status and storage rules. Restore uses the existing typed full 2D state,
 * build identity and validation. A positive CPU limit can change on restore. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_create_v1(
    const tpmshx_preparation_case_2d_v2*,const tpmshx_preparation_continuous_case_2d_v4*,
    const tpmshx_stage_run_request_2d_v3*,const tpmshx_stage_run_control_v1*,void**,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_restore_v1(
    const tpmshx_preparation_case_2d_v2*,const tpmshx_preparation_continuous_case_2d_v4*,
    const tpmshx_stage_run_request_2d_v3*,const tpmshx_stage_run_control_v1*,
    const tpmshx_run_state_field_v1*,size_t,void**,char*,size_t);
/* Saved views use the same lifecycle, status, storage and restore rules.
 * Keep this descriptor and all referenced storage unchanged until transfer
 * or release. Set abi_version=1 and struct_size=sizeof this descriptor.
 * With model_h controls, request.energy records the requested algorithm for
 * validation only. It is not passed as a second set of iteration controls. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_create_saved_v1(
    const tpmshx_stage_saved_case_2d_v1*,const tpmshx_stage_run_request_2d_v3*,
    const tpmshx_stage_run_control_v1*,void**,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_restore_saved_v1(
    const tpmshx_stage_saved_case_2d_v1*,const tpmshx_stage_run_request_2d_v3*,
    const tpmshx_stage_run_control_v1*,const tpmshx_run_state_field_v1*,size_t,void**,char*,size_t);
/* Phases and safe snapshot boundaries match full_2d_run_c_api.h.
 * Snapshots own independent storage; use tpmshx_run_state_release_v1. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_advance_step_v1(void*,uint32_t*,char*,size_t);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_phase_v1(const void*,uint32_t*);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_snapshot_v1(
    const void*,tpmshx_run_state_v1*,char*,size_t);
/* Transfer one completed result. A cancelled run returns 6 without output.
 * Initialize the output as for run_case. Release it with stage_run_2d_release.
 * All raw queries and releases must use this same library. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_take_result_v1(
    void*,tpmshx_stage_run_result_2d_v1*,char*,size_t);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_release_run_v1(void**);
#ifdef __cplusplus
}
#endif
#endif
