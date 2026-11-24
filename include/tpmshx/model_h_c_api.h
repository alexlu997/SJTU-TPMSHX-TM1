#ifndef TPMSHX_MODEL_H_C_API_H
#define TPMSHX_MODEL_H_C_API_H
#include "tpmshx/thermal_c_api.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Optional full-solve overrides. Zero retains each route's current default.
 * Positive tolerances are finite. The budget includes charged startup trials.
 * Physical audit thresholds and chunk sizes remain unchanged. */
typedef struct {
    size_t max_iterations;
    double temperature_tolerance,q_relative_tolerance;
} tpmshx_model_h_iteration_options_v1;
typedef struct {
    size_t outer_index,attempt;
    uint32_t refined;
    size_t max_iterations,chunk_iterations;
    double temperature_tolerance,q_relative_tolerance;
    size_t total_iteration_budget;
} tpmshx_model_h_iteration_record_v1;
typedef struct {
    const tpmshx_model_h_iteration_record_v1* records;
    size_t count;
} tpmshx_model_h_iteration_records_v1;
typedef struct {
    uint32_t enabled;
    size_t sweeps_per_block,history_limit;
} tpmshx_model_h_acceleration_v1;

typedef struct { const double* data; size_t size; } tpmshx_model_h_array_v1;

typedef struct {
    double q_advective,inlet_conduction,exchange;
    double residual_sum,residual_max,linearized_sum,linearized_max;
    double defect_sum,defect_max,mass_net,mass_local_max,mass_in,mass_out;
    double normalization,cell_ratio;
    size_t unknown_inflow_faces;
    double cp_coefficients[5];
    tpmshx_model_h_array_v1 boundary_mass_out[4],boundary_h_out[4],h_faces[2];
    tpmshx_model_h_array_v1 inlet_conduction_faces,residual,linearization_defect;
} tpmshx_model_h_side_2d_v1;
typedef struct {
    tpmshx_model_h_side_2d_v1 sides[2];
    double solid_sum,solid_max,solid_cell_ratio,residual_sum,telescoping_error;
    double net_boundary_in,denominator,energy_imbalance,solid_imbalance;
    uint32_t boundary_complete,finite,energy_ok,solid_ok,equations_ok,passed;
    tpmshx_model_h_array_v1 solid_residual;
} tpmshx_model_h_audit_2d_v1;

typedef struct {
    double mass_out,enthalpy_out,unknown_mass_in,inlet_reverse_mass_out;
    size_t unknown_inflow_count;
    tpmshx_model_h_array_v1 enthalpy_faces;
} tpmshx_model_h_boundary_3d_v1;
typedef struct {
    tpmshx_model_h_boundary_3d_v1 boundaries[6];
    double cp_coefficients[5];
    double temperature_min,temperature_max,mass_net;
    double advective_in,diffusion_in,numerical_external_in,exchange,source;
    double residual_sum,residual_max,normalization,global_ratio,cell_ratio;
    uint32_t boundary_complete;
    tpmshx_model_h_array_v1 residual,inlet_diffusion;
} tpmshx_model_h_side_3d_v1;
typedef struct {
    tpmshx_model_h_side_3d_v1 sides[2];
    double volume,numerical_external_in,explicit_source,solid_sum,solid_max;
    double full_residual_sum,telescoping_error,ltne_source_ratio;
    uint32_t boundary_complete,gates[6],passed;
    tpmshx_model_h_array_v1 solid_residual;
} tpmshx_model_h_audit_3d_v1;

typedef struct {
    size_t iterations;
    /* 2D: passed,equations_ok in [0:2]. 3D: original six phase2a gates. */
    uint32_t gates[6];
} tpmshx_model_h_check_v1;
typedef struct {
    uint32_t dimension,stop,audit_available,has_sources;
    size_t iterations;
    double residual,q_b;
    tpmshx_model_h_audit_2d_v1 plane;
    tpmshx_model_h_audit_3d_v1 volume;
    const tpmshx_model_h_check_v1* finishing_checks;
    size_t finishing_count;
    void* owner;  /* NULL; the full result owner keeps these views */
} tpmshx_model_h_result_v1;

/* Read-only recipe identity. Static storage; NULL for unsupported dimensions. */
TPMSHX_THERMAL_API const char* TPMSHX_THERMAL_CALL tpmshx_model_h_algorithm_v1(uint32_t dimension);

#ifdef __cplusplus
}
#endif
#endif
