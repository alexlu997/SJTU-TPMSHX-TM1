#pragma once
#include "tpmshx/result_arithmetic.hpp"
#include <array>
#include <map>
#include <optional>
#include <string>
#include <variant>
#include <vector>

namespace tpmshx::result::stage {
using Tensor = arithmetic::Tensor;
using Arrays = std::map<std::string, Tensor>;
using Truth = std::optional<bool>;

// Reports retain the public record keys and contain no executable objects.
struct Report {
    using List = std::vector<Report>;
    using Object = std::map<std::string, Report>;
    std::variant<std::nullptr_t, bool, std::int64_t, double, std::string, List, Object> value;
    Report():value(nullptr) {}
    Report(std::nullptr_t):value(nullptr) {}
    Report(bool v):value(v) {}
    Report(int v):value(static_cast<std::int64_t>(v)) {}
    Report(std::int64_t v):value(v) {}
    Report(double v):value(v) {}
    Report(const char* v):value(std::string(v)) {}
    Report(std::string v):value(std::move(v)) {}
    Report(List v):value(std::move(v)) {}
    Report(Object v):value(std::move(v)) {}
    Report(Truth v):Report() {if(v) value=*v;}
};
struct GridEvidence {std::array<std::optional<Tensor>, 3> widths;};
struct FieldDeclaration {std::string unit; std::optional<std::string> state;};
struct PressureEvidence {
    std::optional<Tensor> pressure;
    GridEvidence grid;
    std::optional<Tensor> inlet_fraction, outlet_fraction, outlet_geom_fraction;
    std::optional<Number> reference, inlet_absolute, outlet_absolute;
    std::optional<std::string> unit;
};
struct EnergyPhaseEvidence {
    Truth solved;
    bool solved_is_bool{true};
    std::optional<Tensor> residual;
    Arrays advective_out, diffusive_out;
    std::optional<Tensor> source_integral;
};
struct EnergyEvidence {
    std::optional<std::string> definition, power_units;
    std::optional<int> physical_dimension;
    Truth physical_boundary_complete;
    bool physical_boundary_complete_is_bool{true};
    std::map<std::string, EnergyPhaseEvidence> phases;
    std::optional<Tensor> prescribed_b_power;
};
struct ModelSideEvidence {
    Truth physical_boundary_complete;
    bool physical_boundary_complete_is_bool{true};
    std::vector<Tensor> staggered_power;
    Arrays boundary_power;
};
struct ModelCertificate {
    Truth passed, physical_boundary_complete;
    bool passed_is_bool{true}, physical_boundary_complete_is_bool{true};
    std::array<ModelSideEvidence, 2> sides;
};
struct TrueHEvidence {
    std::optional<std::string> energy_algorithm, boundary_power_units;
    std::optional<int> energy_algorithm_version;
    Truth physical_boundary_complete;
    bool physical_boundary_complete_is_bool{true}, physical_boundary_complete_recorded{true}, energy_algorithm_version_is_int{true};
    std::array<std::optional<Tensor>, 2> enthalpy;
    std::array<std::optional<Number>, 2> inlet_enthalpy;
    std::array<std::vector<Tensor>, 2> mass;
    std::array<Arrays, 2> boundary_power;
};
struct ThermalEvidence {
    std::array<std::vector<Tensor>, 2> mass;
    std::optional<EnergyEvidence> energy, temperature;
    std::optional<TrueHEvidence> true_h;
    std::optional<ModelCertificate> model_h;
    std::array<std::optional<int>, 2> report_direction;
};
struct FineEvidence {
    bool empty_record{};
    GridEvidence grid;
    Arrays fields;
    ThermalEvidence thermal;
    std::array<std::optional<Tensor>, 2> rho_cp, inlet_fraction, outlet_fraction;
    std::optional<Tensor> epsilon;
};
struct TrueHCertificate {
    Truth converged;
    std::optional<Tensor> clip_counts;
    std::array<std::optional<Number>, 2> ratios, tolerances;
};
struct ExecutionSide {std::optional<std::string> fluid; Truth solved;};
struct RangeSample {
    bool captured{}, captured_is_bool{true};
    std::string side, quantity, constraint{"parameter"};
    std::vector<std::string> source;
    std::array<double, 2> bounds{};
    std::vector<std::size_t> shape;
    std::size_t size{}, low{}, high{}, nonfinite{};
    std::optional<double> minimum, maximum;
    Report::Object captured_record;
};
struct RequiredRange {std::string group, side; std::vector<std::string> source;};
struct ApplicabilityEvidence {
    std::string version{"applicability_evidence_v1"};
    std::map<std::string, std::vector<RangeSample>> groups;
    std::vector<RequiredRange> required;
    bool inlet_recorded{};
    Report::List scope_notes;
};
struct QuickSideEvidence {
    std::optional<Number> inlet_temperature, mass_flow, cp, rho, velocity, viscosity;
};
// Optional values denote recorded evidence, never an inferred success.
struct ResultEvidence {
    std::string result_id;
    int dimension{};
    std::optional<int> metadata_dimension;
    std::optional<std::string> quantity_basis, mass_unit;
    std::string mode{"full"};
    std::optional<std::string> thermal_mode, temperature_transport;
    GridEvidence grid;
    Arrays fields;
    std::map<std::string, FieldDeclaration> field_metadata;
    std::array<std::optional<PressureEvidence>, 2> pressure;
    ThermalEvidence thermal;
    std::optional<FineEvidence> fine;
    std::optional<std::string> thermal_state, execution;
    Truth converged;
    std::optional<int> outer_index;
    std::map<std::string, Truth> convergence_gates;
    std::optional<TrueHCertificate> true_h_certificate;
    std::map<std::string, ModelCertificate> model_certificates;
    std::array<std::optional<double>, 4> strict_ratios;
    std::array<std::optional<double>, 2> source_power;
    std::optional<bool> model_active_b;
    Truth richardson_extrapolated;
    std::optional<std::string> execution_version;
    std::map<std::string, ExecutionSide> executed_sides;
    std::optional<ApplicabilityEvidence> applicability;
    std::array<bool, 2> active_fluids{{true, true}};
    std::array<std::optional<int>, 2> direction;
    std::array<std::optional<Number>, 2> inlet_temperature;
    std::array<std::optional<Tensor>, 2> inlet_geom_fraction, outlet_geom_fraction, rho_cp;
    std::optional<Tensor> parameter_epsilon, design_epsilon;
    std::optional<Number> split_a, solid_density;
    std::optional<std::string> quick_model, arrangement;
    std::array<QuickSideEvidence, 2> quick;
    std::optional<Number> hydraulic_diameter;
    std::vector<std::string> absent_records;
    std::optional<std::string> model_certificate_error;
};
struct MetricSpec {std::string name, unit, definition_version{"three_module_v1"}, description;};
struct MetricValue {
    std::optional<double> value;
    MetricSpec spec;
    std::string status{"available"}, reason;
};
struct Applicability {
    std::string definition{"applicability_v1"}, status;
    Truth within_limits;
    Report::Object details;
};
struct PhysicalBalance {
    std::string definition{"physical_balance_v1"};
    int physical_dimension{};
    Report::Object details;
};
struct Verdict {std::string status, source; Truth passed; Report::Object details;};
struct Qualification {
    std::string definition{"result_qualification_v1"}, source_result_id;
    Verdict execution, convergence, physical, applicability, metrics, model_scope, optimization;
    std::string design_status;
    Truth design_eligible;
    Report::Object design_details;
};
struct Evaluation {
    std::string source_result_id;
    std::map<std::string, MetricValue> metrics;
    Qualification qualification;
    Diagnostics diagnostics{};
};
Evaluation evaluate(const ResultEvidence&, const std::optional<MetricSpec>& = std::nullopt);
Applicability evaluate_applicability(const ResultEvidence&);
PhysicalBalance evaluate_physical_balance(const ResultEvidence&);
Qualification evaluate_qualification(const ResultEvidence&, const std::map<std::string, MetricValue>&);
Report report(const Evaluation&);
Report report(const Applicability&);
Report report(const PhysicalBalance&);
Report report(const Qualification&);
std::string json(const Report&);
}  // namespace tpmshx::result::stage
