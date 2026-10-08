#ifndef TPMSHX_TEMPERATURE_EVIDENCE_C_API_H
#define TPMSHX_TEMPERATURE_EVIDENCE_C_API_H
#include "tpmshx/thermal_c_api.h"

/* Read-only full-compute model-enthalpy evidence, version 1.
 * Existing solve/result layouts are unchanged. Arrays borrow the result owner;
 * algorithm is an immutable static string naming the executed thermal method.
 * Each cp_coefficients row is [c0,c1,c2,Tbase,Tref]:
 * cp(T)=c0+c1*(T-Tbase)+c2*(T-Tbase)^2, in J/(kg K), and h(Tref)=0.
 * Advective powers contain signed mass times this integral h(T_face), not cp*T.
 * Residual/source/reservoir/boundary powers use W (3D) or W/m (2D).
 * Boundary planes retain x-,x+,y-,y+,z-,z+ order, including singleton z in 2D.
 * Solved phases are A,B,solid. Prescribed B has all-NaN cp_coefficients,
 * no residual or boundary planes, and its ledger source integral is unavailable.
 * Available means captured evidence, not convergence or physical qualification.
 * This layout is exposed only by the get_model_enthalpy_evidence_v1 queries;
 * it must not be interpreted as the former mass*cp temperature evidence layout.
 */
typedef struct { const double* data; size_t size; } tpmshx_model_enthalpy_array_v1;
typedef struct {
    uint32_t available,physical_dimension,boundary_complete,solved[3];
    const char* algorithm;
    double cp_coefficients[2][5];
    tpmshx_model_enthalpy_array_v1 residual[3];
    tpmshx_model_enthalpy_array_v1 advective_out[3][6],diffusive_out[3][6];
    double source_integral[3],prescribed_b_power;
} tpmshx_model_enthalpy_evidence_v1;
#endif
