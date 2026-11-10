#include "tpmshx/preparation_df.hpp"
#include "tpmshx/preparation_df_data.hpp"
#include "preparation_properties.hpp"
#include "preparation_df_fields.hpp"

#include <algorithm>
#include <array>
#include <cfenv>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace tpmshx::preparation {
namespace {
namespace data = df_data;
static_assert(property_event_count == TPMSHX_PREPARATION_FP_EVENT_COUNT,
              "DF pressure and property arithmetic need the same event extent");
constexpr const char* outside =
    "geometry is outside the fixed sCO2 CFD grid: 4 <= L <= 8 mm and 0.3 <= t <= 0.6 mm";
struct Bracket { std::int64_t lower, upper; double weight; };

void topology_check(std::uint32_t topology) {
    if (topology > 1) throw std::invalid_argument("fixed sCO2 CFD coefficients support Diamond/Gyroid only");
}

template<class Nodes> Bracket bracket(double value, const Nodes& nodes) {
    const double tolerance = data::df_bracket_relative_tolerance * std::max(1., std::abs(value));
    if (value < nodes.front() - tolerance || value > nodes.back() + tolerance)
        throw std::invalid_argument(outside);
    value = std::min(std::max(value, nodes.front()), nodes.back());
    const auto upper = static_cast<std::int64_t>(std::lower_bound(nodes.begin(), nodes.end(), value) - nodes.begin());
    if (upper < static_cast<std::int64_t>(nodes.size())
        && std::abs(value - nodes[static_cast<std::size_t>(upper)]) <= tolerance)
        return {upper, upper, 0.};
    const auto lower = upper - 1;
    const auto lo = lower == -1 ? nodes.size() - 1 : static_cast<std::size_t>(lower);
    return {lower, upper, (value - nodes[lo]) / (nodes[static_cast<std::size_t>(upper)] - nodes[lo])};
}

double value(std::uint32_t topology, const Bracket& length, const Bracket& wall, std::size_t component) {
    const auto l0 = length.lower == -1 ? data::df_L_nodes.size() - 1 : static_cast<std::size_t>(length.lower);
    const auto l1 = static_cast<std::size_t>(length.upper);
    const auto t0 = wall.lower == -1 ? data::df_t_nodes.size() - 1 : static_cast<std::size_t>(wall.lower);
    const auto t1 = static_cast<std::size_t>(wall.upper);
    const auto& table = data::df_values[topology];
    const double low = (1. - length.weight) * table[l0][t0][component]
                     + length.weight * table[l1][t0][component];
    const double high = (1. - length.weight) * table[l0][t1][component]
                      + length.weight * table[l1][t1][component];
    return (1. - wall.weight) * low + wall.weight * high;
}

class FloatingEnvironment {
public:
    FloatingEnvironment() { std::fegetenv(&environment_); }
    ~FloatingEnvironment() { std::fesetenv(&environment_); }
private:
    std::fenv_t environment_;
};
PropertyNumber number(grid::Scalar value) { return {value,0.,0,value.strong ? 1u : 0u}; }
PropertyNumber weak(double value) { return number(grid::weak(value)); }
PropertyNumber gradient(PropertyNumber density,PropertyNumber viscosity,PropertyNumber speed,
    PropertyNumber permeability,PropertyNumber inertial,
    std::array<std::uint32_t,property_event_count>& events) {
    PropertyArithmetic arithmetic(events);
    const auto viscous_product = arithmetic.multiply(viscosity,speed);
    const auto viscous = arithmetic.divide(viscous_product,permeability);
    const auto inertial_coefficient = arithmetic.multiply(density,inertial);
    const auto first_velocity = arithmetic.multiply(inertial_coefficient,speed);
    const auto second_velocity = arithmetic.multiply(first_velocity,speed);
    return arithmetic.add(viscous,second_velocity);
}
DfPressure pressure_result(PropertyNumber value, double outlet_squared, bool no_positive,
    const std::array<std::uint32_t,property_event_count>& events) {
    DfPressure result{};
    result.dP_Pa = value.real.value; result.outlet_squared_Pa = outlet_squared;
    result.no_positive_outlet = no_positive ? 1u : 0u;
    result.precision = value.real.precision; result.strong = value.real.strong;
    std::copy(events.begin(),events.end(),result.floating_events);
    return result;
}
}  // namespace

DfPair fixed_df(std::uint32_t topology, double length_mm, double wall_mm) {
    topology_check(topology);
    const auto length = bracket(length_mm, data::df_L_nodes);
    const auto wall = bracket(wall_mm, data::df_t_nodes);
    return {value(topology, length, wall, 0), value(topology, length, wall, 1)};
}

std::vector<DfPair> fixed_df_batch(std::uint32_t topology,
    ArrayView<const double> lengths, ArrayView<const double> walls) {
    topology_check(topology);
    if (lengths.size != walls.size) throw std::invalid_argument("fixed DF fields must have matching extents");
    std::vector<Bracket> l(lengths.size), t(walls.size);
    for (std::size_t i = 0; i < lengths.size; ++i) l[i] = bracket(lengths[i], data::df_L_nodes);
    for (std::size_t i = 0; i < walls.size; ++i) t[i] = bracket(walls[i], data::df_t_nodes);
    std::vector<DfPair> output(lengths.size);
    for (std::size_t i = 0; i < output.size(); ++i)
        output[i] = {value(topology, l[i], t[i], 0), value(topology, l[i], t[i], 1)};
    return output;
}

