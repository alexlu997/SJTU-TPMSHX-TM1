#ifndef TPMSHX_SIMPLE_3D_C_API_H
#define TPMSHX_SIMPLE_3D_C_API_H

#include "tpmshx/simple_c_api_types.h"

#ifdef __cplusplus
extern "C" {
#endif
#define TPMSHX_SIMPLE_3D_ABI_VERSION 1u
typedef struct tpmshx_simple_3d_handle tpmshx_simple_3d_handle;

enum tpmshx_simple_3d_ordering { TPMSHX_SIMPLE_3D_NATURAL=0, TPMSHX_SIMPLE_3D_RED_BLACK=1 };

typedef struct {
    size_t max_iterations, inner_sweeps, pressure_rebuild_every;
    double alpha_velocity, alpha_pressure, alpha_density;
    double pressure_reference_absolute, gas_constant, pressure_diagonal_drift;
    uint32_t ideal_gas, massflux_inlet, second_order_upwind, adaptive_pressure_tolerance, track_momentum, ordering;
    tpmshx_simple_f2_v1 convergence;
} tpmshx_simple_3d_config_v1;

typedef struct {
    uint32_t success;
    size_t iterations, rebuild_count, hierarchy_bytes;
    int superlu_info;
    double rhs_scale, relative_residual, absolute_residual, iterative_relative_residual;
    double pin_max_abs, diagonal_drift, build_seconds, solve_seconds;
    char method[32], exit[64], amg_exit[64], rebuild_reason[64], detail[512];
} tpmshx_simple_3d_pressure_v1;

typedef struct {
    uint32_t stop, converged, post_closure_measured, post_closure_certified, mass_faces_available;
    size_t iterations, pressure_clip_hits, post_closure_rejections;
    double legacy_residual, legacy_reference;
    tpmshx_simple_momentum_v1 momentum;
    tpmshx_simple_mass_v1 mass;
    tpmshx_simple_3d_pressure_v1 pressure;
} tpmshx_simple_3d_result_v1;

TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_simple_3d_abi_version(void);

/* Prepared +y solver coordinates, SI, contiguous C order. create copies
 * dx[nx],dy[ny],dz[nz],outlet_open[nx*nz] (0/1). One caller per handle at a
 * time; independent handles may run concurrently. destroy(NULL) is allowed.
 * The handle retains its PPE hierarchy, fixed inlet mass target, clip count
 * and histories through warm calls. Supplied fields may contain an explicit
 * coarse seed. No bootstrap, geometry, D-F closure or outer coupling runs.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_simple_3d_create_v1(
    size_t nx,size_t ny,size_t nz,const double* dx,const double* dy,const double* dz,
    const uint8_t* outlet_open,tpmshx_simple_3d_handle** handle,char* error,size_t error_capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_simple_3d_destroy(tpmshx_simple_3d_handle* handle);

/* arrays[21]/sizes[21]: epsilon,mu,mu_eff,K,cF,temperature,
 * u,v,w,gauge_pressure,pressure_correction,d_u,d_v,d_w,density,inlet_velocity,
 * outlet_u_fraction,outlet_w_fraction,mass_x,mass_y,mass_z.
 * Cells are (nx,ny,nz); u/d_u/mass_x are (nx+1,ny,nz), v/d_v/mass_y
 * (nx,ny+1,nz), w/d_w/mass_z (nx,ny,nz+1). inlet_velocity is (nx,nz)
 * and already includes geometric overlap; outlet tangential fractions are
 * (nx+1,nz)/(nx,nz+1). 6..15 and 18..20 are mutable, mutually disjoint and
 * disjoint from fixed arrays. Mass outputs need not be initialized.
 * All flags are 0/1. SOU requires natural ordering. Red-black currently uses
 * the same color order serially, without a native thread pool.
 *
 * The caller owns valid buffers/configuration/callback/result/error storage
 * through return; these must not overlap mutable fields or each other. No
 * pointer can prove allocation size. Error buffer is required, capacity>0.
 * Callbacks run synchronously; they must not throw, modify input/state or
 * re-enter the same handle. Progress reports legacy residual at iteration 1
 * and multiples of 50. cancel polls at entry and each iteration boundary.
 *
 * OK only means execution returned. Inspect stop/converged/certificate.
 * Cancellation, nonfinite or linear failure never returns converged. Raw mass
 * faces describe the returned rho/velocity only if mass_faces_available=1;
 * they receive no balancing/projection and remain untouched otherwise.
 * Error codes leave result untouched; state may be partial and unusable.
 * Numerical failures retain diagnostic evidence, not a publishable field.
 * No exception crosses the boundary. Success clears the bounded error text.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_simple_3d_solve_v1(
    tpmshx_simple_3d_handle* handle,double* const* arrays,const size_t* sizes,
    const tpmshx_simple_3d_config_v1* config,const tpmshx_simple_callbacks_v1* callbacks,
    tpmshx_simple_3d_result_v1* result,char* error,size_t error_capacity);

/* kind: 0 legacy,1 local mass,2 global mass,3 momentum,4 inlet mass target.
 * Momentum rows contain 11 doubles: iteration,max,num[3],den[3],component[3].
 * Target has nx*nz entries after first ideal-gas/massflux solve, else empty.
 * values=NULL/capacity=0 queries required count. Short buffers fail without
 * writing values. Query/copy only when no solve is using the handle.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_simple_3d_history_v1(
    const tpmshx_simple_3d_handle* handle,uint32_t kind,double* values,size_t capacity,
    size_t* required,char* error,size_t error_capacity);
#ifdef __cplusplus
}
#endif
#endif
