#include "tpmshx/result_stage.hpp"
#include "tpmshx/result_balance.hpp"
#include "tpmshx/result_checks.hpp"
#include "tpmshx/result_metrics.hpp"

#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <numeric>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace tpmshx::result::stage {
namespace {
using Object = Report::Object;
using List = Report::List;
const std::array<std::string, 6> face_names{{"x-", "x+", "y-", "y+", "z-", "z+"}};
const std::array<std::string, 3> phase_names{{"A", "B", "solid"}};
class Missing : public NumericError {public: explicit Missing(std::string message):NumericError(key_error, std::move(message)) {}};
class Unsupported : public NumericError {public: explicit Unsupported(std::string message):NumericError(not_implemented, std::move(message)) {}};

template<class T> const T& need(const Recorded<T>& value, std::string_view key) {
    if (!value) throw Missing("'" + std::string(key) + "'");
    return *value;
}
template<class T> const T& entry(const std::map<std::string, T>& values, std::string_view key) {
    const auto found = values.find(std::string(key));
    if (found == values.end()) throw Missing("'" + std::string(key) + "'");
    return found->second;
}
const Tensor& entry(const Arrays& values, std::string_view key) {
    values.check();
    return entry(static_cast<const std::map<std::string, Tensor>&>(values), key);
}
void record(const ResultEvidence& result, const std::string& path) {
    if (std::find(result.absent_records.begin(), result.absent_records.end(), path) != result.absent_records.end())
        throw Missing("'" + path.substr(path.rfind('.') + 1) + "'");
}
thread_local const HostControl* active_host{};
class HostScope {
    const HostControl* previous_;
public:
    explicit HostScope(const HostControl* value):previous_(active_host) {active_host = value;}
    ~HostScope() {active_host = previous_;}
};
void deliver(Diagnostics& diagnostics) {
    if (!active_host || !diagnostics.event_count) return;
    const auto saved = diagnostics;
    diagnostics.event_count = 0;
    const auto* host = active_host;
    HostScope suspended(nullptr);
    host->events(saved);
}
template<class Operation> auto host_call(Diagnostics& diagnostics, Operation operation) {
    try {
        auto value = operation();
        deliver(diagnostics);
        return value;
    } catch (...) {
        deliver(diagnostics);
        throw;
    }
}

std::string side_name(std::size_t side) {return side ? "B" : "A";}
Report nullable(const Recorded<std::string>& value) {return value ? Report(*value) : Report();}
Report nullable(const Recorded<int>& value) {return value ? Report(*value) : Report();}
List strings(const std::vector<std::string>& values) {
    List result;
    for (const auto& value : values) result.emplace_back(value);
    return result;
}
List sizes(const std::vector<std::size_t>& values) {
    List result;
    for (const auto value : values) result.emplace_back(static_cast<std::int64_t>(value));
    return result;
}
Truth all_known(const std::vector<Truth>& values) {
    bool unknown = values.empty();
    for (const auto value : values) {
        if (value == false) return false;
        if (!value) unknown = true;
    }
    return unknown ? Truth{} : Truth{true};
}
Verdict verdict(Truth passed, std::string source, Object details = {}) {
    return {passed == true ? "passed" : passed == false ? "failed" : "unverified",
            std::move(source), passed, std::move(details)};
}
Report verdict_report(const Verdict& value) {
    Object out{{"status", value.status}, {"passed", Report(value.passed)}, {"source", value.source}};
    for (const auto& row : value.details) out.emplace(row.first, row.second);
    return out;
}
bool ends_with(const std::string& value, const std::string& suffix) {
    return value.size() >= suffix.size() && value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}
bool starts_with(const std::string& value, const std::string& prefix) {return value.rfind(prefix, 0) == 0;}

void declarations(const ResultEvidence& result) {
    if (result.declaration_error) {
        const auto& error = *result.declaration_error;
        throw HostError(error.cause, error.message, error.token);
    }
    const auto d = result.dimension;
    if (result.metadata_dimension && *result.metadata_dimension != d)
        throw std::invalid_argument("result metadata dimension disagrees with grid");
    if ((d == 2 || d == 3) && result.quantity_basis &&
        *result.quantity_basis != (d == 2 ? "per_unit_depth" : "total"))
        throw std::invalid_argument("result quantity_basis disagrees with physical dimension");
    if ((result.mode == "screening_2d" && d != 2) ||
        ((result.mode == "screening_3d" || result.mode == "quick_design") && d != 3))
        throw std::invalid_argument("result mode dimension disagrees with grid");
    for (std::size_t side = 0; side < 2; ++side)
        if (result.pressure[side] && result.pressure[side]->unit && *result.pressure[side]->unit != "Pa")
            throw std::invalid_argument("pressure evidence " + side_name(side) + " unit must be Pa");
    if (result.mass_unit && d == 2 && *result.mass_unit != "kg/(s m)" && *result.mass_unit != "kg/(m s)")
        throw std::invalid_argument("mass evidence unit must be one of ('kg/(s m)', 'kg/(m s)')");
    if (result.mass_unit && d == 3 && *result.mass_unit != "kg/s")
        throw std::invalid_argument("mass evidence unit must be one of ('kg/s',)");
    for (const auto& item : result.field_metadata) {
        auto name = item.first;
        if (ends_with(name, "_display")) name.resize(name.size() - 8);
        std::vector<std::string> units;
        if (name == "Ta" || name == "Tb" || name == "Ts") units = {"K"};
        else if (starts_with(name, "P_")) units = {"Pa"};
        else if (name == "ucA" || name == "vcA" || name == "wcA" || name == "ucB" || name == "vcB" || name == "wcB") units = {"m/s"};
        else if (starts_with(name, "h_v")) units = {"W/(m3 K)", "W/(m^3 K)"};
        else if (name == "K_ss" || name == "K_ss_arr" || name == "K_ffA_arr" || name == "K_ffB_arr") units = {"W/(m K)"};
        else if (name == "eps_arr") units = {"1"};
        if (!units.empty() && std::find(units.begin(), units.end(), item.second.unit) == units.end()) {
            std::string text = "field " + item.first + " unit must be one of (";
            for (std::size_t i = 0; i < units.size(); ++i) text += (i ? ", " : "") + std::string("'") + units[i] + "'";
            throw std::invalid_argument(text + (units.size() == 1 ? ",)" : ")"));
        }
    }
}

Tensor plane(const Tensor& values, std::size_t axis, std::size_t index) {
    if (axis >= values.shape.size() || index >= values.shape[axis])
        throw std::invalid_argument("boundary plane index is outside the recorded field");
    auto raw = values.raw();
    auto shape = values.shape;
    auto strides = values.strides;
    raw.offset = static_cast<std::size_t>(static_cast<std::ptrdiff_t>(raw.offset) + static_cast<std::ptrdiff_t>(index) * strides[axis]);
    shape.erase(shape.begin() + static_cast<std::ptrdiff_t>(axis));
    strides.erase(strides.begin() + static_cast<std::ptrdiff_t>(axis));
    raw.rank = shape.size(); raw.shape = shape.data(); raw.strides = strides.data();
    return arithmetic::copy(Array(raw));
}
Tensor reverse(const Tensor& values, std::size_t axis) {
    auto raw = values.raw();
    auto strides = values.strides;
    if (axis >= values.shape.size()) throw std::invalid_argument("array axis is outside the recorded field");
    if (values.shape[axis]) raw.offset = static_cast<std::size_t>(static_cast<std::ptrdiff_t>(raw.offset) +
        static_cast<std::ptrdiff_t>(values.shape[axis] - 1) * strides[axis]);
    strides[axis] = -strides[axis]; raw.strides = strides.data();
    return arithmetic::copy(Array(raw));
}
Tensor transpose_2d(const Tensor& values) {
    if (values.shape.size() != 2) throw std::invalid_argument("pressure evidence requires nonempty three-dimensional cells");
    auto raw = values.raw();
    auto shape = values.shape; auto strides = values.strides;
    std::swap(shape[0], shape[1]); std::swap(strides[0], strides[1]);
    raw.shape = shape.data(); raw.strides = strides.data();
    return arithmetic::copy(Array(raw));
}
Tensor singleton(const Tensor& values) {
    auto raw = values.raw();
    auto shape = values.shape; auto strides = values.strides;
    shape.push_back(1); strides.push_back(static_cast<std::ptrdiff_t>(item_size(values.dtype)));
    raw.rank = shape.size(); raw.shape = shape.data(); raw.strides = strides.data();
    return arithmetic::copy(Array(raw));
}
Tensor broadcast(const Tensor& values, const std::vector<std::size_t>& shape) {
    auto raw = values.raw();
    if (values.shape.size() > shape.size()) throw std::invalid_argument("input operand has more dimensions than allowed by the axis remapping");
    std::vector<std::ptrdiff_t> strides(shape.size());
    const auto shift = shape.size() - values.shape.size();
    for (std::size_t i = 0; i < values.shape.size(); ++i) {
        if (values.shape[i] != 1 && values.shape[i] != shape[i + shift])
            throw std::invalid_argument("operands could not be broadcast together");
        strides[i + shift] = values.shape[i] == 1 ? 0 : values.strides[i];
    }
    raw.rank = shape.size(); raw.shape = shape.data(); raw.strides = strides.data();
    return arithmetic::copy(Array(raw));
}
Tensor scalar(double value) {return arithmetic::scalar(arithmetic::python_float(value));}
Tensor full(const std::vector<std::size_t>& shape, double value) {return broadcast(scalar(value), shape);}
std::vector<std::size_t> boundary_shape(const std::vector<Tensor>& faces, int dimension,
                                      const GridEvidence& grid, bool planes = false,
                                      const Recorded<int>& dimension_index = {}) {
    if (faces.size() == 1 && faces[0].input_error) faces[0].raw();
    if (faces.size() != static_cast<std::size_t>(dimension * (planes ? 2 : 1))) {
        if (planes) throw std::invalid_argument("native boundary requires all boundary face planes");
        throw std::invalid_argument(dimension == 3 ? "native boundary requires all three axis face arrays" : "native boundary requires all two axis face arrays");
    }
    for (const auto& face : faces)
        if (face.shape.size() != static_cast<std::size_t>(dimension - static_cast<int>(planes)))
            throw std::invalid_argument("native boundary face rank disagrees with physical dimension");
    std::vector<std::size_t> shape;
    if (planes) {shape.push_back(faces[2].shape[0]); shape.insert(shape.end(), faces[0].shape.begin(), faces[0].shape.end());}
    else {
        shape = faces[0].shape;
        if (!shape[0]) throw std::invalid_argument("native boundary faces do not share a consistent cell shape");
        --shape[0];
    }
    if (dimension_index) (void)*dimension_index;
    for (const auto n : shape) if (!n) throw std::invalid_argument("native boundary faces do not share a consistent cell shape");
    for (int axis = 0; axis < dimension; ++axis) {
        auto expected = shape;
        if (planes) expected.erase(expected.begin() + axis); else ++expected[static_cast<std::size_t>(axis)];
        const auto count = planes ? 2 : 1;
        for (int end = 0; end < count; ++end)
            if (faces[static_cast<std::size_t>(axis * count + end)].shape != expected)
                throw std::invalid_argument("native boundary faces do not share a consistent cell shape");
        if (grid.widths[static_cast<std::size_t>(axis)] &&
            grid.widths[static_cast<std::size_t>(axis)]->shape != std::vector<std::size_t>{shape[static_cast<std::size_t>(axis)]})
            throw std::invalid_argument(std::string("native boundary faces disagree with ") + "xyz"[axis] + " grid");
    }
    return shape;
}
std::vector<Tensor> boundary_planes(const std::vector<Tensor>& faces, int dimension, const GridEvidence& grid) {
    boundary_shape(faces, dimension, grid);
    std::vector<Tensor> out;
    for (int axis = 0; axis < dimension; ++axis) {
        const auto& face = faces[static_cast<std::size_t>(axis)];
        out.push_back(plane(face, static_cast<std::size_t>(axis), 0));
        out.push_back(plane(face, static_cast<std::size_t>(axis), face.shape[static_cast<std::size_t>(axis)] - 1));
    }
    return out;
}
std::vector<Array> arrays(const std::vector<Tensor>& values) {
    std::vector<Array> out;
    for (const auto& value : values) out.push_back(value.array());
    return out;
}
std::vector<Tensor> six_planes(const Arrays& values, const char* message) {
    values.check();
    if (values.size() != 6 || std::any_of(face_names.begin(), face_names.end(), [&](const auto& name){return !values.count(name);}))
        throw std::invalid_argument(message);
    std::vector<Tensor> out;
    for (const auto& name : face_names) out.push_back(values.at(name));
    return out;
}
bool real_finite(const Tensor& values) {
    return values.dtype != 0 && values.dtype != TPMSHX_RESULT_BOOL && !complex_type(values.dtype) && checks::array_checks(values.array()).all_finite;
}
void finite_values(const Tensor& values, const std::string& name) {
    if (!real_finite(values)) throw std::invalid_argument("physical balance requires finite " + name);
}
double plane_duty(const Arrays& powers, int dimension, const GridEvidence& grid, Diagnostics& diag) {
    auto planes = six_planes(powers, "conservative energy requires all six physical boundary faces");
    const auto shape = boundary_shape(planes, 3, grid, true);
    for (int axis = 0; axis < dimension; ++axis)
        if (need(grid.widths[static_cast<std::size_t>(axis)], std::string("d") + "xyz"[axis]).shape != std::vector<std::size_t>{shape[static_cast<std::size_t>(axis)]})
            throw std::invalid_argument(std::string("conservative boundary powers disagree with ") + "xyz"[axis] + " grid");
    if (dimension == 2 && shape[2] != 1) throw std::invalid_argument("2D conservative energy requires singleton-z boundary planes");
    for (const auto& face : planes)
        if (!real_finite(face)) throw std::invalid_argument("conservative boundary powers must be finite real values");
    return host_call(diag, [&] {return metrics::plane_duty(arrays(planes), diag);});
}
double temperature_duty(const EnergyEvidence& ledger, std::size_t side, int dimension,
                        const GridEvidence& grid, Diagnostics& diag) {
    if (need(ledger.definition, "definition") != "model_enthalpy_temperature_v1")
        throw std::invalid_argument("unsupported temperature transport definition");
    if (need(ledger.physical_dimension, "physical_dimension") != dimension)
        throw std::invalid_argument("temperature evidence dimension disagrees with physical grid");
    if (need(ledger.power_units, "power_units") != (dimension == 2 ? "W/m" : "W"))
        throw std::invalid_argument("temperature boundary power units disagree with physical dimension");
    if (!ledger.physical_boundary_complete_is_bool || ledger.physical_boundary_complete != true)
        throw std::invalid_argument("incomplete physical boundary prevents temperature heat duty");
    const auto& phase = entry(ledger.phases, side_name(side));
    if (!phase.solved_is_bool || phase.solved != true) throw Unsupported("prescribed fluid has no solved boundary heat duty");
    return plane_duty(phase.advective_out, dimension, grid, diag);
}
double conservative_duty(const ResultEvidence& result, const TrueHEvidence& ledger, std::size_t side, int dimension,
                         const GridEvidence& grid, Diagnostics& diag) {
    const auto& algorithm = need(ledger.energy_algorithm, "energy_algorithm");
    if (algorithm != "temperature_fou" && algorithm != "temperature_sou")
        throw std::invalid_argument("unsupported conservative energy algorithm");
    const auto version = need(ledger.energy_algorithm_version, "energy_algorithm_version");
    if (!ledger.energy_algorithm_version_is_int || (version != 1 && !(algorithm == "temperature_sou" && version == 2)))
        throw std::invalid_argument("unsupported conservative energy algorithm version");
    if (need(ledger.boundary_power_units, "boundary_power_units") != (dimension == 2 ? "W/m" : "W"))
        throw std::invalid_argument("conservative boundary power units disagree with physical dimension");
    if (!ledger.physical_boundary_complete_recorded) throw Missing("'physical_boundary_complete'");
    if (!ledger.physical_boundary_complete_is_bool || ledger.physical_boundary_complete != true)
        throw std::invalid_argument("incomplete physical boundary prevents conservative heat duty");
    record(result, "boundary_fluxes.true_h.boundary_power");
    record(result, "boundary_fluxes.true_h.boundary_power." + side_name(side));
    return plane_duty(ledger.boundary_power[side], dimension, grid, diag);
}
double enthalpy_duty(const TrueHEvidence& ledger, std::size_t side, int dimension,
                     const GridEvidence& grid, Diagnostics& diag) {
    const auto& h = need(ledger.enthalpy[side], "h_" + side_name(side));
    const auto& mass = ledger.mass[side];
    if (mass.empty()) throw Missing("'mass_flux_" + side_name(side) + "'");
    const auto shape = boundary_shape(mass, 3, grid);
    if (shape != h.shape || (dimension == 2 && shape[2] != 1))
        throw std::invalid_argument(dimension == 2 ? "2D true-h evidence requires matching singleton-z cells and mass faces" : "native enthalpy cells disagree with mass faces");
    const auto mass_planes = boundary_planes(mass, 3, grid);
    std::vector<Tensor> h_planes;
    for (std::size_t axis = 0; axis < 3; ++axis) {
        h_planes.push_back(plane(h, axis, 0));
        h_planes.push_back(plane(h, axis, h.shape[axis] - 1));
    }
    const auto m = arrays(mass_planes), e = arrays(h_planes);
    return host_call(diag, [&] {return metrics::boundary_enthalpy_duty({e[0], e[1], e[2], e[3], e[4], e[5]},
        {m[0], m[1], m[2], m[3], m[4], m[5]}, need(ledger.inlet_enthalpy[side], "h_in_" + side_name(side)), diag);});
}

double legacy_temperature_duty(const ResultEvidence& result, std::size_t side, bool fine, Diagnostics& diag) {
    record(result, "metadata.parameters");
    const auto& grid = fine ? need(result.fine, "fine").grid : result.grid;
    const auto& data = fine ? need(result.fine, "fine").fields : result.fields;
    const auto& temperature = entry(data, side ? "Tb" : "Ta");
    const auto& rho = need(fine ? result.fine->rho_cp[side] : result.rho_cp[side], "rho_cp_" + side_name(side));
    const auto rho_cp = broadcast(rho, temperature.shape);
    const auto& eps = need(fine ? result.fine->epsilon : result.parameter_epsilon, "eps");
    const auto& raw_split = need(result.split_a, "split_A");
    const Tensor split_tensor = !side ? raw_split : host_call(diag, [&] {
        return raw_split.shape.empty() ? Tensor(metrics::capacity_split(raw_split.array().at(0), true, diag))
                                      : Tensor(metrics::capacity_split_field(raw_split.array(), diag));
    });
    const auto& pressure = need(result.pressure[side], side_name(side));
    const auto& u = entry(data, "uc" + side_name(side));
    const auto& v = entry(data, "vc" + side_name(side));
    const auto direction = need(result.direction[side], "dir_" + side_name(side));
    const auto& dx = need(grid.widths[0], "dx");
    const auto& dy = need(grid.widths[1], "dy");
    const auto& mi = fine ? result.fine->inlet_fraction[side] : pressure.inlet_fraction;
    const auto& mo = fine ? result.fine->outlet_fraction[side] : pressure.outlet_fraction;
    const auto epsilon = host_call(diag, [&] {return metrics::capacity_porosity(eps.array(), split_tensor.array(), diag);});
    const auto& inlet = need(result.inlet_temperature[side], "T_in" + side_name(side));
    const std::size_t axis = direction == 0 || direction == 1 ? 0 : 1;
    const bool reverse_flow = direction != 0 && direction != 2;
    const auto i_in = reverse_flow ? temperature.shape[axis] - 1 : 0;
    const auto i_out = reverse_flow ? 0 : temperature.shape[axis] - 1;
    const auto& velocity = axis ? v : u;
    const auto& area = axis ? dx : dy;
    const auto inlet_mask = mi ? host_call(diag, [&] {return arithmetic::cast(mi->array(), TPMSHX_RESULT_F64, diag);}) : full({temperature.shape[1 - axis]}, 1.0);
    const auto outlet_mask = mo ? host_call(diag, [&] {return arithmetic::cast(mo->array(), TPMSHX_RESULT_F64, diag);}) : full({temperature.shape[1 - axis]}, 1.0);
    const auto u_in = plane(velocity, axis, i_in), u_out = plane(velocity, axis, i_out);
    const auto rho_in = plane(rho_cp, axis, i_in), rho_out = plane(rho_cp, axis, i_out);
    const auto default_inlet = plane(temperature, axis, i_in), t_out = plane(temperature, axis, i_out);
    const auto eps_in = epsilon.shape.empty() ? scalar(arithmetic::to_float(epsilon.array().at(0))) : plane(epsilon, axis, i_in);
    const auto eps_out = epsilon.shape.empty() ? eps_in : plane(epsilon, axis, i_out);
    const auto t_in = result.inlet_temperature_none[side] ? default_inlet
        : Tensor(host_call(diag, [&] {return arithmetic::cast(inlet.array(), TPMSHX_RESULT_F64, diag);}));
    return host_call(diag, [&] {return metrics::capacity_duty({eps_in.array(), rho_in.array(), u_in.array(), area.array(), inlet_mask.array()},
        {eps_out.array(), rho_out.array(), u_out.array(), area.array(), outlet_mask.array()}, t_in.array(), t_out.array(), diag);});
}

double thermal_duty(const ResultEvidence& result, std::size_t side, bool fine, Diagnostics& diag) {
    const auto& mode = need(result.thermal_mode, "thermal_mode");
    const auto& thermal = fine ? need(result.fine, "fine").thermal : result.thermal;
    const auto& grid = fine ? need(result.fine, "fine").grid : result.grid;
    if (mode == "conservative_energy") {
        if (fine) throw Unsupported("conservative energy has no Richardson thermal solve");
        return conservative_duty(result, need(thermal.true_h, "true_h"), side, result.dimension, grid, diag);
    }
    if (mode == "true_h") {
        if (fine) throw Unsupported("true enthalpy has no Richardson thermal solve");
        return enthalpy_duty(need(thermal.true_h, "true_h"), side, result.dimension, grid, diag);
    }
    if (mode == "model_h") {
        const auto& model = need(thermal.model_h, fine ? "model_h_balance" : "model_h");
        const auto& evidence = model.sides[side];
        const auto side_path = std::string(fine ? "boundary_fluxes.fine.model_h_balance." : "boundary_fluxes.model_h.") + side_name(side);
        if (result.dimension == 2) record(result, side_path);
        if (evidence.physical_boundary_complete != true)
            throw std::invalid_argument("unknown inflow prevents a complete heat duty");
        if (result.dimension == 2) {
            const auto faces = boundary_planes(evidence.staggered_power, 2, grid);
            const auto p = arrays(faces);
            return host_call(diag, [&] {return metrics::staggered_power_duty_2d({p[0], p[1], p[2], p[3]}, diag);});
        }
        record(result, side_path);
        const auto planes = six_planes(evidence.boundary_power, "3D model-h requires all six physical boundary faces");
        boundary_shape(planes, 3, grid, true);
        return host_call(diag, [&] {return metrics::plane_duty(arrays(planes), diag);});
    }
    if (result.dimension == 2 && mode != "temperature") throw Unsupported("unsupported thermal mode: " + mode);
    const bool transport = result.temperature_transport || result.thermal.temperature ||
        (result.dimension == 2 && result.fine && result.fine->thermal.temperature);
    if (mode == "temperature" && transport) {
        if (result.dimension == 3 && result.temperature_transport == "legacy_frozen_cp_single_a_cc_v1") {
            if (thermal.temperature) throw std::invalid_argument("legacy single-A sCO2 temperature route cannot carry a model enthalpy ledger");
            throw Unsupported("single-A sCO2 frozen-property research route has no captured complete h(P,T) transport");
        }
        if (result.temperature_transport != "model_enthalpy_temperature_v1")
            throw std::invalid_argument("unsupported temperature transport declaration");
        return temperature_duty(need(thermal.temperature, "temperature"), side, result.dimension, grid, diag);
    }
    if (result.dimension == 3) throw Unsupported("legacy temperature route has no captured complete enthalpy transport");
    return legacy_temperature_duty(result, side, fine, diag);
}

std::array<double, 2> port_pressures(const PressureEvidence& evidence, Diagnostics& diag) {
    const auto& p = need(evidence.pressure, "P");
    if (p.shape.size() != 3 || std::any_of(p.shape.begin(), p.shape.end(), [](auto n){return n == 0;}))
        throw std::invalid_argument("pressure evidence requires nonempty three-dimensional cells");
    for (std::size_t axis = 0; axis < 3; ++axis) {
        const auto& width = need(evidence.grid.widths[axis], std::string("d") + "xyz"[axis]);
        if (width.shape != std::vector<std::size_t>{p.shape[axis]} || !metrics::port_width_valid(width.array()))
            throw std::invalid_argument(std::string("pressure ") + "xyz"[axis] + " widths must be positive, finite and match cells");
    }
    const auto& in = need(evidence.inlet_fraction, "inlet_frac");
    const auto& out = need(evidence.outlet_fraction, "outlet_frac");
    for (const auto& opening : std::array<std::pair<const Tensor*, std::string>, 2>{{{&in, "inlet"}, {&out, "outlet"}}})
        if (opening.first->shape != std::vector<std::size_t>{p.shape[0], p.shape[2]} || !metrics::port_opening_valid(opening.first->array()))
            throw std::invalid_argument("pressure " + opening.second + " fractions must be nonnegative, finite and match faces");
    const auto weights = host_call(diag, [&] {return metrics::port_weights(evidence.grid.widths[0]->array(), evidence.grid.widths[2]->array(), in.array(), out.array(), diag);});
    auto pin = plane(p, 1, 0), pout = plane(p, 1, p.shape[1] - 1);
    if (p.shape[1] >= 2) {
        const auto& dy = *evidence.grid.widths[1];
        const auto d0 = plane(dy, 0, 0), d1 = plane(dy, 0, 1);
        const auto dn = plane(dy, 0, p.shape[1] - 1), dm = plane(dy, 0, p.shape[1] - 2);
        const auto ri = host_call(diag, [&] {return metrics::pressure_ratio(d0.array(), d1.array(), diag);});
        const auto ro = host_call(diag, [&] {return metrics::pressure_ratio(dn.array(), dm.array(), diag);});
        pin = host_call(diag, [&] {return metrics::pressure_face(pin.array(), plane(p, 1, 1).array(), ri.array(), diag);});
        pout = host_call(diag, [&] {return metrics::pressure_face(pout.array(), plane(p, 1, p.shape[1] - 2).array(), ro.array(), diag);});
    }
    return {host_call(diag, [&] {return metrics::weighted_mean(pin.array(), weights[0].array(), diag);}), host_call(diag, [&] {return metrics::weighted_mean(pout.array(), weights[1].array(), diag);})};
}
std::array<double, 2> pressures(const ResultEvidence& result, std::size_t side, Diagnostics& diag) {
    if (result.dimension == 3) return port_pressures(need(result.pressure[side], side_name(side)), diag);
    record(result, "metadata.parameters");
    const auto direction = need(result.direction[side], "dir_" + side_name(side));
    auto p = entry(result.fields, "P_report_" + side_name(side));
    auto dx = need(result.grid.widths[0], "dx"), dy = need(result.grid.widths[1], "dy");
    if (direction == 1 || direction == 3) p = reverse(p, static_cast<std::size_t>(direction / 2));
    if (direction == 0 || direction == 1) {p = transpose_2d(p); std::swap(dx, dy);}
    if (direction == 1 || direction == 3) dy = reverse(dy, 0);
    record(result, "metadata.parameters.boundary_openings");
    record(result, "metadata.parameters.boundary_openings." + side_name(side));
    PressureEvidence pressure;
    pressure.pressure = singleton(p);
    pressure.grid.widths = {dx, dy, full({1}, 1.0)};
    pressure.inlet_fraction = singleton(need(result.inlet_geom_fraction[side], "in_geom_frac"));
    pressure.outlet_fraction = singleton(need(result.outlet_geom_fraction[side], "out_geom_frac"));
    return port_pressures(pressure, diag);
}
std::array<double, 2> mass_flow(const ResultEvidence& result, std::size_t side, Diagnostics& diag) {
    const auto& mass = result.thermal.mass[side];
    if (!result.thermal.mass_recorded[side] && mass.empty()) throw Missing("'mass_" + side_name(side) + "'");
    if (result.thermal.mass_none[side]) throw Missing("'native boundary faces'");
    const auto planes = boundary_planes(mass, result.dimension, result.grid);
    const auto p = arrays(planes);
    return host_call(diag, [&] {return result.dimension == 2 ? metrics::boundary_mass_2d({p[0], p[1], p[2], p[3]}, diag)
        : metrics::boundary_mass_3d({p[0], p[1], p[2], p[3], p[4], p[5]}, diag);});
}
double outlet_temperature(const ResultEvidence& result, std::size_t side, Diagnostics& diag) {
    std::optional<int> direction;
    if (result.dimension == 3) {
        record(result, "boundary_fluxes.report");
        record(result, "boundary_fluxes.report." + side_name(side));
        direction = need(result.thermal.report_direction[side], "direction");
        if (!result.thermal.mass_recorded[side] && result.thermal.mass[side].empty())
            throw Missing("'mass_" + side_name(side) + "'");
    }
    const auto& temperature = entry(result.fields, side ? "Tb" : "Ta");
    const auto& mass = result.thermal.mass[side];
    if (!result.thermal.mass_recorded[side] && mass.empty()) throw Missing("'mass_" + side_name(side) + "'");
    if (result.thermal.mass_none[side]) {
        if (result.dimension == 2) throw NumericError(TPMSHX_RESULT_TYPE_ERROR, "'NoneType' object is not iterable");
        throw Missing("'native boundary faces'");
    }
    if (boundary_shape(mass, result.dimension, result.grid) != temperature.shape)
        throw std::invalid_argument("outlet temperature cells disagree with native mass faces");
    if (result.dimension == 2) {
        record(result, "metadata.parameters");
        direction = need(result.direction[side], "dir_" + side_name(side));
    }
    const std::size_t axis = result.dimension == 2 ? static_cast<std::size_t>(*direction < 2 ? 0 : 1) : static_cast<std::size_t>(*direction / 2);
    if (axis >= mass.size()) throw std::invalid_argument("boundary plane index is outside the recorded field");
    const auto t = plane(temperature, axis, *direction % 2 ? 0 : temperature.shape[axis] - 1);
    const auto flux = plane(mass[axis], axis, *direction % 2 ? 0 : mass[axis].shape[axis] - 1);
    if (result.dimension == 3) return host_call(diag, [&] {return metrics::outlet_temperature_3d(t.array(), flux.array(), *direction % 2 != 0, diag);});
    const auto& opening = need(need(result.pressure[side], side_name(side)).outlet_geom_fraction, "outlet_geom_frac");
    return host_call(diag, [&] {return metrics::outlet_temperature_2d(t.array(), flux.array(), opening.array(), *direction != 0 && *direction != 2, diag);});
}

const QuickHost& quick_host() {
    if (!active_host) throw std::runtime_error("Quick input requires its Python protocol host");
    return active_host->quick;
}
template<class Function, class... Arguments> auto quick_protocol(const Function& function, Arguments&&... arguments) {
    if (!function) throw std::runtime_error("Quick input requires its named Python protocol callback");
    HostScope suspended(nullptr);
    return function(std::forward<Arguments>(arguments)...);
}
Number quick_number(const QuickValue& value) {
    if (value.object) throw NumericError(TPMSHX_RESULT_TYPE_ERROR, "Quick numeric input requires a typed value");
    return value.numeric.array().at(0);
}
bool quick_integer(const QuickValue& value) {
    if (value.object || !value.numeric.shape.empty()) return false;
    const auto number = quick_number(value);
    return number.origin == TPMSHX_RESULT_PYTHON_INT || number.origin == TPMSHX_RESULT_PYTHON_BOOL;
}
unsigned quick_bits(const QuickValue& value) {
    const auto number = quick_number(value);
    auto magnitude = signed_type(number.dtype) ? static_cast<std::uint64_t>(number.signed_value) : number.unsigned_value;
    if (signed_type(number.dtype) && number.signed_value < 0) magnitude = std::uint64_t{} - magnitude;
    unsigned bits = 0;
    for (; magnitude; magnitude >>= 1) ++bits;
    return bits;
}
bool quick_python_product(std::initializer_list<const QuickValue*> values) {
    for (const auto* value : values) if (value->object) return true;
    unsigned bits = 0;
    for (const auto* value : values) {
        if (!quick_integer(*value)) break;
        bits += quick_bits(*value);
        if (bits > 63) return true;
    }
    return false;
}
template<class Scalar, class Field> QuickValue quick_numeric_pair(const QuickValue& first, const QuickValue& second,
    Diagnostics& diagnostics, Scalar scalar, Field field) {
    if (first.object || second.object)
        throw NumericError(TPMSHX_RESULT_TYPE_ERROR, "Quick numeric input requires a typed value");
    if (!first.numeric.shape.empty() || !second.numeric.shape.empty())
        return Tensor(host_call(diagnostics, [&] {return field(first.numeric.array(), second.numeric.array(), diagnostics);}));
    return host_call(diagnostics, [&] {return scalar(quick_number(first), quick_number(second), diagnostics);});
}
double quick_float(const QuickValue& value) {
    if (value.object || !value.numeric.shape.empty())
        return quick_protocol(quick_host().metric_float, value);
    return arithmetic::to_float(quick_number(value));
}
QuickValue quick_input(const ResultEvidence& result, std::size_t side,
    Recorded<QuickValue> QuickTypedSide::*typed, Recorded<Number> QuickSideEvidence::*scalar, const char* name) {
    if (result.quick_typed) return need(result.quick_typed->sides[side].*typed, name);
    return need(result.quick[side].*scalar, name);
}
void quick_access(const ResultEvidence& result, std::size_t side, Recorded<int> QuickTypedSide::*access,
                  const std::string& path) {
    if (result.quick_typed) (void)need(result.quick_typed->sides[side].*access, path.substr(path.rfind('.') + 1));
    else record(result, path);
}
bool label_equal(const StageLabel& value, const std::string& expected) {
    return value.text ? *value.text == expected
        : quick_protocol(quick_host().text_equal, value.value, expected);
}
QuickValue quick_metric_value(const ResultEvidence& result, const std::string& name, Diagnostics& diag) {
    const bool supported = result.quick_typed ? label_equal(need(result.quick_typed->model, "model"), "plug_ltne_analytic_dp_v1")
        : need(result.quick_model, "model") == "plug_ltne_analytic_dp_v1";
    if (!supported) throw Unsupported("unsupported quick-design metric definition");
    const std::size_t side = ends_with(name, "_B") || name == "Q_cold" ? 1 : 0;
    if (name == "T_out_A" || name == "T_out_B") {
        const auto& t = entry(result.fields, side ? "Tb" : "Ta");
        bool cross = false;
        if (side) {
            if (result.quick_typed) cross = label_equal(need(result.quick_typed->arrangement, "arrangement"), "cross");
            else {record(result, "metadata.parameters"); cross = need(result.arrangement, "arrangement") == "cross";}
        }
        (void)t.array();
        if (result.quick_typed && t.shape.size() < 3) throw NumericError(TPMSHX_RESULT_INDEX_ERROR,
            "too many indices for array: array is " + std::to_string(t.shape.size()) + "-dimensional, but 3 were indexed");
        const auto axis = side && cross ? 1u : 0u;
        const bool last = !side || cross;
        if (result.quick_typed && !t.shape[axis]) throw NumericError(TPMSHX_RESULT_INDEX_ERROR,
            "index " + std::string(last ? "-1" : "0") + " is out of bounds for axis " + std::to_string(axis) + " with size 0");
        const auto selected = plane(t, axis, last ? t.shape.at(axis) - 1 : 0);
        if (!selected.size() && result.quick_typed) quick_protocol(quick_host().empty_mean);
        return arithmetic::python_float(host_call(diag, [&] {return metrics::outlet_mean(selected.array(), diag);}));
    }
    if (name == "Q" || name == "Q_cold") {
        quick_access(result, side, &QuickTypedSide::boundary_access, "boundary_fluxes." + side_name(side));
        const auto inlet = quick_input(result, side, &QuickTypedSide::inlet_temperature, &QuickSideEvidence::inlet_temperature, "inlet_temperature_K");
        const auto outlet = quick_float(quick_metric_value(result, side ? "T_out_B" : "T_out_A", diag));
        QuickValue delta;
        if (result.quick_typed && quick_python_product({&inlet})) delta = quick_protocol(quick_host().temperature_difference, inlet, outlet);
        else if (!inlet.numeric.shape.empty()) delta = Tensor(host_call(diag, [&] {return metrics::quick_temperature_difference_field(inlet.numeric.array(), outlet, diag);}));
        else delta = host_call(diag, [&] {return metrics::quick_temperature_difference(quick_number(inlet), outlet, diag);});
        const auto mass = quick_input(result, side, &QuickTypedSide::mass_flow, &QuickSideEvidence::mass_flow, "mass_flow_kg_s");
        const auto cp = quick_input(result, side, &QuickTypedSide::cp, &QuickSideEvidence::cp, "cp_J_kgK");
        const bool protocol = result.quick_typed && quick_python_product({&mass, &cp});
        const auto capacity = protocol ? quick_protocol(quick_host().capacity_product, mass, cp)
            : quick_numeric_pair(mass, cp, diag, metrics::quick_capacity_product, metrics::quick_capacity_product_field);
        if (protocol) return quick_protocol(quick_host().duty_product, capacity, delta, side != 0);
        if (capacity.object || delta.object) throw NumericError(TPMSHX_RESULT_TYPE_ERROR, "Quick numeric input requires a typed value");
        if (!capacity.numeric.shape.empty() || !delta.numeric.shape.empty())
            return Tensor(host_call(diag, [&] {return metrics::quick_duty_from_capacity_field(capacity.numeric.array(), delta.numeric.array(), side != 0, diag);}));
        return host_call(diag, [&] {return metrics::quick_duty_from_capacity(quick_number(capacity), quick_number(delta), side != 0, diag);});
    }
    if (name == "dP_A" || name == "dP_B") {
        QuickValue inlet, outlet;
        if (result.quick_typed) {
            const auto& pressure = result.quick_typed->sides[side];
            quick_access(result, side, &QuickTypedSide::pressure_access, "pressure_evidence." + side_name(side));
            inlet = need(pressure.inlet_pressure, "inlet_absolute_Pa");
            outlet = need(pressure.outlet_pressure, "outlet_absolute_Pa");
        } else {
            const auto& pressure = need(result.pressure[side], side_name(side));
            inlet = need(pressure.inlet_absolute, "inlet_absolute_Pa");
            outlet = need(pressure.outlet_absolute, "outlet_absolute_Pa");
        }
        const bool wide = quick_integer(inlet) && quick_integer(outlet) && std::max(quick_bits(inlet), quick_bits(outlet)) > 62;
        if (result.quick_typed && (inlet.object || outlet.object || wide))
            return quick_protocol(quick_host().pressure_difference, inlet, outlet);
        return quick_numeric_pair(inlet, outlet, diag, metrics::pressure_difference, metrics::pressure_difference_field);
    }
    if (name == "Re_A" || name == "Re_B") {
        if (!result.quick_typed) record(result, "metadata.properties");
        quick_access(result, side, &QuickTypedSide::properties_access, "metadata.properties." + side_name(side));
        quick_access(result, side, &QuickTypedSide::boundary_access, "boundary_fluxes." + side_name(side));
        const auto velocity = quick_input(result, side, &QuickTypedSide::velocity, &QuickSideEvidence::velocity, "velocity_m_s");
        const auto rho = quick_input(result, side, &QuickTypedSide::rho, &QuickSideEvidence::rho, "rho");
        bool protocol = result.quick_typed && quick_python_product({&rho, &velocity});
        if (result.quick_typed && quick_integer(velocity)) {
            const auto value = quick_number(velocity);
            protocol = protocol || (value.origin == TPMSHX_RESULT_PYTHON_INT && signed_type(value.dtype) &&
                                     value.signed_value == std::numeric_limits<std::int64_t>::min());
        }
        const auto flow = protocol ? quick_protocol(quick_host().reynolds_flow, rho, velocity)
            : quick_numeric_pair(rho, velocity, diag, metrics::quick_reynolds_flow, metrics::quick_reynolds_flow_field);
        QuickValue diameter;
        if (result.quick_typed) diameter = need(result.quick_typed->hydraulic_diameter, "D_h");
        else {record(result, "metadata.parameters"); diameter = need(result.hydraulic_diameter, "D_h");}
        protocol = protocol || (result.quick_typed && quick_python_product({&flow, &diameter}));
        const auto numerator = protocol ? quick_protocol(quick_host().reynolds_length, flow, diameter)
            : quick_numeric_pair(flow, diameter, diag, metrics::quick_reynolds_length, metrics::quick_reynolds_length_field);
        const auto mu = quick_input(result, side, &QuickTypedSide::viscosity, &QuickSideEvidence::viscosity, "mu");
        const bool wide = quick_integer(numerator) && quick_integer(mu) && std::max(quick_bits(numerator), quick_bits(mu)) > 53;
        if (result.quick_typed && (protocol || quick_python_product({&mu}) || wide))
            return quick_protocol(quick_host().reynolds_quotient, numerator, mu);
        return quick_numeric_pair(numerator, mu, diag, metrics::quick_reynolds_quotient, metrics::quick_reynolds_quotient_field);
    }
    if (name == "mass_flow_A" || name == "mass_flow_B") {
        quick_access(result, side, &QuickTypedSide::boundary_access, "boundary_fluxes." + side_name(side));
        return quick_input(result, side, &QuickTypedSide::mass_flow, &QuickSideEvidence::mass_flow, "mass_flow_kg_s");
    }
    if (name == "energy_imbalance_rel") {
        auto first = quick_metric_value(result, "Q", diag);
        if (!result.quick_typed) first = arithmetic::python_float(quick_float(first));
        auto second = quick_metric_value(result, "Q_cold", diag);
        if (!result.quick_typed) second = arithmetic::python_float(quick_float(second));
        return quick_numeric_pair(first, second, diag, metrics::quick_energy_imbalance, metrics::quick_energy_imbalance_field);
    }
    throw Unsupported("quick-design does not supply " + name);
}
double quick_metric(const ResultEvidence& result, const std::string& name, Diagnostics& diag) {
    return quick_float(quick_metric_value(result, name, diag));
}

class MetricEvaluation {
public:
    MetricEvaluation(const ResultEvidence& evidence, Diagnostics& diagnostics):result(evidence),diag(diagnostics) {}
    double get(const std::string& name) {
        if (result.mode == "quick_design") return quick_metric(result, name, diag);
        const std::size_t side = ends_with(name, "_B") ? 1 : 0;
        if (result.dimension == 3 && (side || name == "energy_imbalance_rel") && !result.active_fluids[1])
            throw Unsupported("fluid B is inactive in this prepared research case");
        if (name == "Q") return metrics::duty_magnitude(duty(0, false));
        if (name == "Q_A" || name == "Q_B") return duty(side, false);
        if (starts_with(name, "Q_richardson_")) {
            const auto& mode = need(result.thermal_mode, "thermal_mode");
            if (mode == "conservative_energy") throw Unsupported("conservative energy has no Richardson thermal solve");
            if (mode == "true_h") throw Unsupported("true enthalpy has no Richardson thermal solve");
            record(result, "metadata.diagnostics");
            record(result, "metadata.diagnostics.richardson_info");
            if (!result.richardson_extrapolated) throw Missing("'extrapolated'");
            if (*result.richardson_extrapolated == false) throw Unsupported("Richardson extrapolation was not accepted");
            const auto fine = duty(side, true);
            return metrics::richardson_duty(fine, duty(side, false));
        }
        if (starts_with(name, "dP_") || starts_with(name, "P_out_")) {
            const auto p = pressures(result, side, diag);
            if (starts_with(name, "dP_")) return arithmetic::to_float(host_call(diag, [&] {return metrics::pressure_difference(arithmetic::python_float(p[0]), arithmetic::python_float(p[1]), diag);}));
            return result.dimension == 2 ? p[1] : arithmetic::to_float(host_call(diag, [&] {return metrics::absolute_outlet_pressure(arithmetic::python_float(p[1]), need(need(result.pressure[side], side_name(side)).reference, "P_ref_abs"), diag);}));
        }
        if (starts_with(name, "T_out_")) return outlet_temperature(result, side, diag);
        if (starts_with(name, "mass_flow_")) return mass(side)[0];
        if (starts_with(name, "mass_imbalance_rel_")) {const auto m = mass(side); return metrics::mass_imbalance(m[0], m[1]);}
        if (name == "energy_imbalance_rel") {
            const auto a = duty(0, false), b = duty(1, false);
            return metrics::full_energy_imbalance(a, b);
        }
        if (name == "mass") {
            const auto& density = need(result.solid_density, "solid_density_kg_m3");
            record(result, "metadata.design_fields");
            const auto& epsilon = need(result.design_epsilon, "eps_arr");
            const auto& dx = need(result.grid.widths[0], "dx");
            const auto& dy = need(result.grid.widths[1], "dy");
            if (result.dimension == 2) return host_call(diag, [&] {return metrics::solid_mass_2d(epsilon.array(), density.array(), dx.array(), dy.array(), diag);});
            return host_call(diag, [&] {return metrics::solid_mass_3d(epsilon.array(), density.array(), dx.array(), dy.array(), need(result.grid.widths[2], "dz").array(), diag);});
        }
        throw Unsupported("unsupported metric: " + name);
    }
private:
    const ResultEvidence& result;
    Diagnostics& diag;
    std::array<std::array<std::optional<double>, 2>, 2> duties;
    std::array<std::optional<std::array<double, 2>>, 2> masses;
    double duty(std::size_t side, bool fine) {
        auto& value = duties[side][fine ? 1 : 0];
        if (!value) value = thermal_duty(result, side, fine, diag);
        return *value;
    }
    std::array<double, 2> mass(std::size_t side) {
        if (!masses[side]) masses[side] = mass_flow(result, side, diag);
        return *masses[side];
    }
};

Object norm_record(const balance::NormValues& value) {
    return {{"signed_sum", value.signed_sum}, {"l1", value.l1}, {"cell_max", value.cell_max},
            {"cell_count", static_cast<std::int64_t>(value.cell_count)}};
}
Object mass_summary(const std::vector<Tensor>& faces, const GridEvidence& grid, int dimension,
                    const std::string& units, const std::string& source, bool unavailable,
                    const Recorded<int>& dimension_index) {
    if (faces.empty() && unavailable) return {{"status", "unavailable"}, {"reason", "mass faces were not recorded"}, {"source", source}};
    boundary_shape(faces, dimension, grid, false, dimension_index);
    std::vector<RawArray> raw;
    for (const auto& face : faces) {finite_values(face, "mass faces"); raw.push_back(face.raw());}
    Diagnostics diag{};
    const auto value = host_call(diag, [&] {return balance::mass(raw.data(), static_cast<std::size_t>(dimension), diag);});
    Object boundaries;
    for (int i = 0; i < dimension * 2; ++i) boundaries.emplace(face_names[static_cast<std::size_t>(i)], value.boundary_out[i]);
    return {{"status", "available"}, {"source", source}, {"units", units},
        {"inflow", value.inflow}, {"outflow", value.outflow}, {"residual", norm_record(value.residual)},
        {"scale", value.scale}, {"scale_definition", "max(total inward mass, total outward mass)"},
        {"relative_net", value.has_scale ? Report(value.relative_net) : Report()},
        {"relative_l1", value.has_scale ? Report(value.relative_l1) : Report()},
        {"boundary_out", boundaries}, {"telescoping_error", value.telescoping_error}};
}
Object energy_summary(const ResultEvidence& result, const Recorded<EnergyEvidence>& optional, const GridEvidence& grid,
                      int dimension, const std::string& source) {
    if (!optional) return {{"status", "unavailable"}, {"reason", "physical energy audit was not recorded"}, {"source", source}};
    const auto& evidence = *optional;
    const auto& definition = need(evidence.definition, "definition");
    if (definition != "physical_heat_ledger_v1" && definition != "model_enthalpy_temperature_v1")
        throw std::invalid_argument("unsupported physical heat ledger definition");
    const std::string units = dimension == 2 ? "W/m" : "W";
    if (need(evidence.physical_dimension, "physical_dimension") != dimension || need(evidence.power_units, "power_units") != units)
        throw std::invalid_argument("heat ledger units or dimension disagree with result");
    if (!evidence.physical_boundary_complete_is_bool)
        throw std::invalid_argument("heat ledger requires an explicit boundary completeness state");
    if (evidence.phases.size() != 3 || std::any_of(phase_names.begin(), phase_names.end(), [&](const auto& phase) {
        const auto found = evidence.phases.find(phase);
        return found == evidence.phases.end() || !found->second.solved || !found->second.solved_is_bool;
    })) throw std::invalid_argument("heat ledger requires solved flags for each phase");
    if (result.physical_dimension_slice) (void)*result.physical_dimension_slice;
    std::vector<std::size_t> shape;
    for (int axis = 0; axis < dimension; ++axis) {
        const auto& width = need(grid.widths[static_cast<std::size_t>(axis)], std::string("d") + "xyz"[axis]);
        if (width.shape.empty()) throw std::invalid_argument("len() of unsized object");
        shape.push_back(width.shape[0]);
    }
    if (std::any_of(shape.begin(), shape.end(), [](auto n){return n == 0;}))
        throw std::invalid_argument("heat ledger requires nonempty physical cells");
    auto shape3 = shape;
    if (dimension == 2) shape3.push_back(1);
    Object phases;
    std::vector<balance::EnergyPhase> solved;
    std::vector<std::string> solved_names;
    Diagnostics diag{};
    for (const auto& phase : phase_names) {
        const auto& input = evidence.phases.at(phase);
        if (input.solved == false) {
            if (input.residual || !input.advective_out.empty() || !input.diffusive_out.empty() || input.source_integral)
                throw std::invalid_argument("unsolved phase cannot carry a solved energy ledger");
            phases.emplace(phase, Object{{"status", "not_solved"}});
            continue;
        }
        record(result, source + ".residual");
        const auto& residual = need(input.residual, phase);
        finite_values(residual, "energy residual");
        if (residual.shape != shape) throw std::invalid_argument("heat ledger residual shape disagrees with grid");
        balance::EnergyPhase value{};
        value.residual = host_call(diag, [&] {return balance::norms(residual.raw(), diag);});
        Object row{{"status", "available"}, {"residual", norm_record(value.residual)}};
        record(result, source + ".source_integral");
        const auto& source_power = need(input.source_integral, phase);
        finite_values(source_power, "source integral");
        if (!source_power.shape.empty()) throw std::invalid_argument("heat ledger requires scalar source integrals");
        value.source_integral = arithmetic::to_float(source_power.array().at(0));
        row.emplace("source_integral", value.source_integral);
        for (int kind = 0; kind < 2; ++kind) {
            const std::string key = kind ? "diffusive_out" : "advective_out";
            record(result, source + "." + key);
            const auto planes = six_planes(kind ? input.diffusive_out : input.advective_out,
                                           "heat ledger requires all six boundary planes");
            for (const auto& plane_value : planes) finite_values(plane_value, "boundary power");
            if (boundary_shape(planes, 3, {}, true) != shape3)
                throw std::invalid_argument("heat ledger boundary shape disagrees with grid");
            std::array<RawArray, 6> raw{};
            for (std::size_t i = 0; i < 6; ++i) raw[i] = planes[i].raw();
            const auto values = host_call(diag, [&] {return balance::plane_sums(raw.data(), 6, diag);});
            Object sums;
            for (std::size_t i = 0; i < 6; ++i) sums.emplace(face_names[i], values.values[i]);
            row.emplace(key, sums);
            row.emplace(key + "_sum", values.total);
            if (kind) value.diffusive_out_sum = values.total; else value.advective_out_sum = values.total;
        }
        solved.push_back(value); solved_names.push_back(phase);
        phases.emplace(phase, row);
    }
    const auto& reservoir = need(evidence.prescribed_b_power, "prescribed_b_power");
    finite_values(reservoir, "prescribed B power");
    if (!reservoir.shape.empty()) throw std::invalid_argument("heat ledger requires scalar prescribed B power");
    const auto total = balance::energy(solved.data(), solved.size(), arithmetic::to_float(reservoir.array().at(0)));
    for (std::size_t i = 0; i < solved_names.size(); ++i) {
        auto& norms = std::get<Object>(std::get<Object>(phases.at(solved_names[i]).value).at("residual").value);
        norms.emplace("l1_relative", total.l1_relative[i]);
        norms.emplace("cell_max_relative", total.cell_max_relative[i]);
    }
    return {{"status", "available"}, {"source", source}, {"units", units}, {"evidence_definition", definition},
        {"physical_boundary_complete", Report(evidence.physical_boundary_complete)}, {"phases", phases},
        {"boundary_out", solved.empty() ? Report(0) : Report(total.boundary_out)}, {"source_integral", solved.empty() ? Report(0) : Report(total.source_integral)},
        {"prescribed_b_power", total.prescribed_b_power}, {"net_external_in", total.net_external_in},
        {"residual_sum", solved.empty() ? Report(0) : Report(total.residual_sum)}, {"telescoping_error", total.telescoping_error},
        {"scale", total.scale}, {"scale_definition", "max(1 native power unit, abs phase net boundary power, abs phase source, abs reservoir power)"},
        {"relative_external_imbalance", total.relative_external_imbalance}};
}

std::pair<Truth, Object> assess_range(const RangeSample& sample) {
    if (!sample.captured_is_bool) throw std::invalid_argument("range evidence requires an explicit capture flag");
    auto row = sample.captured_record;
    row.insert_or_assign("source", strings(sample.source));
    row.insert_or_assign("side", sample.side);
    row.insert_or_assign("quantity", sample.quantity);
    row.insert_or_assign("captured", sample.captured);
    if (!sample.captured) {
        row.insert_or_assign("status", "unavailable"); row.insert_or_assign("within_limit", Report());
        return {std::nullopt, std::move(row)};
    }
    row.insert_or_assign("bounds", List{sample.bounds[0], sample.bounds[1]});
    row.insert_or_assign("shape", sizes(sample.shape));
    for (const auto& value : std::array<std::pair<std::string, std::size_t>, 4>{{{"size", sample.size}, {"low", sample.low}, {"high", sample.high}, {"nonfinite", sample.nonfinite}}})
        row.insert_or_assign(value.first, static_cast<std::int64_t>(value.second));
    if (!row.count("minimum")) row.emplace("minimum", sample.minimum ? Report(List{*sample.minimum, List{}}) : Report());
    if (!row.count("maximum")) row.emplace("maximum", sample.maximum ? Report(List{*sample.maximum, List{}}) : Report());
    const auto bounds = checks::source_bounds(sample.bounds[0], sample.bounds[1]);
    std::size_t product = 1;
    for (const auto n : sample.shape) {
        if (n && product > std::numeric_limits<std::size_t>::max() / n)
            throw std::invalid_argument("range evidence has inconsistent sample counts");
        product *= n;
    }
    if (!sample.size || sample.size != product || sample.low > sample.size || sample.high > sample.size || sample.nonfinite > sample.size)
        throw std::invalid_argument("range evidence has inconsistent sample counts");
    if (sample.constraint != "parameter" && sample.constraint != "hard_bounds")
        throw std::invalid_argument("unsupported range constraint");
    const bool hard = sample.constraint == "hard_bounds";
    row.insert_or_assign("allowed_bounds", List{hard ? sample.bounds[0] : bounds.lower, hard ? sample.bounds[1] : bounds.upper});
    row.insert_or_assign("allowance_fraction", hard ? Report(0.0) : bounds.positive ? Report(bounds.allowance_fraction) : Report());
    Truth passed;
    if (sample.nonfinite || !sample.minimum || !sample.maximum) {
        row.insert_or_assign("status", "invalid");
        row.insert_or_assign("reason", "sample contains nonfinite values");
        passed = false;
    } else {
        const auto decision = checks::range_values(sample.bounds[0], sample.bounds[1], *sample.minimum, *sample.maximum, hard);
        if (decision.numerical_case == TPMSHX_RESULT_WITHIN_ORIGINAL) {
            row.insert_or_assign("status", "within_original");
            row.insert_or_assign("relative_extrapolation", decision.relative_extrapolation);
            passed = true;
        } else if (decision.numerical_case == TPMSHX_RESULT_DOMAIN_RULE_REQUIRED) {
            row.insert_or_assign("status", "domain_rule_required");
            row.insert_or_assign("reason", "relative extrapolation is undefined for zero or signed source bounds");
        } else {
            passed = decision.numerical_case == TPMSHX_RESULT_WITHIN_MARGIN;
            row.insert_or_assign("status", *passed ? "within_margin" : "outside_limit");
            row.insert_or_assign("relative_extrapolation", decision.relative_present ? Report(decision.relative_extrapolation) : Report());
        }
    }
    row.insert_or_assign("within_limit", Report(passed));
    return {passed, std::move(row)};
}

using Gates = std::vector<std::pair<std::string, Truth>>;
List gate_report(const Gates& values) {
    List out;
    for (const auto& gate : values) out.emplace_back(List{gate.first, Report(gate.second)});
    return out;
}
Truth gate_passed(const Gates& gates) {
    std::vector<Truth> values;
    for (const auto& gate : gates) values.push_back(gate.second);
    return all_known(values);
}
Gates energy_gates(const ResultEvidence& result) {
    const auto& mode = need(result.thermal_mode, "thermal_mode");
    if (mode == "true_h" || mode == "conservative_energy") {
        record(result, "metadata.diagnostics");
        const auto& certificate = need(result.true_h_certificate, "true_h_balance");
        const auto& clips = need(certificate.clip_counts, "total");
        Gates gates{{"true-h thermal solve converged", certificate.converged.is_true()},
            {"true-h enthalpy remains unclipped", clips.shape == std::vector<std::size_t>{2} && checks::array_checks(clips.array()).all_zero}};
        Diagnostics diag{};
        for (std::size_t i = 0; i < 2; ++i) {
            const std::string name = i ? "equation" : "coupled";
            gates.emplace_back("true-h " + name + " energy balance",
                host_call(diag, [&] {return checks::energy_ratio(need(certificate.ratios[i], "ratio"), need(certificate.tolerances[i], name + "_energy_tol"), diag);}));
        }
        return gates;
    }
    if (mode == "temperature") {
        if (result.temperature_transport != "model_enthalpy_temperature_v1")
            throw Unsupported("capacity-temperature has no common energy certificate");
        record(result, "metadata.diagnostics");
        record(result, "metadata.diagnostics.convergence_detail");
        return {{"native strict integral-enthalpy thermal gate", entry(result.convergence_gates, "ltne_ok").is_true()}};
    }
    if (mode != "model_h") throw Unsupported("thermal route has no common energy certificate");
    if (need(result.metadata_dimension, "dimension") == 2) {
        record(result, "metadata.diagnostics");
        if (result.model_certificate_error) throw Missing(*result.model_certificate_error);
        if (result.model_certificates.empty() && !result.model_certificates_recorded) throw Missing("'model_h_balance'");
        Gates gates;
        auto levels = result.model_certificate_order;
        if (levels.empty()) for (const auto& row : result.model_certificates) levels.push_back(row.first);
        for (const auto& level : levels) {
            const auto found = result.model_certificates.find(level);
            if (found == result.model_certificates.end()) continue;
            const auto& certificate = found->second;
            gates.emplace_back("2D " + level + " native model-h certificate", certificate.passed_is_bool && certificate.passed == true);
            for (std::size_t side = 0; side < 2; ++side)
                gates.emplace_back("2D " + level + " " + side_name(side) + " physical boundary complete",
                                   certificate.sides[side].physical_boundary_complete_is_bool && certificate.sides[side].physical_boundary_complete == true);
        }
        if (result.model_certificates.size() != 2 || !result.model_certificates.count("main") || !result.model_certificates.count("fine"))
            throw std::invalid_argument("2D energy certificate requires main and fine thermal results");
        record(result, "metadata.diagnostics.convergence_detail");
        gates.emplace_back("2D native Richardson check", entry(result.convergence_gates, "richardson_ok").is_true());
        return gates;
    }
    record(result, "metadata.diagnostics");
    record(result, "metadata.parameters");
    const bool active_b = need(result.model_active_b, "fluid_B_cfg");
    const auto& b_coupling = entry(result.fields, "h_vB");
    std::array<double, 4> ratios;
    for (std::size_t i = 0; i < 4; ++i) ratios[i] = result.strict_ratios[i].value_or(std::numeric_limits<double>::quiet_NaN());
    const auto qa = need(result.source_power[0], "Q_sA"), qb = need(result.source_power[1], "Q_sB");
    const auto certificate = checks::strict_certificate(active_b, ratios, qa, qb);
    Gates gates;
    for (std::size_t side = 0; side < 2; ++side) {
        if (side && !active_b) {
            const bool disabled = !result.strict_ratios[2] && !result.strict_ratios[3] && qb == 0.0 &&
                                  checks::array_checks(b_coupling.array()).all_zero;
            gates.emplace_back("B disabled: no certificate and zero coupling", disabled);
        } else {
            gates.emplace_back(side_name(side) + " strict global < 1 %", certificate.strict[side * 2] != 0);
            gates.emplace_back(side_name(side) + " strict cellmax < 1 %", certificate.strict[side * 2 + 1] != 0);
        }
    }
    gates.emplace_back("full-volume LTNE source balance < 1 %", certificate.source_pass != 0);
    const auto recorded = result.model_certificates.find("main");
    const auto* model_certificate = recorded == result.model_certificates.end() ? nullptr : &recorded->second;
    if (model_certificate) gates.emplace_back("physical boundary data complete",
        model_certificate->physical_boundary_complete_is_bool && model_certificate->physical_boundary_complete == true);
    else if (active_b) gates.emplace_back("two-fluid model-h boundary ledger available", false);
    return gates;
}

std::string full_version(const std::string& name) {
    if (starts_with(name, "dP_") || starts_with(name, "P_out_")) return "pressure_face_v1";
    if (name == "Q" || starts_with(name, "Q_") || starts_with(name, "T_out_") || starts_with(name, "mass_flow_") || name == "energy_imbalance_rel")
        return "native_boundary_v1";
    return "three_module_v1";
}
std::string description(const std::string& name) {
    if (name == "Q") return "Absolute A-side heat loss from the native main thermal boundary state; no side selection or extrapolation.";
    if (name == "Q_A" || name == "Q_B") return "Signed " + side_name(name == "Q_B" ? 1 : 0) + "-side heat loss from the native main thermal boundary state; heat loss is positive.";
    if (starts_with(name, "Q_richardson_")) return side_name(ends_with(name, "_B") ? 1 : 0) + "-side Richardson extrapolation of absolute coarse/fine duties; separate from main-grid Q.";
    if (starts_with(name, "T_out_")) return "Raw main thermal outlet temperature weighted by positive outward native mass flux.";
    if (starts_with(name, "mass_flow_")) return "Total inward signed boundary mass from the main thermal input state.";
    if (name == "energy_imbalance_rel") return "Absolute sum of native signed A/B duties divided by their maximum absolute value.";
    if (starts_with(name, "dP_")) return "Geometric-area-weighted inlet minus outlet pressure, extrapolated to physical port faces from the final SIMPLE field.";
    if (starts_with(name, "P_out_")) return "Absolute pressure at the physical outlet face, weighted by geometric opening area.";
    return {};
}
struct Definition {std::string name, kind, unit;};
std::vector<Definition> definitions(const ResultEvidence& result) {
    const bool d3 = result.dimension == 3;
    const std::string power = d3 ? "W" : "W/m", flow = d3 ? "kg/s" : "kg/(s m)";
    std::vector<Definition> out{{"Q", "Q", power}, {"dP_A", "dP", "Pa"}, {"dP_B", "dP", "Pa"},
        {"T_out_A", "T_out", "K"}, {"T_out_B", "T_out", "K"},
        {"mass_flow_A", "mass_flow", flow}, {"mass_flow_B", "mass_flow", flow},
        {"mass_imbalance_rel_A", "mass_imbalance_rel", "1"}, {"mass_imbalance_rel_B", "mass_imbalance_rel", "1"},
        {"energy_imbalance_rel", "energy_imbalance_rel", "1"}, {"mass", "mass", d3 ? "kg" : "kg/m"}};
    if (result.mode == "quick_design") {
        out.push_back({"Q_cold", "Q", "W"}); out.push_back({"Re_A", "Re", "1"}); out.push_back({"Re_B", "Re", "1"});
    } else {
        out.push_back({"Q_A", "Q_A", power}); out.push_back({"Q_B", "Q_B", power});
        out.push_back({"P_out_A", "P_out", "Pa"}); out.push_back({"P_out_B", "P_out", "Pa"});
        if (!d3) {out.push_back({"Q_richardson_A", "Q_richardson_A", power}); out.push_back({"Q_richardson_B", "Q_richardson_B", power});}
    }
    return out;
}
std::string python_repr(const std::string& value) {
    const char quote = value.find('\'') != std::string::npos && value.find('"') == std::string::npos ? '"' : '\'';
    std::string out(1, quote);
    for (char c : value) {
        if (c == quote || c == '\\') out += '\\';
        if (c == '\n') out += "\\n"; else if (c == '\r') out += "\\r"; else if (c == '\t') out += "\\t"; else out += c;
    }
    return out + quote;
}
std::string spec_repr(const MetricSpec& value) {
    return "MetricSpec(name=" + python_repr(value.name) + ", unit=" + python_repr(value.unit) + ", definition_version=" +
        python_repr(value.definition_version) + ", description=" + python_repr(value.description) + ")";
}
}  // namespace

