#pragma once
// Library-internal C entries behind the saved-stage and Quick Design stage
// APIs. The shared solver image does not export these names. Each definition
// includes this header, so a signature change fails to compile.
#include "tpmshx/full_2d_run_c_api.h"
#include "tpmshx/full_3d_run_c_api.h"
#include "tpmshx/solver_c_api.h"

extern "C" {
/* Complete prepared Quick Design solve. SI: K, Pa(abs), kg/s, m, m2/m3,
 * W/(m K), J/(kg K). shape[3] = nx, ny, nz; arrays[9] and sizes[9] contain
 * contiguous C-order doubles: dx, dy, dz, epsilon, epsilon_A, K_ss, T_A, T_B, T_s.
 * Only the final three arrays are mutable. Each size is an element count.
 * epsilon, epsilon_A and K_ss must be uniform, epsilon_A=epsilon/2.
 * The current QD policy uses one const pass or exactly two mean passes.
 * Prepared pressure fractions are retained, including choked values >=1.
 * max/chunk iterations are resolved positive budgets per property pass.
 * For nz=1 alpha must be 0.7; nz>1 uses the 3D temperature scheme.
 * TPMSHX_OK means execution returned; inspect result.stop for convergence.
 * Only passes below completed_passes are valid. On any nonzero error code,
 * result is left untouched and mutable arrays may be partial.
 */
int TPMSHX_THERMAL_CALL tpmshx_solve_quick_design_v1(
    const size_t* shape, double* const* arrays, const size_t* sizes,
    const tpmshx_qd_config_v1* config, const tpmshx_callbacks_v1* callbacks,
    tpmshx_qd_result_v1* result, char* error, size_t error_capacity);

/* Full 2D run. shape[2]=(nx,ny). Creation copies the 29 prepared arrays,
 * controls and callback table:
 *   dx,dy,dz={1},KffA,KffB,Kss,total_epsilon,A0,Dh,cell_length,
 *   for each side A,B:
 *     row_K,row_cF,optional_full_K,optional_full_cF,inlet_geometry,
 *     outlet_geometry,inlet_profile,outlet_profile,outlet_u_fraction.
 *   followed by the per-cell Nu geometry ratio (Dh_m * 1000) / cell_length_mm.
 * Full K/cF use +y SIMPLE coordinates; thermal arrays use physical x/y.
 * energy, explicit_energy and model_h are optional; supply a maximum of one.
 * Status: 0 returned, 1 invalid argument, 2 water state, 3 arithmetic,
 * 4 envelope, 5 other native exception. Error is required and bounded.
 * Output handles must be null. Restore requires the same build, input and
 * controls. Calls on one run must not overlap. No C++ exception crosses C.
 * A taken result owns its views until tpmshx_full_2d_release_v2. */
int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_create_v2(const size_t* shape,const double* const* arrays,const size_t* sizes,
    const tpmshx_full_2d_config_v2* config,const tpmshx_energy_options_v1* energy,
    const tpmshx_full_2d_energy_control_v4* explicit_energy,
    const tpmshx_model_h_iteration_options_v1* model_h,
    size_t cpu_threads,const tpmshx_full_2d_callbacks_v2* callbacks,void** run,char* error,size_t capacity);
int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_restore_v2(const size_t* shape,const double* const* arrays,const size_t* sizes,
    const tpmshx_full_2d_config_v2* config,const tpmshx_energy_options_v1* energy,
    const tpmshx_full_2d_energy_control_v4* explicit_energy,
    const tpmshx_model_h_iteration_options_v1* model_h,
    size_t cpu_threads,const tpmshx_full_2d_callbacks_v2* callbacks,
    const tpmshx_run_state_field_v1* fields,size_t count,void** run,char* error,size_t capacity);
/* Advance both SIMPLE sides by one complete step, one thermal block,
 * or one controller transition. Refined thermal blocks are included. */
int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_advance_step_v1(void* run,uint32_t* phase,char* error,size_t capacity);
int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_phase_v1(const void* run,uint32_t* phase);
int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_snapshot_v1(
    const void* run,tpmshx_run_state_v1* state,char* error,size_t capacity);
/* Transfer a completed or cancelled result once. */
int TPMSHX_THERMAL_CALL tpmshx_full_2d_run_take_result_v1(
    void* run,tpmshx_full_2d_result_v2* result,char* error,size_t capacity);
void TPMSHX_THERMAL_CALL tpmshx_full_2d_run_release_v1(void** run);
/* Release clears the struct and accepts NULL or an already cleared result. */
void TPMSHX_THERMAL_CALL tpmshx_full_2d_release_v2(tpmshx_full_2d_result_v2* result);

/* Full 3D run. Creation copies all prepared arrays, controls and the callback
 * table. Full immutable fields, physical port rectangles and D-F application
 * scales are mandatory. Sources are optional empty arrays. SIMPLE controls
 * preserve their v1 meaning except max_iterations/reference/ideal_gas, which
 * the outer driver owns. The optional energy argument uses strict finite,
 * positive thresholds and requires the two-sided true-h route. Optional
 * model_h adds integral h(T) controls and cannot be combined with energy.
 * Status: 0 returned, 1 invalid input, 2 water phase, 3 arithmetic,
 * 4 native error. Output handles must be null. Restore requires the same
 * build, input and controls. Calls on one run must not overlap.
 * A taken result owns its views until tpmshx_full_3d_release_v1. */
int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_create_v3(
    const tpmshx_full3d_input_v1* in,const tpmshx_full3d_control_v1* c,const tpmshx_energy_options_v2* energy,
    const tpmshx_model_h_iteration_options_v1* model_h,size_t cpu_threads,const tpmshx_full3d_callbacks_v1* callbacks,void** run,char* error,size_t capacity);
int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_restore_v3(
    const tpmshx_full3d_input_v1* in,const tpmshx_full3d_control_v1* c,const tpmshx_energy_options_v2* energy,
    const tpmshx_model_h_iteration_options_v1* model_h,size_t cpu_threads,const tpmshx_full3d_callbacks_v1* callbacks,const tpmshx_run_state_field_v1* fields,size_t count,
    void** run,char* error,size_t capacity);
/* Advance one complete SIMPLE step, thermal block, or controller transition.
 * Coarse bootstrap stays atomic before its fine SIMPLE boundary. */
int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_advance_step_v1(void* run,uint32_t* phase,char* error,size_t capacity);
int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_phase_v1(const void* run,uint32_t* phase);
int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_snapshot_v1(
    const void* run,tpmshx_run_state_v1* state,char* error,size_t capacity);
/* Transfer the completed or cancelled result once. */
int TPMSHX_THERMAL_CALL tpmshx_full_3d_run_take_result_v1(
    void* run,tpmshx_full3d_result_v1* result,char* error,size_t capacity);
void TPMSHX_THERMAL_CALL tpmshx_full_3d_run_release_v1(void** run);
/* Release accepts NULL or an already cleared result and clears the entire POD. */
void TPMSHX_THERMAL_CALL tpmshx_full_3d_release_v1(tpmshx_full3d_result_v1* result);
}
