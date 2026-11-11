#ifndef TPMSHX_STAGE_RUN_C_API_H
#define TPMSHX_STAGE_RUN_C_API_H
#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/full_2d_c_api.h"
#include "tpmshx/result_stage_c_api.h"

#define TPMSHX_STAGE_RUN_ABI_VERSION 1u

typedef struct { uint32_t present; size_t value; } tpmshx_stage_size_option_v1;
typedef struct { uint32_t present; double value; } tpmshx_stage_double_option_v1;
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
 * Callback lifetime and exception rules match the existing full 2D API.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_run_case_2d_v1(
    const tpmshx_preparation_case_2d_v1*,const tpmshx_stage_run_request_2d_v1*,
    const tpmshx_stage_run_control_v1*,tpmshx_stage_run_result_2d_v1*,char*,size_t);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_stage_run_2d_release_v1(
    tpmshx_stage_run_result_2d_v1*);
#ifdef __cplusplus
}
#endif
#endif
