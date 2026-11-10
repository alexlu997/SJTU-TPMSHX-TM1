#include "tpmshx/result_checks.hpp"

#include <algorithm>
#include <cerrno>
#include <cmath>
#include <limits>
#include <vector>

namespace tpmshx::result::checks {
namespace {
namespace a = arithmetic;

void require_double(const Array& values) {
    if (values.raw().dtype != TPMSHX_RESULT_F64)
        throw std::invalid_argument("range and Mach field buffers require float64");
}
double double_at(const Array& values, std::size_t index) {
    return static_cast<double>(real_value(values.at(index)));
}
std::array<double, 2> margin(double lower, double upper) {
    constexpr double allowance=.1;
    return {(1.-allowance)*lower,(1.+allowance)*upper};
}
}  // namespace

tpmshx_result_range_sample_v1 collect_range(const Array& values, double lower, double upper) {
    require_double(values);
    tpmshx_result_range_sample_v1 output{};
    output.size = values.size();
    for (std::size_t index=0; index<values.size(); ++index) {
        const double value=double_at(values,index);
        if (!std::isfinite(value)) {++output.nonfinite;continue;}
        if (!output.have_finite) {
            output.minimum=output.maximum=value;
            output.minimum_index=output.maximum_index=index;
            output.have_finite=1;
        } else {
            if (value<output.minimum) {output.minimum=value;output.minimum_index=index;}
            if (value>output.maximum) {output.maximum=value;output.maximum_index=index;}
        }
        output.low += value<lower;
        output.high += value>upper;
    }
    return output;
}

tpmshx_result_scalar_sample_indices_v1 scalar_samples(const Array& values, double lower, double upper) {
    require_double(values);
    tpmshx_result_scalar_sample_indices_v1 output{};
    if (!values.size()) return output;
    std::vector<std::size_t> selected{0,values.size()-1};
    const auto sample=collect_range(values,lower,upper);
    if (sample.have_finite) {
        selected.push_back(sample.minimum_index);
        selected.push_back(sample.maximum_index);
    }
    bool first_nonfinite=true,first_below=true,first_above=true,first_violation=true;
    for (std::size_t index=0; index<values.size(); ++index) {
        const double value=double_at(values,index);
        const bool is_finite=std::isfinite(value),below=value<lower,above=value>upper;
        if (first_nonfinite && !is_finite) {selected.push_back(index);first_nonfinite=false;}
        if (first_below && below) {selected.push_back(index);first_below=false;}
        if (first_above && above) {selected.push_back(index);first_above=false;}
        if (first_violation && is_finite && (below || above)) {
            selected.push_back(index);first_violation=false;
        }
    }
    std::sort(selected.begin(),selected.end());
    selected.erase(std::unique(selected.begin(),selected.end()),selected.end());
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
        output.all_finite=output.all_finite && finite(value);
        output.all_zero=output.all_zero && zero(value);
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

bool energy_ratio(const Number& ratio,const Number& tolerance,Diagnostics& diagnostics) {
    const auto as_double=[](const Number& value) {
        if (complex_type(value.dtype) && value.origin==TPMSHX_RESULT_PYTHON_COMPLEX)
            throw NumericError(TPMSHX_RESULT_TYPE_ERROR,"must be real number, not complex");
        return static_cast<double>(complex_type(value.dtype)?value.real:real_value(value));
    };
    return std::isfinite(as_double(ratio)) && std::isfinite(as_double(tolerance))
        && a::less_equal(a::python_float(0.),ratio,diagnostics)
        && a::less_equal(ratio,tolerance,diagnostics)
        && a::less(a::python_float(0.),tolerance,diagnostics);
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
    require_double(temperature);
    const auto floor=a::scalar(a::python_float(1.));
    return a::maximum(temperature,floor.array(),diagnostics);
}
a::Tensor field_sound_speed(const Array& temperature,double gamma,double gas_constant,Diagnostics& diagnostics) {
    require_double(temperature);
    const auto factor=a::scalar(a::python_float(gamma*gas_constant));
    const auto square=a::multiply(factor.array(),temperature,diagnostics);
    return a::square_root(square.array(),diagnostics);
}
double field_mach_max(const Array& speed,const Array& sound,Diagnostics& diagnostics) {
    require_double(speed);require_double(sound);
    const auto ratio=a::divide(speed,sound,diagnostics);
    return a::to_float(a::maximum(ratio.array(),diagnostics));
}
std::uint32_t pressure_flags(const Number& pressure,double floor,double allowance,Diagnostics& diagnostics) {
    if (!finite(pressure)) return 1;
    if (pressure.origin==TPMSHX_RESULT_PYTHON_COMPLEX)
        throw NumericError(TPMSHX_RESULT_TYPE_ERROR,"'<=' not supported between instances of 'complex' and 'float'");
    return a::less_equal(pressure,a::python_float(floor*(1.+allowance)),diagnostics)?2u:0u;
}
std::uint32_t mach_limit_flags(const Number& mach,const Number& limit,Diagnostics& diagnostics) {
    if (!finite(mach)) return 1;
    if (limit.origin==TPMSHX_RESULT_PYTHON_COMPLEX && mach.origin==TPMSHX_RESULT_PYTHON_FLOAT)
        throw NumericError(TPMSHX_RESULT_TYPE_ERROR,"'>=' not supported between instances of 'float' and 'complex'");
    return a::less_equal(limit,mach,diagnostics)?2u:0u;
}
std::uint32_t mach_limit_array_flags(const Number& mach,const Array& limit,Diagnostics& diagnostics) {
    if (!finite(mach)) return 1;
    Number point{};
    point.dtype=limit.raw().dtype;point.origin=limit.raw().origin;
    if (limit.size()) point=limit.at(0);
    // The weak cast precedes array truth, including empty arrays. Its flags
    // depend on the dtype and Mach, not on unused comparison elements.
    const bool comparison=a::less_equal(point,mach,diagnostics);
    return limit.size()==1 && comparison?2u:0u;
}
Number box_density_length(const Number& density,const Number& length,Diagnostics& diagnostics) {
    return a::scalar_result(a::multiply(density,length,diagnostics));
}
Number box_bulk_mass(const Number& density_length,const Number& height,const Number& depth,Diagnostics& diagnostics) {
    const auto first=a::scalar_result(a::multiply(density_length,height,diagnostics));
    return a::scalar_result(a::multiply(first,depth,diagnostics));
}
Number box_solid_mass(const Number& bulk_mass,const Number& epsilon,Diagnostics& diagnostics) {
    const auto fraction=a::scalar_result(a::subtract(a::python_float(1.),epsilon,diagnostics));
    return a::scalar_result(a::multiply(bulk_mass,fraction,diagnostics));
}
arithmetic::Tensor box_density_length_array(const Array& density,const Array& length,Diagnostics& diagnostics) {
    return a::multiply(density,length,diagnostics);
}
arithmetic::Tensor box_bulk_mass_array(const Array& density_length,const Array& height,
    const Array& depth,Diagnostics& diagnostics) {
    auto first=a::multiply(density_length,height,diagnostics);
    if (first.shape.empty() && first.origin==TPMSHX_RESULT_NUMPY_ARRAY)
        first.origin=TPMSHX_RESULT_NUMPY_SCALAR;
    return a::multiply(first.array(),depth,diagnostics);
}
arithmetic::Tensor box_solid_mass_array(const Array& bulk_mass,const Array& epsilon,Diagnostics& diagnostics) {
    const auto one=a::scalar(a::python_float(1.));
    auto fraction=a::subtract(one.array(),epsilon,diagnostics);
    if (fraction.shape.empty() && fraction.origin==TPMSHX_RESULT_NUMPY_ARRAY)
        fraction.origin=TPMSHX_RESULT_NUMPY_SCALAR;
    return a::multiply(bulk_mass,fraction.array(),diagnostics);
}

}  // namespace tpmshx::result::checks
