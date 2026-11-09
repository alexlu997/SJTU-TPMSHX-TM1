#ifndef TPMSHX_SIMPLE_C_API_TYPES_H
#define TPMSHX_SIMPLE_C_API_TYPES_H

#include "tpmshx/thermal_c_api.h"

enum tpmshx_simple_error {
    TPMSHX_SIMPLE_OK = 0, TPMSHX_SIMPLE_INVALID_ARGUMENT = 1,
    TPMSHX_SIMPLE_ARITHMETIC_ERROR = 2, TPMSHX_SIMPLE_NATIVE_ERROR = 3
};
enum tpmshx_simple_stop {
    TPMSHX_SIMPLE_ONGOING = 0, TPMSHX_SIMPLE_TOL = 1, TPMSHX_SIMPLE_STALL = 2,
    TPMSHX_SIMPLE_ITERATION_LIMIT = 3, TPMSHX_SIMPLE_NONFINITE = 4,
    TPMSHX_SIMPLE_CANCELLED = 5, TPMSHX_SIMPLE_PRESSURE_FAILURE = 6,
    TPMSHX_SIMPLE_POST_CLOSURE = 7
};

typedef struct {
    double momentum_tolerance, local_mass_tolerance, global_mass_tolerance;
    double backflow_maximum, velocity_check_tolerance, stall_ratio;
    size_t confirmations, momentum_interval, stall_window;
} tpmshx_simple_f2_v1;

typedef struct {
    int (TPMSHX_THERMAL_CALL *cancel)(void* context);
    void (TPMSHX_THERMAL_CALL *progress)(void* context, size_t iteration, double residual);
    void* context;
} tpmshx_simple_callbacks_v1;

typedef struct {
    double numerator[3], denominator[3], component[3], maximum;
} tpmshx_simple_momentum_v1;  /* unused 2D w component is zero */

typedef struct {
    double local_residual, mass_in, mass_out, global_residual, backflow_fraction;
    size_t counted_cells;
} tpmshx_simple_mass_v1;  /* mass is kg/(s m) in 2D, kg/s in 3D */

#endif