PhysicalBalance evaluate_physical_balance(const ResultEvidence& result, const HostControl* host) {
    HostScope host_scope(host);
    declarations(result);
    if (result.dimension != 2 && result.dimension != 3) throw std::invalid_argument("physical balances require dimension 2 or 3");
    PhysicalBalance out;
    out.physical_dimension = result.dimension;
    Object mass;
    for (std::size_t side = 0; side < 2; ++side)
        mass.emplace(side_name(side), mass_summary(result.thermal.mass[side], result.grid, result.dimension,
            result.dimension == 2 ? "kg/(s m)" : "kg/s", "boundary_fluxes.mass_" + side_name(side),
            !result.thermal.mass_recorded[side] || result.thermal.mass_none[side], result.physical_dimension_index));
    const bool energy = static_cast<bool>(result.thermal.energy);
    out.details = {{"state", result.thermal_state.value_or("not_recorded")}, {"outer_index", nullable(result.outer_index)},
        {"mass", mass}, {"energy", energy_summary(result, energy ? result.thermal.energy : result.thermal.temperature, result.grid,
            result.dimension, energy ? "boundary_fluxes.energy" : "boundary_fluxes.temperature")},
        {"signs", Object{{"mass", "positive divergence is net outward mass"},
            {"power", "positive boundary power is outward; sources and reservoir power are inward"},
            {"residual", "physical RHS minus diagonal times state"}}}};
    if (result.fine) {
        const bool recorded = static_cast<bool>(result.fine->thermal.energy);
        out.details.emplace("fine_energy", energy_summary(result, recorded ? result.fine->thermal.energy : result.fine->thermal.temperature,
            result.fine->grid, result.dimension, recorded ? "boundary_fluxes.fine.energy" : "boundary_fluxes.fine.temperature"));
    }
    return out;
}

