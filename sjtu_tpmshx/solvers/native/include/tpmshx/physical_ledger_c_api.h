#ifndef TPMSHX_PHYSICAL_LEDGER_C_API_H
#define TPMSHX_PHYSICAL_LEDGER_C_API_H
#include "tpmshx/thermal_c_api.h"

/* Actual heat evidence. Available does not imply convergence or qualification.
 * Phases are A, B and solid. Boundary planes are x-, x+, y-, y+, z-, z+.
 * Boundary power is signed outward. Cell residual is physical RHS minus diagonal times state.
 * Powers use W in 3D and W/m for a 2D unit-depth solve.
 * A prescribed B has no B equation or boundary arrays. Its exchange enters
 * the other phases as prescribed_b_power. Unavailable evidence is not zero.
 * Arrays borrow the full result owner until release. */
typedef struct { const double* data; size_t size; } tpmshx_physical_array_v1;
typedef struct {
    uint32_t available,physical_dimension,boundary_complete,solved[3];
    tpmshx_physical_array_v1 residual[3];
    tpmshx_physical_array_v1 advective_out[3][6],diffusive_out[3][6];
    double source_integral[3],prescribed_b_power;
} tpmshx_physical_heat_ledger_v1;

typedef struct {
    tpmshx_physical_heat_ledger_v1 main,fine;
} tpmshx_full_2d_physical_heat_ledger_v1;
#endif
