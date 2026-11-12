#ifndef TPMSHX_RESULT_STAGE_C_API_H
#define TPMSHX_RESULT_STAGE_C_API_H
#include "tpmshx/result_c_api.h"

#define TPMSHX_RESULT_STAGE_ABI_VERSION 1u

/* All input storage is borrowed for the call. A null pointer means absent
 * evidence. Truth values are -1 (unknown), 0 (false), and 1 (true).
 * Values -2 and -3 retain non-boolean truthy and False-equal declarations.
 * Value -5 retains a falsy declaration that does not compare equal to False.
 * A true-h completeness value of -4 means that the key was not recorded. */
typedef struct { const char* name; tpmshx_result_array_v1 value; } tpmshx_stage_named_array_v1;
/* Non-boolean gates require their original numeric scalar or text for reports.
 * Supply one recorded value. Boolean and unknown gates need neither pointer. */
typedef struct {
    const char* name;
    int value;
    const tpmshx_result_scalar_v1* recorded_number;
    const char* recorded_text;
} tpmshx_stage_gate_v1;
typedef struct { const tpmshx_result_array_v1* widths[3]; } tpmshx_stage_grid_v1;
typedef struct { const char* name; const char* unit; const char* state; } tpmshx_stage_field_declaration_v1;
typedef struct {
    const tpmshx_result_array_v1* pressure;
    tpmshx_stage_grid_v1 grid;
    const tpmshx_result_array_v1 *inlet_fraction, *outlet_fraction, *outlet_geom_fraction;
    const tpmshx_result_scalar_v1 *reference, *inlet_absolute, *outlet_absolute;
    const char* unit;
} tpmshx_stage_pressure_v1;
typedef struct {
    const char* name;
    int solved;
    const tpmshx_result_array_v1* residual;
    const tpmshx_stage_named_array_v1 *advective_out, *diffusive_out;
    size_t advective_count, diffusive_count;
    const tpmshx_result_array_v1* source_integral;
} tpmshx_stage_energy_phase_v1;
typedef struct {
    const char *definition, *power_units;
    int physical_dimension, physical_boundary_complete;
    const tpmshx_stage_energy_phase_v1* phases;
    size_t phase_count;
    const tpmshx_result_array_v1* prescribed_b_power;
} tpmshx_stage_energy_v1;
typedef struct {
    int physical_boundary_complete;
    const tpmshx_result_array_v1* staggered_power;
    size_t staggered_count;
    const tpmshx_stage_named_array_v1* boundary_power;
    size_t boundary_count;
} tpmshx_stage_model_side_v1;
typedef struct {
    int passed, physical_boundary_complete;
    tpmshx_stage_model_side_v1 sides[2];
} tpmshx_stage_model_certificate_v1;
typedef struct {
    const char *energy_algorithm, *boundary_power_units;
    const int* energy_algorithm_version;
    int physical_boundary_complete;
    const tpmshx_result_array_v1* enthalpy[2];
    const tpmshx_result_scalar_v1* inlet_enthalpy[2];
    const tpmshx_result_array_v1* mass[2];
    size_t mass_count[2];
    const tpmshx_stage_named_array_v1* boundary_power[2];
    size_t boundary_count[2];
    int invalid_version_type;
} tpmshx_stage_true_h_v1;
typedef struct {
    const tpmshx_result_array_v1* mass[2];
    size_t mass_count[2];
    const tpmshx_stage_energy_v1 *energy, *temperature;
    const tpmshx_stage_true_h_v1* true_h;
    const tpmshx_stage_model_certificate_v1* model_h;
    const int* report_direction[2];
} tpmshx_stage_thermal_v1;
typedef struct {
    tpmshx_stage_grid_v1 grid;
    const tpmshx_stage_named_array_v1* fields;
    size_t field_count;
    tpmshx_stage_thermal_v1 thermal;
    const tpmshx_result_array_v1 *rho_cp[2], *inlet_fraction[2], *outlet_fraction[2], *epsilon;
    int empty_record;
} tpmshx_stage_fine_v1;
typedef struct {
    int converged;
    const tpmshx_result_array_v1* clip_counts;
    const tpmshx_result_scalar_v1 *ratios[2], *tolerances[2];
} tpmshx_stage_true_h_certificate_v1;
typedef struct { const char* level; tpmshx_stage_model_certificate_v1 value; } tpmshx_stage_model_level_v1;
typedef struct { const char *side, *fluid; int solved; } tpmshx_stage_execution_side_v1;
typedef struct {
    int captured;
    const char *side, *quantity, *constraint, *stage, *layout, *unit, *reason;
    const char* const* source;
    size_t source_count;
    double bounds[2];
    const size_t* shape;
    size_t rank, size, low, high, nonfinite;
    const double *minimum, *maximum;
    const size_t *minimum_index, *maximum_index;
} tpmshx_stage_range_sample_v1;
typedef struct {
    const char *group, *side;
    const char* const* source;
    size_t source_count;
} tpmshx_stage_required_range_v1;
typedef struct {
    const char* version;
    const tpmshx_stage_range_sample_v1 *inlet, *final_state;
    size_t inlet_count, final_count;
    const tpmshx_stage_required_range_v1* required;
    size_t required_count;
    int inlet_recorded;
    const char* const* scope_notes;
    size_t scope_note_count;
} tpmshx_stage_applicability_v1;
typedef struct {
    const tpmshx_result_scalar_v1 *inlet_temperature, *mass_flow, *cp, *rho, *velocity, *viscosity;
} tpmshx_stage_quick_side_v1;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    const char* result_id;
    int dimension;
    const int* metadata_dimension;
    const char *quantity_basis, *mass_unit, *mode, *thermal_mode, *temperature_transport;
    tpmshx_stage_grid_v1 grid;
    const tpmshx_stage_named_array_v1* fields;
    size_t field_count;
    const tpmshx_stage_field_declaration_v1* field_metadata;
    size_t field_metadata_count;
    const tpmshx_stage_pressure_v1* pressure[2];
    tpmshx_stage_thermal_v1 thermal;
    const tpmshx_stage_fine_v1* fine;
    const char *thermal_state, *execution;
    int converged;
    const int* outer_index;
    const tpmshx_stage_gate_v1* convergence_gates;
    size_t convergence_gate_count;
    const tpmshx_stage_true_h_certificate_v1* true_h_certificate;
    const tpmshx_stage_model_level_v1* model_certificates;
    size_t model_certificate_count;
    const double *strict_ratios[4], *source_power[2];
    int model_active_b, richardson_extrapolated;
    const char* execution_version;
    const tpmshx_stage_execution_side_v1* executed_sides;
    size_t executed_side_count;
    const tpmshx_stage_applicability_v1* applicability;
    int active_fluids[2];
    const int* direction[2];
    const tpmshx_result_scalar_v1* inlet_temperature[2];
    const tpmshx_result_array_v1 *inlet_geom_fraction[2], *outlet_geom_fraction[2], *rho_cp[2];
    const tpmshx_result_array_v1 *parameter_epsilon, *design_epsilon;
    const tpmshx_result_scalar_v1 *split_a, *solid_density;
    const char *quick_model, *arrangement;
    tpmshx_stage_quick_side_v1 quick[2];
    const tpmshx_result_scalar_v1* hydraulic_diameter;
    /* Absent original DTO containers preserve historical first-error reasons. */
    const char* const* absent_records;
    size_t absent_record_count;
    const char* model_certificate_error;
} tpmshx_result_evidence_v1;
typedef struct { const char *name, *unit, *definition_version, *description; } tpmshx_stage_metric_spec_v1;
typedef struct {
    const char* name;
    tpmshx_stage_metric_spec_v1 spec;
    int has_value;
    double value;
    const char *status, *reason;
} tpmshx_stage_metric_value_v1;
typedef struct {
    size_t struct_size;
    void* owner;
    const char* json;
    const tpmshx_stage_metric_value_v1* metrics;
    size_t metric_count;
    tpmshx_result_diagnostics_v1 diagnostics;
} tpmshx_stage_output_v1;
/* v2 keeps host conversion failures lazy and delivers NumPy notices in order.
 * A fault points to its borrowed v1 scalar, array, string, or record storage.
 * Callback failure codes use result numerical causes, plus 6: KeyError,
 * 7: NotImplementedError, and 8: an unchanged host exception.
 */
