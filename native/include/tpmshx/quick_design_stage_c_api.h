#ifndef TPMSHX_QUICK_DESIGN_STAGE_C_API_H
#define TPMSHX_QUICK_DESIGN_STAGE_C_API_H

#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/solver_c_api.h"
#include "tpmshx/result_stage_c_api.h"
#include "tpmshx/property_c_api.h"
#include "tpmshx/closure_evidence_c_api.h"

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

/* V2 uses float64 values and stored controls. V1 layouts stay unchanged. */
#define TPMSHX_QUICK_PREPARATION_ABI_VERSION 2u
#define TPMSHX_QUICK_HOST_FAILURE 20
#define TPMSHX_QUICK_RANGE_CAPACITY 8u

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
    double values[TPMSHX_QUICK_VALUE_COUNT];
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
/* One fitted empirical property range at the inlet temperature.
 * label points to static library storage. side is 0=A or 1=B.
 */
typedef struct {
    const char* label;
    uint32_t side;
    double bounds[2];
    double temperature_K;
} tpmshx_quick_range_v2;
/* floating_events has one word for each side and stage, in the order
 * A properties, A Prandtl, B properties, B Prandtl. Each word combines the
 * stage's FP flag bits and keeps the operation code of its first event.
 * inlet_pressure keeps the ordered D-F pressure events. ranges keeps the
 * fitted property ranges in calculation order.
 */
typedef struct {
    uint32_t abi_version; size_t struct_size; void* owner;
    size_t shape[3];
    tpmshx_preparation_array_v1 widths[3],edges[3],initial[3];
    tpmshx_preparation_array_v1 epsilon,epsilon_a,solid_conductivity;
    tpmshx_preparation_geometry_cache_v3 geometry;
    double cell_length_m,wall_thickness_m,fractions[2];
    tpmshx_quick_controls_v2 controls;
    tpmshx_preparation_df_pressure_v1 inlet_pressure[2];
    uint32_t floating_events[4];
    tpmshx_quick_range_v2 ranges[TPMSHX_QUICK_RANGE_CAPACITY];
    size_t range_count;
} tpmshx_quick_prepared_v2;
typedef struct {
    uint32_t abi_version; size_t struct_size;
    double fractions[2];
    tpmshx_preparation_df_pressure_v1 inlet_pressure[2];
    uint32_t floating_events[4];
    tpmshx_quick_range_v2 ranges[TPMSHX_QUICK_RANGE_CAPACITY];
    size_t range_count;
} tpmshx_quick_pressure_v2;

/* Cache hooks transport completed values only. They never calculate them.
 * geometry_cache: action 0 looks up and sets hit to 0 or 1; action 1 publishes.
 * eos_cache: fluid 2 (sCO2) stores one value for property_index 0..3
 * (rho, mu, k, cp). Fluid 3 (CO2) stores the five-value D,V,L,C,H bundle.
 * Action 0 looks up: the host writes count values and sets hit. Action 1
 * publishes count values. A nonzero return stops the call with status 20.
 */
typedef struct {
    uint32_t abi_version; size_t struct_size; void* context;
    int (TPMSHX_PREPARATION_CALL *geometry_cache)(void*,uint32_t,
        tpmshx_preparation_geometry_cache_v3*,uint32_t*);
    int (TPMSHX_PREPARATION_CALL *eos_cache)(void*,uint32_t action,uint32_t fluid,uint32_t property_index,
        double temperature_K,double pressure_Pa,double* values,size_t capacity,size_t* count,uint32_t* hit);
} tpmshx_quick_callbacks_v2;

#ifdef __cplusplus
extern "C" {
#endif
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
 * preserves the result. Run the stored V2 controls and fields with the
 * matching input labels. The input and prepared views stay valid until this
 * call returns.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_run_quick_design_v2(
    const tpmshx_quick_input_v2*,const tpmshx_quick_prepared_v2*,
    const tpmshx_quick_run_control_v1*,tpmshx_quick_run_result_v1*,char*,size_t);
typedef struct {
    const tpmshx_stage_range_record_v1* data;
    size_t count;
} tpmshx_quick_ranges_v2;
/* These pass and side records belong to the live run result. */
TPMSHX_THERMAL_API tpmshx_quick_ranges_v2 TPMSHX_THERMAL_CALL tpmshx_quick_run_ranges_v2(
    const tpmshx_quick_run_result_v1*,size_t pass,size_t side);
/* Temperature recipe used by a live completed run. The returned string
 * is immutable static storage. A missing run owner returns NULL. */
TPMSHX_THERMAL_API const char* TPMSHX_THERMAL_CALL tpmshx_quick_run_temperature_algorithm_v1(
    const tpmshx_quick_run_result_v1*);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_quick_run_release_v1(
    tpmshx_quick_run_result_v1*);
/* Float64 preparation retains the validation and calculation order.
 * Text uses explicit byte lengths. No environment is read.
 * Native callers provide all 13 values; have_height=0 substitutes span.
 * Status 10/11/12 reports a water/CO2/sCO2 state error.
 * Status 13 reports scalar division by zero.
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
