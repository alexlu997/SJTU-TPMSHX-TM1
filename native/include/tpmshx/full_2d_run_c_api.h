#ifndef TPMSHX_FULL_2D_RUN_C_API_H
#define TPMSHX_FULL_2D_RUN_C_API_H
#include "tpmshx/full_2d_c_api.h"
#include "tpmshx/run_state_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif

enum {
    TPMSHX_FULL2D_CREATED=0,TPMSHX_FULL2D_OUTER_BOUNDARY=1,TPMSHX_FULL2D_READY=2,
    TPMSHX_FULL2D_COMPLETED=3,TPMSHX_FULL2D_CANCELLED=4,TPMSHX_FULL2D_FAILED=5,
    TPMSHX_FULL2D_FLOW=6,TPMSHX_FULL2D_THERMAL=7,TPMSHX_FULL2D_REFINEMENT=8
};

/* Creation copies the 29 prepared arrays, controls and callback table.
 * Callbacks and their context must remain valid until run release.
 * Calls on one run must not overlap. Error codes match the one-shot API.
 * Optional energy arguments retain their v3/v4 contracts; model-h uses v5.
 * Output handles must be null. Errors do not replace output handles.
 * Restore copies typed state and requires the same build, input and controls.
 * Host paths can differ. Restore does not reset consumed work. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_create_v1(
    const size_t* shape,const double* const* arrays,const size_t* sizes,
    const tpmshx_full_2d_config_v2*,const tpmshx_energy_options_v1*,
    const tpmshx_full_2d_energy_control_v4*,const tpmshx_model_h_iteration_options_v1*,
    const tpmshx_full_2d_callbacks_v2*,void** run,char* error,size_t capacity);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_restore_v1(
    const size_t* shape,const double* const* arrays,const size_t* sizes,
    const tpmshx_full_2d_config_v2*,const tpmshx_energy_options_v1*,
    const tpmshx_full_2d_energy_control_v4*,const tpmshx_model_h_iteration_options_v1*,
    const tpmshx_full_2d_callbacks_v2*,const tpmshx_run_state_field_v1*,size_t count,void** run,char* error,size_t capacity);
/* Advance completes initialization, one outer step, or refinement and capture.
 * Failed and cancelled runs cannot produce a new checkpoint. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_advance_v1(
    void* run,uint32_t* phase,char* error,size_t capacity);
/* Advance both SIMPLE sides by one complete step, one thermal block,
 * or one controller transition. Refined thermal blocks are included. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_advance_step_v1(
    void* run,uint32_t* phase,char* error,size_t capacity);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_phase_v1(const void* run,uint32_t* phase);
/* Snapshots own their fields independently. Release them with run_state_release.
 * Strings contain UTF-8 bytes; their counts exclude the terminator. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_snapshot_v1(
    const void* run,tpmshx_run_state_v1*,char* error,size_t capacity);
/* Transfer a completed or cancelled result once. Existing result release and
 * evidence queries remain valid after run release. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_take_result_v1(
    void* run,tpmshx_full_2d_result_v2*,char* error,size_t capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_full_2d_run_release_v1(void** run);
#ifdef __cplusplus
}
#endif
#endif
