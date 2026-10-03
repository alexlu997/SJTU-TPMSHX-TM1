#ifndef TPMSHX_TEMPERATURE_DRIVER_C_API_H
#define TPMSHX_TEMPERATURE_DRIVER_C_API_H
#include "tpmshx/thermal_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif
#define TPMSHX_TEMPERATURE_DRIVER_ABI_VERSION 1u

enum tpmshx_temperature_scheme {
    TPMSHX_TEMPERATURE_CC_2D = 0,
    TPMSHX_TEMPERATURE_CC_3D = 1,
    TPMSHX_TEMPERATURE_STAGGERED_3D = 2
};
typedef struct {
    uint32_t scheme,direction_a,direction_b,warm_start,second_order_b;
    uint32_t conservative,red_black,accelerate;
    size_t max_iterations,chunk_iterations;
    double inlet_a,inlet_b,q_relative_tolerance,alpha_a,alpha_solid,alpha_b;
} tpmshx_temperature_config_v1;
typedef struct {
    int (TPMSHX_THERMAL_CALL *cancel)(void*);
    void (TPMSHX_THERMAL_CALL *progress)(void*,size_t,size_t);
    void* context;
} tpmshx_temperature_callbacks_v1;
typedef struct {
    uint32_t available;
    const double* cells;
    size_t cell_count;
    double sum,maximum,exchange,global_ratio,cell_ratio;
} tpmshx_temperature_residual_v1;
typedef struct {
    uint32_t skipped,used_bordered_lu;
    size_t cg_iterations;
    double rhs_mean,residual_relative;
} tpmshx_mac_projection_v1;
typedef struct {
    uint32_t scheme,stop;
    size_t iterations;
    double residual,q_b;
    tpmshx_temperature_residual_v1 fluid[2];
    tpmshx_mac_projection_v1 projection[2];
    void* owner;
} tpmshx_temperature_result_v1;

typedef struct tpmshx_temperature_driver_v1 tpmshx_temperature_driver_v1;
TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_temperature_driver_abi_version(void);
/* Explicit owner of the last grid's MAC hierarchy. Independent handles may be
 * used concurrently; one handle must not be called concurrently or from its
 * callbacks. A failed create leaves *driver untouched. Destroy accepts NULL.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_temperature_driver_create_v1(
    tpmshx_temperature_driver_v1** driver,char* error,size_t error_capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_temperature_driver_destroy_v1(
    tpmshx_temperature_driver_v1* driver);

/* Complete fixed-coefficient temperature solve; no property or flow update.
 * shape has nx,ny,nz. Arrays[31]/sizes[31], contiguous C-order doubles:
 *  dx,dy,dz,Kss,source_s,prescribed_b,
 *  Ka,hva,eps_a,rhoCp_a,u_a,v_a,w_a,profile_a,opening_a,inlet_capacity_a,source_a,
 *  Kb,hvb,eps_b,rhoCp_b,u_b,v_b,w_b,profile_b,opening_b,inlet_capacity_b,source_b,
 *  Ta,Tb,Ts.
 * K already includes its porosity factor; eps_a/b are single-channel fields.
 * Only Ta/Tb/Ts are mutable. w is empty in 2D; all velocities are cell fields
 * for CC and face arrays for staggered. CC2D requires nz=1,dz[0]=1 and alpha
 * (.7,1,1). Both 3D schemes require nz>1 and second_order_b=1.
 * Empty profile/opening mean scalar Tin/full face; inlet_capacity is optional
 * signed inward W/(m K) in 2D or W/K in 3D and already includes opening.
 * Empty sources mean zero; nonzero sources and conservative projection require
 * staggered. RB is allowed for CC2D and staggered; the caller resolves the
 * original grid-size/opt-in gates. accelerate must be 0 (non-model-h rule).
 * Warm state is used only if warm_start=1; prescribed_b, if nonempty, pins B.
 * max_iterations may be 0; chunk_iterations is positive. Every requested
 * chunk is charged even if its internal 1e-10 K shortcut exits earlier.
 * Inputs and control tables remain immutable through callbacks. They and
 * result/error/owner storage must not overlap mutable state or one another.
 * Pointer arguments cannot establish allocation extents; the caller owns all
 * fixed-size tables and correct buffer storage. Callbacks must not throw.
 *
 * Stop: 0 converged, 1 budget exhausted, 2 cancelled. Status: 0 normal,
 * 1 invalid argument, 2 arithmetic error, 3 native exception. Nonzero status
 * leaves result untouched; after any failure/cancel discard updated states.
 * Error storage is mandatory, positive capacity, bounded/NUL terminated.
 * On normal return result owns any residual views independently of driver
 * and inputs until release. Only available fluids have valid views/metrics.
 * They are original final equations, not additional acceptance gates. Powers
 * are W/m for CC2D, W for 3D. Projection evidence applies only to conservative
 * staggered. Q_b is the B interface integral and NaN before an audited chunk.
 * Release each normal result, including cancelled, before reusing its struct.
 * Never copy owner handles/free views. Release clears and accepts an already
 * cleared result. No C++ exception crosses any entry point.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_temperature_v1(
    tpmshx_temperature_driver_v1* driver,const size_t* shape,double* const* arrays,
    const size_t* sizes,const tpmshx_temperature_config_v1* config,
    const tpmshx_temperature_callbacks_v1* callbacks,
    tpmshx_temperature_result_v1* result,char* error,size_t error_capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_temperature_release_v1(
    tpmshx_temperature_result_v1* result);
#ifdef __cplusplus
}
#endif
#endif
