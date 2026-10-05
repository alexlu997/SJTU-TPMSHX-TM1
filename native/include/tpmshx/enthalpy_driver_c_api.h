#ifndef TPMSHX_ENTHALPY_DRIVER_C_API_H
#define TPMSHX_ENTHALPY_DRIVER_C_API_H

#include "tpmshx/thermal_c_api.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TPMSHX_ENTHALPY_DRIVER_ABI_VERSION 1u

enum tpmshx_enthalpy_fluid {
    TPMSHX_ENTHALPY_AIR = 0, TPMSHX_ENTHALPY_WATER = 1, TPMSHX_ENTHALPY_SCO2 = 2
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

/* Additive selection/evidence for new entry points. Existing v1 POD layouts
 * and calls retain the legacy H-FOU algorithm. */
enum tpmshx_energy_algorithm {
    TPMSHX_ENERGY_LEGACY_H_FOU = 0,
    TPMSHX_ENERGY_TEMPERATURE_FOU = 1,
    TPMSHX_ENERGY_TEMPERATURE_SOU = 2
};
typedef struct {
    uint32_t algorithm;
    double temperature_update_tolerance; /* maximum actual A/B/solid change, K */
} tpmshx_energy_options_v1;
/* Explicit full3D v3 controls. Existing options_v1 layout is unchanged.
 * update_tolerance, iteration budget, sweeps and omega remain in the full3D
 * control_v1. The optional h gate is dimensionless, never Kelvin. */
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
 * Scalar inlet P sets inlet h; cell P sets the local EOS. Mathematical h
 * brackets retain legal inlet/warm states and do not replace phase guards.
 *
 * Gate/warm flags must be 0 or 1. Enabled gate tolerances must be positive.
 * CO2 requires an absolute UTF-8 table_directory (NUL terminated). The native
 * library fixes that path on first BICUBIC use; repeated same-path calls are
 * allowed, conflicting paths fail. Cancellation precedes BICUBIC creation.
 * An air/water-only call does not use table_directory and may pass NULL.
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
 * this boundary. A normal return always has final exact-HEOS T. Audit exists
 * only when a gate was requested; coupled-only fluid residual metrics are NaN
 * and fluid_equations_computed=false. Unrequested audits must not be inferred.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_enthalpy_v1(
    const size_t* shape, double* const* arrays, const size_t* sizes,
    const tpmshx_enthalpy_config_v1* config,
    const tpmshx_enthalpy_callbacks_v1* callbacks,
    tpmshx_enthalpy_result_v1* result, char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
