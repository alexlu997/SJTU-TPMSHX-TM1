#ifndef TPMSHX_QUICK_DESIGN_STAGE_C_API_H
#define TPMSHX_QUICK_DESIGN_STAGE_C_API_H

#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/solver_c_api.h"
#include "tpmshx/result_stage_c_api.h"
#include "tpmshx/property_c_api.h"

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

/* V2 keeps raw scalar kinds and stored controls. V1 layouts stay unchanged. */
#define TPMSHX_QUICK_PREPARATION_ABI_VERSION 2u
#define TPMSHX_QUICK_HOST_FAILURE 20

enum tpmshx_quick_value_v2 {
    TPMSHX_QUICK_CELL=0, TPMSHX_QUICK_WALL, TPMSHX_QUICK_SPAN,
    TPMSHX_QUICK_LENGTH, TPMSHX_QUICK_HEIGHT, TPMSHX_QUICK_CONDUCTIVITY,
    TPMSHX_QUICK_TOLERANCE, TPMSHX_QUICK_MASS_A, TPMSHX_QUICK_MASS_B,
    TPMSHX_QUICK_TEMPERATURE_A, TPMSHX_QUICK_TEMPERATURE_B,
    TPMSHX_QUICK_PRESSURE_A, TPMSHX_QUICK_PRESSURE_B,
    TPMSHX_QUICK_VALUE_COUNT
};
typedef struct {
    uint32_t abi_version; size_t struct_size;
    tpmshx_grid_scalar_v1 values[TPMSHX_QUICK_VALUE_COUNT];
    tpmshx_preparation_text_v1 topology,arrangement,property_mode,fluids[2];
    uint32_t have_height,have_chi,strict; double chi;
    uint32_t warm_start; size_t initial_shape[3];
    tpmshx_preparation_array_v1 initial[3];
} tpmshx_quick_input_v2;
typedef struct {
    uint32_t dir_b; size_t ny,nz,max_iterations;
    double alpha,q_relative_tolerance; size_t chunk_iterations;
    uint32_t have_q_relative_tolerance,have_chunk_iterations;
} tpmshx_quick_controls_v2;
typedef struct {
    uint32_t abi_version; size_t struct_size; void* owner;
    size_t shape[3];
    tpmshx_preparation_array_v1 widths[3],edges[3],initial[3];
    uint32_t width_precision[3],solid_precision;
    tpmshx_preparation_array_v1 epsilon,epsilon_a,solid_conductivity;
    tpmshx_preparation_geometry_cache_v3 geometry;
    tpmshx_grid_scalar_v1 cell_length_m,wall_thickness_m,fractions[2];
    tpmshx_quick_controls_v2 controls;
    tpmshx_preparation_df_pressure_v1 inlet_pressure[2];
} tpmshx_quick_prepared_v2;
typedef struct {
    uint32_t abi_version; size_t struct_size;
    tpmshx_grid_scalar_v1 fractions[2];
    tpmshx_preparation_df_pressure_v1 inlet_pressure[2];
} tpmshx_quick_pressure_v2;

/* These named operations preserve host object and observation protocols.
 * They cannot call a model, property, pressure or solver implementation.
 * The stage selects every operation and numerical branch. A nonzero callback
 * result stops the call. The host then raises its saved original exception.
 */