Applicability evaluate_applicability(const ResultEvidence& result, const HostControl* host) {
    HostScope host_scope(host);
    Applicability out;
    if (!result.applicability) {
        out.status = "unavailable";
        out.details.emplace("reason", "original-bound and final-state evidence was not recorded");
        return out;
    }
    const auto& evidence = *result.applicability;
    if (evidence.version != "applicability_evidence_v1") throw std::invalid_argument("unsupported applicability evidence version");
    Object checks_record;
    std::vector<Truth> values;
    for (const auto& group : {"inlet", "final"}) {
        List rows;
        for (const auto& sample : entry(evidence.groups, group)) {
            auto row = assess_range(sample);
            values.push_back(row.first); rows.emplace_back(std::move(row.second));
        }
        checks_record.emplace(group, std::move(rows));
    }
    List missing;
    for (const auto& required : evidence.required) {
        const auto& group = entry(evidence.groups, required.group);
        if (std::none_of(group.begin(), group.end(), [&](const auto& sample) {
            return sample.captured && sample.side == required.side && sample.source == required.source;
        })) missing.emplace_back(Object{{"group", required.group}, {"side", required.side}, {"source", strings(required.source)}});
    }
    if (!evidence.inlet_recorded) missing.emplace_back(Object{{"group", "inlet"}, {"reason", "prepared source evidence was not recorded"}});
    if (!missing.empty()) values.push_back(std::nullopt);
    out.within_limits = all_known(values);
    out.status = out.within_limits == false ? "outside_limits" : out.within_limits == true ? "within_limits" : "unverified";
    out.details = {{"checks", checks_record}, {"missing", missing},
        {"policy", "positive original [L,U] permits [0.9L,1.1U]; hard bounds remain fixed"}, {"scope_notes", evidence.scope_notes}};
    return out;
}

