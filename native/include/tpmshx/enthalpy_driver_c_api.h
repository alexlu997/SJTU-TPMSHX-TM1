#ifndef TPMSHX_ENTHALPY_DRIVER_C_API_H
#define TPMSHX_ENTHALPY_DRIVER_C_API_H

#include "tpmshx/thermal_c_api.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Stop codes of tpmshx_enthalpy_result_v1. */
enum tpmshx_enthalpy_stop {
    TPMSHX_ENTHALPY_CONVERGED = 0, TPMSHX_ENTHALPY_LIMITED = 1,
    TPMSHX_ENTHALPY_ITERATION_LIMIT = 2, TPMSHX_ENTHALPY_CANCELLED = 3
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

#ifdef __cplusplus
}
#endif
#endif
