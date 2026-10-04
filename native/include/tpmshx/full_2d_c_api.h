#ifndef TPMSHX_FULL_2D_C_API_H
#define TPMSHX_FULL_2D_C_API_H
#include "tpmshx/simple_2d_c_api.h"
#include "tpmshx/model_h_c_api.h"
#include "tpmshx/enthalpy_driver_c_api.h"
#include "tpmshx/closure_evidence_c_api.h"

#ifdef __cplusplus
extern "C" {
#endif
#define TPMSHX_FULL_2D_ABI_VERSION 2u

typedef struct {
    uint32_t fluid,direction,uniform_inlet;
    double inlet_temperature,inlet_pressure,inlet_velocity,initial_viscosity;
    double seed_permeability,seed_forchheimer,inlet_lo,inlet_hi,outlet_lo,outlet_hi;
    double side_area_density,side_hydraulic_diameter,reference_area_density,reference_hydraulic_diameter;
} tpmshx_full_2d_side_v2;
typedef struct {
    uint32_t topology,thermal_mode,asymmetric,have_solid_seed,pressure_shooting,red_black,spatial_geometry;
    tpmshx_full_2d_side_v2 sides[2];
    double reference_cell_length,reference_porosity,split_a,sco2_nu_multiplier,solid_seed;
    size_t simple_iterations,simple_sweeps,outer_iterations,thermal_iterations,thermal_chunk;
    double alpha_velocity,alpha_pressure,alpha_density,gas_constant,cf_anisotropy;
    uint32_t massflux_inlet,close_outlet_on_exit;
    tpmshx_simple_f2_v1 f2;
    double outer_temperature_tolerance,outer_density_tolerance,outer_relaxation;
    double thermal_q_tolerance,enthalpy_update_tolerance;
    const char* envelope_mode;
    const char* table_directory;
} tpmshx_full_2d_config_v2;
typedef struct {
    int (TPMSHX_THERMAL_CALL *cancel)(void*);
    void (TPMSHX_THERMAL_CALL *progress)(void*,size_t,size_t);
    void (TPMSHX_THERMAL_CALL *residual)(void*,size_t,size_t,double);
    void* context;
} tpmshx_full_2d_callbacks_v2;

typedef struct {
    uint32_t available,passed;
    double specified_Pa,realized_Pa,outlet_Pa,outlet_gauge_Pa,minimum_Pa;
    double relative_error,relative_tolerance;
    const char* definition;
} tpmshx_full_2d_pressure_v2;
typedef struct {
    const char* stage;
    double anchor_Pa;
    uint32_t have_estimate,have_relative_error,have_target,have_step;
    double estimate_Pa2,relative_error,target_Pa2,step_fraction;
    const char* method;
} tpmshx_full_2d_pressure_iteration_v2;
typedef struct {
    tpmshx_model_h_array_v1 dx,dy,u,v,pressure,pressure_correction,d_u,d_v,density,inlet_velocity;
    tpmshx_model_h_array_v1 viscosity,effective_viscosity,temperature,epsilon,uc,vc,absolute_pressure,mass_x,mass_y;
    double reference_pressure,taper_flux_scale;
    tpmshx_simple_2d_result_v1 result;
    /* Histories: legacy, local mass, global mass, momentum (rows of 8 doubles
       iteration,max,num_u,num_v,den_u,den_v,res_u,res_v). */
    tpmshx_model_h_array_v1 history[4];
    tpmshx_full_2d_pressure_v2 inlet_pressure;
    const tpmshx_full_2d_pressure_iteration_v2* pressure_iterations;
    size_t pressure_iteration_count;
    uint32_t envelope_valid;
    const char* const* envelope_reasons;
    size_t envelope_reason_count;
} tpmshx_full_2d_flow_v2;
typedef struct {
    size_t nx,ny;
    uint32_t mode,stop;
    size_t iterations;
    double residual,q_b;
    tpmshx_model_h_array_v1 dx,dy,temperature[3],hv[2],conductivity[2],pressure[2],rho_cp[2];
    tpmshx_model_h_array_v1 mass_x[2],mass_y[2],inlet_capacity[2],solid_conductivity,enthalpy[2];
    tpmshx_model_h_array_v1 uc[2],vc[2],epsilon,inlet_profile[2],outlet_profile[2];
    /* Only the matching mode is meaningful. model_h views borrow the outer
       owner; its nested owner is NULL and must not be separately released. */
    tpmshx_model_h_result_v1 model_h;
    tpmshx_enthalpy_result_v1 true_h;
} tpmshx_full_2d_thermal_v2;
typedef struct {
    size_t iteration,thermal_iterations;
    uint32_t thermal_converged,outer_converged;
    double relative_density_change[2],temperature_change[3];
} tpmshx_full_2d_outer_v2;
typedef struct {
    uint32_t cancelled,converged,outer_converged,post_after_last_thermal;
    uint32_t simple_ok,thermal_ok,envelope_ok,pair_balance_ok,model_balance_ok;
    size_t iterations;
    tpmshx_full_2d_flow_v2 flow[2];
    tpmshx_full_2d_thermal_v2 main,fine;
    uint32_t have_fine,fine_accepted,fine_extrapolated,fine_warning;
    double fine_duty[2],extrapolated_duty[2];
    tpmshx_model_h_array_v1 density[2],viscosity[2],rho_cp[2];
    const tpmshx_full_2d_outer_v2* outer_history;
    size_t outer_history_count;
    double pressure_drop[2],outlet_temperature[2],inlet_mass[2],duty[2];
    double q_total,q_solid,energy_imbalance;
    tpmshx_nu_observation_v1 nu_observations[2];
    const tpmshx_range_observation_v1* range_observations;
    size_t range_observation_count;
    void* owner;
} tpmshx_full_2d_result_v2;

TPMSHX_THERMAL_API uint32_t TPMSHX_THERMAL_CALL tpmshx_full_2d_abi_version(void);
/* Complete prepared rectangular 2D numerical driver, including original
 * mandatory thermal Richardson and final gates (true-h bypasses Richardson).
 * SI; heat and face mass are W/m and kg/(s m). shape[2]=(nx,ny).
 * arrays[29]/sizes[29] are borrowed read-only C-order doubles:
 *   dx,dy,dz={1},KffA,KffB,Kss,total_epsilon,A0,Dh,cell_length,
 *   for each side A,B:
 *     row_K,row_cF,optional_full_K,optional_full_cF,inlet_geometry,
 *     outlet_geometry,inlet_profile,outlet_profile,outlet_u_fraction.
 *   followed by the per-cell dimensionless Nu geometry ratio, evaluated as
 *     (Dh_m * 1000) / original_cell_length_mm in the prepared case.
 * ABI 2 requires this original closure input: an SI length rounded during
 * preparation cannot recover the same ratio by converting back to mm.
 * Geometry/Kff inputs retain the already-prepared case's values. Full K/cF
 * use +y SIMPLE coordinates; thermal arrays use physical x/y. All required
 * buffers must have declared extents and outlive the synchronous call.
 * Fluid=air0/water1/CO2=2, topology=diamond0/gyroid1,
 * thermal_mode=temperature0/model_h1/true_h2. Booleans require 0/1.
 * spatial_geometry retains original scalar-versus-field provenance during
 * refinement; uniform Kff/Kss/epsilon buffers must be constant.
 * red_black is the original opt-in; main/fine independently apply cells>30000.
 * No geometry/D-F fitting, display smoothing or CaseData persistence occurs.
 *
 * Input/result/error/control storage must not overlap. No pointer can prove
 * allocation size. Callbacks must not throw or mutate inputs; SIMPLE sides
 * run concurrently so cancel/residual callbacks must be thread safe. The
 * other callbacks run on the caller thread. NULL callbacks are allowed.
 *
 * Status:0 returned,1 invalid argument,2 water state,3 arithmetic,4 envelope,
 * 5 other native exception. Error is required, bounded and NUL terminated.
 * Nonzero status leaves result untouched. Zero does not certify convergence:
 * inspect converged. Cancelled state has no accepted result and may be partial.
 * Every normal return owns all array/string views independently of inputs;
 * release it before reusing the struct. Do not copy handles or free views.
 * Release clears the struct and accepts NULL/already-cleared results.
 * No C++ exception crosses either entry point.
 */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_full_2d_v2(
    const size_t* shape,const double* const* arrays,const size_t* sizes,
    const tpmshx_full_2d_config_v2* config,const tpmshx_full_2d_callbacks_v2* callbacks,
    tpmshx_full_2d_result_v2* result,char* error,size_t error_capacity);
TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL tpmshx_full_2d_release_v2(tpmshx_full_2d_result_v2* result);
/* Explicit conservative energy selection with unchanged ABI 2 buffers and
 * result ownership. options is required; release with full_2d_release_v2. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_solve_full_2d_v3(
    const size_t*,const double* const*,const size_t*,const tpmshx_full_2d_config_v2*,
    const tpmshx_energy_options_v1*,const tpmshx_full_2d_callbacks_v2*,
    tpmshx_full_2d_result_v2*,char*,size_t);
typedef struct {
    uint32_t available;
    tpmshx_energy_result_v1 energy;
    tpmshx_model_h_array_v1 actual_conductivity[2];
    /* Outward signed W/m, x-,x+,y-,y+,z-,z+; singleton-z boundary planes. */
    tpmshx_model_h_array_v1 boundary_power[2][6];
} tpmshx_full_2d_energy_state_v1;
typedef struct {
    tpmshx_full_2d_energy_state_v1 main,fine;
    const tpmshx_energy_result_v1* outer;
    size_t outer_count;
} tpmshx_full_2d_energy_evidence_v1;
/* Read-only evidence from the same final thermal call. Arrays borrow the live
 * result owner; no solver/EOS execution. Missing/cancelled candidate states
 * have available=0. Status 1 leaves output unchanged. */
TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL tpmshx_full_2d_get_energy_evidence_v1(
    const tpmshx_full_2d_result_v2*,tpmshx_full_2d_energy_evidence_v1*);
#ifdef __cplusplus
}
#endif
#endif
