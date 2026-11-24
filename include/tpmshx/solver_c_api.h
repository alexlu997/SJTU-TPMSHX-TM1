#ifndef TPMSHX_SOLVER_C_API_H
#define TPMSHX_SOLVER_C_API_H

#include "tpmshx/thermal_c_api.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TPMSHX_SOLVER_ABI_VERSION 1u

enum tpmshx_fluid { TPMSHX_AIR = 0, TPMSHX_WATER = 1, TPMSHX_SCO2 = 2 };
enum tpmshx_topology { TPMSHX_DIAMOND = 0, TPMSHX_GYROID = 1 };
enum tpmshx_qd_arrangement { TPMSHX_CROSS = 0, TPMSHX_COUNTER = 1 };
enum tpmshx_qd_properties { TPMSHX_CONSTANT = 0, TPMSHX_MEAN = 1 };
enum tpmshx_stop { TPMSHX_CONVERGED = 0, TPMSHX_BUDGET_EXHAUSTED = 1, TPMSHX_CANCELLED = 2 };
enum tpmshx_error {
    TPMSHX_OK = 0, TPMSHX_INVALID_ARGUMENT = 1, TPMSHX_WATER_INPUT = 2,
    TPMSHX_WATER_FIELD = 3, TPMSHX_ARITHMETIC_ERROR = 4, TPMSHX_NATIVE_ERROR = 5
};

typedef struct {
    uint32_t fluid;
    double inlet_temperature, inlet_pressure, mass_flow, inlet_pressure_fraction;
} tpmshx_qd_side_v1;

typedef struct {
    uint32_t topology, arrangement, property_mode, warm_start;
    double length, span, height, cell_length, area_density, hydraulic_diameter;
    tpmshx_qd_side_v1 sides[2];
    size_t max_iterations, chunk_iterations;
    double q_relative_tolerance, alpha;
} tpmshx_qd_config_v1;

typedef struct {
    double evaluation_temperature, rho, mu, k, cp, pr;
    double reynolds, speed, hv, conductivity;
} tpmshx_qd_pass_side_v1;

typedef struct {
    tpmshx_qd_pass_side_v1 sides[2];
    uint32_t stop;
    size_t iterations;
    double residual, q_b;
} tpmshx_qd_pass_v1;

typedef struct { double inlet, outlet; uint32_t choked; } tpmshx_qd_pressure_v1;

typedef struct {
    uint32_t stop;
    size_t completed_passes;
    tpmshx_qd_pass_v1 passes[2];
    tpmshx_qd_pressure_v1 pressure[2];
} tpmshx_qd_result_v1;

/* Callbacks execute synchronously on the calling thread; they must not throw
 * or mutate the arrays/configuration. cancel returns nonzero to stop. NULL
 * callbacks are allowed. context is borrowed and never freed by the library.
 */
typedef struct {
    int (TPMSHX_THERMAL_CALL *cancel)(void* context);
    void (TPMSHX_THERMAL_CALL *progress)(void* context, unsigned percent);
    void* context;
} tpmshx_callbacks_v1;

TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_solver_abi_version(void);

#ifdef __cplusplus
}
#endif
#endif
