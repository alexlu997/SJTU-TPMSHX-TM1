#ifndef TPMSHX_FULL_3D_RUN_C_API_H
#define TPMSHX_FULL_3D_RUN_C_API_H
#include "tpmshx/full_3d_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif

enum {
    TPMSHX_RUN_STATE_F64=0,TPMSHX_RUN_STATE_U64=1,TPMSHX_RUN_STATE_I64=2,
    TPMSHX_RUN_STATE_U8=3,TPMSHX_RUN_STATE_UTF8=4
};
enum {
    TPMSHX_FULL3D_CREATED=0,TPMSHX_FULL3D_OUTER_BOUNDARY=1,TPMSHX_FULL3D_READY=2,
    TPMSHX_FULL3D_COMPLETED=3,TPMSHX_FULL3D_CANCELLED=4,TPMSHX_FULL3D_FAILED=5,
    TPMSHX_FULL3D_INITIAL_A=6,TPMSHX_FULL3D_INITIAL_B=7,TPMSHX_FULL3D_THERMAL=8,
    TPMSHX_FULL3D_POST_A=9,TPMSHX_FULL3D_POST_B=10
};
typedef struct {
    const char* name;
    uint32_t type;
    const void* data;
    size_t count;
} tpmshx_run_state_field_v1;
typedef struct {
    const tpmshx_run_state_field_v1* fields;
    size_t count;
    void* owner;
} tpmshx_run_state_v1;

/* Creation copies all prepared arrays, controls and the callback table.
 * Callback functions and their context must stay valid until run release.
 * Calls on one run must not overlap. Status codes match the one-shot API.
 * An optional energy argument has the full_3d_v3 strict-control contract.
 * Output handles must be null. Errors do not replace output handles.
 * Restore copies the typed fields and requires exact build, input and controls.
 * It does not reset counters or rerun initialization. Host paths can differ. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_create_v1(
    const tpmshx_full3d_input_v1*,const tpmshx_full3d_control_v1*,const tpmshx_energy_options_v2*,
    const tpmshx_full3d_callbacks_v1*,void** run,char* error,size_t capacity);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_restore_v1(
    const tpmshx_full3d_input_v1*,const tpmshx_full3d_control_v1*,const tpmshx_energy_options_v2*,
    const tpmshx_full3d_callbacks_v1*,const tpmshx_run_state_field_v1*,size_t count,
    void** run,char* error,size_t capacity);
/* Add integral h(T) controls to the same run owner. Null keeps route defaults.
 * Active model-h options cannot be combined with EOS energy options.
 * Restore requires the same overrides and retains actual call records. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_create_v2(
    const tpmshx_full3d_input_v1*,const tpmshx_full3d_control_v1*,const tpmshx_energy_options_v2*,
    const tpmshx_model_h_iteration_options_v1*,const tpmshx_full3d_callbacks_v1*,
    void** run,char* error,size_t capacity);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_restore_v2(
    const tpmshx_full3d_input_v1*,const tpmshx_full3d_control_v1*,const tpmshx_energy_options_v2*,
    const tpmshx_model_h_iteration_options_v1*,const tpmshx_full3d_callbacks_v1*,
    const tpmshx_run_state_field_v1*,size_t count,void** run,char* error,size_t capacity);
/* Advance completes initialization, one outer step, or final result capture.
 * A cancelled or failed run cannot produce a new checkpoint.
 * A failed advance leaves its phase readable as FAILED. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_advance_v1(
    void* run,uint32_t* phase,char* error,size_t capacity);
/* Advance one complete SIMPLE step, thermal block, or controller transition.
 * Coarse bootstrap stays atomic before its fine SIMPLE boundary.
 * The same owner serves both advance entries. All active phases can be saved. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_advance_step_v1(
    void* run,uint32_t* phase,char* error,size_t capacity);
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_phase_v1(const void* run,uint32_t* phase);
/* Snapshot fields are independent of the run. Copy or persist them before
 * snapshot release. The release operations accept a null owner repeatedly.
 * String counts are UTF-8 bytes; the terminator is not included. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_snapshot_v1(
    const void* run,tpmshx_run_state_v1* state,char* error,size_t capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_run_state_release_v1(tpmshx_run_state_v1*);
/* Transfer the completed or cancelled result once. Its existing release and
 * evidence queries remain valid after the run handle is released. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_take_result_v1(
    void* run,tpmshx_full3d_result_v1* result,char* error,size_t capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_full_3d_run_release_v1(void** run);
#ifdef __cplusplus
}
#endif
#endif
