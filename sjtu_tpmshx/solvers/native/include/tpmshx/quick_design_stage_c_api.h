#ifndef TPMSHX_QUICK_DESIGN_STAGE_C_API_H
#define TPMSHX_QUICK_DESIGN_STAGE_C_API_H

#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/solver_c_api.h"
#include "tpmshx/result_stage_c_api.h"

#define TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION 1u
#define TPMSHX_QUICK_STAGE_CANCELLED 6

typedef struct {
    uint32_t fluid;
    double temperature_K,pressure_Pa,mass_flow_kg_s;
} tpmshx_quick_inlet_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    uint32_t topology,arrangement,property_mode;
    double cell_length_mm,wall_thickness_mm,span_m,length_m;
    tpmshx_quick_inlet_v1 sides[2];
    uint32_t have_height,have_solid_conductivity,have_tolerance;
    double height_m,solid_conductivity_W_mK,tolerance;
    uint32_t warm_start;
    size_t initial_shape[3];
    tpmshx_preparation_array_v1 initial[3];
} tpmshx_quick_input_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    void* owner;
    tpmshx_quick_input_v1 input;
    size_t shape[3];
    tpmshx_preparation_array_v1 widths[3],edges[3];
    tpmshx_preparation_array_v1 epsilon,epsilon_a,solid_conductivity;
    tpmshx_preparation_array_v1 initial[3];
    double wall_thickness_m,solid_conductivity_W_mK,tolerance;
    size_t geometry_resolution;
    tpmshx_qd_config_v1 resolved;
    tpmshx_preparation_df_pressure_v1 inlet_pressure[2];
} tpmshx_quick_prepared_v1;
typedef struct {
    const char* result_id;
    tpmshx_callbacks_v1 callbacks;
} tpmshx_quick_run_control_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    void* owner;
    tpmshx_qd_result_v1 raw;
    tpmshx_result_evidence_v1 evidence;
} tpmshx_quick_run_result_v1;

#ifdef __cplusplus
extern "C" {
#endif
/* Native double operating points use the existing Quick Design model.
 * Enum values match solver_c_api.h. Cross uses (60,40,1); counter (60,1,2).
 * Omitted height uses span. Omitted conductivity uses 16 W/(m K).
 * Omitted tolerance uses 1e-5. Flags must be 0 or 1. Warm fields are C order.
 * No environment variables are read. D-F uses the fixed CFD table.
 * Input arrays are copied. All result views belong to the returned owner.
 * Initialize result ABI, struct size and owner=NULL. Failure preserves result.
 * Release with the same preparation library. Input, result and error storage
 * must be disjoint. Error storage must be writable and nonempty.
 * Status codes follow preparation_c_api.h; water rejection uses status 10.
 * Python object, arbitrary-integer and NumPy scalar protocols are not encoded
 * by this native-double input. Their production adapters remain separate.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_quick_design_v1(
    const tpmshx_quick_input_v1*,tpmshx_quick_prepared_v1*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_quick_prepared_release_v1(
    tpmshx_quick_prepared_v1*);
/* Run the supplied prepared fields without preparing them again. The existing
 * Quick Design driver owns const/mean passes, budgets and stopping rules.
 * The returned owner copies all grid, field and scalar evidence. The prepared
 * owner can then be released. The raw result is a value, not another owner.
 * A cancelled call returns status 6 and does not publish a result. Other
 * statuses follow solver_c_api.h. Callbacks keep that API's lifetime rules.
 * The existing Quick Design driver has no per-call CPU setting.
 * Input, result and error storage must be disjoint.
 * Initialize result ABI, struct size and owner=NULL; failure preserves it.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_run_quick_design_v1(
    const tpmshx_quick_prepared_v1*,const tpmshx_quick_run_control_v1*,
    tpmshx_quick_run_result_v1*,char*,size_t);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_quick_run_release_v1(
    tpmshx_quick_run_result_v1*);
#ifdef __cplusplus
}
#endif
#endif