Qualification evaluate_qualification(const ResultEvidence& result, const std::map<std::string, MetricValue>& metrics_values, const HostControl* host) {
    HostScope host_scope(host);
    if (result.qualification_error) (void)*result.qualification_error;
    Qualification out;
    out.source_result_id = result.result_id;
    const Truth completed = result.execution ? Truth(*result.execution == "completed") : Truth{};
    out.execution = verdict(completed, "run_status.execution", {{"state", nullable(result.execution)}});
    Object gates, raw_fields, pressure_states;
    std::vector<Truth> raw_values;
    for (const auto& name : {"simple_ok", "ltne_ok", "outer_converged", "fields_finite", "envelope_ok", "richardson_ok"}) {
        const auto found = result.convergence_gates.find(name);
        if (found != result.convergence_gates.end()) {
            gates.emplace(name, found->second.recorded);
        }
    }
    auto field_names = result.field_order;
    if (field_names.empty()) for (const auto& field : result.fields) field_names.push_back(field.first);
    for (const auto& name : field_names)
        if (!ends_with(name, "_display")) raw_fields.emplace(name, checks::array_checks(result.fields.at(name).array()).all_finite != 0);
    for (const auto& name : {"Ta", "Tb", "Ts"}) if (!raw_fields.count(name)) raw_fields.emplace(name, Report());
    if (result.fine && !result.fine->empty_record) {
        for (const auto& name : {"Ta", "Tb", "Ts"}) {
            const auto found = result.fine->fields.find(name);
            raw_fields.emplace(std::string("fine.") + name, found == result.fine->fields.end() ? Report() : Report(checks::array_checks(found->second.array()).all_finite != 0));
        }
    }
    for (const auto& field : raw_fields)
        raw_values.push_back(std::holds_alternative<bool>(field.second.value) ? Truth(std::get<bool>(field.second.value)) : Truth{});
    Truth convergence_passed = true;
    const auto consume = [&](const TruthEvidence& value) {
        if (convergence_passed == false) return;
        const auto checked = value.qualified();
        if (checked != true) convergence_passed = checked;
    };
    consume(result.converged);
    const auto raw_passed = all_known(raw_values);
    consume(raw_passed ? TruthEvidence(*raw_passed) : TruthEvidence{});
    for (const auto& gate : gates) {
        const auto& value = result.convergence_gates.at(gate.first);
        if (value.value) consume(value);
    }
    for (std::size_t side = 0; side < 2; ++side) if (result.pressure[side]) {
        const auto found = result.field_metadata.find("P_report_" + side_name(side));
        pressure_states.emplace(side_name(side), found == result.field_metadata.end() ? Report() : nullable(found->second.state));
    }
    out.convergence = verdict(convergence_passed, "run_status.converged, metadata.diagnostics.convergence_detail and raw fields",
        {{"gates", gates}, {"raw_fields", raw_fields}, {"thermal_state", nullable(result.thermal_state)}, {"pressure_states", pressure_states}});
    const bool full_compute = result.mode == "full";
    const std::map<std::string, ExecutionSide> empty_sides;
    const bool full_execution = result.execution_label
        ? label_equal(*result.execution_label, "full_execution_v1")
        : result.execution_version == "full_execution_v1";
    const auto& sides = full_execution ? result.executed_sides : empty_sides;
    out.physical = verdict({}, "boundary_fluxes and metadata.diagnostics", {{"checks", List{}}});
    if (full_compute) {
        try {
            const auto physical = evaluate_physical_balance(result, host);
            Gates checks_list;
            std::vector<std::string> stages{"energy"};
            if (physical.physical_dimension == 2 && (result.thermal_mode == "model_h" || result.thermal_mode == "temperature")) stages.push_back("fine_energy");
            for (const auto& stage : stages) {
                const auto found = physical.details.find(stage);
                const Object empty;
                const auto& row = found == physical.details.end() ? empty : std::get<Object>(found->second.value);
                const bool available = row.count("status") && std::get<std::string>(row.at("status").value) == "available";
                checks_list.emplace_back(stage + " ledger available", available ? Truth(true) : Truth{});
                if (available) {
                    const auto& complete = row.at("physical_boundary_complete").value;
                    checks_list.emplace_back(stage + " physical boundary complete", std::holds_alternative<bool>(complete) ? Truth(std::get<bool>(complete)) : Truth{});
                }
            }
            const auto& mass = std::get<Object>(physical.details.at("mass").value);
            for (std::size_t side = 0; side < 2; ++side) {
                const auto found = sides.find(side_name(side));
                if (!result.pressure[side] && full_execution && result.execution_sides_access_error)
                    (void)*result.execution_sides_access_error;
                if (result.pressure[side] || (found != sides.end() && found->second.solved.is_true())) {
                    const auto& row = std::get<Object>(mass.at(side_name(side)).value);
                    checks_list.emplace_back(side_name(side) + " thermal mass faces available",
                        std::get<std::string>(row.at("status").value) == "available" ? Truth(true) : Truth{});
                }
            }
            try {
                const auto route = energy_gates(result);
                checks_list.insert(checks_list.end(), route.begin(), route.end());
            } catch (const NumericError& error) {
                if (error.cause != key_error && error.cause != TPMSHX_RESULT_TYPE_ERROR && error.cause != not_implemented) throw;
                checks_list.emplace_back("route energy certificate unavailable", Truth{});
                out.physical.details.emplace("reason", error.what());
            }
            out.physical.details.insert_or_assign("checks", gate_report(checks_list));
            out.physical.details.emplace("balance", report(physical));
            out.physical.passed = gate_passed(checks_list);
            out.physical.status = verdict(out.physical.passed, "").status;
        } catch (const NumericError& error) {
            if (error.cause == key_error || error.cause == TPMSHX_RESULT_TYPE_ERROR)
                out.physical.details.emplace("reason", error.what());
            else if (error.cause == TPMSHX_RESULT_VALUE_ERROR || error.cause == TPMSHX_RESULT_INDEX_ERROR)
                out.physical = verdict(false, out.physical.source, {{"checks", List{}}, {"reason", error.what()}});
            else throw;
        }
        catch (const std::invalid_argument& error) {out.physical = verdict(false, out.physical.source, {{"checks", List{}}, {"reason", error.what()}});}
        catch (const std::out_of_range& error) {out.physical = verdict(false, out.physical.source, {{"checks", List{}}, {"reason", error.what()}});}
    } else out.physical.details.emplace("reason", "Quick Design does not provide a full physical solve");
    try {
        const auto application = evaluate_applicability(result, host);
        List checks_list;
        const auto found = application.details.find("checks");
        if (found != application.details.end()) {
            const auto& groups = std::get<Object>(found->second.value);
            for (const auto& group : {"inlet", "final"}) {
                for (const auto& input : std::get<List>(groups.at(group).value)) {
                    const auto& row = std::get<Object>(input.value);
                    checks_list.emplace_back(Object{{"group", group}, {"side", row.at("side")}, {"source", row.at("source")},
                        {"quantity", row.at("quantity")}, {"status", row.at("status")}, {"passed", row.at("within_limit")}});
                }
            }
        }
        out.applicability = verdict(application.within_limits, "metadata.applicability_evidence",
            {{"definition", application.definition}, {"state", application.status},
            {"missing", application.details.count("missing") ? application.details.at("missing") : Report(List{})},
            {"scope_notes", application.details.count("scope_notes") ? application.details.at("scope_notes") : Report(List{})},
            {"checks", checks_list}});
    } catch (const NumericError& error) {
        if (error.cause != key_error && error.cause != TPMSHX_RESULT_TYPE_ERROR &&
            error.cause != TPMSHX_RESULT_VALUE_ERROR && error.cause != TPMSHX_RESULT_INDEX_ERROR) throw;
        out.applicability = verdict(false, "metadata.applicability_evidence", {{"reason", error.what()}});
    } catch (const std::invalid_argument& error) {
        out.applicability = verdict(false, "metadata.applicability_evidence", {{"reason", error.what()}});
    } catch (const std::out_of_range& error) {
        out.applicability = verdict(false, "metadata.applicability_evidence", {{"reason", error.what()}});
    }
    Object statuses;
    std::vector<Truth> availability;
    for (const auto& name : {"Q", "Q_B", "dP_A", "dP_B", "T_out_A", "T_out_B"}) {
        const auto found = metrics_values.find(name);
        const auto status = found == metrics_values.end() ? "not_evaluated" : found->second.status;
        statuses.emplace(name, status);
        availability.push_back(status == "not_evaluated" ? Truth{} : Truth(status == "available"));
    }
    const auto available = all_known(availability);
    out.metrics = verdict(available, "PerformanceResult.metrics", {{"required", statuses}});
    if (full_execution && result.execution_sides_error) (void)*result.execution_sides_error;
    const bool recorded = sides.size() == 2 && sides.count("A") && sides.count("B") &&
        std::all_of(sides.begin(), sides.end(), [](const auto& row){return row.second.fluid && !row.second.fluid->empty() && row.second.solved.is_bool;});
    Truth scope = recorded ? Truth(true) : Truth{};
    std::string scope_reason = recorded ? "" : "executed side models were not fully recorded";
    const bool sco2 = std::any_of(sides.begin(), sides.end(), [](const auto& row){return row.second.fluid == "sco2" && row.second.solved.value == true;});
    if (sco2) {scope.reset(); scope_reason = "sCO2 joint P/T/Pr and wall heating or cooling qualification remains unverified";}
    out.model_scope = verdict(scope, "metadata.execution_record.sides", {{"reason", scope_reason}});
    const std::vector<std::pair<std::string, Truth>> requirements{{"execution", completed}, {"convergence", out.convergence.passed},
        {"physical", out.physical.passed}, {"applicability", out.applicability.passed}, {"metrics", available},
        {"model_scope", scope}, {"full_solve", full_compute ? Truth(true) : Truth{}}};
    Object design_requirements, optimization_requirements;
    List reasons, optimization_reasons, deferred;
    std::vector<Truth> design_values, optimization_values;
    for (const auto& requirement : requirements) {
        design_requirements.emplace(requirement.first, Report(requirement.second));
        design_values.push_back(requirement.second);
        if (requirement.second != true) reasons.emplace_back(requirement.first);
        if (recorded && sco2 && requirement.first == "model_scope") {deferred.emplace_back(requirement.first); continue;}
        optimization_requirements.emplace(requirement.first, Report(requirement.second));
        optimization_values.push_back(requirement.second);
        if (requirement.second != true) optimization_reasons.emplace_back(requirement.first);
    }
    out.optimization = verdict(all_known(optimization_values), "result_qualification_v1 required optimization gates",
        {{"requirements", optimization_requirements}, {"reasons", optimization_reasons}, {"deferred", deferred}});
    out.design_eligible = all_known(design_values);
    out.design_status = out.design_eligible == true ? "eligible" : out.design_eligible == false ? "rejected" : "unverified";
    out.design_details = {{"requirements", design_requirements}, {"reasons", reasons},
        {"scope", "current recorded numerical and model gates; experimental and desktop acceptance remain separate"}};
    return out;
}

