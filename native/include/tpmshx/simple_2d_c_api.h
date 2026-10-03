#ifndef TPMSHX_SIMPLE_2D_C_API_H
#define TPMSHX_SIMPLE_2D_C_API_H

#include "tpmshx/simple_c_api_types.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TPMSHX_SIMPLE_2D_ABI_VERSION 1u
typedef struct tpmshx_simple_2d_handle tpmshx_simple_2d_handle;

typedef struct {
    size_t max_iterations, inner_sweeps;
    double alpha_velocity, alpha_pressure, alpha_density;
    double pressure_reference_absolute, gas_constant, cf_anisotropy;
    uint32_t ideal_gas, massflux_inlet, close_outlet_on_exit;
    double reference_inlet_velocity, taper_flux_scale, inlet_density_reference;
    uint32_t have_inlet_density_reference;
    tpmshx_simple_f2_v1 f2;
} tpmshx_simple_2d_config_v1;

typedef struct {
    uint32_t stop, converged, post_closure_measured, post_closure_certified;
    size_t iterations, pressure_clip_hits;
    double legacy_residual;
    tpmshx_simple_momentum_v1 momentum;
    tpmshx_simple_mass_v1 mass;
    uint32_t have_massflux_target;
    double massflux_target;
    uint32_t pressure_success;
    int pressure_superlu_info;
    double pressure_relative_residual, pressure_pin_maximum;
    char pressure_exit[64], pressure_detail[512];
} tpmshx_simple_2d_result_v1;

TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_simple_2d_abi_version(void);

/* Prepared +y solver coordinates, SI, contiguous C order, unit depth.
 * create copies dx[nx], dy[ny] and outlet_open[nx] (0/1).
 * A handle owns its width/support copies, pressure cache, inlet target and
 * histories across warm solves. One caller at a time per handle; separate
 * handles may run on separate threads. destroy(NULL) is allowed.
 * Caller buffers must have the declared extents and remain live throughout
 * the call. No Python runtime or callback is needed for a normal solve.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_simple_2d_create_v1(
    size_t nx, size_t ny, const double* dx, const double* dy,
    const uint8_t* outlet_open, tpmshx_simple_2d_handle** handle,
    char* error, size_t error_capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_simple_2d_destroy(
    tpmshx_simple_2d_handle* handle);

/* arrays[16]/sizes[16]: epsilon, mu, mu_eff, K, cF, temperature,
 * u, v, gauge_pressure, pressure_correction, d_u, d_v, density,
 * inlet_velocity, inlet_fraction, outlet_u_fraction.
 * Cell fields: (nx,ny); u/d_u: (nx+1,ny); v/d_v: (nx,ny+1);
 * inlet fields: nx; outlet_u_fraction: nx+1. Arrays 6..13 are mutable and
 * must not overlap one another or read-only arrays 0..5/14..15.
 * The resolved controls are explicit; no threshold is replaced here.
 * The pressure-outlet cells retain their supplied gauge pressure.
 *
 * Callbacks are synchronous and must not throw, re-enter the same handle or
 * retain internal references. Cancellation is a normal nonconverged result.
 * Error returns leave result unchanged; state can be partially updated after
 * arithmetic/native errors. A successful API return does not mean convergence:
 * inspect converged and post_closure_certified before accepting the fields.
 * Numerical nonfinite/linear-solve failures preserve state as evidence.
 * This ends at the SIMPLE call; it performs no geometry/D-F preparation, EOS,
 * thermal coupling, physical-axis mapping or outer physical acceptance.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_simple_2d_solve_v1(
    tpmshx_simple_2d_handle* handle, double* const* arrays, const size_t* sizes,
    const tpmshx_simple_2d_config_v1* config,
    const tpmshx_simple_callbacks_v1* callbacks,
    tpmshx_simple_2d_result_v1* result, char* error, size_t error_capacity);

/* kind 0=legacy, 1=local mass, 2=global mass, 3=momentum.
 * Momentum is flattened rows of 8 doubles:
 * iteration,max,num_u,num_v,den_u,den_v,res_u,res_v.
 * Query with values=NULL/capacity=0. required receives the total double count.
 * A short buffer is rejected without writing any values. Histories remain
 * handle-owned; query/copy is allowed only when no solve is running.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_simple_2d_history_v1(
    const tpmshx_simple_2d_handle* handle, uint32_t kind, double* values,
    size_t capacity, size_t* required, char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
