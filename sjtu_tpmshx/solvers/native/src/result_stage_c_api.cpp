#include "tpmshx/result_stage_c_api.h"
#include "tpmshx/result_stage.hpp"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <limits>
#include <memory>
#include <set>
#include <stdexcept>
#include <utility>

namespace {
using namespace tpmshx::result;
using namespace tpmshx::result::stage;

// The stage has a variable number of arrays. All borrowed spans remain read-only.
class Inputs {
public:
    struct Span {std::uintptr_t first, last;};
    std::vector<Span> spans;
    std::map<const void*, InputError> errors;
    std::set<const void*> none_values;
    bool host_input{};
    bool copied_inputs{};
    const InputError* error(const void* value) const {
        const auto found = errors.find(value);
        return found == errors.end() ? nullptr : &found->second;
    }
    template<class T> const T* sequence(const T* pointer, std::size_t count) {
        add(pointer, count, sizeof(T), alignof(T));
        return pointer;
    }
    void add(const void* pointer, std::size_t count, std::size_t width, std::size_t alignment) {
        if (!count) return;
        const auto address = reinterpret_cast<std::uintptr_t>(pointer);
        if (!pointer || address % alignment) throw std::invalid_argument("result buffer requires valid aligned storage");
        if (count > std::numeric_limits<std::size_t>::max() / width)
            throw std::invalid_argument("result buffer extent overflows size_t");
        const auto length = count * width;
        if (length - 1 > std::numeric_limits<std::uintptr_t>::max() - address)
            throw std::invalid_argument("result buffer address range overflows");
        spans.push_back({address, address + length - 1});
    }
    bool disjoint(const void* pointer, std::size_t bytes) const {
        if (!pointer || !bytes) return false;
        const auto first = reinterpret_cast<std::uintptr_t>(pointer);
        if (bytes - 1 > std::numeric_limits<std::uintptr_t>::max() - first) return false;
        const auto last = first + bytes - 1;
        return std::none_of(spans.begin(), spans.end(), [&](const auto& input){return first <= input.last && input.first <= last;});
    }
    Recorded<std::string> string(const char* value) {
        if (!value) return {};
        if (const auto* failure = error(value)) {sequence(value, 1); return Recorded<std::string>(*failure);}
        sequence(value, std::strlen(value) + 1);
        return std::string(value);
    }
    std::string text(const char* value, const char* name) {
        const auto result = string(value);
        if (!result) throw std::invalid_argument(std::string("stage record requires ") + name);
        return *result;
    }
    template<class T> Recorded<T> optional(const T* value) {
        if (!value) return {};
        sequence(value, 1);
        if (const auto* failure = error(value)) return Recorded<T>(*failure);
        return *value;
    }
    Recorded<Number> number(const RawScalar* value) {
        if (!value) return {};
        sequence(value, 1);
        if (const auto* failure = error(value)) return Recorded<Number>(*failure);
        return read_scalar(*value);
    }
    Recorded<Tensor> scalar_array(const RawScalar* value) {
        if (value) sequence(value, 1);
        if (const auto* failure = error(value)) return Recorded<Tensor>(*failure);
        const auto scalar = number(value);
        return scalar ? Recorded<Tensor>(Tensor(*scalar)) : Recorded<Tensor>{};
    }
    Tensor array(const RawArray& value) {
        add(value.data, value.bytes, 1, 1);
        if (const auto* failure = error(&value)) {
            sequence(value.shape, value.rank); sequence(value.strides, value.rank);
            Tensor deferred({}, TPMSHX_RESULT_F64);
            if (value.rank) deferred.shape.assign(value.shape, value.shape + value.rank);
            deferred.dtype = 0;
            deferred.input_error = *failure;
            return deferred;
        }
        sequence(value.shape, value.rank); sequence(value.strides, value.rank);
        return arithmetic::copy(Array(value));
    }
    Recorded<Tensor> array(const RawArray* value) {
        if (!value) return {};
        sequence(value, 1); return array(*value);
    }
    Recorded<QuickValue> quick_value(const tpmshx_stage_quick_value_v3* value) {
        if (!value) return {};
        sequence(value, 1);
        auto numeric = array(value->numeric);
        if (const auto* failure = error(value)) return Recorded<QuickValue>(*failure);
        if (numeric.has_value() == (value->object != 0))
            throw std::invalid_argument("Quick value requires one numeric view or object token");
        return numeric ? QuickValue(*numeric) : QuickValue(value->object);
    }
    Recorded<StageLabel> label(const tpmshx_stage_label_v3* value) {
        if (!value) return {};
        sequence(value, 1);
        const auto text = string(value->text);
        const auto object = quick_value(value->value);
        if (const auto* failure = error(value)) return Recorded<StageLabel>(*failure);
        if (text.has_value() == object.has_value())
            throw std::invalid_argument("stage label requires text or one host value");
        StageLabel result;
        if (text) result.text = *text;
        else result.value = *object;
        return result;
    }
    std::vector<Tensor> arrays(const RawArray* values, std::size_t count) {
        if (const auto* failure = count ? nullptr : error(values)) {
            Tensor deferred({}, TPMSHX_RESULT_F64);
            deferred.input_error = *failure;
            return {std::move(deferred)};
        }
        sequence(values, count);
        std::vector<Tensor> out;
        for (std::size_t i = 0; i < count; ++i) out.push_back(array(values[i]));
        return out;
    }
    Arrays named(const tpmshx_stage_named_array_v1* values, std::size_t count) {
        Arrays out;
        sequence(values, count);
        if (const auto* failure = error(values)) {out.input_error = *failure; return out;}
        for (std::size_t i = 0; i < count; ++i) {
            const auto name = text(values[i].name, "an array name");
            if (!out.emplace(name, array(values[i].value)).second) throw std::invalid_argument("duplicate stage array name");
        }
        return out;
    }
    std::vector<std::string> strings(const char* const* values, std::size_t count) {
        sequence(values, count); std::vector<std::string> out;
        for (std::size_t i = 0; i < count; ++i) out.push_back(text(values[i], "a string"));
        return out;
    }
};
Truth truth(int value) {
    if ((value < -3 && value != -5) || value > 1) throw std::invalid_argument("invalid stage truth declaration");
    return value == -1 ? Truth{} : Truth(value == 1 || value == -2);
}
TruthEvidence declared_truth(int value) {
    TruthEvidence out;
    out.value = truth(value); out.is_bool = value == 0 || value == 1;
    out.equals_false = value == 0 || value == -3;
    if (out.is_bool) out.recorded = Report(*out.value);
    return out;
}
TruthEvidence gate_evidence(Inputs& input, const tpmshx_stage_gate_v1& gate) {
    auto out = declared_truth(gate.value);
    if (const auto* failure = input.error(&gate.value)) out.equals_false = Recorded<bool>(*failure);
    if (input.host_input && !gate.recorded_number && !gate.recorded_text) return out;
    const auto number = input.number(gate.recorded_number);
    const auto text = input.string(gate.recorded_text);
    if (out.is_bool || !out.value) {
        if (number || text) throw std::invalid_argument("boolean or unknown gate has a redundant recorded value");
        return out;
    }
    if (number.has_value() == text.has_value())
        throw std::invalid_argument("non-boolean gate requires its recorded numeric scalar or text");
    int expected;
    if (number) {
        if (complex_type(number->dtype) || number->dtype == TPMSHX_RESULT_BOOL)
            throw std::invalid_argument("non-boolean gate requires an original real numeric scalar");
        expected = zero(*number) ? -3 : -2;
        if (integer_type(number->dtype))
            out.recorded = signed_type(number->dtype) ? Report(number->signed_value) : Report(number->unsigned_value);
        else out.recorded = Report(arithmetic::to_float(*number));
    } else {
        expected = text->empty() ? -5 : -2;
        out.recorded = Report(*text);
    }
    if (gate.value != expected) throw std::invalid_argument("gate truth declaration disagrees with its recorded value");
    return out;
}
bool boolean(int value) {
    const auto converted = truth(value);
    if (value < 0) throw std::invalid_argument("stage flag requires an explicit boolean");
    return *converted;
}
GridEvidence grid(Inputs& input, const tpmshx_stage_grid_v1& value) {
    GridEvidence out;
    for (std::size_t i = 0; i < 3; ++i) out.widths[i] = input.array(value.widths[i]);
    return out;
}
Recorded<PressureEvidence> pressure(Inputs& input, const tpmshx_stage_pressure_v1* value) {
    if (!value) return {};
    input.sequence(value, 1);
    if (const auto* failure = input.error(value)) return Recorded<PressureEvidence>(*failure);
    PressureEvidence out;
    out.pressure = input.array(value->pressure); out.grid = grid(input, value->grid);
    out.inlet_fraction = input.array(value->inlet_fraction); out.outlet_fraction = input.array(value->outlet_fraction);
    out.outlet_geom_fraction = input.array(value->outlet_geom_fraction);
    out.reference = input.number(value->reference); out.inlet_absolute = input.number(value->inlet_absolute);
    out.outlet_absolute = input.number(value->outlet_absolute); out.unit = input.string(value->unit);
    return out;
}
Recorded<EnergyEvidence> energy(Inputs& input, const tpmshx_stage_energy_v1* value) {
    if (!value) return {};
    input.sequence(value, 1);
    if (const auto* failure = input.error(value)) return Recorded<EnergyEvidence>(*failure);
    EnergyEvidence out;
    out.definition = input.string(value->definition); out.power_units = input.string(value->power_units);
    out.physical_dimension = value->physical_dimension;
    out.physical_boundary_complete = truth(value->physical_boundary_complete);
    out.physical_boundary_complete_is_bool = value->physical_boundary_complete >= -1;
    input.sequence(value->phases, value->phase_count);
    for (std::size_t i = 0; i < value->phase_count; ++i) {
        const auto& raw = value->phases[i]; EnergyPhaseEvidence phase;
        phase.solved = truth(raw.solved); phase.solved_is_bool = raw.solved >= -1; phase.residual = input.array(raw.residual);
        phase.advective_out = input.named(raw.advective_out, raw.advective_count);
        phase.diffusive_out = input.named(raw.diffusive_out, raw.diffusive_count);
        phase.source_integral = input.array(raw.source_integral);
        if (!out.phases.emplace(input.text(raw.name, "a phase name"), std::move(phase)).second)
            throw std::invalid_argument("duplicate stage energy phase");
    }
    out.prescribed_b_power = input.array(value->prescribed_b_power);
    return out;
}
ModelCertificate model(Inputs& input, const tpmshx_stage_model_certificate_v1& value) {
    ModelCertificate out;
    out.passed = truth(value.passed); out.physical_boundary_complete = truth(value.physical_boundary_complete);
    out.passed_is_bool = value.passed >= -1; out.physical_boundary_complete_is_bool = value.physical_boundary_complete >= -1;
    if (const auto* failure = input.error(&value.passed)) {out.passed = Recorded<bool>(*failure); out.passed_is_bool = true;}
    if (const auto* failure = input.error(&value.physical_boundary_complete)) {
        out.physical_boundary_complete = Recorded<bool>(*failure); out.physical_boundary_complete_is_bool = true;
    }
    for (std::size_t i = 0; i < 2; ++i) {
        const auto& side = value.sides[i];
        out.sides[i].physical_boundary_complete = truth(side.physical_boundary_complete);
        out.sides[i].physical_boundary_complete_is_bool = side.physical_boundary_complete >= -1;
        if (const auto* failure = input.error(&side.physical_boundary_complete)) {
            out.sides[i].physical_boundary_complete = Recorded<bool>(*failure);
            out.sides[i].physical_boundary_complete_is_bool = true;
        }
        out.sides[i].staggered_power = input.arrays(side.staggered_power, side.staggered_count);
        out.sides[i].boundary_power = input.named(side.boundary_power, side.boundary_count);
    }
    return out;
}
ThermalEvidence thermal(Inputs& input, const tpmshx_stage_thermal_v1& value) {
    ThermalEvidence out;
    for (std::size_t i = 0; i < 2; ++i) {
        out.mass[i] = input.arrays(value.mass[i], value.mass_count[i]);
        out.mass_recorded[i] = input.host_input ? value.mass[i] != nullptr : !out.mass[i].empty();
        out.mass_none[i] = input.none_values.count(value.mass[i]) != 0;
        out.report_direction[i] = input.optional(value.report_direction[i]);
    }
    out.energy = energy(input, value.energy); out.temperature = energy(input, value.temperature);
    if (value.model_h) {
        input.sequence(value.model_h, 1);
        if (const auto* failure = input.error(value.model_h)) out.model_h = Recorded<ModelCertificate>(*failure);
        else {out.model_h = model(input, *value.model_h);}
    }
    if (value.true_h) input.sequence(value.true_h, 1);
    if (value.true_h && input.error(value.true_h)) out.true_h = Recorded<TrueHEvidence>(*input.error(value.true_h));
    else if (value.true_h) {
        const auto& raw = *value.true_h; TrueHEvidence record;
        record.energy_algorithm = input.string(raw.energy_algorithm);
        record.boundary_power_units = input.string(raw.boundary_power_units);
        record.energy_algorithm_version = input.optional(raw.energy_algorithm_version);
        record.physical_boundary_complete = raw.physical_boundary_complete == -4 ? Truth{} : truth(raw.physical_boundary_complete);
        record.physical_boundary_complete_recorded = raw.physical_boundary_complete != -4;
        record.physical_boundary_complete_is_bool = raw.physical_boundary_complete >= -1;
        record.energy_algorithm_version_is_int = !raw.invalid_version_type;
        for (std::size_t i = 0; i < 2; ++i) {
            record.enthalpy[i] = input.array(raw.enthalpy[i]); record.inlet_enthalpy[i] = input.number(raw.inlet_enthalpy[i]);
            record.mass[i] = input.arrays(raw.mass[i], raw.mass_count[i]);
            record.boundary_power[i] = input.named(raw.boundary_power[i], raw.boundary_count[i]);
        }
        out.true_h = std::move(record);
    }
    return out;
}
std::vector<RangeSample> ranges(Inputs& input, const tpmshx_stage_range_sample_v1* values, std::size_t count) {
    input.sequence(values, count); std::vector<RangeSample> out;
    for (std::size_t i = 0; i < count; ++i) {
        const auto& raw = values[i]; RangeSample sample;
        sample.captured = truth(raw.captured).value_or(false); sample.captured_is_bool = raw.captured >= 0;
        sample.side = input.text(raw.side, "a range side"); sample.quantity = input.text(raw.quantity, "a range quantity");
        sample.source = input.strings(raw.source, raw.source_count);
        sample.constraint = input.string(raw.constraint).value_or("parameter");
        sample.bounds = {raw.bounds[0], raw.bounds[1]};
        input.sequence(raw.shape, raw.rank);
        if (raw.rank) sample.shape.assign(raw.shape, raw.shape + raw.rank);
        sample.size = raw.size; sample.low = raw.low; sample.high = raw.high; sample.nonfinite = raw.nonfinite;
        sample.minimum = input.optional(raw.minimum); sample.maximum = input.optional(raw.maximum);
        for (const auto& provenance : std::array<std::pair<const char*, const char*>, 5>{{
            {"stage", raw.stage}, {"layout", raw.layout}, {"unit", raw.unit}, {"reason", raw.reason}, {"constraint", raw.constraint}}}) {
            const auto text = input.string(provenance.second);
            if (text) sample.captured_record.emplace(provenance.first, *text);
        }
        for (const auto& extreme : std::array<std::pair<const char*, bool>, 2>{{{"minimum", false}, {"maximum", true}}}) {
            const auto number = extreme.second ? sample.maximum : sample.minimum;
            Report value;
            if (number) {
                const auto indices = extreme.second ? raw.maximum_index : raw.minimum_index;
                input.sequence(indices, raw.rank); Report::List index;
                for (std::size_t axis = 0; axis < raw.rank; ++axis) index.emplace_back(static_cast<std::int64_t>(indices[axis]));
                value = Report::List{*number, std::move(index)};
            }
            if (sample.captured) sample.captured_record.emplace(extreme.first, std::move(value));
        }
        out.push_back(std::move(sample));
    }
    return out;
}
Recorded<ApplicabilityEvidence> applicability(Inputs& input, const tpmshx_stage_applicability_v1* value) {
    if (!value) return {};
    input.sequence(value, 1);
    if (const auto* failure = input.error(value)) return Recorded<ApplicabilityEvidence>(*failure);
    ApplicabilityEvidence out;
    out.version = input.text(value->version, "an applicability version");
    out.inlet_recorded = truth(value->inlet_recorded).value_or(false);
    out.groups.emplace("inlet", ranges(input, value->inlet, value->inlet_count));
    out.groups.emplace("final", ranges(input, value->final_state, value->final_count));
    input.sequence(value->required, value->required_count);
    for (std::size_t i = 0; i < value->required_count; ++i) {
        const auto& raw = value->required[i];
        out.required.push_back({input.text(raw.group, "a required range group"), input.text(raw.side, "a required range side"), input.strings(raw.source, raw.source_count)});
    }
    for (const auto& note : input.strings(value->scope_notes, value->scope_note_count)) out.scope_notes.emplace_back(note);
    return out;
}
ResultEvidence evidence(Inputs& input, const tpmshx_result_evidence_v1* value) {
    input.sequence(value, 1);
    if (value->abi_version != TPMSHX_RESULT_STAGE_ABI_VERSION || value->struct_size != sizeof(*value))
        throw std::invalid_argument("unsupported result stage evidence ABI");
    ResultEvidence out;
    out.result_id = input.text(value->result_id, "a result ID"); out.dimension = value->dimension;
    if (const auto* failure = input.error(&value->dimension)) out.declaration_error = *failure;
    out.metadata_dimension = input.optional(value->metadata_dimension);
    out.quantity_basis = input.string(value->quantity_basis); out.mass_unit = input.string(value->mass_unit);
    out.mode = input.string(value->mode).value_or("full");
    out.thermal_mode = input.string(value->thermal_mode); out.temperature_transport = input.string(value->temperature_transport);
    out.grid = grid(input, value->grid); out.fields = input.named(value->fields, value->field_count);
    for (std::size_t i = 0; i < value->field_count; ++i) out.field_order.push_back(value->fields[i].name);
    input.sequence(value->field_metadata, value->field_metadata_count);
    for (std::size_t i = 0; i < value->field_metadata_count; ++i) {
        const auto& row = value->field_metadata[i];
        if (!out.field_metadata.emplace(input.text(row.name, "a field name"), FieldDeclaration{input.text(row.unit, "a field unit"), input.string(row.state)}).second)
            throw std::invalid_argument("duplicate stage field declaration");
    }
    for (std::size_t i = 0; i < 2; ++i) out.pressure[i] = pressure(input, value->pressure[i]);
    out.thermal = thermal(input, value->thermal);
    if (value->fine) input.sequence(value->fine, 1);
    if (value->fine && input.error(value->fine)) out.fine = Recorded<FineEvidence>(*input.error(value->fine));
    else if (value->fine) {
        FineEvidence fine; fine.empty_record = boolean(value->fine->empty_record);
        fine.grid = grid(input, value->fine->grid); fine.fields = input.named(value->fine->fields, value->fine->field_count);
        fine.thermal = thermal(input, value->fine->thermal); fine.epsilon = input.array(value->fine->epsilon);
        for (std::size_t i = 0; i < 2; ++i) {
            fine.rho_cp[i] = input.array(value->fine->rho_cp[i]); fine.inlet_fraction[i] = input.array(value->fine->inlet_fraction[i]);
            fine.outlet_fraction[i] = input.array(value->fine->outlet_fraction[i]);
        }
        out.fine = std::move(fine);
    }
    out.thermal_state = input.string(value->thermal_state); out.execution = input.string(value->execution);
    out.converged = declared_truth(value->converged);
    if (const auto* failure = input.error(&value->converged)) out.converged.equals_false = Recorded<bool>(*failure);
    out.outer_index = input.optional(value->outer_index);
    input.sequence(value->convergence_gates, value->convergence_gate_count);
    for (std::size_t i = 0; i < value->convergence_gate_count; ++i) {
        const auto& gate = value->convergence_gates[i];
        if (!out.convergence_gates.emplace(input.text(gate.name, "a convergence gate name"), gate_evidence(input, gate)).second)
            throw std::invalid_argument("duplicate stage convergence gate");
    }
    if (value->true_h_certificate) input.sequence(value->true_h_certificate, 1);
    if (value->true_h_certificate && input.error(value->true_h_certificate))
        out.true_h_certificate = Recorded<TrueHCertificate>(*input.error(value->true_h_certificate));
    else if (value->true_h_certificate) {
        TrueHCertificate cert;
        cert.converged = declared_truth(value->true_h_certificate->converged);
        if (const auto* failure = input.error(&value->true_h_certificate->converged))
            cert.converged.identity_access = Recorded<int>(*failure);
        cert.clip_counts = input.array(value->true_h_certificate->clip_counts);
        for (std::size_t i = 0; i < 2; ++i) {
            cert.ratios[i] = input.number(value->true_h_certificate->ratios[i]);
            cert.tolerances[i] = input.number(value->true_h_certificate->tolerances[i]);
        }
        out.true_h_certificate = std::move(cert);
    }
    input.sequence(value->model_certificates, value->model_certificate_count);
    for (std::size_t i = 0; i < value->model_certificate_count; ++i) {
        const auto& row = value->model_certificates[i];
        out.model_certificate_order.push_back(input.text(row.level, "a model certificate level"));
        if (!out.model_certificates.emplace(input.text(row.level, "a model certificate level"), model(input, row.value)).second)
            throw std::invalid_argument("duplicate stage model certificate");
    }
    for (std::size_t i = 0; i < 4; ++i) out.strict_ratios[i] = input.optional(value->strict_ratios[i]);
    for (std::size_t i = 0; i < 2; ++i) out.source_power[i] = input.optional(value->source_power[i]);
    if (const auto* failure = input.error(&value->model_active_b)) out.model_active_b = Recorded<bool>(*failure);
    else out.model_active_b = truth(value->model_active_b);
    out.richardson_extrapolated = truth(value->richardson_extrapolated);
    out.execution_version = input.string(value->execution_version);
    if (const auto* failure = input.error(&value->executed_side_count))
        out.execution_sides_access_error = Recorded<int>(*failure);
    input.sequence(value->executed_sides, value->executed_side_count);
    if (const auto* failure = input.error(value->executed_sides)) {
        input.sequence(value->executed_sides, 1);
        out.execution_sides_error = Recorded<int>(*failure);
    }
    for (std::size_t i = 0; i < value->executed_side_count; ++i) {
        const auto& row = value->executed_sides[i];
        auto solved = declared_truth(row.solved);
        if (const auto* failure = input.error(&row.solved)) solved.value = Recorded<bool>(*failure);
        if (!out.executed_sides.emplace(input.text(row.side, "an executed side"), ExecutionSide{input.string(row.fluid), std::move(solved)}).second)
            throw std::invalid_argument("duplicate stage executed side");
    }
    out.applicability = applicability(input, value->applicability);
    for (std::size_t i = 0; i < 2; ++i) {
        out.active_fluids[i] = boolean(value->active_fluids[i]); out.direction[i] = input.optional(value->direction[i]);
        out.inlet_temperature[i] = input.scalar_array(value->inlet_temperature[i]);
        out.inlet_geom_fraction[i] = input.array(value->inlet_geom_fraction[i]);
        out.outlet_geom_fraction[i] = input.array(value->outlet_geom_fraction[i]); out.rho_cp[i] = input.array(value->rho_cp[i]);
        const auto& raw = value->quick[i]; auto& side = out.quick[i];
        side.inlet_temperature = input.number(raw.inlet_temperature); side.mass_flow = input.number(raw.mass_flow);
        side.cp = input.number(raw.cp); side.rho = input.number(raw.rho); side.velocity = input.number(raw.velocity);
        side.viscosity = input.number(raw.viscosity);
    }
    out.parameter_epsilon = input.array(value->parameter_epsilon); out.design_epsilon = input.array(value->design_epsilon);
    out.split_a = input.scalar_array(value->split_a); out.solid_density = input.scalar_array(value->solid_density);
    out.quick_model = input.string(value->quick_model); out.arrangement = input.string(value->arrangement);
    out.hydraulic_diameter = input.number(value->hydraulic_diameter);
    out.absent_records = input.strings(value->absent_records, value->absent_record_count);
    out.model_certificate_error = input.string(value->model_certificate_error);
    out.model_certificates_recorded = input.host_input && std::find(out.absent_records.begin(), out.absent_records.end(),
        "metadata.diagnostics.model_h_balance") == out.absent_records.end();
    return out;
}
MetricSpec spec(Inputs& input, const tpmshx_stage_metric_spec_v1& value) {
    return {input.text(value.name, "a metric name"), input.text(value.unit, "a metric unit"),
        input.text(value.definition_version, "a metric definition version"), input.string(value.description).value_or("")};
}
void copy_quick(Inputs& input, const tpmshx_stage_input_v3& value, ResultEvidence& evidence) {
    evidence.execution_label = input.label(value.execution_version);
    if (!value.model) return;
    QuickTypedEvidence quick;
    quick.model = input.label(value.model);
    quick.arrangement = input.label(value.arrangement);
    quick.hydraulic_diameter = input.quick_value(value.hydraulic_diameter);
    for (std::size_t i = 0; i < 2; ++i) {
        const auto& from = value.sides[i]; auto& to = quick.sides[i];
        to.boundary_access = input.optional(from.boundary_access);
        to.properties_access = input.optional(from.properties_access);
        to.pressure_access = input.optional(from.pressure_access);
        to.inlet_temperature = input.quick_value(from.inlet_temperature);
        to.mass_flow = input.quick_value(from.mass_flow); to.cp = input.quick_value(from.cp);
        to.rho = input.quick_value(from.rho); to.velocity = input.quick_value(from.velocity);
        to.viscosity = input.quick_value(from.viscosity);
        to.inlet_pressure = input.quick_value(from.inlet_pressure);
        to.outlet_pressure = input.quick_value(from.outlet_pressure);
    }
    evidence.quick_typed = std::move(quick);
}
struct QuickView {
    RawArray numeric{};
    tpmshx_stage_quick_value_v3 value{};
    explicit QuickView(const QuickValue& source) {
        if (source.object) value.object = source.object;
        else {numeric = source.numeric.raw(); value.numeric = &numeric;}
    }
};
void callback_error(int status, const tpmshx_stage_host_error_v2& failure) {
    if (!status) return;
    if (!failure.cause || failure.cause > host_exception || !failure.message)
        throw std::runtime_error("invalid result host callback error");
    HostError error(failure.cause, failure.message, failure.token);
    error.error_number = failure.error_number;
    throw error;
}
QuickValue callback_value(Inputs& input, const tpmshx_stage_quick_value_v3& value) {
    const bool complete = input.copied_inputs;
    input.copied_inputs = false;
    auto copied = *input.quick_value(&value);
    input.copied_inputs = complete;
    return copied;
}
void quick_callback_error(Inputs& input, int status, const tpmshx_stage_host_error_v2& failure) {
    if (status && failure.message) (void)input.string(failure.message);
    callback_error(status, failure);
}
QuickHost quick_host(Inputs& input, const tpmshx_stage_quick_protocol_v3& protocol) {
    QuickHost host;
    const auto context = protocol.context;
    if (protocol.text_equal) host.text_equal = [&, context, call=protocol.text_equal](const QuickValue& value, const std::string& expected) {
        const QuickView argument(value); int output{}; tpmshx_stage_host_error_v2 failure{};
        quick_callback_error(input, call(context, &argument.value, expected.c_str(), &output, &failure), failure);
        return boolean(output);
    };
    if (protocol.text_not_equal) host.text_not_equal = [&, context, call=protocol.text_not_equal](const QuickValue& value, const std::string& expected) {
        const QuickView argument(value); int output{}; tpmshx_stage_host_error_v2 failure{};
        quick_callback_error(input, call(context, &argument.value, expected.c_str(), &output, &failure), failure);
        return boolean(output);
    };
    if (protocol.temperature_difference) host.temperature_difference = [&, context, call=protocol.temperature_difference](const QuickValue& inlet, double outlet) {
        const QuickView first(inlet); tpmshx_stage_quick_value_v3 value{}; tpmshx_stage_host_error_v2 failure{};
        quick_callback_error(input, call(context, &first.value, outlet, &value, &failure), failure);
        return callback_value(input, value);
    };
    const auto pair = [&, context](auto call) -> std::function<QuickValue(const QuickValue&, const QuickValue&)> {
        if (!call) return {};
        return [&, context, call](const QuickValue& left, const QuickValue& right) {
            const QuickView first(left), second(right);
            tpmshx_stage_quick_value_v3 value{}; tpmshx_stage_host_error_v2 failure{};
            quick_callback_error(input, call(context, &first.value, &second.value, &value, &failure), failure);
            return callback_value(input, value);
        };
    };
    host.capacity_product = pair(protocol.capacity_product);
    host.pressure_difference = pair(protocol.pressure_difference);
    host.reynolds_flow = pair(protocol.reynolds_flow);
    host.reynolds_length = pair(protocol.reynolds_length);
    host.reynolds_quotient = pair(protocol.reynolds_quotient);
    if (protocol.duty_product) host.duty_product = [&, context, call=protocol.duty_product](const QuickValue& capacity, const QuickValue& delta, bool cold) {
        const QuickView first(capacity), second(delta);
        tpmshx_stage_quick_value_v3 value{}; tpmshx_stage_host_error_v2 failure{};
        quick_callback_error(input, call(context, &first.value, &second.value, cold ? 1 : 0, &value, &failure), failure);
        return callback_value(input, value);
    };
    if (protocol.metric_float) host.metric_float = [&, context, call=protocol.metric_float](const QuickValue& source) {
        const QuickView argument(source); double value{}; tpmshx_stage_host_error_v2 failure{};
        quick_callback_error(input, call(context, &argument.value, &value, &failure), failure);
        return value;
    };
    if (protocol.empty_mean) host.empty_mean = [&, context, call=protocol.empty_mean]() {
        tpmshx_stage_host_error_v2 failure{};
        quick_callback_error(input, call(context, &failure), failure);
    };
    return host;
}

struct Output {
    Evaluation evaluation;
    std::string json_text;
    std::vector<tpmshx_stage_metric_value_v1> metrics;
    void bind_metrics(bool ordered = false) {
        auto names = evaluation.metric_order;
        if (!ordered || names.empty()) {
            names.clear();
            for (const auto& row : evaluation.metrics) names.push_back(row.first);
        }
        for (const auto& name : names) {
            const auto& row = *evaluation.metrics.find(name);
            const auto& v = row.second;
            metrics.push_back({row.first.c_str(), {v.spec.name.c_str(), v.spec.unit.c_str(), v.spec.definition_version.c_str(), v.spec.description.c_str()},
                v.value ? 1 : 0, v.value.value_or(0.0), v.status.c_str(), v.reason.c_str()});
        }
    }
};

template<class Run> int boundary(const tpmshx_result_evidence_v1* value, tpmshx_stage_output_v1* output,
                                 char* error, std::size_t capacity, Run run,
                                 const tpmshx_stage_input_v2* extension = nullptr,
                                 Diagnostics* diagnostics = nullptr, std::uint64_t* error_token = nullptr,
                                 const tpmshx_stage_input_v3* quick_extension = nullptr) noexcept {
    FloatingEnvironment environment;
    Inputs input;
    int status = TPMSHX_RESULT_OK;
    Diagnostics failure_diagnostics{};
    std::uint64_t failure_token{};
    const char* message = "";
    std::string saved_message;
    const auto save_message = [&](const char* value, const char* fallback) noexcept {
        try {saved_message = value; message = saved_message.c_str();}
        catch (...) {message = fallback;}
    };
    bool output_valid = false, copy_started = false;
    try {
        if (!error || !capacity) throw std::invalid_argument("result calls require nonempty error storage");
        Inputs writable;
        writable.sequence(output, 1); writable.sequence(error, capacity);
        if (reinterpret_cast<std::uintptr_t>(output) <= reinterpret_cast<std::uintptr_t>(error) + capacity - 1 &&
            reinterpret_cast<std::uintptr_t>(error) <= reinterpret_cast<std::uintptr_t>(output) + sizeof(*output) - 1)
            throw std::invalid_argument("result writable storage overlaps another buffer");
        if (quick_extension) {
            input.sequence(quick_extension, 1);
            if (quick_extension->abi_version != 3 || quick_extension->struct_size != sizeof(*quick_extension))
                throw std::invalid_argument("unsupported Quick result host ABI");
            extension = quick_extension->host;
            if (!extension) throw std::invalid_argument("Quick result host requires its v2 input");
        }
        if (extension) {
            input.host_input = true;
            writable.sequence(diagnostics, 1); writable.sequence(error_token, 1);
            for (const auto& a : writable.spans) for (const auto& b : writable.spans)
                if (&a != &b && a.first <= b.last && b.first <= a.last)
                    throw std::invalid_argument("result writable storage overlaps another buffer");
            input.sequence(extension, 1);
            if (extension->abi_version != 2 || extension->struct_size != sizeof(*extension))
                throw std::invalid_argument("unsupported result host ABI");
            input.sequence(extension->errors, extension->error_count);
            for (std::size_t i = 0; i < extension->error_count; ++i) {
                const auto& fault = extension->errors[i];
                if (!fault.value || !fault.cause || fault.cause > host_exception)
                    throw std::invalid_argument("invalid deferred result input error");
                const auto fault_message = input.text(fault.message, "a deferred error message");
                if (!input.errors.emplace(fault.value, InputError{fault.cause, fault_message, fault.token}).second)
                    throw std::invalid_argument("duplicate deferred result input error");
            }
            input.sequence(extension->none_values, extension->none_count);
            for (std::size_t i = 0; i < extension->none_count; ++i) {
                if (!extension->none_values[i] || !input.none_values.insert(extension->none_values[i]).second)
                    throw std::invalid_argument("invalid explicit None storage");
            }
            value = extension->evidence;
        }
        output_valid = true;
        if (output->struct_size != sizeof(*output)) throw std::invalid_argument("unsupported result stage output size");
        if (output->owner) throw std::invalid_argument("release the previous result stage output before reuse");
        input.sequence(value, 1);
        if (value->abi_version != TPMSHX_RESULT_STAGE_ABI_VERSION || value->struct_size != sizeof(*value))
            throw std::invalid_argument("unsupported result stage evidence ABI");
        copy_started = true;
        auto copied = evidence(input, value);
        if (extension) {
            copied.invalid_mode_repr = input.string(extension->invalid_mode_repr);
            copied.physical_dimension_index = input.optional(extension->physical_dimension_index);
            copied.physical_dimension_slice = input.optional(extension->physical_dimension_slice);
            copied.qualification_error = input.optional(extension->qualification_error);
            copied.solid_density = input.array(extension->solid_density);
            copied.split_a = input.array(extension->split_a);
            for (std::size_t i = 0; i < 2; ++i) {
                copied.inlet_temperature[i] = input.array(extension->inlet_temperature[i]);
                copied.inlet_temperature_none[i] = input.none_values.count(extension->inlet_temperature[i]) != 0;
            }
        }
        if (quick_extension) copy_quick(input, *quick_extension, copied);
        input.copied_inputs = true;
        auto owned = std::make_unique<Output>();
        run(input, copied, *owned);
        if (!input.copied_inputs) throw std::invalid_argument("incomplete Quick callback storage");
        if (!input.disjoint(output, sizeof(*output)) || !input.disjoint(error, capacity))
            throw std::invalid_argument("result writable storage overlaps another buffer");
        if (extension && (!input.disjoint(diagnostics, sizeof(*diagnostics)) ||
                          !input.disjoint(error_token, sizeof(*error_token))))
            throw std::invalid_argument("result writable storage overlaps another buffer");
        owned->bind_metrics(extension != nullptr);
        tpmshx_stage_output_v1 published{sizeof(*output), owned.get(), owned->json_text.c_str(),
            owned->metrics.data(), owned->metrics.size(), owned->evaluation.diagnostics};
        *output = published;
        owned.release();
    } catch (const NumericError& failure) {
        status = TPMSHX_RESULT_NUMERIC;
        failure_diagnostics.python_cause = failure.cause;
        failure_diagnostics.error_number = failure.error_number;
        if (const auto* host_error = dynamic_cast<const HostError*>(&failure)) failure_token = host_error->token;
        save_message(failure.what(), "native result numerical failure");
    }
    catch (const std::invalid_argument& failure) {status = TPMSHX_RESULT_INVALID; save_message(failure.what(), "invalid native result input");}
    catch (const std::bad_alloc&) {status = TPMSHX_RESULT_ALLOCATION; message = "native result allocation failed";}
    catch (const std::exception& failure) {status = TPMSHX_RESULT_RUNTIME; save_message(failure.what(), "native result runtime failure");}
    catch (...) {status = TPMSHX_RESULT_RUNTIME; message = "unknown native result failure";}
    // An interrupted copy can leave unvisited borrowed spans. Do not write there.
    if ((!copy_started || input.copied_inputs) && error && capacity && input.disjoint(error, capacity) && output_valid &&
        !(reinterpret_cast<std::uintptr_t>(output) <= reinterpret_cast<std::uintptr_t>(error) + capacity - 1 &&
          reinterpret_cast<std::uintptr_t>(error) <= reinterpret_cast<std::uintptr_t>(output) + sizeof(*output) - 1))
        std::snprintf(error, capacity, "%s", message);
    if (extension && input.copied_inputs && diagnostics && error_token &&
        input.disjoint(diagnostics, sizeof(*diagnostics)) && input.disjoint(error_token, sizeof(*error_token))) {
        *diagnostics = failure_diagnostics;
        *error_token = failure_token;
    }
    return status;
}
int query_stage(const tpmshx_stage_input_v2* input, const tpmshx_stage_input_v3* quick,
    uint32_t query, const tpmshx_stage_metric_spec_v1* requested,
    const tpmshx_stage_metric_value_v1* metrics, size_t count,
    tpmshx_stage_output_v1* output, Diagnostics* diagnostics, uint64_t* error_token,
    char* error, size_t capacity) {
    return boundary(nullptr, output, error, capacity, [&](Inputs& packed, const ResultEvidence& copied, Output& owned) {
        const auto* base = quick ? quick->host : input;
        HostControl host;
        host.events = [base](const Diagnostics& events) {
            if (!base->events) return;
            tpmshx_stage_host_error_v2 failure{};
            callback_error(base->events(base->context, &events, &failure), failure);
        };
        if (quick) host.quick = quick_host(packed, quick->protocol);
        if (query == 0) {
            std::optional<MetricSpec> selection;
            if (requested) {packed.sequence(requested, 1); selection = spec(packed, *requested);}
            owned.evaluation = evaluate(copied, selection, &host);
            owned.json_text = json(report(owned.evaluation));
        } else if (query == 1) {
            owned.json_text = json(report(evaluate_applicability(copied, &host)));
        } else if (query == 2) {
            owned.json_text = json(report(evaluate_physical_balance(copied, &host)));
        } else if (query == 3) {
            packed.sequence(metrics, count);
            std::map<std::string, MetricValue> values;
            for (std::size_t i = 0; i < count; ++i) {
                const auto& raw = metrics[i];
                MetricValue metric{boolean(raw.has_value) ? std::optional<double>(raw.value) : std::nullopt,
                    spec(packed, raw.spec), packed.text(raw.status, "a metric status"), packed.string(raw.reason).value_or("")};
                if (!values.emplace(packed.text(raw.name, "a metric key"), std::move(metric)).second)
                    throw std::invalid_argument("duplicate stage metric key");
            }
            owned.json_text = json(report(evaluate_qualification(copied, values, &host)));
        } else throw std::invalid_argument("unsupported result stage query");
    }, input, diagnostics, error_token, quick);
}
}  // namespace