Evaluation evaluate(const ResultEvidence& result, const std::optional<MetricSpec>& requested, const HostControl* host) {
    HostScope host_scope(host);
    declarations(result);
    if (result.dimension != 2 && result.dimension != 3) throw std::invalid_argument("postprocessing requires physical dimension 2 or 3");
    if (result.invalid_mode_repr) throw std::invalid_argument("unsupported postprocessing mode: " + *result.invalid_mode_repr);
    if (result.mode != "full" && result.mode != "quick_design") throw std::invalid_argument("unsupported postprocessing mode: " + python_repr(result.mode));
    Evaluation out;
    out.source_result_id = result.result_id;
    MetricEvaluation compute(result, out.diagnostics);
    for (const auto& definition : definitions(result)) {
        if (requested && requested->name != definition.kind && requested->name != definition.name) continue;
        const auto version = result.mode == "full" ? full_version(definition.name) : "three_module_v1";
        MetricValue value;
        value.spec = requested.value_or(MetricSpec{definition.kind, definition.unit, version, result.mode == "full" ? description(definition.name) : ""});
        try {
            if (value.spec.unit != definition.unit || value.spec.definition_version != version)
                throw Unsupported("unsupported requested definition: " + spec_repr(value.spec));
            const auto number = compute.get(definition.name);
            if (!std::isfinite(number)) throw std::invalid_argument("native evidence produced a non-finite metric");
            value.value = number;
        } catch (const Missing& error) {value.status = "insufficient_data"; value.reason = "missing or incomplete evidence: " + std::string(error.what());}
        catch (const Unsupported& error) {value.status = "unsupported"; value.reason = error.what();}
        catch (const NumericError& error) {
            if (error.cause == key_error || error.cause == TPMSHX_RESULT_TYPE_ERROR) {
                value.status = "insufficient_data";
                value.reason = "missing or incomplete evidence: " + std::string(error.what());
            } else if (error.cause == not_implemented) {
                value.status = "unsupported"; value.reason = error.what();
            } else if (error.cause == TPMSHX_RESULT_VALUE_ERROR || error.cause == TPMSHX_RESULT_INDEX_ERROR) {
                value.status = "invalid"; value.reason = error.what();
            } else throw;
        } catch (const std::invalid_argument& error) {value.status = "invalid"; value.reason = error.what();}
        catch (const std::out_of_range& error) {value.status = "invalid"; value.reason = error.what();}
        out.metric_order.push_back(definition.name);
        out.metrics.emplace(definition.name, std::move(value));
    }
    if (requested && out.metrics.empty()) {
        out.metric_order.push_back(requested->name);
        out.metrics.emplace(requested->name, MetricValue{{}, *requested, "unsupported", "unknown metric"});
    }
    out.qualification = evaluate_qualification(result, out.metrics, host);
    return out;
}

