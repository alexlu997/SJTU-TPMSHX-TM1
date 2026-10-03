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

/* Complete prepared Quick Design solve, with no Python runtime dependency.
 * All quantities are SI: K, Pa(abs), kg/s, m, m2/m3, W/(m K), J/(kg K).
 * shape[3] = nx, ny, nz; arrays[9] and sizes[9] contain contiguous C-order
 * doubles: dx, dy, dz, epsilon, epsilon_A, K_ss, T_A, T_B, T_s.
 * Only the final three arrays are mutable. Each size is an element count.
 * epsilon, epsilon_A and K_ss must be uniform, epsilon_A=epsilon/2.
 * The current QD policy uses one const pass or exactly two mean passes.
 * Prepared pressure fractions are retained, including choked values >=1.
 * max/chunk iterations are resolved positive budgets per property pass.
 * For nz=1 alpha must be 0.7; nz>1 uses the 3D temperature scheme.
 *
 * The caller owns every buffer until return. Fixed tables, config, callbacks,
 * result and error must have their declared storage and must not overlap array
 * storage or one another. A pointer cannot prove the size of its allocation.
 * error must be non-NULL with error_capacity>0; messages are bounded and NUL
 * terminated. No exception crosses this boundary.
 *
 * TPMSHX_OK means execution returned; inspect result.stop for convergence.
 * Cancellation is TPMSHX_OK/TPMSHX_CANCELLED. Only passes below
 * completed_passes are valid. Cancelled temperatures can be partial and must
 * not be published as a solved field. Before any completed pass, pressure is
 * also unavailable. On any nonzero error code, result is left untouched and
 * mutable arrays may be partial and must be discarded. Success clears error.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_quick_design_v1(
    const size_t* shape, double* const* arrays, const size_t* sizes,
    const tpmshx_qd_config_v1* config, const tpmshx_callbacks_v1* callbacks,
    tpmshx_qd_result_v1* result, char* error, size_t error_capacity);

#ifdef __cplusplus
}
#endif
#endif
