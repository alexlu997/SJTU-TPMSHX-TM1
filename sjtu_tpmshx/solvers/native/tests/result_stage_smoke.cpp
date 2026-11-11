#include "tpmshx/result_stage.hpp"
#include "tpmshx/result_stage_c_api.h"
#include <cmath>
#include <cstddef>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>

using namespace tpmshx::result;
using namespace tpmshx::result::stage;
namespace {
void require(bool condition, const char* message) {if (!condition) throw std::runtime_error(message);}
Tensor tensor(std::vector<std::size_t> shape, std::initializer_list<double> values) {
    Tensor out(std::move(shape), TPMSHX_RESULT_F64);
    require(out.size() == values.size(), "fixture shape");
    std::size_t i = 0;
    for (auto value : values) out.put(i++, arithmetic::python_float(value));
    return out;
}
Tensor zero(std::vector<std::size_t> shape) {
    Tensor out(std::move(shape), TPMSHX_RESULT_F64);
    for (std::size_t i = 0; i < out.size(); ++i) out.put(i, arithmetic::python_float(0));
    return out;
}
ModelCertificate model(double q) {
    ModelCertificate out; out.passed = true; out.physical_boundary_complete = true;
    for (std::size_t side = 0; side < 2; ++side) {
        out.sides[side].physical_boundary_complete = true;
        const auto first = side ? q / 2 : q, last = side ? q : q / 2;
        out.sides[side].staggered_power = {tensor({3, 2}, {first, first, 0, 0, last, last}), zero({2, 3})};
    }
    return out;
}
EnergyEvidence ledger() {
    EnergyEvidence out; out.definition = "physical_heat_ledger_v1"; out.power_units = "W/m";
    out.physical_dimension = 2; out.physical_boundary_complete = true; out.prescribed_b_power = zero({});
    for (const auto& name : {"A", "B", "solid"}) {
        EnergyPhaseEvidence phase; phase.solved = true; phase.residual = zero({2, 2}); phase.source_integral = zero({});
        for (const auto& face : {"x-", "x+", "y-", "y+", "z-", "z+"}) {
            const auto shape = face[0] == 'z' ? std::vector<std::size_t>{2, 2} : std::vector<std::size_t>{2, 1};
            phase.advective_out.emplace(face, zero(shape)); phase.diffusive_out.emplace(face, zero(shape));
        }
        out.phases.emplace(name, std::move(phase));
    }
    return out;
}
ResultEvidence fixture() {
    ResultEvidence out; out.result_id = "native-stage"; out.dimension = 2; out.metadata_dimension = 2;
    out.thermal_mode = "model_h"; out.grid.widths[0] = tensor({2}, {.1, .1}); out.grid.widths[1] = tensor({2}, {.1, .1});
    out.fields.emplace("Ta", tensor({2, 2}, {350, 360, 300, 320}));
    out.fields.emplace("Tb", tensor({2, 2}, {300, 300, 300, 300}));
    out.fields.emplace("Ts", tensor({2, 2}, {325, 325, 325, 325}));
    out.fields.emplace("Ta_display", tensor({2, 2}, {1000, 1000, 1000, 1000}));
    for (std::size_t side = 0; side < 2; ++side) {
        out.fields.emplace(side ? "P_report_B" : "P_report_A", tensor({2, 2}, {100, 100, 20, 20}));
        out.thermal.mass[side] = {tensor({3, 2}, {1, 3, 1, 3, 1, 3}), zero({2, 3})};
        out.direction[side] = 0;
        out.inlet_geom_fraction[side] = tensor({2}, {.25, .75}); out.outlet_geom_fraction[side] = tensor({2}, {.3, .9});
        PressureEvidence p; p.outlet_geom_fraction = tensor({2}, {.3, .9}); out.pressure[side] = std::move(p);
    }
    out.thermal.model_h = model(10); out.thermal.energy = ledger();
    FineEvidence fine; fine.grid = out.grid; fine.fields = out.fields; fine.thermal.model_h = model(13); fine.thermal.energy = ledger();
    out.fine = std::move(fine);
    out.model_certificates.emplace("main", model(10)); out.model_certificates.emplace("fine", model(13));
    out.richardson_extrapolated = true; out.execution = "completed"; out.converged = true;
    out.convergence_gates.emplace("richardson_ok", true);
    out.execution_version = "full_execution_v1";
    out.executed_sides.emplace("A", ExecutionSide{std::string("air"), true}); out.executed_sides.emplace("B", ExecutionSide{std::string("air"), true});
    ApplicabilityEvidence applicability; applicability.inlet_recorded = true;
    RangeSample sample; sample.captured = true; sample.side = "A"; sample.quantity = "Re"; sample.source = {"nu", "air"};
    sample.bounds = {100, 200}; sample.size = 1; sample.minimum = 150; sample.maximum = 150;
    applicability.groups.emplace("inlet", std::vector<RangeSample>{sample}); applicability.groups.emplace("final", std::vector<RangeSample>{});
    out.applicability = std::move(applicability);
    return out;
}
void cpp_contract() {
    auto input = fixture();
    auto output = evaluate(input);
    require(output.metrics.size() == 17, "full 2D definitions");
    require(output.metrics.at("Q").value == 10, "main A duty");
    require(output.metrics.at("Q_B").value == -10, "signed B duty");
    require(output.metrics.at("Q_richardson_A").value == 14, "fine duty remains separate");
    require(output.metrics.at("dP_A").value == 160, "physical pressure faces");
    require(output.metrics.at("T_out_A").value == 315, "native outward weighting");
    require(output.metrics.at("mass_flow_A").value == 4, "native inflow");
    require(output.metrics.at("mass").status == "insufficient_data", "missing mass evidence");
    require(output.qualification.design_eligible == true, "recorded qualification gates");
    require(output.metrics.at("Q_A").spec.description.rfind("Signed A-side", 0) == 0, "metric definition text");
    input.executed_sides.at("A").fluid = "sco2";
    output = evaluate(input);
    require(!output.qualification.design_eligible, "sCO2 model scope stays unverified");
    require(output.qualification.optimization.passed == true, "recorded sCO2 numerical study scope");
    input.applicability.reset();
    require(!evaluate(input).qualification.optimization.passed, "missing range evidence stays unverified");
    require(evaluate_applicability(input).status == "unavailable", "historical missing range status");
    input.thermal.mass[0].clear();
    output = evaluate(input);
    require(output.metrics.at("mass_flow_A").status == "insufficient_data", "missing native faces");
    require(output.metrics.at("Q").value == 10, "duty does not borrow mass report");
    input = fixture();
    input.fields.at("Ta").put(0, arithmetic::python_float(std::numeric_limits<double>::quiet_NaN()));
    require(evaluate(input).qualification.convergence.passed == false, "raw nonfinite field rejects convergence");
    const auto unsupported = evaluate(input, MetricSpec{"Q", "W/m", "three_module_v1", ""});
    require(unsupported.metrics.at("Q").status == "unsupported", "metric version selection");
    const auto unknown = evaluate(input, MetricSpec{"unknown", "1", "v1", ""});
    require(unknown.metrics.at("unknown").reason == "unknown metric", "unknown metric status");
    input = fixture(); input.applicability->groups.at("inlet")[0].maximum = 221;
    require(evaluate_applicability(input).within_limits == false, "range policy retains existing margin");
}
void c_contract() {
    tpmshx_result_evidence_v1 input{};
    input.abi_version = TPMSHX_RESULT_STAGE_ABI_VERSION; input.struct_size = sizeof(input);
    input.result_id = "historical"; input.dimension = 2; input.converged = -1;
    input.model_active_b = -1; input.richardson_extrapolated = -1;
    input.active_fluids[0] = input.active_fluids[1] = 1;
    tpmshx_stage_output_v1 output{}; output.struct_size = sizeof(output);
    char error[1024]{};
    require(tpmshx_result_stage_applicability_v1(&input, &output, error, sizeof(error)) == 0, "C applicability");
    require(std::strstr(output.json, "original-bound and final-state evidence was not recorded") != nullptr, "C missing evidence reason");
    tpmshx_result_stage_release_v1(&output);
    require(!output.owner && !output.json && output.struct_size == sizeof(output), "creating library releases output");
    require(tpmshx_result_stage_evaluate_v1(&input, nullptr, &output, error, sizeof(error)) == 0, "C complete evaluation");
    require(output.metric_count == 17, "C typed metric list");
    require(std::strstr(output.json, "unverified") != nullptr, "C historical qualification");
    tpmshx_result_stage_release_v1(&output);
    input.struct_size = 0;
    const auto before = output;
    require(tpmshx_result_stage_evaluate_v1(&input, nullptr, &output, error, sizeof(error)) != 0, "C ABI size check");
    require(std::memcmp(&before, &output, sizeof(output)) == 0, "C failed output is atomic");
    require(std::strstr(error, "ABI") != nullptr, "C bounded error");
    input.struct_size = sizeof(input);
    require(tpmshx_result_stage_evaluate_v1(&input, nullptr, &output, reinterpret_cast<char*>(&input), sizeof(input)) != 0,
            "C output cannot overwrite borrowed evidence");
    require(input.abi_version == TPMSHX_RESULT_STAGE_ABI_VERSION, "C alias rejection preserves inputs");
    auto good = tensor({1}, {42.});
    auto bad = good.raw(); bad.dtype = 0;
    tpmshx_stage_named_array_v1 fields[]{{"first", bad}, {"last", good.raw()}};
    input.fields = fields; input.field_count = 2;
    require(tpmshx_result_stage_evaluate_v1(&input, nullptr, &output,
        reinterpret_cast<char*>(good.bytes.data()), good.bytes.size()) != 0, "C invalid array fails before report publication");
    require(arithmetic::to_float(good.array().at(0)) == 42., "C early failure preserves unvisited borrowed storage");
}
struct HostProbe {std::uint32_t cause{}; std::size_t calls{};};
int TPMSHX_RESULT_CALL reject_event(void* context, const tpmshx_result_diagnostics_v1* events,
                                   tpmshx_stage_host_error_v2* error) {
    auto& probe = *static_cast<HostProbe*>(context);
    require(events->event_count > 0, "host receives a real numerical event");
    ++probe.calls;
    *error = {probe.cause, 0, 77, "host policy rejected this operation"};
    return 1;
}
void host_contract() {
    tpmshx_result_evidence_v1 evidence{};
    evidence.abi_version = TPMSHX_RESULT_STAGE_ABI_VERSION; evidence.struct_size = sizeof(evidence);
    evidence.result_id = "host"; evidence.dimension = 2; evidence.converged = -1;
    evidence.model_active_b = -1; evidence.richardson_extrapolated = -1;
    evidence.active_fluids[0] = evidence.active_fluids[1] = 1;
    auto epsilon = tensor({1, 1}, {-1.});
    auto density = tensor({}, {std::numeric_limits<double>::max()});
    auto width = tensor({1}, {1.});
    const auto eps = epsilon.raw(), rho = density.raw(), dx = width.raw();
    evidence.design_epsilon = &eps; evidence.grid.widths[0] = evidence.grid.widths[1] = &dx;
    HostProbe probe{TPMSHX_RESULT_VALUE_ERROR, 0};
    tpmshx_stage_input_v2 input{};
    input.abi_version = 2; input.struct_size = sizeof(input); input.evidence = &evidence;
    input.solid_density = &rho; input.context = &probe; input.events = reject_event;
    tpmshx_stage_output_v1 output{}; output.struct_size = sizeof(output);
    tpmshx_result_diagnostics_v1 diagnostics{}; std::uint64_t token{};
    tpmshx_stage_metric_spec_v1 requested{"mass", "kg/m", "three_module_v1", ""};
    char error[1024]{};
    require(tpmshx_result_stage_query_v2(&input, 0, &requested, nullptr, 0,
        &output, &diagnostics, &token, error, sizeof(error)) == 0, "metric consumes a host ValueError");
    require(probe.calls == 1 && output.metric_count == 1, "one original primitive boundary");
    require(std::strcmp(output.metrics[0].status, "invalid") == 0 && token == 0,
            "consumed callback errors do not escape the successful stage");
    tpmshx_result_stage_release_v1(&output);
    probe.cause = 8; probe.calls = 0;
    const auto before = output;
    require(tpmshx_result_stage_query_v2(&input, 0, &requested, nullptr, 0,
        &output, &diagnostics, &token, error, sizeof(error)) == TPMSHX_RESULT_NUMERIC,
        "unhandled host error stops the stage");
    require(probe.calls == 1 && token == 77 && diagnostics.python_cause == 8,
        "unhandled callback keeps its original host identity");
    require(std::memcmp(&before, &output, sizeof(output)) == 0, "host failure does not publish a report");
}

void deferred_alias_contract() {
    for (int kind = 0; kind < 10; ++kind) for (int channel = 0; channel < 4; ++channel) {
        alignas(std::max_align_t) unsigned char borrowed[4096]{};
        tpmshx_result_evidence_v1 evidence{};
        evidence.abi_version = TPMSHX_RESULT_STAGE_ABI_VERSION; evidence.struct_size = sizeof(evidence);
        evidence.result_id = "deferred-alias"; evidence.dimension = 2; evidence.converged = -1;
        evidence.model_active_b = -1; evidence.richardson_extrapolated = -1;
        evidence.active_fluids[0] = evidence.active_fluids[1] = 1;
        switch (kind) {
        case 0: evidence.pressure[0] = reinterpret_cast<tpmshx_stage_pressure_v1*>(borrowed); break;
        case 1: evidence.thermal.energy = reinterpret_cast<tpmshx_stage_energy_v1*>(borrowed); break;
        case 2: evidence.thermal.model_h = reinterpret_cast<tpmshx_stage_model_certificate_v1*>(borrowed); break;
        case 3: evidence.thermal.true_h = reinterpret_cast<tpmshx_stage_true_h_v1*>(borrowed); break;
        case 4: evidence.fine = reinterpret_cast<tpmshx_stage_fine_v1*>(borrowed); break;
        case 5: evidence.true_h_certificate = reinterpret_cast<tpmshx_stage_true_h_certificate_v1*>(borrowed); break;
        case 6: evidence.outer_index = reinterpret_cast<int*>(borrowed); break;
        case 7: evidence.solid_density = reinterpret_cast<tpmshx_result_scalar_v1*>(borrowed); break;
        case 8: evidence.applicability = reinterpret_cast<tpmshx_stage_applicability_v1*>(borrowed); break;
        case 9: evidence.thermal_state = reinterpret_cast<char*>(borrowed); break;
        }
        tpmshx_stage_input_error_v2 failure{borrowed, TPMSHX_RESULT_TYPE_ERROR, "deferred input", 17};
        tpmshx_stage_input_v2 input{};
        input.abi_version = 2; input.struct_size = sizeof(input); input.evidence = &evidence;
        input.errors = &failure; input.error_count = 1;
        tpmshx_stage_output_v1 result{}; result.struct_size = sizeof(result);
        tpmshx_result_diagnostics_v1 diagnostic{}; std::uint64_t token{}; char error[128]{};
        auto* output = channel == 0 ? reinterpret_cast<tpmshx_stage_output_v1*>(borrowed) : &result;
        if (channel == 0) output->struct_size = sizeof(*output);
        auto* diagnostics = channel == 1 ? reinterpret_cast<tpmshx_result_diagnostics_v1*>(borrowed) : &diagnostic;
        auto* identity = channel == 2 ? reinterpret_cast<std::uint64_t*>(borrowed) : &token;
        auto* message = channel == 3 ? reinterpret_cast<char*>(borrowed) : error;
        unsigned char before[sizeof(borrowed)]; std::memcpy(before, borrowed, sizeof(borrowed));
        const auto status = tpmshx_result_stage_query_v2(&input, 1, nullptr, nullptr, 0,
            output, diagnostics, identity, message, sizeof(error));
        require(status != 0, "v2 writable storage cannot alias a deferred input");
        require(std::memcmp(before, borrowed, sizeof(borrowed)) == 0,
                "v2 deferred input storage remains unchanged after rejection");
    }
}

struct QuickProbe {
    const RawArray* numeric{};
    const char* message{"Quick host failure"};
    std::uint32_t cause{};
    std::size_t calls{};
};
int TPMSHX_RESULT_CALL quick_pressure(void* context, const tpmshx_stage_quick_value_v3* inlet,
    const tpmshx_stage_quick_value_v3* outlet, tpmshx_stage_quick_value_v3* value,
    tpmshx_stage_host_error_v2* error) {
    auto& probe = *static_cast<QuickProbe*>(context);
    ++probe.calls;
    require(inlet->object == 11 && outlet->numeric, "Quick callback receives its selected operands");
    if (probe.cause) {*error = {probe.cause, 0, 77, probe.message}; return 1;}
    *value = {probe.numeric, 0};
    return 0;
}
int TPMSHX_RESULT_CALL quick_label_equal(void* context, const tpmshx_stage_quick_value_v3* value,
    const char* expected, int* output, tpmshx_stage_host_error_v2*) {
    auto& calls = *static_cast<std::size_t*>(context);
    ++calls;
    require(value->object == 19, "label host keeps its original object token");
    require(std::strcmp(expected, "plug_ltne_analytic_dp_v1") == 0,
        "native model policy supplies the comparison text");
    *output = 1;
    return 0;
}
void quick_host_contract() {
    tpmshx_result_evidence_v1 evidence{};
    evidence.abi_version = TPMSHX_RESULT_STAGE_ABI_VERSION; evidence.struct_size = sizeof(evidence);
    evidence.result_id = "quick-host"; evidence.dimension = 3; evidence.mode = "quick_design";
    evidence.converged = -1; evidence.model_active_b = -1; evidence.richardson_extrapolated = -1;
    evidence.active_fluids[0] = evidence.active_fluids[1] = 1;
    tpmshx_stage_input_v2 host{}; host.abi_version = 2; host.struct_size = sizeof(host); host.evidence = &evidence;
    auto first = tensor({}, {12.}), second = tensor({}, {3.}), returned = tensor({}, {42.});
    const auto first_array = first.raw(), second_array = second.raw(), returned_array = returned.raw();
    tpmshx_stage_quick_value_v3 inlet{&first_array, 0}, outlet{&second_array, 0};
    const int yes = 1;
    tpmshx_stage_input_v3 input{}; input.abi_version = 3; input.struct_size = sizeof(input);
    const tpmshx_stage_label_v3 model_label{"plug_ltne_analytic_dp_v1", nullptr};
    input.host = &host; input.model = &model_label; input.sides[0].pressure_access = &yes;
    input.sides[0].inlet_pressure = &inlet; input.sides[0].outlet_pressure = &outlet;
    tpmshx_stage_output_v1 output{}; output.struct_size = sizeof(output);
    tpmshx_result_diagnostics_v1 diagnostics{}; std::uint64_t token{}; char error[1024]{};
    const tpmshx_stage_metric_spec_v1 requested{"dP_A", "Pa", "three_module_v1", ""};
    const auto call = [&]() {return tpmshx_result_stage_query_v3(&input, 0, &requested, nullptr, 0,
        &output, &diagnostics, &token, error, sizeof(error));};
    require(call() == 0 && output.metrics[0].value == 9., "typed Quick input needs no host arithmetic");
    tpmshx_result_stage_release_v1(&output);
    const auto large_inlet = pack_scalar(arithmetic::python_int((std::int64_t{1} << 62) + 1));
    const auto large_outlet = pack_scalar(arithmetic::python_int(std::int64_t{1} << 62));
    tpmshx_stage_pressure_v1 old_pressure{};
    old_pressure.inlet_absolute = &large_inlet; old_pressure.outlet_absolute = &large_outlet;
    evidence.quick_model = "plug_ltne_analytic_dp_v1"; evidence.pressure[0] = &old_pressure;
    require(tpmshx_result_stage_evaluate_v1(&evidence, &requested, &output, error, sizeof(error)) == 0 &&
        output.metrics[0].value == 1., "v1 wide scalar cancellation needs no new host");
    tpmshx_result_stage_release_v1(&output);
    require(tpmshx_result_stage_query_v2(&host, 0, &requested, nullptr, 0,
        &output, &diagnostics, &token, error, sizeof(error)) == 0 && output.metrics[0].value == 1.,
        "v2 wide scalar cancellation needs no new host");
    tpmshx_result_stage_release_v1(&output);
    const tpmshx_stage_quick_value_v3 host_label_value{nullptr, 19};
    const tpmshx_stage_label_v3 host_label{nullptr, &host_label_value};
    std::size_t label_calls{};
    input.model = &host_label; input.protocol.context = &label_calls;
    input.protocol.text_equal = quick_label_equal;
    require(call() == 0 && label_calls == 1 && output.metrics[0].value == 9.,
        "native model comparison uses only the fixed host equality protocol");
    tpmshx_result_stage_release_v1(&output);
    input.model = &model_label; input.protocol.text_equal = nullptr;
    inlet = {nullptr, 11};
    const auto before = output;
    require(call() == TPMSHX_RESULT_RUNTIME && std::strstr(error, "named Python protocol callback"),
        "missing selected Quick callback fails explicitly");
    require(std::memcmp(&before, &output, sizeof(output)) == 0, "missing Quick callback keeps output atomic");
    QuickProbe probe{&returned_array};
    input.protocol.context = &probe; input.protocol.pressure_difference = quick_pressure;
    require(call() == 0 && probe.calls == 1 && output.metrics[0].value == 42., "named Quick callback supplies its typed expression");
    returned.put(0, arithmetic::python_float(99.));
    require(output.metrics[0].value == 42., "Quick report owns copied callback values");
    tpmshx_result_stage_release_v1(&output);
    probe.cause = TPMSHX_RESULT_VALUE_ERROR;
    require(call() == 0 && std::strcmp(output.metrics[0].status, "invalid") == 0 && token == 0,
        "Quick metric consumes its original ValueError");
    tpmshx_result_stage_release_v1(&output);
    probe.cause = 8;
    require(call() == TPMSHX_RESULT_NUMERIC && token == 77 && diagnostics.python_cause == 8,
        "Quick callback preserves unhandled host identity");
    require(std::memcmp(&before, &output, sizeof(output)) == 0, "Quick host failure keeps output atomic");
    probe.cause = 0;
    for (int channel = 0; channel < 4; ++channel) {
        alignas(std::max_align_t) unsigned char borrowed[4096]{};
        auto alias = returned_array; alias.data = borrowed;
        probe.numeric = &alias;
        auto* result = channel == 0 ? reinterpret_cast<tpmshx_stage_output_v1*>(borrowed) : &output;
        if (channel == 0) result->struct_size = sizeof(*result);
        auto* report = channel == 1 ? reinterpret_cast<tpmshx_result_diagnostics_v1*>(borrowed) : &diagnostics;
        auto* identity = channel == 2 ? reinterpret_cast<std::uint64_t*>(borrowed) : &token;
        auto* message = channel == 3 ? reinterpret_cast<char*>(borrowed) : error;
        unsigned char saved[sizeof(borrowed)]; std::memcpy(saved, borrowed, sizeof(borrowed));
        require(tpmshx_result_stage_query_v3(&input, 0, &requested, nullptr, 0,
            result, report, identity, message, sizeof(error)) != 0, "Quick callback cannot return writable storage");
        require(std::memcmp(saved, borrowed, sizeof(borrowed)) == 0, "Quick alias rejection preserves callback storage");
    }
    std::size_t shape = 1; const std::ptrdiff_t stride = 8;
    auto invalid = returned_array; invalid.data = nullptr; invalid.rank = 1; invalid.shape = &shape; invalid.strides = &stride;
    probe.numeric = &invalid;
    const auto saved_diagnostics = diagnostics; const auto saved_token = token;
    require(tpmshx_result_stage_query_v3(&input, 0, &requested, nullptr, 0,
        &output, &diagnostics, &token, reinterpret_cast<char*>(&shape), sizeof(shape)) != 0,
        "interrupted Quick callback copy cannot publish a report");
    require(shape == 1 && token == saved_token && std::memcmp(&saved_diagnostics, &diagnostics, sizeof(diagnostics)) == 0,
        "interrupted callback copy preserves unvisited storage and diagnostics");
    require(std::memcmp(&before, &output, sizeof(output)) == 0, "interrupted callback copy keeps output atomic");
    alignas(std::max_align_t) char borrowed_message[4096] = "unchanged Quick host failure";
    probe.cause = 8; probe.message = borrowed_message;
    char saved_message[sizeof(borrowed_message)]; std::memcpy(saved_message, borrowed_message, sizeof(saved_message));
    require(tpmshx_result_stage_query_v3(&input, 0, &requested, nullptr, 0,
        &output, reinterpret_cast<tpmshx_result_diagnostics_v1*>(borrowed_message), &token, error, sizeof(error)) != 0,
        "Quick callback error text cannot alias diagnostics");
    require(std::memcmp(saved_message, borrowed_message, sizeof(saved_message)) == 0,
        "Quick callback error text remains unchanged");
}

}
int main() {
    try {cpp_contract(); c_contract(); host_contract(); deferred_alias_contract(); quick_host_contract(); std::cout << "result stage contracts passed\n";}
    catch (const std::exception& error) {std::cerr << error.what() << '\n'; return 1;}
    return 0;
}
