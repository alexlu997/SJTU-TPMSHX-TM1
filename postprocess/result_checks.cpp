#include "tpmshx/result_checks.hpp"
#include "../numerics/scalar_range_samples.hpp"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <limits>
#include <vector>

namespace tpmshx::result::checks {
namespace {
namespace a = arithmetic;

std::array<double, 2> margin(double lower, double upper) {
    constexpr double allowance=.1;
    return {(1.-allowance)*lower,(1.+allowance)*upper};
}
}  // namespace

tpmshx_result_range_sample_v1 collect_range(const Array& values, double lower, double upper) {
    return detail::collect_range<tpmshx_result_range_sample_v1>(values.size(),
        [&](std::size_t index) {return values.at(index);},lower,upper);
}

tpmshx_result_scalar_sample_indices_v1 scalar_samples(const Array& values, double lower, double upper) {
    tpmshx_result_scalar_sample_indices_v1 output{};
    const auto selected=detail::scalar_range_samples(values.size(),
        [&](std::size_t index) {return values.at(index);},lower,upper);
    output.count=selected.size();
    std::copy(selected.begin(),selected.end(),output.indices);
    return output;
}

std::array<double,2> parameter_bounds(double lower,double upper) {
    if (!(std::isfinite(lower) && std::isfinite(upper) && 0.<lower && lower<=upper))
        throw std::invalid_argument("relative range limits require positive ordered source bounds");
    return margin(lower,upper);
}

tpmshx_result_source_bounds_values_v1 source_bounds(double lower,double upper) {
    if (!(std::isfinite(lower) && std::isfinite(upper) && lower<=upper))
        throw std::invalid_argument("range evidence requires finite ordered source bounds");
    const bool positive=lower>0.;
    const auto allowed=positive?margin(lower,upper):std::array<double,2>{lower,upper};
    return {allowed[0],allowed[1],positive?.1:0.,positive?1u:0u};
}

tpmshx_result_range_decision_v1 range_values(double lower,double upper,double minimum,
    double maximum,bool hard_bounds) {
    const auto bounds=source_bounds(lower,upper);
    if (!(std::isfinite(minimum) && std::isfinite(maximum) && minimum<=maximum))
        throw std::invalid_argument("range evidence requires finite ordered extrema");
    if (lower<=minimum && maximum<=upper)
        return {0.,TPMSHX_RESULT_WITHIN_ORIGINAL,1};
    if (!hard_bounds && !bounds.positive)
        return {0.,TPMSHX_RESULT_DOMAIN_RULE_REQUIRED,0};
    const double infinity=std::numeric_limits<double>::infinity();
    const bool inside=hard_bounds?(lower<=minimum && maximum<=upper):
        (std::nextafter(bounds.lower,-infinity)<=minimum && maximum<=std::nextafter(bounds.upper,infinity));
    double fraction=0.;
    if (bounds.positive) {
        const double below=(lower-minimum)/lower,above=(maximum-upper)/upper;
        if (below>fraction) fraction=below;
        if (above>fraction) fraction=above;
    }
    return {fraction,static_cast<std::uint32_t>(inside?TPMSHX_RESULT_WITHIN_MARGIN:TPMSHX_RESULT_OUTSIDE_LIMIT),
        bounds.positive};
}

tpmshx_result_array_check_values_v1 array_checks(const Array& values) {
    tpmshx_result_array_check_values_v1 output{1,1};
    for (std::size_t index=0; index<values.size(); ++index) {
        const auto value=values.at(index);
        output.all_finite=output.all_finite && std::isfinite(value);
        output.all_zero=output.all_zero && value==0.;
    }
    return output;
}

tpmshx_result_strict_values_v1 strict_certificate(bool active_b,const std::array<double,4>& ratios,
    double source_a,double source_b) {
    tpmshx_result_strict_values_v1 output{};
    for (std::size_t index=0; index<(active_b?4u:2u); ++index)
        output.strict[index]=std::isfinite(ratios[index]) && 0.<=ratios[index] && ratios[index]<.01;
    const double first=std::abs(source_a),second=std::abs(source_b);
    double scale=first;
    if (second>scale) scale=second;
    if (1.>scale) scale=1.;
    output.source_residual=std::abs(source_a+source_b);
    output.source_normalization=scale;
    output.epsilon_ltne=output.source_residual/scale;
    output.source_pass=std::isfinite(output.epsilon_ltne) && output.epsilon_ltne<.01;
    return output;
}

// Python float comparisons: NaN fails each ordered test without a notice.
bool energy_ratio(double ratio,double tolerance) {
    return std::isfinite(ratio) && std::isfinite(tolerance)
        && 0.<=ratio && ratio<=tolerance && 0.<tolerance;
}

double pressure_square(double inlet) {
    const double output=std::pow(inlet,2.);
    if (std::isfinite(inlet) && std::isinf(output))
        throw NumericError(TPMSHX_RESULT_OVERFLOW,"Result too large",ERANGE);
    return output;
}
double outlet_pressure_squared(double square,double gas_constant,double temperature,double drag,double length) {
    return square-2.*gas_constant*temperature*drag*length;
}
double sound_speed(double gamma,double gas_constant,double temperature) {
    const double square=gamma*gas_constant*temperature;
    if (square<0.) throw NumericError(TPMSHX_RESULT_VALUE_ERROR,"math domain error");
    return std::sqrt(square);
}
double mach_from_sound(double speed,double sound) {
    if (sound==0.) throw NumericError(TPMSHX_RESULT_ZERO_DIVISION,"float division by zero");
    return speed/sound;
}

a::Tensor field_temperature_floor(const Array& temperature,Diagnostics& diagnostics) {
    const auto floor=a::scalar(a::python_float(1.));
    return a::maximum(temperature,floor.array(),diagnostics);
}
a::Tensor field_sound_speed(const Array& temperature,double gamma,double gas_constant,Diagnostics& diagnostics) {
    const auto factor=a::scalar(a::python_float(gamma*gas_constant));
    const auto square=a::multiply(factor.array(),temperature,diagnostics);
    return a::square_root(square.array(),diagnostics);
}
double field_mach_max(const Array& speed,const Array& sound,Diagnostics& diagnostics) {
    const auto ratio=a::divide(speed,sound,diagnostics);
    return a::maximum(ratio.array()).value;
}
std::uint32_t pressure_flags(double pressure,double floor,double allowance) {
    if (!std::isfinite(pressure)) return 1;
    return pressure<=floor*(1.+allowance)?2u:0u;
}
std::uint32_t mach_limit_flags(double mach,double limit) {
    if (!std::isfinite(mach)) return 1;
    return limit<=mach?2u:0u;
}
std::uint32_t mach_limit_array_flags(double mach,const Array& limit) {
    if (!std::isfinite(mach)) return 1;
    return limit.size()==1 && limit.at(0)<=mach?2u:0u;
}
double box_density_length(double density,double length) {return density*length;}
double box_bulk_mass(double density_length,double height,double depth) {return density_length*height*depth;}
double box_solid_mass(double bulk_mass,double epsilon) {return bulk_mass*(1.-epsilon);}
arithmetic::Tensor box_density_length_array(const Array& density,const Array& length,Diagnostics& diagnostics) {
    return a::multiply(density,length,diagnostics);
}
arithmetic::Tensor box_bulk_mass_array(const Array& density_length,const Array& height,
    const Array& depth,Diagnostics& diagnostics) {
    auto first=a::multiply(density_length,height,diagnostics);
    if (first.shape.empty()) first.kind=Kind::numpy_scalar;
    return a::multiply(first.array(),depth,diagnostics);
}
arithmetic::Tensor box_solid_mass_array(const Array& bulk_mass,const Array& epsilon,Diagnostics& diagnostics) {
    const auto one=a::scalar(a::python_float(1.));
    auto fraction=a::subtract(one.array(),epsilon,diagnostics);
    if (fraction.shape.empty()) fraction.kind=Kind::numpy_scalar;
    return a::multiply(bulk_mass,fraction.array(),diagnostics);
}

}  // namespace tpmshx::result::checks