typedef struct {
    const void* value;
    uint32_t cause;
    const char* message;
    uint64_t token;
} tpmshx_stage_input_error_v2;
typedef struct {
    uint32_t cause;
    int32_t error_number;
    uint64_t token;
    const char* message;
} tpmshx_stage_host_error_v2;
typedef int (TPMSHX_RESULT_CALL *tpmshx_stage_events_v2)(
    void*, const tpmshx_result_diagnostics_v1*, tpmshx_stage_host_error_v2*);
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    const tpmshx_result_evidence_v1* evidence;
    const tpmshx_stage_input_error_v2* errors;
    size_t error_count;
    const void* const* none_values;
    size_t none_count;
    const tpmshx_result_array_v1 *solid_density, *split_a, *inlet_temperature[2];
    const char* invalid_mode_repr;
    const int *physical_dimension_index, *physical_dimension_slice, *qualification_error;
    void* context;
    tpmshx_stage_events_v2 events;
} tpmshx_stage_input_v2;


/* V3 preserves the fixed Quick Design Python protocol boundaries.
 * Numeric values borrow typed arrays. Nonzero object tokens name host-owned
 * portable values or exact Python integers. Use exactly one representation.
 * A callback result stays valid until this synchronous query returns.
 * Callbacks cannot select metrics, change native policy or replace a report.
 */
typedef struct {
    const tpmshx_result_array_v1* numeric;
    uint64_t object;
} tpmshx_stage_quick_value_v3;
/* A label borrows null-terminated UTF-8 text or one original host value.
 * Use a host value for text that this C string cannot represent without loss.
 * Native policy owns the text. The host applies the original comparison operator. */
