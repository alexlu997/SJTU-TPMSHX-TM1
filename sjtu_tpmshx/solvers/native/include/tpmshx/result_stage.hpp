#pragma once
#include "tpmshx/result_arithmetic.hpp"
#include <array>
#include <algorithm>
#include <string_view>
#include <map>
#include <functional>
#include <optional>
#include <string>
#include <type_traits>
#include <variant>
#include <vector>

namespace tpmshx::result::stage {
enum HostCause : std::uint32_t {key_error = 6, not_implemented = 7, host_exception = 8};
struct HostError : NumericError {
    std::uint64_t token{};
    HostError(std::uint32_t cause, std::string message, std::uint64_t identity = 0)
        : NumericError(cause, message), token(identity) {}
};
struct InputError {std::uint32_t cause{}; std::string message; std::uint64_t token{};};

// A host conversion fails only when the original consumer reads that value.
template<class T> class Recorded {
    std::optional<T> value_;
    std::optional<InputError> error_;
    void check() const {if (error_) throw HostError(error_->cause, error_->message, error_->token);}
public:
    Recorded() = default;
    Recorded(std::nullopt_t) {}
    Recorded(const T& value):value_(value) {}
    Recorded(T&& value):value_(std::move(value)) {}
    Recorded(std::optional<T> value):value_(std::move(value)) {}
    template<class U, std::enable_if_t<std::is_constructible_v<T, U>, int> = 0>
    Recorded(U&& value):value_(std::forward<U>(value)) {}
    explicit Recorded(InputError error):error_(std::move(error)) {}
    explicit operator bool() const {return value_.has_value() || error_.has_value();}
    bool has_value() const {return static_cast<bool>(*this);}
    void reset() {value_.reset(); error_.reset();}
    const T& operator*() const {check(); return *value_;}
    T& operator*() {check(); return *value_;}
    const T* operator->() const {return &**this;}
    T* operator->() {return &**this;}
    template<class U> T value_or(U&& other) const {check(); return value_.value_or(std::forward<U>(other));}
    template<class U> bool operator==(const U& other) const {check(); return value_ == other;}
    template<class U> bool operator!=(const U& other) const {return !(*this == other);}
};

struct Tensor : arithmetic::Tensor {
    std::optional<InputError> input_error;
    using arithmetic::Tensor::Tensor;
    Tensor(arithmetic::Tensor value):arithmetic::Tensor(std::move(value)) {}
    Tensor(Number value):arithmetic::Tensor(arithmetic::scalar(value)) {}
    RawArray raw() const {
        if (input_error) throw HostError(input_error->cause, input_error->message, input_error->token);
        return arithmetic::Tensor::raw();
    }
    Array array() const {return Array(raw());}
};
struct Arrays : std::map<std::string, Tensor> {
    using std::map<std::string, Tensor>::map;
    std::optional<InputError> input_error;
    void check() const {
        if (input_error) throw HostError(input_error->cause, input_error->message, input_error->token);
    }
};
using Truth = std::optional<bool>;

// Public reports retain the order in which their fields are defined.
template<class T> class ReportObject {
    using Item = std::pair<std::string, T>;
    std::vector<Item> values_;
public:
    ReportObject() = default;
    ReportObject(std::initializer_list<Item> values):values_(values) {}
    auto begin() {return values_.begin();}
    auto end() {return values_.end();}
    auto begin() const {return values_.begin();}
    auto end() const {return values_.end();}
    auto find(std::string_view key) {return std::find_if(begin(), end(), [&](const auto& row){return row.first == key;});}
    auto find(std::string_view key) const {return std::find_if(begin(), end(), [&](const auto& row){return row.first == key;});}
    std::size_t count(std::string_view key) const {return find(key) != end();}
    bool empty() const {return values_.empty();}
    std::size_t size() const {return values_.size();}
    T& at(std::string_view key) {
        const auto found = find(key);
        if (found == end()) throw std::out_of_range("missing report field");
        return found->second;
    }
    const T& at(std::string_view key) const {
        const auto found = find(key);
        if (found == end()) throw std::out_of_range("missing report field");
        return found->second;
    }
    template<class U> auto emplace(std::string key, U&& value) {
        auto found = find(key);
        if (found != end()) return std::make_pair(found, false);
        values_.emplace_back(std::move(key), std::forward<U>(value));
        return std::make_pair(std::prev(end()), true);
    }
    template<class U> void insert_or_assign(std::string key, U&& value) {
        const auto found = find(key);
        if (found == end()) values_.emplace_back(std::move(key), std::forward<U>(value));
        else found->second = std::forward<U>(value);
    }
};
// Reports contain recorded data and contain no executable objects.
struct Report {
    using List = std::vector<Report>;
    using Object = ReportObject<Report>;
    std::variant<std::nullptr_t, bool, std::int64_t, std::uint64_t, double, std::string, List, Object> value;
    Report():value(nullptr) {}
    Report(std::nullptr_t):value(nullptr) {}
    Report(bool v):value(v) {}
    Report(int v):value(static_cast<std::int64_t>(v)) {}
    Report(std::int64_t v):value(v) {}
    Report(std::uint64_t v):value(v) {}
    Report(double v):value(v) {}
    Report(const char* v):value(std::string(v)) {}
    Report(std::string v):value(std::move(v)) {}
    Report(List v):value(std::move(v)) {}
    Report(Object v):value(std::move(v)) {}
    Report(Truth v):Report() {if(v) value=*v;}
};
// Qualification needs both exact bool identity and equality to False.
struct TruthEvidence {
    Recorded<bool> value;
    Recorded<int> identity_access;
    bool is_bool{};
    Recorded<bool> equals_false{false};
    Report recorded;
    TruthEvidence() = default;
    TruthEvidence(bool input):value(input),is_bool(true),equals_false(!input),recorded(input) {}
    bool is_true() const {
        if (identity_access) (void)*identity_access;
        return is_bool && value == true;
    }
    Truth qualified() const {
        if (*equals_false) return false;
        return is_true() ? Truth(true) : Truth{};
    }
};
struct GridEvidence {std::array<Recorded<Tensor>, 3> widths;};
struct FieldDeclaration {std::string unit; Recorded<std::string> state;};
struct PressureEvidence {
    Recorded<Tensor> pressure;
    GridEvidence grid;
    Recorded<Tensor> inlet_fraction, outlet_fraction, outlet_geom_fraction;
    Recorded<Number> reference, inlet_absolute, outlet_absolute;
    Recorded<std::string> unit;
};
struct EnergyPhaseEvidence {
    Truth solved;
    bool solved_is_bool{true};
    Recorded<Tensor> residual;
    Arrays advective_out, diffusive_out;
    Recorded<Tensor> source_integral;
};
struct EnergyEvidence {
    Recorded<std::string> definition, power_units;
    Recorded<int> physical_dimension;
    Truth physical_boundary_complete;
    bool physical_boundary_complete_is_bool{true};
    std::map<std::string, EnergyPhaseEvidence> phases;
    Recorded<Tensor> prescribed_b_power;
};
struct ModelSideEvidence {
    Recorded<bool> physical_boundary_complete;
    bool physical_boundary_complete_is_bool{true};
    std::vector<Tensor> staggered_power;
    Arrays boundary_power;
};
struct ModelCertificate {
    Recorded<bool> passed, physical_boundary_complete;
    bool passed_is_bool{true}, physical_boundary_complete_is_bool{true};
    std::array<ModelSideEvidence, 2> sides;
};
struct TrueHEvidence {
    Recorded<std::string> energy_algorithm, boundary_power_units;
    Recorded<int> energy_algorithm_version;
    Truth physical_boundary_complete;
    bool physical_boundary_complete_is_bool{true}, physical_boundary_complete_recorded{true}, energy_algorithm_version_is_int{true};
    std::array<Recorded<Tensor>, 2> enthalpy;
    std::array<Recorded<Number>, 2> inlet_enthalpy;
    std::array<std::vector<Tensor>, 2> mass;
    std::array<Arrays, 2> boundary_power;
};
struct ThermalEvidence {
    std::array<std::vector<Tensor>, 2> mass;
    std::array<bool, 2> mass_recorded{}, mass_none{};
    Recorded<EnergyEvidence> energy, temperature;
    Recorded<TrueHEvidence> true_h;
    Recorded<ModelCertificate> model_h;
    std::array<Recorded<int>, 2> report_direction;
};
struct FineEvidence {
    bool empty_record{};
    GridEvidence grid;
    Arrays fields;
    ThermalEvidence thermal;
    std::array<Recorded<Tensor>, 2> rho_cp, inlet_fraction, outlet_fraction;
    Recorded<Tensor> epsilon;
};
struct TrueHCertificate {
    TruthEvidence converged;
    Recorded<Tensor> clip_counts;
    std::array<Recorded<Number>, 2> ratios, tolerances;
};
struct ExecutionSide {Recorded<std::string> fluid; TruthEvidence solved;};
struct RangeSample {
    bool captured{}, captured_is_bool{true};
    std::string side, quantity, constraint{"parameter"};
    std::vector<std::string> source;
    std::array<double, 2> bounds{};
    std::vector<std::size_t> shape;
    std::size_t size{}, low{}, high{}, nonfinite{};
    Recorded<double> minimum, maximum;
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
// Quick values keep typed intermediate arrays or a host-only protocol value.
struct QuickValue {
    Tensor numeric{{}, TPMSHX_RESULT_F64};
    std::uint64_t object{};
    QuickValue() = default;
    QuickValue(Number value):numeric(value) {}
    QuickValue(Tensor value):numeric(std::move(value)) {}
    explicit QuickValue(std::uint64_t token):object(token) {}
};
struct StageLabel {
    std::optional<std::string> text;
    QuickValue value;
};
struct QuickTypedSide {
    Recorded<int> boundary_access, properties_access, pressure_access;
    Recorded<QuickValue> inlet_temperature, mass_flow, cp, rho, velocity, viscosity;
    Recorded<QuickValue> inlet_pressure, outlet_pressure;
};
struct QuickTypedEvidence {
    Recorded<StageLabel> model, arrangement;
    std::array<QuickTypedSide, 2> sides;
    Recorded<QuickValue> hydraulic_diameter;
};
struct QuickHost {
    std::function<bool(const QuickValue&, const std::string&)> text_equal;
    std::function<QuickValue(const QuickValue&, double)> temperature_difference;
    std::function<QuickValue(const QuickValue&, const QuickValue&)> capacity_product;
    std::function<QuickValue(const QuickValue&, const QuickValue&, bool)> duty_product;
    std::function<QuickValue(const QuickValue&, const QuickValue&)> pressure_difference;
    std::function<QuickValue(const QuickValue&, const QuickValue&)> reynolds_flow;
    std::function<QuickValue(const QuickValue&, const QuickValue&)> reynolds_length;
    std::function<QuickValue(const QuickValue&, const QuickValue&)> reynolds_quotient;
    std::function<double(const QuickValue&)> metric_float;
    std::function<void()> empty_mean;
};
struct QuickSideEvidence {
    Recorded<Number> inlet_temperature, mass_flow, cp, rho, velocity, viscosity;
};
// Optional values denote recorded evidence, never an inferred success.
struct ResultEvidence {
    std::string result_id;
    std::optional<InputError> declaration_error;
    int dimension{};
    Recorded<int> metadata_dimension, physical_dimension_index, physical_dimension_slice, qualification_error;
    Recorded<std::string> quantity_basis, mass_unit;
    std::string mode{"full"};
    Recorded<std::string> invalid_mode_repr;
    Recorded<std::string> thermal_mode, temperature_transport;
    GridEvidence grid;
    Arrays fields;
    std::vector<std::string> field_order, model_certificate_order;
    std::map<std::string, FieldDeclaration> field_metadata;
    std::array<Recorded<PressureEvidence>, 2> pressure;
    ThermalEvidence thermal;
    Recorded<FineEvidence> fine;
    Recorded<std::string> thermal_state, execution;
    TruthEvidence converged;
    Recorded<int> outer_index;
    std::map<std::string, TruthEvidence> convergence_gates;
    Recorded<TrueHCertificate> true_h_certificate;
    std::map<std::string, ModelCertificate> model_certificates;
    bool model_certificates_recorded{};
    std::array<Recorded<double>, 4> strict_ratios;
    std::array<Recorded<double>, 2> source_power;
    Recorded<bool> model_active_b;
    Truth richardson_extrapolated;
    Recorded<std::string> execution_version;
    Recorded<StageLabel> execution_label;
    Recorded<int> execution_sides_error, execution_sides_access_error;
    std::map<std::string, ExecutionSide> executed_sides;
    Recorded<ApplicabilityEvidence> applicability;
    std::array<bool, 2> active_fluids{{true, true}};
    std::array<Recorded<int>, 2> direction;
    std::array<Recorded<Tensor>, 2> inlet_temperature;
    std::array<bool, 2> inlet_temperature_none{};
    std::array<Recorded<Tensor>, 2> inlet_geom_fraction, outlet_geom_fraction, rho_cp;
    Recorded<Tensor> parameter_epsilon, design_epsilon;
    Recorded<Tensor> split_a, solid_density;
    Recorded<std::string> quick_model, arrangement;
    std::array<QuickSideEvidence, 2> quick;
    Recorded<Number> hydraulic_diameter;
    std::optional<QuickTypedEvidence> quick_typed;
    std::vector<std::string> absent_records;
    Recorded<std::string> model_certificate_error;
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
    std::vector<std::string> metric_order;
    Qualification qualification;
    Diagnostics diagnostics{};
};
struct HostControl {
    std::function<void(const Diagnostics&)> events;
    QuickHost quick;
};
Evaluation evaluate(const ResultEvidence&, const std::optional<MetricSpec>& = std::nullopt, const HostControl* = nullptr);
Applicability evaluate_applicability(const ResultEvidence&, const HostControl* = nullptr);
PhysicalBalance evaluate_physical_balance(const ResultEvidence&, const HostControl* = nullptr);
Qualification evaluate_qualification(const ResultEvidence&, const std::map<std::string, MetricValue>&, const HostControl* = nullptr);
Report report(const Evaluation&);
Report report(const Applicability&);
Report report(const PhysicalBalance&);
Report report(const Qualification&);
std::string json(const Report&);
}  // namespace tpmshx::result::stage
