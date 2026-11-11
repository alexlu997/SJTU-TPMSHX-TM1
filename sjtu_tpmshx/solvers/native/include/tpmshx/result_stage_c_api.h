#ifndef TPMSHX_RESULT_STAGE_C_API_H
#define TPMSHX_RESULT_STAGE_C_API_H
#include "tpmshx/result_c_api.h"

#define TPMSHX_RESULT_STAGE_ABI_VERSION 1u

/* All input storage is borrowed for the call. A null pointer means absent
 * evidence. Truth values are -1 (unknown), 0 (false), and 1 (true).
 * Values -2 and -3 retain non-boolean true/false declarations for validation.
 * A true-h completeness value of -4 means that the key was not recorded. */
typedef struct { const char* name; tpmshx_result_array_v1 value; } tpmshx_stage_named_array_v1;
typedef struct { const char* name; int value; } tpmshx_stage_gate_v1;
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
#ifdef __cplusplus
extern "C" {
#endif
/* Output storage is set only on success. Release it in the creating library. */
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
TPMSHX_RESULT_API void TPMSHX_RESULT_CALL tpmshx_result_stage_release_v1(tpmshx_stage_output_v1*);
#ifdef __cplusplus
}
#endif
#endif
