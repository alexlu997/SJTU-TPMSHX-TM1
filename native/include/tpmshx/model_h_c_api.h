#ifndef TPMSHX_MODEL_H_C_API_H
#define TPMSHX_MODEL_H_C_API_H
#include "tpmshx/thermal_c_api.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TPMSHX_MODEL_H_ABI_VERSION 1u

typedef struct { const double* data; size_t size; } tpmshx_model_h_array_v1;
typedef struct {
    uint32_t dimension, fluid_a, fluid_b, direction_a, direction_b;
    uint32_t warm_start, accelerate, red_black;
    size_t max_iterations, chunk_iterations;
    double inlet_a, inlet_b, q_relative_tolerance, alpha_a, alpha_solid, alpha_b;
} tpmshx_model_h_config_v1;
typedef struct {
    int (TPMSHX_THERMAL_CALL *cancel)(void*);
    void (TPMSHX_THERMAL_CALL *progress)(void*,size_t,size_t);
    void* context;
} tpmshx_model_h_callbacks_v1;

typedef struct {
    double q_advective,inlet_conduction,exchange;
    double residual_sum,residual_max,linearized_sum,linearized_max;
    double defect_sum,defect_max,mass_net,mass_local_max,mass_in,mass_out;
    double normalization,cell_ratio;
    size_t unknown_inflow_faces;
    double cp_coefficients[5];
    tpmshx_model_h_array_v1 boundary_mass_out[4],boundary_h_out[4],h_faces[2];
    tpmshx_model_h_array_v1 inlet_conduction_faces,residual,linearization_defect;
} tpmshx_model_h_side_2d_v1;
typedef struct {
    tpmshx_model_h_side_2d_v1 sides[2];
    double solid_sum,solid_max,solid_cell_ratio,residual_sum,telescoping_error;
    double net_boundary_in,denominator,energy_imbalance,solid_imbalance;
    uint32_t boundary_complete,finite,energy_ok,solid_ok,equations_ok,passed;
    tpmshx_model_h_array_v1 solid_residual;
} tpmshx_model_h_audit_2d_v1;

typedef struct {
    double mass_out,enthalpy_out,unknown_mass_in,inlet_reverse_mass_out;
    size_t unknown_inflow_count;
    tpmshx_model_h_array_v1 enthalpy_faces;
} tpmshx_model_h_boundary_3d_v1;
typedef struct {
    tpmshx_model_h_boundary_3d_v1 boundaries[6];
    double cp_coefficients[5];
    double temperature_min,temperature_max,mass_net;
    double advective_in,diffusion_in,numerical_external_in,exchange,source;
    double residual_sum,residual_max,normalization,global_ratio,cell_ratio;
    uint32_t boundary_complete;
    tpmshx_model_h_array_v1 residual,inlet_diffusion;
} tpmshx_model_h_side_3d_v1;
typedef struct {
    tpmshx_model_h_side_3d_v1 sides[2];
    double volume,numerical_external_in,explicit_source,solid_sum,solid_max;
    double full_residual_sum,telescoping_error,ltne_source_ratio;
    uint32_t boundary_complete,gates[6],passed;
    tpmshx_model_h_array_v1 solid_residual;
} tpmshx_model_h_audit_3d_v1;

typedef struct {
    size_t iterations;
    /* 2D: passed,equations_ok in [0:2]. 3D: original six phase2a gates. */
    uint32_t gates[6];
} tpmshx_model_h_check_v1;
typedef struct {
    uint32_t dimension,stop,audit_available,has_sources;
    size_t iterations;
    double residual,q_b;
    tpmshx_model_h_audit_2d_v1 plane;
    tpmshx_model_h_audit_3d_v1 volume;
    const tpmshx_model_h_check_v1* finishing_checks;
    size_t finishing_count;
    void* owner;  /* private; release with tpmshx_model_h_release_v1 */
} tpmshx_model_h_result_v1;

TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_model_h_abi_version(void);

/* Complete fixed-flow thermal solve. No EOS/flow/outer coupling is performed.
 * dimension=2 requires nz=1,dz[0]=1 and air/water sides. dimension=3 requires
 * nz>1 and AA/AW/WA. Grid and all fields use C order. Arrays[24]/sizes[24]:
 *  dx,dy,dz,Kss,source_s,
 *  Ka,hva,mass_a_x,mass_a_y,mass_a_z,profile_a,opening_a,source_a,
 *  Kb,hvb,mass_b_x,mass_b_y,mass_b_z,profile_b,opening_b,source_b,
 *  Ta,Tb,Ts.
 * Optional empty profiles/openings mean scalar Tin/full inlet. Sources may
 * be empty for zero. 2D requires empty z masses and all source arrays.
 * Only Ta/Tb/Ts are mutated. Every array is borrowed until return, immutable
 * through callbacks except those three state buffers. Array/control/result/
 * error storage must not overlap mutable state or one another. A pointer
 * cannot prove allocation size. Callbacks run synchronously and must not throw.
 * Alpha values in2D must be(.2,1,.2); 3D retains explicit alpha in(0,1] and
 * caps fluid alpha at the current generated model-h relaxation.
 *
 * stop:0converged,1budget exhausted,2cancelled. Status/error return:0normal,
 * 1invalid argument,2arithmetic failure,3native exception. Nonzero return
 * leaves result untouched; state may be partial and must be discarded.
 * Cancellation returns no audit and its fields must also be discarded.
 * error is required, positive capacity, always bounded/NUL terminated.
 *
 * On normal return, result owns read-only audit arrays until release. Only
 * plane or volume matching dimension is valid and only if audit_available.
 * Duties/residuals are W/m in2D, W in3D; mass is kg/(s m) or kg/s. Inputs
 * need not remain alive to use these owned audit views. Do not copy owner
 * handles or free views. Release every normal result, including cancelled,
 * before reusing its struct. Release clears it and accepts an already-cleared
 * result. No C++ exception crosses either entry point.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_model_h_v1(
    const size_t* shape,double* const* arrays,const size_t* sizes,
    const tpmshx_model_h_config_v1* config,const tpmshx_model_h_callbacks_v1* callbacks,
    tpmshx_model_h_result_v1* result,char* error,size_t error_capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_model_h_release_v1(tpmshx_model_h_result_v1* result);

#ifdef __cplusplus
}
#endif
#endif
