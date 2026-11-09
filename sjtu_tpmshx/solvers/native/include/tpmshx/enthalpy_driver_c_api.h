#ifndef TPMSHX_ENTHALPY_DRIVER_C_API_H
#define TPMSHX_ENTHALPY_DRIVER_C_API_H

#include "tpmshx/thermal_c_api.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TPMSHX_ENTHALPY_DRIVER_ABI_VERSION 1u

enum tpmshx_enthalpy_fluid {
    TPMSHX_ENTHALPY_AIR = 0, TPMSHX_ENTHALPY_WATER = 1, TPMSHX_ENTHALPY_SCO2 = 2, TPMSHX_ENTHALPY_CO2 = 3
};
enum tpmshx_enthalpy_stop {
    TPMSHX_ENTHALPY_CONVERGED = 0, TPMSHX_ENTHALPY_LIMITED = 1,
    TPMSHX_ENTHALPY_ITERATION_LIMIT = 2, TPMSHX_ENTHALPY_CANCELLED = 3
};
enum tpmshx_enthalpy_error {
    TPMSHX_ENTHALPY_OK = 0, TPMSHX_ENTHALPY_INVALID_ARGUMENT = 1,
    TPMSHX_ENTHALPY_WATER_STATE = 2, TPMSHX_ENTHALPY_ARITHMETIC_ERROR = 3,
    TPMSHX_ENTHALPY_NATIVE_ERROR = 4
};

/* IDs 0 and 1 identify historical records. Current execution accepts only
 * T-SOU (2). Existing result POD layouts remain readable. */
enum tpmshx_energy_algorithm {
    TPMSHX_ENERGY_LEGACY_H_FOU = 0,
    TPMSHX_ENERGY_TEMPERATURE_FOU = 1,
    TPMSHX_ENERGY_TEMPERATURE_SOU = 2
};
/* SOU recipe 2 uses trial-first Anderson with ordinary final confirmation.
 * Retired or unsupported algorithms return zero. This read-only query
 * does not change any POD or ABI. */
TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_energy_algorithm_version_v1(uint32_t algorithm);
typedef struct {
    uint32_t algorithm;
    double temperature_update_tolerance; /* maximum actual A/B/solid change, K */
} tpmshx_energy_options_v1;
/* Explicit energy gates. Existing options_v1 layout is unchanged.
 * The full driver supplies the iteration, sweep, relaxation and h-update
 * controls separately. The optional h gate is dimensionless, never Kelvin. */
typedef struct {
    uint32_t algorithm;
    double temperature_update_tolerance;
    double coupled_energy_tolerance;
    double equation_energy_tolerance;
    uint32_t require_enthalpy_update_on_temperature; /* 0 or 1; default 0 */
} tpmshx_energy_options_v2;
typedef struct {
    uint32_t algorithm, has_temperature_update;
    double temperature_update; /* K; unavailable on legacy/cancelled returns */
    double picard_relaxation; /* actual whole-block T relaxation, 0 < value <= 1 */
} tpmshx_energy_result_v1;

