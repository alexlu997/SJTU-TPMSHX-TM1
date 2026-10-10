#ifndef TPMSHX_FULL_3D_C_API_H
#define TPMSHX_FULL_3D_C_API_H
#include "tpmshx/simple_3d_c_api.h"
#include "tpmshx/model_h_c_api.h"
#include "tpmshx/enthalpy_driver_c_api.h"
#include "tpmshx/closure_evidence_c_api.h"
#include "tpmshx/temperature_evidence_c_api.h"
#ifdef __cplusplus
extern "C" {
#endif
#define TPMSHX_FULL_3D_ABI_VERSION 1u

typedef struct { const double* data; size_t size; } tpmshx_full3d_array_v1;
typedef struct {
    uint32_t fluid,direction,solver_axes[3];
    double inlet_temperature,inlet_pressure,inlet_velocity;
    double inlet_rectangle[4],outlet_rectangle[4];
    tpmshx_full3d_array_v1 inlet_opening,outlet_opening;
    double permeability_scale,forchheimer_scale,dispersion,sco2_nusselt_multiplier;
    double heat_transfer_geometry[4];
} tpmshx_full3d_side_v1;
typedef struct {
    size_t shape[3];
    tpmshx_full3d_array_v1 widths[3],epsilon,epsilon_a,epsilon_b,permeability,forchheimer;
    tpmshx_full3d_array_v1 solid_conductivity,cell_length,area_density,hydraulic_diameter;
    double reference_cell_length,reference_hydraulic_diameter;
    uint32_t topology,spatial,asymmetric,solve_b;
    tpmshx_full3d_side_v1 sides[2];
    tpmshx_full3d_array_v1 sources[3];
} tpmshx_full3d_input_v1;
typedef struct {
    size_t max_outer,initial_simple_iterations,warm_simple_iterations,thermal_iterations;
    double outer_temperature_tolerance,thermal_relaxation;
    uint32_t pressure_shooting,variable_rho_cp,conservative,strict_mass_balance,force_cell_centered;
    uint32_t refined_port_energy,red_black_energy,sco2_local_pressure_a,coarse_bootstrap,outer_anderson;
    size_t coarse_iterations,anderson_history,anderson_patience;
    double anderson_trust;
    uint32_t roughness_mode,envelope_mode,has_initial_solid_temperature;
    double roughness_height,initial_solid_temperature;
    tpmshx_simple_3d_config_v1 simple;
    size_t enthalpy_iterations,enthalpy_sweeps;
    double enthalpy_omega,enthalpy_update_tolerance;
    const char* table_directory;
} tpmshx_full3d_control_v1;
typedef struct {
    int (TPMSHX_THERMAL_CALL *cancel)(void*);
    void (TPMSHX_THERMAL_CALL *progress)(void*,double);
    void (TPMSHX_THERMAL_CALL *outer_iteration)(void*,size_t,size_t);
    void* context;
} tpmshx_full3d_callbacks_v1;
typedef struct {
    uint32_t available,passed;
    double specified,realized,outlet,outlet_gauge,minimum,relative_error,relative_tolerance;
    const char* definition;
} tpmshx_full3d_pressure_state_v1;
typedef struct {
    const char* stage;
    double anchor,estimate,relative_error,target,step_fraction;
    uint32_t has_estimate,has_relative_error,has_target,has_step_fraction;
    const char* method;
} tpmshx_full3d_pressure_iteration_v1;
typedef struct {
    uint32_t available,applied,converged;
    size_t iterations,shape[3];
    double residual;
    const char* reason;
} tpmshx_full3d_bootstrap_v1;
typedef struct {
    uint32_t available;
    size_t applied,rejected,resets;
    tpmshx_full3d_array_v1 residuals;
} tpmshx_full3d_anderson_v1;
typedef struct {
    tpmshx_full3d_array_v1 widths[3],epsilon,permeability,forchheimer,temperature;
    tpmshx_full3d_array_v1 viscosity,effective_viscosity,density,u,v,w,pressure,pressure_correction,d_u,d_v,d_w;
    tpmshx_full3d_array_v1 inlet_velocity,inlet_opening,outlet_opening,outlet_u_fraction,outlet_w_fraction,fixed_inlet_massflux;
    tpmshx_full3d_array_v1 pressure_real,density_real,speed_real,velocity_real[3],face_velocity_real[3];
    double pressure_reference;
    tpmshx_simple_3d_result_v1 last;
    tpmshx_full3d_array_v1 legacy,local_mass,global_mass,momentum;
    const tpmshx_full3d_pressure_iteration_v1* pressure_iterations;
    size_t pressure_iteration_count;
    tpmshx_full3d_pressure_state_v1 inlet_pressure;
    tpmshx_full3d_bootstrap_v1 bootstrap;
    tpmshx_full3d_anderson_v1 anderson;
} tpmshx_full3d_flow_v1;
typedef struct {
    uint32_t available,skipped,used_bordered_lu;
    size_t cg_iterations;
    double rhs_mean,residual_relative;
    tpmshx_full3d_array_v1 residual_cells;
    uint32_t residual_available;
    double residual_sum,residual_max,exchange,global_ratio,cell_ratio;
} tpmshx_full3d_projection_v1;
typedef struct {
    size_t outer_index,thermal_iterations;
    double thermal_residual,temperature_change[3];
    tpmshx_full3d_pressure_state_v1 inlet_pressure[2];
    double pressure_reference[2],pressure_range[2][2];
    uint32_t thermal_converged,coupling_converged;
    const size_t* rejected_startup_iterations;
    size_t rejected_startup_count,startup_total_iterations;
    const char* const* rejected_startup_reasons;
    uint32_t has_model_h,has_true_h;
    tpmshx_model_h_result_v1 model_h;
    tpmshx_enthalpy_result_v1 true_h;
} tpmshx_full3d_outer_v1;
typedef struct {
    uint32_t stop,converged,simple_ok,thermal_ok,outer_ok,finite_fields,envelope_ok,post_after_last_thermal;
    uint32_t thermal_mode;
    size_t thermal_outer_index;
    tpmshx_full3d_flow_v1 flow[2];
    tpmshx_full3d_array_v1 temperature[3],thermal_pressure[2],hv[2],rho_cp[2],conductivity[2];
    tpmshx_full3d_array_v1 mass[2][3],face_velocity[2][3],inlet_capacity[2],enthalpy[2];
    uint32_t has_model_h,has_true_h;
    tpmshx_model_h_result_v1 model_h;
    tpmshx_enthalpy_result_v1 true_h;
    tpmshx_full3d_projection_v1 staggered[2];
    const tpmshx_full3d_outer_v1* outer;
    size_t outer_count;
    const char* const* simple_failures;
    size_t simple_failure_count;
    const char* const* warnings;
    size_t warning_count;
    const char* const* envelope_reasons;
    size_t envelope_reason_count;
    tpmshx_full3d_array_v1 final_conductivity[2],final_rho_cp[2];
    double inlet_cp[2];
    tpmshx_nu_observation_v1 nu_observations[2];
    const tpmshx_range_observation_v1* range_observations;
    size_t range_observation_count;
    double pressure_drop[2],outlet_temperature[2],inlet_mass[2],duty[2],maximum_mach[2],minimum_pressure[2];
    double solid_exchange[2],interior_exchange[2],physical_mass_in[2],physical_mass_out[2],mass_imbalance[2];
    double energy_imbalance,interior_duty,interior_imbalance,enthalpy_imbalance;
    void* owner;
} tpmshx_full3d_result_v1;

/* Additive diagnostic view: the existing ABI 1 result layout is unchanged. */
typedef struct {
    size_t depth,fine_shape[3],coarse_shape[3],iteration_cap,charged_iterations;
    uint32_t solve_started,applied,converged,child_selected;
    const char* stop;
} tpmshx_full3d_bootstrap_level_v1;
typedef struct {
    uint32_t available,selected;
    const char* policy;
    const char* decision;
    size_t fine_shape[3],coarse_iteration_cap,recursive_iteration_cap,auto_cell_threshold,min_coarse_axis;
    const tpmshx_full3d_bootstrap_level_v1* levels;
    size_t level_count,actual_levels,started_cap_sum,total_charged_iterations;
} tpmshx_full3d_bootstrap_trace_v1;

TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_full_3d_abi_version(void);
/* Full prepared-data 3D execution in SI. Input geometry is physical (x,y,z),
 * C order; side openings are prepared solver (cross1,cross2). Full immutable
 * fields, physical port rectangles and D-F application scales are mandatory.
 * Sources are optional empty arrays. No numerical Python callback is used.
 * Flags are 0/1; fluid 0air/1water/2sCO2/3CO2, topology 0Diamond/1Gyroid,
 * direction 0+x/1-x/2+y/3-y/4+z/5-z. SIMPLE controls preserve their v1 meaning
 * except max_iterations/reference/ideal_gas are owned by the outer driver.
 * All input storage is borrowed through return; callbacks are synchronous and
 * must not throw or mutate inputs. error is required with positive capacity.
 * Status 0 means return, not convergence. stop0 converged/1cap/2cancelled.
 * Status1 invalid input,2 water phase,3 arithmetic,4 native error leaves result
 * untouched. No exception crosses C. Cancellation never certifies partial
 * fields. Always release every successful result, including cancellation.
 * Owned read-only views survive the input buffers. They are freed together by
 * release. Do not copy owner or independently release the borrowed model_h
 * subresult. release accepts NULL/already-cleared and clears the entire POD.
 * Detached thermal evidence precedes any final capped post; flow is the final
 * SIMPLE state. Histories/momentum rows are iteration,max,num3,den3,component3.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_full_3d_v1(
    const tpmshx_full3d_input_v1*,const tpmshx_full3d_control_v1*,
    const tpmshx_full3d_callbacks_v1*,tpmshx_full3d_result_v1*,char*,size_t);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_full_3d_release_v1(tpmshx_full3d_result_v1*);
/* Explicit conservative energy selection. Reuses the ABI 1 input/control and
 * result ownership; release with full_3d_release_v1. options is required.
 * The original entry point always selects legacy H-FOU. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_full_3d_v2(
    const tpmshx_full3d_input_v1*,const tpmshx_full3d_control_v1*,
    const tpmshx_energy_options_v1*,const tpmshx_full3d_callbacks_v1*,
    tpmshx_full3d_result_v1*,char*,size_t);
/* Explicit strict thermal controls; options_v2 is required. All thresholds
 * must be finite and positive, and the new flag must be 0 or 1. Uses the
 * original input/control/result PODs, error statuses and owner release.
 * Requires the existing two-sided true-h route (solve_b and at least one
 * sCO2 side); unused thermal controls are rejected before flow execution.
 * v1/v2 retain their .001 coupled/equation gates and disabled extra h gate. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_full_3d_v3(
    const tpmshx_full3d_input_v1*,const tpmshx_full3d_control_v1*,
    const tpmshx_energy_options_v2*,const tpmshx_full3d_callbacks_v1*,
    tpmshx_full3d_result_v1*,char*,size_t);

typedef struct {
    uint32_t available,algorithm,require_enthalpy_update_on_temperature;
    size_t max_iterations,sweeps;
    double omega,update_tolerance,temperature_update_tolerance;
    double coupled_energy_tolerance,equation_energy_tolerance;
} tpmshx_energy_effective_settings_v1;
typedef struct {
    tpmshx_energy_effective_settings_v1 resolved,last;
    const tpmshx_energy_effective_settings_v1* outer;
    size_t outer_count;
} tpmshx_full3d_energy_effective_settings_v1;
/* No numerical work. resolved contains the validated control adopted by the
 * full driver, including on cooperative cancellation. Its values alone do
 * not prove execution: available is true only after an actual completed
 * (possibly iteration-limited) true-h call, as for last/outer. All available
 * flags are false on full-driver cancellation or non-true-h routes.
 * outer indices match result.outer exactly. Values never imply convergence.
 * Views borrow the live result owner until release_v1. Status 1 for null or
 * released arguments leaves output unchanged. No owner is created on errors.
 * update_tolerance is the dimensionless h residual; temperature_update_tolerance
 * is K. Legacy H-FOU always uses its original h gate. T algorithms use the h
 * gate only when require_enthalpy_update_on_temperature is 1. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_get_energy_effective_settings_v1(
    const tpmshx_full3d_result_v1*,tpmshx_full3d_energy_effective_settings_v1*);

typedef struct {
    uint32_t available;
    tpmshx_energy_result_v1 energy;
    tpmshx_full3d_array_v1 actual_conductivity[2];
    /* Outward signed m*h_face; x-,x+,y-,y+,z-,z+; C-order boundary planes. */
    tpmshx_full3d_array_v1 boundary_power[2][6];
    const tpmshx_energy_result_v1* outer;
    size_t outer_count;
} tpmshx_full3d_energy_evidence_v1;
/* Read-only final thermal evidence and scalar outer history. Views borrow the
 * live result owner until release. available is false without a completed
 * candidate thermal call, including cancellation; no numerical work occurs.
 * Error status 1 leaves output unchanged. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_get_energy_evidence_v1(
    const tpmshx_full3d_result_v1*,tpmshx_full3d_energy_evidence_v1*);
/* Read-only query, side 0=A/1=B, status 0 success/1 invalid argument or no
 * live owner. Leaves output untouched on error. Views borrow the result owner
 * through release, including an existing cooperative-cancelled result. Hard
 * solve errors still publish no owner, so cannot expose a trace through this
 * API. No allocation, numerical execution or global state is involved.
 * solve_started means at least one iteration of that coarse level was entered;
 * charged includes an entered failing iteration. started_cap_sum is the sum
 * of those levels' caps, not a shared/global iteration limit. Other levels can
 * retain their configured cap while contributing zero. Existing bootstrap
 * summary fields retain their original first-coarse-level meaning. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_get_bootstrap_trace_v1(
    const tpmshx_full3d_result_v1*,size_t,tpmshx_full3d_bootstrap_trace_v1*);
/* Read-only actual model-enthalpy CC state, including budget-limited returns.
 * Invalid/null/released owners return 1 and leave output unchanged. Cancelled
 * and states without this ledger have available=0. No solver, EOS or allocation;
 * arrays borrow the owner until full_3d_release_v1. Nz=1 uses physical W. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_3d_get_model_enthalpy_evidence_v1(
    const tpmshx_full3d_result_v1*,tpmshx_model_enthalpy_evidence_v1*);
#ifdef __cplusplus
}
#endif
#endif
