#ifndef TPMSHX_SIMPLE_3D_C_API_H
#define TPMSHX_SIMPLE_3D_C_API_H

#include "tpmshx/simple_c_api_types.h"

#ifdef __cplusplus
extern "C" {
#endif

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

#ifdef __cplusplus
}
#endif
#endif
