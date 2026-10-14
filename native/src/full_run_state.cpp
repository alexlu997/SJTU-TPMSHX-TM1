#include "tpmshx/full_3d_state.hpp"
#include "tpmshx/full_2d_state.hpp"
#include "native_state_build.hpp"
#include <limits>
#include <map>
#include <stdexcept>
#include <type_traits>

namespace tpmshx {
namespace {
#define FIELD(name) archive(#name,value.name);
template<class Archive,class Value> void walk(Archive& archive,Value& value,FluidProperties*) {
    FIELD(rho) FIELD(mu) FIELD(k) FIELD(cp) FIELD(pr)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,GridView*) {
    FIELD(nx) FIELD(ny) FIELD(nz) FIELD(dx) FIELD(dy)
    FIELD(dz)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DGeometry*) {
    FIELD(grid) FIELD(epsilon) FIELD(epsilon_a) FIELD(epsilon_b) FIELD(permeability)
    FIELD(forchheimer) FIELD(solid_conductivity) FIELD(cell_length) FIELD(area_density) FIELD(hydraulic_diameter)
    FIELD(reference_cell_length) FIELD(reference_hydraulic_diameter) FIELD(spatial) FIELD(asymmetric)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DSide*) {
    FIELD(fluid) FIELD(direction) FIELD(solver_axes) FIELD(inlet_temperature) FIELD(inlet_pressure)
    FIELD(inlet_velocity) FIELD(inlet_rectangle) FIELD(outlet_rectangle) FIELD(inlet_opening) FIELD(outlet_opening)
    FIELD(permeability_scale) FIELD(forchheimer_scale) FIELD(dispersion) FIELD(sco2_nusselt_multiplier) FIELD(heat_transfer_geometry)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DInput*) {
    FIELD(geometry) FIELD(topology) FIELD(a) FIELD(b) FIELD(solve_b)
    FIELD(sources)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,SimpleF2Control*) {
    FIELD(momentum_tolerance) FIELD(local_mass_tolerance) FIELD(global_mass_tolerance) FIELD(backflow_maximum) FIELD(velocity_check_tolerance)
    FIELD(stall_ratio) FIELD(confirmations) FIELD(momentum_interval) FIELD(stall_window)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Simple3DControl*) {
    FIELD(max_iterations) FIELD(inner_sweeps) FIELD(pressure_rebuild_every) FIELD(alpha_velocity) FIELD(alpha_pressure)
    FIELD(alpha_density) FIELD(pressure_reference_absolute) FIELD(gas_constant) FIELD(pressure_diagonal_drift) FIELD(ideal_gas)
    FIELD(massflux_inlet) FIELD(second_order_upwind) FIELD(adaptive_pressure_tolerance) FIELD(track_momentum) FIELD(ordering)
    FIELD(convergence)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,EnthalpyControl*) {
    FIELD(max_iterations) FIELD(sweeps) FIELD(omega) FIELD(update_tolerance) FIELD(coupled_energy_tolerance)
    FIELD(equation_energy_tolerance) FIELD(algorithm) FIELD(temperature_update_tolerance) FIELD(require_enthalpy_update_on_temperature)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHIterationOverrides*) {
    FIELD(max_iterations) FIELD(temperature_tolerance) FIELD(q_relative_tolerance)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHIterationSettings*) {
    FIELD(max_iterations) FIELD(chunk_iterations) FIELD(temperature_tolerance) FIELD(q_relative_tolerance) FIELD(total_iteration_budget)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DControl*) {
    FIELD(max_outer) FIELD(initial_simple_iterations) FIELD(warm_simple_iterations) FIELD(thermal_iterations) FIELD(outer_temperature_tolerance)
    FIELD(thermal_relaxation) FIELD(pressure_shooting) FIELD(variable_rho_cp) FIELD(conservative) FIELD(strict_mass_balance)
    FIELD(force_cell_centered) FIELD(refined_port_energy) FIELD(red_black_energy) FIELD(sco2_local_pressure_a) FIELD(coarse_bootstrap)
    FIELD(outer_anderson) FIELD(coarse_iterations) FIELD(anderson_history) FIELD(anderson_patience) FIELD(anderson_trust)
    FIELD(roughness_mode) FIELD(roughness_height) FIELD(envelope_mode) FIELD(simple) FIELD(enthalpy)
    FIELD(initial_solid_temperature) FIELD(model_h_iterations)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,PropertySample*) {
    FIELD(side) FIELD(stage) FIELD(quantity) FIELD(provider) FIELD(temperature)
    FIELD(pressure) FIELD(operation) FIELD(outer_index)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,PressureSystem*) {
    FIELD(row_offsets) FIELD(columns) FIELD(values) FIELD(rhs) FIELD(pin_mask)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,PressureState*) {
    FIELD(construction) FIELD(rebuild_count)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,PressureResult*) {
    FIELD(success) FIELD(method) FIELD(exit) FIELD(amg_exit) FIELD(rebuild_reason)
    FIELD(detail) FIELD(x) FIELD(iterations) FIELD(rebuild_count) FIELD(hierarchy_bytes)
    FIELD(superlu_info) FIELD(rhs_scale) FIELD(relative_residual) FIELD(absolute_residual) FIELD(iterative_relative_residual)
    FIELD(pin_max_abs) FIELD(diagonal_drift) FIELD(build_seconds) FIELD(solve_seconds)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,SimpleMomentumResidual*) {
    FIELD(numerator) FIELD(denominator) FIELD(component) FIELD(maximum)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,SimpleMomentumRecord*) {
    FIELD(iteration) FIELD(residual)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,SimpleHistory*) {
    FIELD(legacy) FIELD(local_mass) FIELD(global_mass) FIELD(momentum)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,SimpleMassAudit*) {
    FIELD(local_residual) FIELD(mass_in) FIELD(mass_out) FIELD(global_residual) FIELD(backflow_fraction)
    FIELD(counted_cells)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Simple3DResult*) {
    FIELD(stop) FIELD(converged) FIELD(post_closure_measured) FIELD(post_closure_certified) FIELD(iterations)
    FIELD(pressure_clip_hits) FIELD(post_closure_rejections) FIELD(legacy_residual) FIELD(legacy_reference) FIELD(momentum)
    FIELD(mass) FIELD(linear)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Simple3DOwnerState*) {
    FIELD(widths) FIELD(outlet) FIELD(pressure) FIELD(history) FIELD(massflux_target)
    FIELD(pressure_clip_hits) FIELD(charged_iterations)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,AndersonState*) {
    FIELD(history_limit) FIELD(condition_limit) FIELD(x) FIELD(r)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,OuterAndersonStats*) {
    FIELD(applied) FIELD(rejected) FIELD(resets) FIELD(residuals)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,OuterAndersonState*) {
    FIELD(accelerator) FIELD(trust) FIELD(residual_min) FIELD(patience) FIELD(stale)
    FIELD(initialized) FIELD(sizes) FIELD(scales) FIELD(statistics)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,PressureIteration*) {
    FIELD(stage) FIELD(anchor_Pa) FIELD(estimate_Pa2) FIELD(relative_error) FIELD(target_Pa2)
    FIELD(step_fraction) FIELD(method)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,PressurePortState*) {
    FIELD(specified_Pa) FIELD(realized_Pa) FIELD(outlet_Pa) FIELD(outlet_gauge_Pa) FIELD(minimum_Pa)
    FIELD(relative_error) FIELD(relative_tolerance) FIELD(passed) FIELD(definition)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DFlowState::Bootstrap*) {
    FIELD(applied) FIELD(converged) FIELD(iterations) FIELD(residual) FIELD(shape)
    FIELD(reason)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DFlowState::BootstrapLevel*) {
    FIELD(depth) FIELD(iteration_cap) FIELD(charged_iterations) FIELD(fine_shape) FIELD(coarse_shape)
    FIELD(solve_started) FIELD(applied) FIELD(converged) FIELD(child_selected) FIELD(stop)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DFlowState::BootstrapTrace*) {
    FIELD(available) FIELD(selected) FIELD(fine_shape) FIELD(coarse_iteration_cap) FIELD(policy)
    FIELD(decision) FIELD(levels)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DFlowState*) {
    FIELD(widths) FIELD(epsilon) FIELD(permeability) FIELD(forchheimer) FIELD(temperature)
    FIELD(viscosity) FIELD(effective_viscosity) FIELD(density) FIELD(u) FIELD(v)
    FIELD(w) FIELD(pressure) FIELD(pressure_correction) FIELD(d_u) FIELD(d_v)
    FIELD(d_w) FIELD(inlet_velocity) FIELD(inlet_opening) FIELD(outlet_opening) FIELD(outlet_u_fraction)
    FIELD(outlet_w_fraction) FIELD(fixed_inlet_massflux) FIELD(pressure_reference) FIELD(last) FIELD(history)
    FIELD(pressure_iterations) FIELD(inlet_pressure) FIELD(bootstrap) FIELD(bootstrap_trace) FIELD(pressure_real)
    FIELD(density_real) FIELD(speed_real) FIELD(velocity_real) FIELD(face_velocity_real) FIELD(property_sampling)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHBoundaryAudit3D*) {
    FIELD(mass_out) FIELD(enthalpy_out) FIELD(unknown_mass_in) FIELD(inlet_reverse_mass_out) FIELD(unknown_inflow_count)
    FIELD(enthalpy_faces)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHSideAudit3D*) {
    FIELD(boundaries) FIELD(cp_coefficients) FIELD(temperature_min) FIELD(temperature_max) FIELD(mass_net)
    FIELD(advective_in) FIELD(diffusion_in) FIELD(numerical_external_in) FIELD(exchange) FIELD(source)
    FIELD(residual_sum) FIELD(residual_max) FIELD(normalization) FIELD(global_ratio) FIELD(cell_ratio)
    FIELD(boundary_complete) FIELD(residual) FIELD(inlet_diffusion)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHAudit3D*) {
    FIELD(sides) FIELD(solid_residual) FIELD(volume) FIELD(numerical_external_in) FIELD(explicit_source)
    FIELD(solid_sum) FIELD(solid_max) FIELD(full_residual_sum) FIELD(telescoping_error) FIELD(ltne_source_ratio)
    FIELD(boundary_complete) FIELD(gates) FIELD(passed)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHFinishingCheck3D*) {
    FIELD(iterations) FIELD(gates) FIELD(physical_passed) FIELD(energy_error_ratio)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHResult3D*) {
    FIELD(stop) FIELD(iterations) FIELD(residual) FIELD(q_b) FIELD(audit_available)
    FIELD(has_sources) FIELD(audit) FIELD(finishing_checks) FIELD(physical_audit_available) FIELD(energy_error_ratio)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ClipCounts*) {
    FIELD(a) FIELD(b)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,EnergyAudit*) {
    FIELD(q_a) FIELD(q_b) FIELD(net) FIELD(solid_abs_sum) FIELD(denominator)
    FIELD(coupled_ratio) FIELD(fluid_abs_sum) FIELD(fluid_cell_max) FIELD(equation_ratio) FIELD(fluid_equations_computed)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,EnthalpyResult*) {
    FIELD(stop) FIELD(iterations) FIELD(residual) FIELD(q_a) FIELD(q_b)
    FIELD(energy_imbalance) FIELD(inlet_enthalpy) FIELD(last_clips) FIELD(total_clips) FIELD(final_audit)
    FIELD(used_bicubic) FIELD(heos_polish) FIELD(algorithm) FIELD(temperature_update) FIELD(picard_relaxation)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,TemperatureResult*) {
    FIELD(stop) FIELD(iterations) FIELD(residual) FIELD(q_b)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,MacProjectionInfo*) {
    FIELD(skipped) FIELD(used_bordered_lu) FIELD(cg_iterations) FIELD(rhs_mean) FIELD(residual_relative)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,StaggeredFluidResidual*) {
    FIELD(available) FIELD(cells) FIELD(sum) FIELD(maximum) FIELD(exchange)
    FIELD(global_ratio) FIELD(cell_ratio)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,StaggeredTemperatureResult*) {
    FIELD(iteration) FIELD(projection) FIELD(residual)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,PhysicalHeatLedger*) {
    FIELD(advective_out) FIELD(diffusive_out) FIELD(residual) FIELD(source_integral) FIELD(solved)
    FIELD(prescribed_b_power) FIELD(boundary_complete)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DThermalEvidence*) {
    FIELD(property_sampling) FIELD(mode) FIELD(outer_index) FIELD(temperature) FIELD(pressure)
    FIELD(hv) FIELD(rho_cp) FIELD(conductivity) FIELD(mass) FIELD(face_velocity)
    FIELD(inlet_capacity) FIELD(enthalpy) FIELD(actual_conductivity) FIELD(enthalpy_boundary_power) FIELD(model_h)
    FIELD(true_h) FIELD(staggered) FIELD(temperature_cp_coefficients) FIELD(temperature_algorithm) FIELD(physical_audit)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DOuterRecord*) {
    FIELD(outer_index) FIELD(thermal_iterations) FIELD(thermal_residual) FIELD(temperature_change) FIELD(inlet_pressure)
    FIELD(pressure_reference) FIELD(pressure_range) FIELD(thermal_converged) FIELD(coupling_converged) FIELD(rejected_startup_iterations)
    FIELD(rejected_startup_reasons) FIELD(startup_total_iterations) FIELD(model_h) FIELD(true_h) FIELD(model_h_iterations)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,NuObservation*) {
    FIELD(available) FIELD(cells) FIELD(floor_cells) FIELD(raw_min) FIELD(raw_max)
    FIELD(re_min) FIELD(re_max) FIELD(pr_min) FIELD(pr_max) FIELD(temperature_min)
    FIELD(temperature_max) FIELD(pressure)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,RangeSample*) {
    FIELD(have_finite) FIELD(minimum) FIELD(maximum) FIELD(minimum_index) FIELD(maximum_index)
    FIELD(low) FIELD(high) FIELD(size) FIELD(nonfinite)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,RangeObservation*) {
    FIELD(view) FIELD(model) FIELD(topology) FIELD(stage) FIELD(layout)
    FIELD(side) FIELD(shape) FIELD(bounds) FIELD(have_finite) FIELD(minimum)
    FIELD(maximum) FIELD(minimum_index) FIELD(maximum_index) FIELD(low) FIELD(high)
    FIELD(size) FIELD(nonfinite) FIELD(last)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DResult*) {
    FIELD(stop) FIELD(converged) FIELD(simple_ok) FIELD(thermal_ok) FIELD(outer_ok)
    FIELD(finite_fields) FIELD(envelope_ok) FIELD(post_after_last_thermal) FIELD(flow) FIELD(thermal)
    FIELD(outer) FIELD(simple_failures) FIELD(warnings) FIELD(envelope_reasons) FIELD(final_conductivity)
    FIELD(final_rho_cp) FIELD(property_sampling) FIELD(inlet_cp) FIELD(nu_observations) FIELD(range_observations)
    FIELD(pressure_drop) FIELD(outlet_temperature) FIELD(inlet_mass) FIELD(duty) FIELD(maximum_mach)
    FIELD(minimum_pressure) FIELD(solid_exchange) FIELD(interior_exchange) FIELD(physical_mass_in) FIELD(physical_mass_out)
    FIELD(mass_imbalance) FIELD(energy_imbalance) FIELD(interior_duty) FIELD(interior_imbalance) FIELD(enthalpy_imbalance)
    FIELD(anderson)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DRunState*) {
    FIELD(phase) FIELD(result) FIELD(inlet) FIELD(drag_k) FIELD(drag_cf)
    FIELD(mass_flux) FIELD(dispersion) FIELD(hv_ratio) FIELD(conductivity) FIELD(rho_cp)
    FIELD(hv) FIELD(temperature) FIELD(previous) FIELD(simple) FIELD(anderson)
    FIELD(flow_convergence) FIELD(flow_iteration) FIELD(thermal)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,SimpleF2State*) {
    FIELD(minimum_iterations) FIELD(streak) FIELD(window_start_iteration) FIELD(momentum_at_window_start) FIELD(previous)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHChunkState*) {
    FIELD(count) FIELD(completed) FIELD(acceleration)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHIterationState*) {
    FIELD(temperature) FIELD(previous) FIELD(previous_q) FIELD(have_q) FIELD(chunk)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHRunState2D*) {
    FIELD(iteration) FIELD(result)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHRunState3D*) {
    FIELD(iteration) FIELD(result) FIELD(carry)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,TemperatureRunState*) {
    FIELD(temperature) FIELD(result)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,StaggeredTemperatureRunState*) {
    FIELD(iteration) FIELD(velocity) FIELD(projection)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,EnthalpySideState*) {
    FIELD(lower) FIELD(upper) FIELD(transport) FIELD(table_lower) FIELD(table_upper)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,EnthalpyRunState*) {
    FIELD(fields) FIELD(sides) FIELD(result) FIELD(acceleration) FIELD(next_temperatures)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full3DThermalRunState*) {
    FIELD(evidence) FIELD(record) FIELD(initial) FIELD(budget) FIELD(remaining)
    FIELD(model_h_2d) FIELD(model_h_3d) FIELD(staggered) FIELD(legacy) FIELD(enthalpy)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DSide*) {
    FIELD(fluid) FIELD(direction) FIELD(inlet_temperature) FIELD(inlet_pressure) FIELD(inlet_velocity)
    FIELD(initial_viscosity) FIELD(seed_permeability) FIELD(seed_forchheimer) FIELD(row_permeability) FIELD(row_forchheimer)
    FIELD(permeability) FIELD(forchheimer) FIELD(inlet_geometry) FIELD(outlet_geometry) FIELD(inlet_profile)
    FIELD(outlet_profile) FIELD(outlet_u_fraction) FIELD(inlet_lo) FIELD(inlet_hi) FIELD(outlet_lo)
    FIELD(outlet_hi) FIELD(uniform_inlet) FIELD(side_area_density) FIELD(side_hydraulic_diameter) FIELD(reference_area_density)
    FIELD(reference_hydraulic_diameter)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DProblem*) {
    FIELD(grid) FIELD(sides) FIELD(topology) FIELD(thermal_mode) FIELD(fluid_conductivity)
    FIELD(solid_conductivity) FIELD(total_porosity) FIELD(area_density) FIELD(hydraulic_diameter) FIELD(cell_length)
    FIELD(nu_geometry_ratio) FIELD(reference_cell_length) FIELD(reference_porosity) FIELD(split_a) FIELD(sco2_nu_multiplier)
    FIELD(asymmetric) FIELD(initial_solid_temperature) FIELD(spatial_geometry)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Simple2DControl*) {
    FIELD(max_iterations) FIELD(inner_sweeps) FIELD(alpha_velocity) FIELD(alpha_pressure) FIELD(alpha_density)
    FIELD(pressure_reference_absolute) FIELD(gas_constant) FIELD(cf_anisotropy) FIELD(ideal_gas) FIELD(massflux_inlet)
    FIELD(close_outlet_on_exit) FIELD(convergence)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DControl*) {
    FIELD(flow) FIELD(outer_iterations) FIELD(thermal_iterations) FIELD(thermal_chunk) FIELD(outer_temperature_tolerance)
    FIELD(outer_density_tolerance) FIELD(outer_relaxation) FIELD(thermal_q_tolerance) FIELD(pressure_shooting) FIELD(thermal_red_black)
    FIELD(envelope_mode) FIELD(enthalpy) FIELD(model_h_iterations)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Simple2DResult*) {
    FIELD(stop) FIELD(converged) FIELD(post_closure_measured) FIELD(post_closure_certified) FIELD(iterations)
    FIELD(pressure_clip_hits) FIELD(legacy_residual) FIELD(momentum) FIELD(mass) FIELD(linear)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DFlow*) {
    FIELD(dx) FIELD(dy) FIELD(u) FIELD(v) FIELD(pressure)
    FIELD(pressure_correction) FIELD(d_u) FIELD(d_v) FIELD(density) FIELD(inlet_velocity)
    FIELD(viscosity) FIELD(effective_viscosity) FIELD(temperature) FIELD(epsilon) FIELD(reference_pressure)
    FIELD(taper_flux_scale) FIELD(massflux_target) FIELD(result) FIELD(history) FIELD(pressure_state)
    FIELD(pressure_iterations) FIELD(uc) FIELD(vc) FIELD(absolute_pressure) FIELD(mass_x)
    FIELD(mass_y) FIELD(property_sampling)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHSideAudit2D*) {
    FIELD(q_advective) FIELD(inlet_conduction) FIELD(exchange) FIELD(residual_sum) FIELD(residual_max)
    FIELD(linearized_sum) FIELD(linearized_max) FIELD(defect_sum) FIELD(defect_max) FIELD(mass_net)
    FIELD(mass_local_max) FIELD(mass_in) FIELD(mass_out) FIELD(normalization) FIELD(cell_ratio)
    FIELD(unknown_inflow_faces) FIELD(boundary_mass_out) FIELD(boundary_h_out) FIELD(h_faces) FIELD(inlet_conduction_faces)
    FIELD(residual) FIELD(linearization_defect) FIELD(cp_coefficients)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHAudit2D*) {
    FIELD(sides) FIELD(solid_residual) FIELD(solid_sum) FIELD(solid_max) FIELD(solid_cell_ratio)
    FIELD(residual_sum) FIELD(telescoping_error) FIELD(net_boundary_in) FIELD(denominator) FIELD(energy_imbalance)
    FIELD(solid_imbalance) FIELD(boundary_complete) FIELD(finite) FIELD(energy_ok) FIELD(solid_ok)
    FIELD(equations_ok) FIELD(passed)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHFinishingCheck2D*) {
    FIELD(iterations) FIELD(passed) FIELD(equations_ok) FIELD(energy_error_ratio)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,ModelHResult2D*) {
    FIELD(stop) FIELD(iterations) FIELD(residual) FIELD(q_b) FIELD(audit_available)
    FIELD(audit) FIELD(finishing_checks) FIELD(last_a) FIELD(last_b) FIELD(physical_audit_available)
    FIELD(energy_error_ratio)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DThermalState*) {
    FIELD(model_h_iterations) FIELD(property_sampling) FIELD(temperature) FIELD(hv) FIELD(conductivity)
    FIELD(pressure) FIELD(rho_cp) FIELD(mass_x) FIELD(mass_y) FIELD(inlet_capacity)
    FIELD(solid_conductivity) FIELD(h_a) FIELD(h_b) FIELD(actual_conductivity) FIELD(enthalpy_boundary_power)
    FIELD(result) FIELD(temperature_cp_coefficients) FIELD(temperature_algorithm) FIELD(physical_audit)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DOuterRecord*) {
    FIELD(model_h_iterations) FIELD(iteration) FIELD(thermal_iterations) FIELD(thermal_converged) FIELD(outer_converged)
    FIELD(relative_density_change) FIELD(temperature_change) FIELD(enthalpy_algorithm) FIELD(thermal_temperature_update) FIELD(thermal_picard_relaxation)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DRefinedState*) {
    FIELD(dx) FIELD(dy) FIELD(epsilon) FIELD(uc) FIELD(vc)
    FIELD(inlet_profile) FIELD(outlet_profile) FIELD(thermal) FIELD(accepted) FIELD(extrapolated)
    FIELD(warning) FIELD(duty) FIELD(extrapolated_duty)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,EnvelopeAssessment*) {
    FIELD(valid) FIELD(reasons)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DResult*) {
    FIELD(cancelled) FIELD(outer_converged) FIELD(post_after_last_thermal) FIELD(iterations) FIELD(flow)
    FIELD(thermal) FIELD(outer_history) FIELD(envelope) FIELD(density) FIELD(viscosity)
    FIELD(rho_cp) FIELD(refined) FIELD(property_sampling) FIELD(converged) FIELD(simple_ok)
    FIELD(thermal_ok) FIELD(envelope_ok) FIELD(pair_balance_ok) FIELD(model_balance_ok) FIELD(pressure_drop)
    FIELD(outlet_temperature) FIELD(inlet_mass) FIELD(duty) FIELD(q_total) FIELD(q_solid)
    FIELD(energy_imbalance) FIELD(nu_observations) FIELD(range_observations)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DRunState*) {
    FIELD(phase) FIELD(result) FIELD(inlet) FIELD(previous) FIELD(flow) FIELD(thermal)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Simple2DOwnerState*) {
    FIELD(widths) FIELD(depth) FIELD(outlet) FIELD(pressure) FIELD(history) FIELD(massflux_target) FIELD(pressure_clip_hits)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Simple2DRunState*) {
    FIELD(owner) FIELD(fields) FIELD(convergence) FIELD(result)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DFlowRunState*) {
    FIELD(flow) FIELD(iteration)
}
template<class Archive,class Value> void walk(Archive& archive,Value& value,Full2DThermalRunState*) {
    FIELD(model_h) FIELD(enthalpy)
}
#undef FIELD

template<class T> constexpr bool numeric=std::is_arithmetic_v<T>||std::is_enum_v<T>;
template<class T> using Stored=std::conditional_t<std::is_floating_point_v<T>,double,
    std::conditional_t<std::is_same_v<T,bool>||std::is_same_v<T,unsigned char>,unsigned char,
    std::conditional_t<std::is_unsigned_v<T>,std::uint64_t,std::int64_t>>>;

struct Writer {
    RunStateRecord& fields;
    std::string path;
    template<class T> void operator()(const std::string& name,const T& value) {
        Writer child{fields,path.empty()?name:path+"."+name};child.put(value);
    }
    template<class T> void numbers(const T* data,std::size_t count) {
        std::vector<Stored<T>> values;values.reserve(count);
        for(std::size_t i=0;i<count;++i)values.push_back(static_cast<Stored<T>>(data[i]));
        fields.push_back({path,std::move(values)});
    }
    template<class T> void put(const T& value) {
        if constexpr(numeric<T>)numbers(&value,1);
        else walk(*this,value,static_cast<T*>(nullptr));
    }
    void put(const std::string& value) {fields.push_back({path,value});}
    template<class... T> void put(const std::variant<T...>& value) {
        (*this)("index",value.index());
        std::visit([&](const auto& item){(*this)("value",item);},value);
    }
    template<class T> void put(const std::optional<T>& value) {
        (*this)("present",value.has_value());if(value)(*this)("value",*value);
    }
    template<class T> void put(const std::vector<T>& value) {
        if constexpr(numeric<T>)numbers(value.data(),value.size());
        else {(*this)("size",value.size());for(std::size_t i=0;i<value.size();++i)(*this)(std::to_string(i),value[i]);}
    }
    template<class T,std::size_t N> void put(const std::array<T,N>& value) {
        if constexpr(numeric<T>)numbers(value.data(),N);
        else for(std::size_t i=0;i<N;++i)(*this)(std::to_string(i),value[i]);
    }
    template<class T,std::size_t N> void put(const T (&value)[N]) {numbers(value,N);}
    template<class T> void put(ArrayView<const T> value) {numbers(value.data,value.size);}
};

int enum_max(Full2DPhase) {return static_cast<int>(Full2DPhase::refinement_boundary);}
int enum_max(Full3DPhase) {return static_cast<int>(Full3DPhase::post_flow_b);}
int enum_max(Full3DStop) {return static_cast<int>(Full3DStop::cancelled);}
int enum_max(Full3DThermalMode) {return static_cast<int>(Full3DThermalMode::true_h);}
int enum_max(SimpleStop) {return static_cast<int>(SimpleStop::post_closure);}
int enum_max(TemperatureStop) {return static_cast<int>(TemperatureStop::cancelled);}
int enum_max(EnthalpyStop) {return static_cast<int>(EnthalpyStop::cancelled);}
int enum_max(EnthalpyAlgorithm) {return static_cast<int>(EnthalpyAlgorithm::temperature_sou);}

template<class T> T checked_number(Stored<T> value) {
    bool valid=true;
    if constexpr(std::is_enum_v<T>)valid=value>=0 && value<=enum_max(T{});
    else if constexpr(std::is_same_v<T,bool>)valid=value<=1;
    else if constexpr(std::is_integral_v<T>)
        valid=value>=static_cast<Stored<T>>(std::numeric_limits<T>::lowest()) && value<=static_cast<Stored<T>>(std::numeric_limits<T>::max());
    if(!valid)throw std::invalid_argument("native state integer is outside its field range");
    return static_cast<T>(value);
}

using Entries=std::map<std::string,const RunStateValue*>;
struct Reader {
    Entries& remaining;
    std::string path;
    const RunStateValue& take() {
        const auto it=remaining.find(path);
        if(it==remaining.end())throw std::invalid_argument("native state field is missing: "+path);
        const auto& value=*it->second;remaining.erase(it);return value;
    }
    template<class T> const T& typed() {
        const auto* value=std::get_if<T>(&take());
        if(!value)throw std::invalid_argument("native state field type differs: "+path);
        return *value;
    }
    template<class T> void operator()(const std::string& name,T& value) {
        Reader child{remaining,path.empty()?name:path+"."+name};child.get(value);
    }
    template<class T> void numbers(T* data,std::size_t count) {
        const auto& values=typed<std::vector<Stored<T>>>();
        if(values.size()!=count)throw std::invalid_argument("native state field size differs: "+path);
        for(std::size_t i=0;i<count;++i)data[i]=checked_number<T>(values[i]);
    }
    template<class T> void get(T& value) {
        if constexpr(numeric<T>)numbers(&value,1);
        else walk(*this,value,static_cast<T*>(nullptr));
    }
    void get(std::string& value) {value=typed<std::string>();}
    template<std::size_t I=0,class... T> void alternative(std::variant<T...>& value,std::size_t index) {
        if constexpr(I<sizeof...(T)) {
            if(index==I) {value.template emplace<I>();(*this)("value",std::get<I>(value));}
            else alternative<I+1>(value,index);
        } else throw std::invalid_argument("native state variant index is invalid: "+path);
    }
    template<class... T> void get(std::variant<T...>& value) {
        std::size_t index=0;(*this)("index",index);alternative(value,index);
    }
    template<class T> void get(std::optional<T>& value) {
        bool present=false;(*this)("present",present);
        if(present) {value.emplace();(*this)("value",*value);} else value.reset();
    }
    template<class T> void get(std::vector<T>& value) {
        if constexpr(numeric<T>) {
            const auto& values=typed<std::vector<Stored<T>>>();value.resize(values.size());
            for(std::size_t i=0;i<values.size();++i)value[i]=checked_number<T>(values[i]);
        } else {
            std::size_t size=0;(*this)("size",size);
            if(size>remaining.size())throw std::invalid_argument("native state record count exceeds its fields");
            value.resize(size);for(std::size_t i=0;i<size;++i)(*this)(std::to_string(i),value[i]);
        }
    }
    template<class T,std::size_t N> void get(std::array<T,N>& value) {
        if constexpr(numeric<T>)numbers(value.data(),N);
        else for(std::size_t i=0;i<N;++i)(*this)(std::to_string(i),value[i]);
    }
    template<class T,std::size_t N> void get(T (&value)[N]) {numbers(value,N);}
};

template<class Input,class Control> RunStateRecord identity(const Input& input,const Control& control) {
    RunStateRecord fields;Writer writer{fields,""};
    writer("format",std::uint64_t{2});writer("build",std::string(TPMSHX_STATE_BUILD_ID));
    writer("platform",std::string(TPMSHX_STATE_PLATFORM));writer("input",input);writer("control",control);
    return fields;
}
} // namespace

RunStateRecord export_full_3d_state(const Full3DInput& input,const Full3DControl& control,const Full3DRunState& state) {
    auto fields=identity(input,control);Writer{fields,""}("state",state);return fields;
}
namespace {
template<class State,class Input,class Control>
State import_state(const Input& input,const Control& control,const RunStateRecord& fields) {
    Entries remaining;
    for(const auto& field:fields)
        if(field.name.empty() || !remaining.emplace(field.name,&field.value).second)
            throw std::invalid_argument("native state has an empty or duplicate field name");
    for(const auto& expected:identity(input,control)) {
        Reader reader{remaining,expected.name};
        if(reader.take()!=expected.value)throw std::invalid_argument("native state identity differs: "+expected.name);
    }
    State state;Reader{remaining,""}("state",state);
    if(!remaining.empty())throw std::invalid_argument("native state contains unknown fields");
    return state;
}
} // namespace

Full3DRunState import_full_3d_state(const Full3DInput& input,const Full3DControl& control,const RunStateRecord& fields) {
    return import_state<Full3DRunState>(input,control,fields);
}
RunStateRecord export_full_2d_state(const Full2DProblem& input,const Full2DControl& control,const Full2DRunState& state) {
    auto fields=identity(input,control);Writer{fields,""}("state",state);return fields;
}
Full2DRunState import_full_2d_state(const Full2DProblem& input,const Full2DControl& control,const RunStateRecord& fields) {
    return import_state<Full2DRunState>(input,control,fields);
}

} // namespace tpmshx