extern "C" {
int TPMSHX_RESULT_CALL tpmshx_result_stage_evaluate_v1(const tpmshx_result_evidence_v1* value,
    const tpmshx_stage_metric_spec_v1* requested, tpmshx_stage_output_v1* output, char* error, size_t capacity) {
    return boundary(value, output, error, capacity, [&](Inputs& input, const ResultEvidence& copied, Output& owned) {
        std::optional<MetricSpec> selection;
        if (requested) {input.sequence(requested, 1); selection = spec(input, *requested);}
        owned.evaluation = evaluate(copied, selection);
        owned.json_text = json(report(owned.evaluation));
    });
}
int TPMSHX_RESULT_CALL tpmshx_result_stage_applicability_v1(const tpmshx_result_evidence_v1* value,
    tpmshx_stage_output_v1* output, char* error, size_t capacity) {
    return boundary(value, output, error, capacity, [](Inputs&, const ResultEvidence& copied, Output& owned) {
        owned.json_text = json(report(evaluate_applicability(copied)));
    });
}
int TPMSHX_RESULT_CALL tpmshx_result_stage_physical_balance_v1(const tpmshx_result_evidence_v1* value,
    tpmshx_stage_output_v1* output, char* error, size_t capacity) {
    return boundary(value, output, error, capacity, [](Inputs&, const ResultEvidence& copied, Output& owned) {
        owned.json_text = json(report(evaluate_physical_balance(copied)));
    });
}
int TPMSHX_RESULT_CALL tpmshx_result_stage_qualification_v1(const tpmshx_result_evidence_v1* value,
    const tpmshx_stage_metric_value_v1* metrics, size_t count, tpmshx_stage_output_v1* output, char* error, size_t capacity) {
    return boundary(value, output, error, capacity, [&](Inputs& input, const ResultEvidence& copied, Output& owned) {
        input.sequence(metrics, count); std::map<std::string, MetricValue> values;
        for (std::size_t i = 0; i < count; ++i) {
            const auto& raw = metrics[i];
            const auto present = boolean(raw.has_value);
            MetricValue metric{present ? std::optional<double>(raw.value) : std::nullopt, spec(input, raw.spec),
                input.text(raw.status, "a metric status"), input.string(raw.reason).value_or("")};
            if (!values.emplace(input.text(raw.name, "a metric key"), std::move(metric)).second)
                throw std::invalid_argument("duplicate stage metric key");
        }
        owned.json_text = json(report(evaluate_qualification(copied, values)));
    });
}
int TPMSHX_RESULT_CALL tpmshx_result_stage_query_v2(const tpmshx_stage_input_v2* input,
    uint32_t query, const tpmshx_stage_metric_spec_v1* requested,
    const tpmshx_stage_metric_value_v1* metrics, size_t count,
    tpmshx_stage_output_v1* output, Diagnostics* diagnostics, uint64_t* error_token,
    char* error, size_t capacity) {
    return query_stage(input, nullptr, query, requested, metrics, count, output, diagnostics, error_token, error, capacity);
}
int TPMSHX_RESULT_CALL tpmshx_result_stage_query_v3(const tpmshx_stage_input_v3* input,
    uint32_t query, const tpmshx_stage_metric_spec_v1* requested,
    const tpmshx_stage_metric_value_v1* metrics, size_t count,
    tpmshx_stage_output_v1* output, Diagnostics* diagnostics, uint64_t* error_token,
    char* error, size_t capacity) {
    return query_stage(nullptr, input, query, requested, metrics, count, output, diagnostics, error_token, error, capacity);
}
void TPMSHX_RESULT_CALL tpmshx_result_stage_release_v1(tpmshx_stage_output_v1* value) {
    if (!value || value->struct_size != sizeof(*value)) return;
    delete static_cast<Output*>(value->owner);
    *value = {}; value->struct_size = sizeof(*value);
}
}