typedef struct {
    uint32_t available,algorithm,require_enthalpy_update_on_temperature;
    size_t max_iterations,sweeps;
    double omega,update_tolerance,temperature_update_tolerance;
    double coupled_energy_tolerance,equation_energy_tolerance;
} tpmshx_energy_effective_settings_v1;
typedef struct {
    uint32_t available,reference_independent;
    double scale[2]; /* J/kg; max(cp_in*abs(T_in_A-T_in_B), 1) for full runs */
} tpmshx_energy_update_scale_v1;
/* Read full-driver defaults without numerical work. available is zero.
 * dimension is 2 or 3; algorithm is 2; has_water is 0 or 1.
 * Invalid arguments return 1
 * and leave output unchanged. Explicit caller controls still take priority. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_enthalpy_defaults_v1(
    uint32_t dimension,uint32_t algorithm,uint32_t has_water,tpmshx_energy_effective_settings_v1*);

typedef struct {
    uint32_t fluid;
    double inlet_temperature, inlet_pressure;
} tpmshx_enthalpy_side_v1;

typedef struct {
    tpmshx_enthalpy_side_v1 sides[2];
    uint32_t warm_a, warm_b, warm_solid;
    uint32_t coupled_gate, equation_gate;
    size_t max_iterations, sweeps;
    double omega, update_tolerance, coupled_tolerance, equation_tolerance;
    const char* table_directory;
} tpmshx_enthalpy_config_v1;

typedef struct {
    int (TPMSHX_THERMAL_CALL *cancel)(void* context);
    void* context;
} tpmshx_enthalpy_callbacks_v1;

typedef struct {
    double q_a, q_b, net, solid_abs_sum, denominator, coupled_ratio;
    double fluid_abs_sum[2], fluid_cell_max[2], equation_ratio;
    uint32_t fluid_equations_computed;
} tpmshx_enthalpy_audit_v1;

typedef struct {
    uint32_t stop;
    size_t iterations;
    double residual, q_a, q_b, energy_imbalance, inlet_enthalpy[2];
    uint64_t last_clips[2], total_clips[2];
    uint32_t used_bicubic[2], heos_polish, audit_available;
    tpmshx_enthalpy_audit_v1 audit;
    char coolprop_version[32];
} tpmshx_enthalpy_result_v1;

TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_enthalpy_driver_abi_version(void);

/* Complete true-h thermal driver, without a Python runtime. This starts after
 * mass-face/pressure/hv preparation; it performs no flow balancing or coupling
 * refresh. All quantities are SI. A unit-depth nz=1 extrusion returns W/m;
 * physical 3D returns W. No thresholds or iteration budgets are substituted.
 *
 * shape[3]=(nx,ny,nz); arrays[21]/sizes[21] are contiguous C-order doubles:
 *   dx,dy,dz,K_ss,
 *   P_A,epsilon_A,hv_A,mass_A_x,mass_A_y,mass_A_z,
 *   P_B,epsilon_B,hv_B,mass_B_x,mass_B_y,mass_B_z,
 *   h_A,h_B,T_A,T_B,T_s.
 * Only the last five arrays are mutable. h_A/h_B need not be initialized.
 * Warm flags independently select supplied temperature fields. False warm
 * flags initialize that field using the existing inlet/mean policy.
 * Scalar inlet P sets inlet h; cell P sets the local EOS. T-SOU uses
 * checked HEOS PT states and retains physical phase and range guards.
 * Version 1 applies a fixed 1e-8 K update limit. Version 2 takes that limit
 * as an argument. Both entries retain the strict normalized-h update and
 * relative boundary energy gates.
 *
 * Gate/warm flags must be 0 or 1. Enabled gate tolerances must be positive.
 * table_directory is retained in the C layout for historical callers.
 * This library does not read it or create EOS tables; NULL is permitted.
 *
 * The caller owns all storage through return. Array storage must not overlap
 * mutable arrays, config, callbacks, result or error. Fixed array storage may
 * be shared with other fixed arrays. No pointer can prove allocation size.
 * error must be non-NULL, error_capacity>0; text is bounded/NUL terminated.
 * Optional cancel executes synchronously on the calling thread; it must not
 * throw or modify any inputs. The library borrows its context.
 *
 * OK means execution returned; inspect stop for convergence. Cancelled fields
 * are partial and must be discarded; only stop/iterations/clips are evidence,
 * and audit_available is false. On nonzero error, result remains untouched;
 * mutable fields may be partial and must be discarded. No exception crosses
 * this boundary. A normal return has checked HEOS PT state. Audit exists
 * only when a gate was requested; coupled-only fluid residual metrics are NaN
 * and fluid_equations_computed=false. Unrequested audits must not be inferred.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_enthalpy_v1(
    const size_t* shape, double* const* arrays, const size_t* sizes,
    const tpmshx_enthalpy_config_v1* config,
    const tpmshx_enthalpy_callbacks_v1* callbacks,
    tpmshx_enthalpy_result_v1* result, char* error, size_t error_capacity);


/* T-SOU uses the same arrays, warm flags and optional audit output as v1.
 * temperature_tolerance is a separate positive finite Kelvin limit.
 * Normalized-h update must be strictly less than config.update_tolerance.
 * Relative boundary energy imbalance must remain below 0.05, as in v1.
 * Both limits must pass. No caller tolerance or budget is replaced.
 * energy reports the actual executed algorithm and Kelvin update. Its update
 * is unavailable after cancellation. On errors, both outputs stay unchanged.
 * All v1 storage and error-buffer requirements apply; energy must be non-NULL.
 * Its storage must not overlap any other argument storage.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_enthalpy_v2(
    const size_t* shape, double* const* arrays, const size_t* sizes,
    const tpmshx_enthalpy_config_v1* config, double temperature_tolerance,
    const tpmshx_enthalpy_callbacks_v1* callbacks,
    tpmshx_enthalpy_result_v1* result, tpmshx_energy_result_v1* energy,
    char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