typedef struct {
    const char* text;
    const tpmshx_stage_quick_value_v3* value;
} tpmshx_stage_label_v3;
typedef struct {
    const int *boundary_access, *properties_access, *pressure_access;
    const tpmshx_stage_quick_value_v3 *inlet_temperature, *mass_flow, *cp, *rho, *velocity, *viscosity;
    const tpmshx_stage_quick_value_v3 *inlet_pressure, *outlet_pressure;
} tpmshx_stage_quick_side_v3;
/* Each member has one fixed expression. The native stage supplies its operands
 * only at the existing Python protocol boundary and in the original order. */
typedef struct {
    void* context;
    int (TPMSHX_RESULT_CALL *text_equal)(void*, const tpmshx_stage_quick_value_v3*, const char*,
        int*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *text_not_equal)(void*, const tpmshx_stage_quick_value_v3*, const char*,
        int*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *temperature_difference)(void*, const tpmshx_stage_quick_value_v3*, double,
        tpmshx_stage_quick_value_v3*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *capacity_product)(void*, const tpmshx_stage_quick_value_v3*, const tpmshx_stage_quick_value_v3*,
        tpmshx_stage_quick_value_v3*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *duty_product)(void*, const tpmshx_stage_quick_value_v3*, const tpmshx_stage_quick_value_v3*, int,
        tpmshx_stage_quick_value_v3*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *pressure_difference)(void*, const tpmshx_stage_quick_value_v3*, const tpmshx_stage_quick_value_v3*,
        tpmshx_stage_quick_value_v3*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *reynolds_flow)(void*, const tpmshx_stage_quick_value_v3*, const tpmshx_stage_quick_value_v3*,
        tpmshx_stage_quick_value_v3*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *reynolds_length)(void*, const tpmshx_stage_quick_value_v3*, const tpmshx_stage_quick_value_v3*,
        tpmshx_stage_quick_value_v3*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *reynolds_quotient)(void*, const tpmshx_stage_quick_value_v3*, const tpmshx_stage_quick_value_v3*,
        tpmshx_stage_quick_value_v3*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *metric_float)(void*, const tpmshx_stage_quick_value_v3*, double*, tpmshx_stage_host_error_v2*);
    int (TPMSHX_RESULT_CALL *empty_mean)(void*, tpmshx_stage_host_error_v2*);
} tpmshx_stage_quick_protocol_v3;
typedef struct {
    uint32_t abi_version;
    size_t struct_size;
    const tpmshx_stage_input_v2* host;
    const tpmshx_stage_label_v3 *model, *arrangement, *execution_version;
    tpmshx_stage_quick_side_v3 sides[2];
    const tpmshx_stage_quick_value_v3* hydraulic_diameter;
    tpmshx_stage_quick_protocol_v3 protocol;
} tpmshx_stage_input_v3;

#ifdef __cplusplus
extern "C" {
#endif
/* Output storage is set only on success. Release it in the creating library.
 * A wrong output size or a nonempty owner leaves diagnostic storage unchanged.
 */
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_stage_evaluate_v1(
    const tpmshx_result_evidence_v1*, const tpmshx_stage_metric_spec_v1*,
    tpmshx_stage_output_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_stage_applicability_v1(
    const tpmshx_result_evidence_v1*, tpmshx_stage_output_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_stage_physical_balance_v1(
    const tpmshx_result_evidence_v1*, tpmshx_stage_output_v1*, char*, size_t);
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_stage_qualification_v1(
    const tpmshx_result_evidence_v1*, const tpmshx_stage_metric_value_v1*, size_t,
    tpmshx_stage_output_v1*, char*, size_t);
/* query: 0 evaluate, 1 applicability, 2 physical balance, 3 qualification.
 * A host may omit report-only gate values and restore them after this call.
 * Gate truth declarations and deferred comparisons still control native policy.
 * Diagnostic/cause storage is independent of the success-only output.
 */
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_stage_query_v2(
    const tpmshx_stage_input_v2*, uint32_t,
    const tpmshx_stage_metric_spec_v1*, const tpmshx_stage_metric_value_v1*, size_t,
    tpmshx_stage_output_v1*, tpmshx_result_diagnostics_v1*, uint64_t*, char*, size_t);
/* V3 uses the same queries, output ownership and deferred-error rules as v2.
 * A null model omits typed Quick operands. The execution label remains usable
 * by full-result queries.
 * All input and callback-returned storage must be disjoint from writable output.
 * Missing protocol callbacks are errors when the selected input requires one.
 */
TPMSHX_RESULT_API int TPMSHX_RESULT_CALL tpmshx_result_stage_query_v3(
    const tpmshx_stage_input_v3*, uint32_t,
    const tpmshx_stage_metric_spec_v1*, const tpmshx_stage_metric_value_v1*, size_t,
    tpmshx_stage_output_v1*, tpmshx_result_diagnostics_v1*, uint64_t*, char*, size_t);
TPMSHX_RESULT_API void TPMSHX_RESULT_CALL tpmshx_result_stage_release_v1(tpmshx_stage_output_v1*);
#ifdef __cplusplus
}
#endif
#endif
