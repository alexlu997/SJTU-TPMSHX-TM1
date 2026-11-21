#include "execution_report.hpp"

namespace tpmshx::stages {
namespace {
using Object = Report::Object;
using List = Report::List;
constexpr const char* sides[]{"A", "B"};
Report text(const char* value) { return value ? Report(value) : Report(); }
Report samples(const tpmshx_property_sampling_v1& values) {
    List rows;
    for (size_t i = 0; i < values.count; ++i) {
        const auto& r = values.records[i];
        rows.emplace_back(Object{{"side", sides[r.side]}, {"outer_index", r.outer_index},
            {"stage", text(r.stage)}, {"quantity", text(r.quantity)}, {"provider", text(r.provider)},
            {"temperature", text(r.temperature)}, {"pressure", text(r.pressure)}, {"operation", text(r.operation)}});
    }
    return rows;
}
Report iterations(const tpmshx_stage_execution_v1& run) {
    List rows;
    for (size_t i = 0; i < run.model_h.count; ++i) {
        const auto& r = run.model_h.records[i];
        Object settings{{"max_iterations", r.max_iterations}, {"chunk_iterations", r.chunk_iterations},
            {"temperature_update_tolerance_K", r.temperature_tolerance}, {"q_relative_tolerance", r.q_relative_tolerance},
            {"total_iteration_budget", r.total_iteration_budget}};
        if (run.acceleration) {
            const auto& policy = run.acceleration[i];
            settings.emplace("acceleration", Object{{"enabled", bool(policy.enabled)},
                {"sweeps_per_block", policy.sweeps_per_block}, {"history_limit", policy.history_limit}});
        }
        rows.emplace_back(Object{{"outer_index", r.outer_index}, {"attempt", r.attempt},
            {"stage", r.refined ? "refined_thermal" : "outer_thermal"}, {"settings", std::move(settings)}});
    }
    return Object{{"version", "model_h_iterations_v1"}, {"records", std::move(rows)}};
}
Report normalization(const tpmshx_energy_update_scale_v1& value) {
    if (!value.available) return {};
    return Object{{"definition", value.reference_independent ? "inlet_cp_times_temperature_difference_v1" : "inlet_enthalpy_difference_v1"},
        {"unit", "J/kg"}, {"sides", Object{{"A", value.scale[0]}, {"B", value.scale[1]}}},
        {"source", "native_completed_thermal_call"}};
}
const char* field_state(const tpmshx_result_evidence_v1& evidence, const std::string& name) {
    for (size_t i = 0; i < evidence.field_metadata_count; ++i)
        if (name == evidence.field_metadata[i].name) return evidence.field_metadata[i].state;
    throw std::logic_error("completed result lacks a field declaration for " + name);
}
}
Report::Object execution_report(const tpmshx_stage_execution_v1& run, const tpmshx_result_evidence_v1& e) {
    Object fluids, directions, pressure, executed;
    List shape;
    for (int i = 0; i < e.dimension; ++i) shape.emplace_back(e.grid.widths[i]->shape[0]);
    for (size_t i = 0; i < 2; ++i) {
        const std::string side = sides[i];
        const auto& relation = run.records->energy[i];
        fluids.emplace(side, e.executed_sides[i].fluid);
        if (e.active_fluids[i])
            directions.emplace(side, *(e.dimension == 2 ? e.direction[i] : e.thermal.report_direction[i]));
        if (e.pressure[i]) pressure.emplace(side, field_state(e, "P_report_" + side));
        Object energy{{"relation", relation.relation}, {"property_provider", text(relation.provider)},
            {"temperature_field", i ? "Tb" : "Ta"}};
        Object evaluation{{"state_update", text(relation.state_update)}};
        if (relation.eos_fluid) {
            energy.emplace("fluid", relation.eos_fluid);
            energy.emplace("pressure_field", "P_thermal_" + side);
            energy.emplace("pressure_state", field_state(e, "P_thermal_" + side));
            evaluation.emplace("final_property_backend", "HEOS");
        }
        executed.emplace(side, Object{{"fluid", e.executed_sides[i].fluid}, {"solved", bool(relation.solved)},
            {"energy", std::move(energy)}, {"property_evaluation", std::move(evaluation)}});
    }
    return {{"property_sampling", samples(run.records->sampling)}, {"model_h_iterations", iterations(run)},
        {"enthalpy_update_normalization", normalization(run.update_scale)}, {"last_main_model_h", run.last_main_model_h},
        {"input", Object{{"shape", std::move(shape)}, {"fluids", std::move(fluids)}, {"directions", std::move(directions)}}},
        {"facts", Object{{"version", e.execution_version}, {"dimension", e.dimension}, {"sides", std::move(executed)},
            {"thermal", Object{{"thermal_mode", e.thermal_mode}, {"unknown", run.unknown}, {"temperature_transport", text(e.temperature_transport)}}},
            {"evidence", Object{{"thermal_state", field_state(e, "Ta")}, {"mass_state", e.thermal_state},
                {"pressure_report_states", std::move(pressure)}, {"outer_index", *e.outer_index}}}}}};
}

namespace {
Report coefficients(const double (&values)[5]) {
    return List(values, values + 5);
}
}
Report plane_balance(const tpmshx_model_h_result_v1& result, size_t cells, double area) {
    const auto& audit = result.plane;
    Object out{
            {"units", "W/m; kg/(s m)"},
            {"state", "raw final thermal return"},
            {"boundary_order", List{"-x", "+x", "-y", "+y"}},
            {"sou_A", true},
            {"sou_B", true},
            {"cell_count", cells},
            {"area_m2", area},
            {"solid_boundary_W_per_m", 0.0},
            {"solid_source_W_per_m", 0.0},
            {"solid_residual_sum_W_per_m", audit.solid_sum},
            {"solid_residual_max_abs_W_per_m", audit.solid_max},
            {"solid_residual_cellmax_rel", audit.solid_cell_ratio},
            {"equation_tolerance", 0.01},
            {"residual_sum_W_per_m", audit.residual_sum},
            {"telescoping_error_W_per_m", audit.telescoping_error},
            {"net_boundary_in_W_per_m", audit.net_boundary_in},
            {"D2_W_per_m", audit.denominator},
            {"energy_imbalance_rel", audit.energy_imbalance},
            {"solid_imbalance_rel", audit.solid_imbalance},
            {"physical_boundary_complete", bool(audit.boundary_complete)},
            {"finite", bool(audit.finite)},
            {"energy_ok", bool(audit.energy_ok)},
            {"solid_ok", bool(audit.solid_ok)},
            {"equations_ok", bool(audit.equations_ok)},
            {"passed", bool(audit.passed)},
            {"thermal_converged", result.stop == 0},
            {"thermal_iterations", result.iterations},
            {"thermal_residual_K", result.residual}};
    for (size_t i = 0; i < 2; ++i) {
        const auto& side = audit.sides[i];
        out.emplace(sides[i], Object{
            {"Q_advective_W_per_m", side.q_advective},
            {"inlet_conduction_W_per_m", side.inlet_conduction},
            {"exchange_W_per_m", side.exchange},
            {"source_W_per_m", 0.0},
            {"residual_sum_W_per_m", side.residual_sum},
            {"residual_max_abs_W_per_m", side.residual_max},
            {"linearized_residual_sum_W_per_m", side.linearized_sum},
            {"linearized_residual_max_abs_W_per_m", side.linearized_max},
            {"linearization_defect_sum_W_per_m", side.defect_sum},
            {"linearization_defect_max_abs_W_per_m", side.defect_max},
            {"mass_net_out_kg_s_per_m", side.mass_net},
            {"mass_local_max_abs_kg_s_per_m", side.mass_local_max},
            {"mass_in_kg_s_per_m", side.mass_in},
            {"mass_out_kg_s_per_m", side.mass_out},
            {"cp_coefficients", coefficients(side.cp_coefficients)},
            {"unknown_inflow_faces", side.unknown_inflow_faces},
            {"physical_boundary_complete", side.unknown_inflow_faces == 0},
            {"strict_normalization_W_per_m", side.normalization},
            {"residual_cellmax_rel", side.cell_ratio}});
    }
    return out;
}
Report volume_balance(const tpmshx_model_h_result_v1& result, size_t cells) {
    const auto& audit = result.volume;
    constexpr const char* names[]{"x-", "x+", "y-", "y+", "z-", "z+"};
    Object out, side_rows;
    for (size_t i = 0; i < 2; ++i) {
        const std::string label = sides[i];
        const auto& side = audit.sides[i];
        Object faces;
        for (size_t j = 0; j < 6; ++j) {
            const auto& face = side.boundaries[j];
            faces.emplace(names[j], Object{
            {"outward_mass_kg_s", face.mass_out},
            {"outward_model_h_W", face.enthalpy_out},
            {"non_inlet_inward_mass_kg_s", face.unknown_mass_in},
            {"unknown_inflow_count", face.unknown_inflow_count},
            {"inlet_reverse_outward_mass_kg_s", face.inlet_reverse_mass_out}});
        }
        side_rows.emplace(label, Object{
            {"faces", std::move(faces)},
            {"physical_boundary_complete", bool(side.boundary_complete)},
            {"model_cp_coefficients", coefficients(side.cp_coefficients)},
            {"temperature_range_K", List{side.temperature_min, side.temperature_max}},
            {"net_outward_mass_kg_s", side.mass_net},
            {"convective_inward_W", side.advective_in},
            {"inlet_diffusion_inward_W", side.diffusion_in},
            {"numerical_external_inward_W", side.numerical_external_in},
            {"physical_external_inward_W", side.boundary_complete ? Report(side.numerical_external_in) : Report()},
            {"fluid_solid_exchange_to_fluid_W", side.exchange},
            {"explicit_source_W", side.source},
            {"residual_sum_W", side.residual_sum},
            {"residual_max_abs_W", side.residual_max},
            {"strict_normalization_W", side.normalization}});
        out.emplace("eps_" + label + "_strict", side.global_ratio);
        out.emplace("eps_" + label + "_strict_cellmax", side.cell_ratio);
        out.emplace("Q_s" + label, side.exchange);
    }
    out.emplace("delegated_to_2d", false);
    out.emplace("model_h_balance", Object{
            {"reference_K", audit.sides[0].cp_coefficients[4]},
            {"cell_count", cells},
            {"full_volume_m3", audit.volume},
            {"mass_source", "completed SIMPLE raw faces before capacity balance/MAC"},
            {"thermal_state", "last returned temperatures; nonlinear model h and temperature SOU"},
            {"sides", std::move(side_rows)},
            {"physical_boundary_complete", bool(audit.boundary_complete)},
            {"numerical_external_inward_W", audit.numerical_external_in},
            {"physical_external_inward_W", audit.boundary_complete ? Report(audit.numerical_external_in) : Report()},
            {"explicit_source_W", audit.explicit_source},
            {"solid_external_diffusion_W", 0.0},
            {"solid_residual_sum_W", audit.solid_sum},
            {"solid_residual_max_abs_W", audit.solid_max},
            {"full_residual_sum_W", audit.full_residual_sum},
            {"telescoping_error_W", audit.telescoping_error},
            {"qualification", "No physical acceptance inferred. Non-inlet inflow uses numerical self-extrapolation; its external h is unspecified."}});
    return out;
}
}