double df_incompressible(std::uint32_t topology, double length_mm, double wall_mm,
    double speed, double density, double viscosity, double channel_length) {
    return df_incompressible_typed(topology,length_mm,wall_mm,grid::weak(speed),grid::weak(density),
                                  grid::weak(viscosity),grid::weak(channel_length)).dP_Pa;
}

DfPressure df_incompressible_typed(std::uint32_t topology, double length_mm, double wall_mm,
    grid::Scalar speed, grid::Scalar density, grid::Scalar viscosity, grid::Scalar channel_length) {
    const auto drag = fixed_df(topology, length_mm, wall_mm);
    FloatingEnvironment environment;
    std::array<std::uint32_t,property_event_count> events{};
    PropertyArithmetic arithmetic(events);
    {
        const auto viscous_product = arithmetic.multiply(number(viscosity),number(speed));
        const auto viscous = arithmetic.divide(viscous_product,weak(drag.K));
        const auto inertial_coefficient = arithmetic.multiply(number(density),weak(drag.cF));
        const auto squared_speed = arithmetic.power(number(speed),weak(2.));
        const auto inertial = arithmetic.multiply(inertial_coefficient,squared_speed);
        const auto gradient = arithmetic.add(viscous,inertial);
        const auto result = arithmetic.multiply(gradient,number(channel_length));
        return pressure_result(result,0.,false,events);
    }
}

DfPressure df_compressible(std::uint32_t topology, double length_mm, double wall_mm,
    double mass_flux, double temperature, double inlet_pressure, double viscosity,
    double channel_length, bool strict) {
    return df_compressible_typed(topology,length_mm,wall_mm,grid::weak(mass_flux),grid::weak(temperature),
        grid::weak(inlet_pressure),grid::weak(viscosity),grid::weak(channel_length),strict);
}

DfPressure df_compressible_typed(std::uint32_t topology, double length_mm, double wall_mm,
    grid::Scalar mass_flux, grid::Scalar temperature, grid::Scalar inlet_pressure,
    grid::Scalar viscosity, grid::Scalar channel_length, bool strict) {
    const auto drag = fixed_df(topology, length_mm, wall_mm);
    FloatingEnvironment environment;
    std::array<std::uint32_t,property_event_count> events{};
    PropertyArithmetic arithmetic(events);
    {
        const auto viscous_product = arithmetic.multiply(number(viscosity),number(mass_flux));
        const auto viscous = arithmetic.divide(viscous_product,weak(drag.K));
        const auto squared_flux = arithmetic.power(number(mass_flux),weak(2.));
        const auto inertial = arithmetic.multiply(weak(drag.cF),squared_flux);
        const auto force = arithmetic.add(viscous,inertial);
        const auto squared_pressure = arithmetic.power(number(inlet_pressure),weak(2.));
        const auto gas_factor = arithmetic.multiply(weak(2.),weak(data::r_air_default));
        const auto thermal_factor = arithmetic.multiply(gas_factor,number(temperature));
        const auto pressure_gradient = arithmetic.multiply(thermal_factor,force);
        const auto pressure_loss = arithmetic.multiply(pressure_gradient,number(channel_length));
        const auto outlet_squared = arithmetic.subtract(squared_pressure,pressure_loss);
        if (outlet_squared.real.value <= 0.)
            return pressure_result(strict ? weak(std::numeric_limits<double>::quiet_NaN()) : number(inlet_pressure),
                                   outlet_squared.real.value,true,events);
        // The original math.sqrt returns a weak Python float.
        const auto outlet = weak(std::sqrt(outlet_squared.real.value));
        const auto drop = arithmetic.subtract(number(inlet_pressure),outlet);
        return pressure_result(drop,outlet_squared.real.value,false,events);
    }
}

PropertyResult df_pressure_gradient(PropertyInput density,PropertyInput viscosity,
    PropertyInput speed,PropertyInput permeability,PropertyInput inertial) {
    const auto count = density.values.size;
    for (const auto input : {density,viscosity,speed,permeability,inertial}) {
        if (input.values.size != count) throw std::invalid_argument("pressure-gradient input extents differ");
        grid::checked({0.,input.kind.precision,input.kind.strong});
        if (input.layout > 3 || (!input.kind.strong && input.layout) || (input.kind.strong && !input.layout))
            throw std::invalid_argument("pressure-gradient input layout does not match its scalar kind");
    }
    FloatingEnvironment environment;
    PropertyResult output;
    output.values.resize(count); output.imaginary.assign(count,0.);
    const auto point = [](PropertyInput input,std::size_t index,bool empty) {
        const double value = empty ? input.kind.value : input.values[index];
        return PropertyNumber{{value,input.kind.precision,input.kind.strong},0.,0,input.layout,
                              empty && input.layout == 3};
    };
    for (std::size_t i = 0; i < std::max(std::size_t{1},count); ++i) {
        const auto value = gradient(point(density,i,!count),point(viscosity,i,!count),
            point(speed,i,!count),point(permeability,i,!count),point(inertial,i,!count),output.events);
        if (!i) { output.kind = {0.,value.real.precision,value.real.strong}; output.category = value.category; }
        if (value.real.precision != output.kind.precision || value.real.strong != output.kind.strong
            || value.category != output.category)
            throw std::runtime_error("pressure-gradient result type varies within one array");
        if (count) { output.values[i] = value.real.value; output.imaginary[i] = value.imaginary; }
    }
    return output;
}

}  // namespace tpmshx::preparation