enum tpmshx_quick_host_operation_v2 {
    TPMSHX_QUICK_WARM_CHECK=1, TPMSHX_QUICK_LABEL_CHECK,
    TPMSHX_QUICK_POSITIVE_SNAPSHOT, TPMSHX_QUICK_POSITIVE_CHECK,
    TPMSHX_QUICK_SHAPE_CHECK, TPMSHX_QUICK_GEOMETRY_PACK,
    TPMSHX_QUICK_MATERIAL_PACK, TPMSHX_QUICK_WIDTH_PACK,
    TPMSHX_QUICK_OPERATING_SNAPSHOT, TPMSHX_QUICK_PROPERTY_ENTRY,
    TPMSHX_QUICK_STATE_PACK, TPMSHX_QUICK_PROPERTY_PACK,
    TPMSHX_QUICK_PROPERTY_RESULT, TPMSHX_QUICK_PRANDTL_PACK,
    TPMSHX_QUICK_SECTIONS_PACK, TPMSHX_QUICK_PRESSURE_ENTRY,
    TPMSHX_QUICK_FLOW_PACK, TPMSHX_QUICK_FLOW_RESULT,
    TPMSHX_QUICK_PRESSURE_COMPARE, TPMSHX_QUICK_PRESSURE_PACK,
    TPMSHX_QUICK_PRESSURE_RESULT, TPMSHX_QUICK_FRACTION_PACK,
    TPMSHX_QUICK_CONFIG_SNAPSHOT, TPMSHX_QUICK_UNIT_PACK,
    TPMSHX_QUICK_UNIT_RESULT, TPMSHX_QUICK_FINAL_SNAPSHOT,
    TPMSHX_QUICK_FAILURE, TPMSHX_QUICK_SECTIONS_RESULT,
    TPMSHX_QUICK_EOS_CACHE_LOOKUP, TPMSHX_QUICK_EOS_CACHE_STORE
};
/* A request is borrowed only during its callback. The operation fixes which
 * fields are inputs and outputs; see native-stages.md. Index identifies an
 * axis, positive-input slot or property (rho,mu,k,cp,Pr). Side is 0=A,1=B.
 * property_inputs carry already-broadcast buffers with original scalar tags.
 * property_values supplies a stored EOS result only for cache lookup. Other
 * property_values and geometry fields are observations, not model callbacks.
 * Host scalars/flags/text contain only raw packing or fixed operator results.
 */
typedef struct {
    uint32_t operation,side,index,flags[4];
    tpmshx_grid_scalar_v1 scalars[6];
    tpmshx_preparation_text_v1 text;
    tpmshx_property_input_v1 property_inputs[3];
    double imaginary_inputs[3]; uint32_t categories[3];
    tpmshx_preparation_array_v1 property_values,property_imaginary;
    tpmshx_grid_scalar_v1 property_kind;
    uint32_t property_category;
    const uint32_t* floating_events; size_t floating_event_count;
    const tpmshx_preparation_geometry_cache_v3* geometry;
    const tpmshx_preparation_df_pressure_v1* pressure;
    const tpmshx_property_failure_v1* failure;
    int status;
} tpmshx_quick_host_request_v2;
typedef struct {
    uint32_t abi_version; size_t struct_size; void* context; uint32_t raw_objects;
    int (TPMSHX_PREPARATION_CALL *host)(void*,tpmshx_quick_host_request_v2*);
    int (TPMSHX_PREPARATION_CALL *geometry_cache)(void*,uint32_t,
        tpmshx_preparation_geometry_cache_v3*,uint32_t*);
} tpmshx_quick_callbacks_v2;

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
 * Input, result and error storage must be disjoint. If storage checks stop
 * early, error bytes stay unchanged. Semantic errors with safe storage write
 * a diagnostic. Initialize result ABI, struct size and owner=NULL; failure
 * preserves the result.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_run_quick_design_v1(
    const tpmshx_quick_prepared_v1*,const tpmshx_quick_run_control_v1*,
    tpmshx_quick_run_result_v1*,char*,size_t);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_quick_run_release_v1(
    tpmshx_quick_run_result_v1*);
/* Typed raw preparation retains the original validation and calculation order.
 * Text uses explicit byte lengths. No environment is read without host hooks.
 * Native callers provide all 13 values; have_height=0 substitutes span.
 * The pressure-only query skips full validation and allocates no thermal grid.
 * Every non-cross arrangement uses counter sections for that query only.
 * Results require version=2, exact struct_size and owner=NULL where present.
 * Failure preserves results. Borrowed callbacks and their data must outlive
 * the call. Release full output with the same preparation library.
 */
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_prepare_quick_design_v2(
    const tpmshx_quick_input_v2*,const tpmshx_quick_callbacks_v2*,
    tpmshx_quick_prepared_v2*,char*,size_t);
TPMSHX_PREPARATION_API int TPMSHX_PREPARATION_CALL tpmshx_quick_pressure_fractions_v2(
    const tpmshx_quick_input_v2*,const tpmshx_quick_callbacks_v2*,
    tpmshx_quick_pressure_v2*,char*,size_t);
TPMSHX_PREPARATION_API void TPMSHX_PREPARATION_CALL tpmshx_quick_prepared_release_v2(
    tpmshx_quick_prepared_v2*);

#ifdef __cplusplus
}
#endif
#endif
