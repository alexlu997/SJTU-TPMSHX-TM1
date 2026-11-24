#ifndef TPMSHX_SIMPLE_2D_C_API_H
#define TPMSHX_SIMPLE_2D_C_API_H

#include "tpmshx/simple_c_api_types.h"

#ifdef __cplusplus
extern "C" {
#endif

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

#ifdef __cplusplus
}
#endif
#endif