Report report(const Applicability& value) {
    Object out{{"definition", value.definition}, {"status", value.status}, {"within_limits", Report(value.within_limits)}};
    for (const auto& row : value.details) out.emplace(row.first, row.second);
    return out;
}
Report report(const PhysicalBalance& value) {
    Object out{{"definition", value.definition}, {"physical_dimension", value.physical_dimension}};
    for (const auto& row : value.details) out.emplace(row.first, row.second);
    return out;
}
Report report(const Qualification& value) {
    Object design{{"status", value.design_status}, {"eligible", Report(value.design_eligible)}};
    for (const auto& row : value.design_details) design.emplace(row.first, row.second);
    return Object{{"definition", value.definition}, {"source_result_id", value.source_result_id},
        {"execution", verdict_report(value.execution)}, {"convergence", verdict_report(value.convergence)},
        {"physical", verdict_report(value.physical)}, {"applicability", verdict_report(value.applicability)},
        {"metrics", verdict_report(value.metrics)}, {"model_scope", verdict_report(value.model_scope)},
        {"optimization", verdict_report(value.optimization)}, {"design", design}};
}
Report report(const Evaluation& value) {
    Object metrics_record;
    for (const auto& item : value.metrics) {
        const auto& metric = item.second;
        metrics_record.emplace(item.first, Object{{"value", metric.value ? Report(*metric.value) : Report()},
            {"spec", Object{{"name", metric.spec.name}, {"unit", metric.spec.unit}, {"definition_version", metric.spec.definition_version}, {"description", metric.spec.description}}},
            {"status", metric.status}, {"reason", metric.reason}});
    }
    return Object{{"source_result_id", value.source_result_id}, {"metrics", metrics_record}, {"qualification", report(value.qualification)}};
}
namespace {
void json_string(std::ostream& out, const std::string& value) {
    out << '"';
    const char* hex = "0123456789abcdef";
    for (const auto c : value) {
        const auto byte = static_cast<unsigned char>(c);
        if (c == '"' || c == '\\') out << '\\' << c;
        else if (byte < 32) out << "\\u00" << hex[byte >> 4] << hex[byte & 15];
        else out << c;
    }
    out << '"';
}
void json_value(std::ostream& out, const Report& value) {
    std::visit([&out](const auto& item) {
        using T = std::decay_t<decltype(item)>;
        if constexpr (std::is_same_v<T, std::nullptr_t>) out << "null";
        else if constexpr (std::is_same_v<T, bool>) out << (item ? "true" : "false");
        else if constexpr (std::is_same_v<T, std::string>) json_string(out, item);
        else if constexpr (std::is_same_v<T, Report::List>) {
            out << '[';
            for (std::size_t i = 0; i < item.size(); ++i) {if (i) out << ','; json_value(out, item[i]);}
            out << ']';
        } else if constexpr (std::is_same_v<T, Report::Object>) {
            out << '{'; bool first = true;
            for (const auto& row : item) {if (!first) out << ','; first = false; json_string(out, row.first); out << ':'; json_value(out, row.second);}
            out << '}';
        } else if constexpr (std::is_same_v<T, double>) {
            if (std::isnan(item)) out << "NaN";
            else if (std::isinf(item)) out << (item > 0 ? "Infinity" : "-Infinity");
            else out << std::setprecision(std::numeric_limits<double>::max_digits10) << std::showpoint << item << std::noshowpoint;
        } else out << item;
    }, value.value);
}
}  // namespace
std::string json(const Report& value) {
    std::ostringstream out;
    out.imbue(std::locale::classic());
    json_value(out, value);
    return out.str();
}
}  // namespace tpmshx::result::stage
