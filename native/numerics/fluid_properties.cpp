#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "property_kernels.hpp"

#include <CoolProp/AbstractState.h>
#include <CoolProp/Exceptions.h>

#include <algorithm>
#include <cerrno>
#include <cfenv>
#include <cmath>
#include <mutex>
#include <string>


namespace tpmshx {
std::mutex detail::eos_factory_mutex;


std::unique_ptr<CoolProp::AbstractState> make_eos_state(const char* backend, const char* fluid) {
    // CoolProp lazily mutates shared fluid/table libraries during construction;
    // serialize initialization while all subsequent updates stay local.
    // ponytail: one factory lock; split initialization only if startup throughput matters.
    const std::lock_guard<std::mutex> lock(detail::eos_factory_mutex);
    if (!backend || !fluid) throw std::invalid_argument("missing EOS backend or fluid");
    auto state = std::unique_ptr<CoolProp::AbstractState>(CoolProp::AbstractState::factory(backend, fluid));
    return state;
}

namespace {
namespace data = model_coefficients;

void positive_state(double temperature, double pressure) {
    if (!std::isfinite(temperature) || !std::isfinite(pressure)
        || temperature <= 0. || pressure <= 0.)
        throw std::invalid_argument("properties require finite positive K and Pa(abs)");
}

std::size_t topology_row(Topology topology) {
    switch (topology) {
        case Topology::diamond: return 0;
        case Topology::gyroid: return 1;
    }
    throw std::invalid_argument("unsupported property topology");
}

void nu_inputs(double re,double length,double diameter) {
    if (!std::isfinite(re) || re < 0. || !std::isfinite(length) || length <= 0.
        || !std::isfinite(diameter) || diameter <= 0.)
        throw std::invalid_argument("Nu requires finite nonnegative Re and positive cell length/Dh");
}
}  // namespace

PropertyEvaluator::PropertyEvaluator() = default;
PropertyEvaluator::~PropertyEvaluator() = default;

double detail::check_water_pt(std::unique_ptr<CoolProp::AbstractState>& state,
                            double temperature, double pressure) {
    if (!std::isfinite(temperature) || !std::isfinite(pressure)
        || temperature <= 0. || pressure <= 0.)
        throw WaterStateError("water requires finite positive K and Pa(abs)");
    try {
        if (!state) state = make_eos_state("HEOS", "Water");
        state->update(CoolProp::PT_INPUTS, pressure, temperature);
        const auto phase = state->phase();
        if (phase == CoolProp::iphase_supercritical_liquid)
            throw WaterStateError("high-pressure liquid: T-only model applicability unconfirmed");
        if (phase != CoolProp::iphase_liquid)
            throw WaterStateError("only stable single-phase liquid water is supported");
        if (!state->has_melting_line())
            throw WaterStateError("solid/liquid stability unconfirmed");
        const double melting = state->melting_line(CoolProp::iT, CoolProp::iP, pressure);
        if (!std::isfinite(melting) || temperature <= melting)
            throw WaterStateError("freezing boundary or solid/metastable water unsupported");
        return melting;
    } catch (const CoolProp::CoolPropBaseError& error) {
        throw WaterStateError(error.what(),true);
    }
}

void detail::check_co2_pt(std::unique_ptr<CoolProp::AbstractState>& state,
                         double temperature, double pressure) {
    positive_state(temperature,pressure);
    if (!state) state = make_eos_state("HEOS", "CO2");
    if (temperature <= state->Ttriple())
        throw std::invalid_argument("CO2 at/below triple-point temperature is unsupported");
    state->update(CoolProp::PT_INPUTS,pressure,temperature);
    const auto phase = state->phase();
    if (phase != CoolProp::iphase_liquid && phase != CoolProp::iphase_gas
        && phase != CoolProp::iphase_supercritical && phase != CoolProp::iphase_supercritical_gas
        && phase != CoolProp::iphase_supercritical_liquid)
        throw std::invalid_argument("CO2 requires stable single-phase PT; saturation, two-phase and critical-point states are unsupported");
}

double PropertyEvaluator::check_water(double temperature, double pressure) {
    return detail::check_water_pt(water_,temperature,pressure);
}

void PropertyEvaluator::check_co2(double temperature, double pressure) {
    detail::check_co2_pt(co2_,temperature,pressure);
}

const std::array<double,5>& model_h_coefficients(Fluid fluid) {
    if(fluid==Fluid::air)return data::model_h_air;
    if(fluid==Fluid::water)return data::model_h_water;
    throw std::invalid_argument("model enthalpy requires air or water");
}

double nusselt_floor(Fluid fluid) {
    return data::nu_laminar_floor * (fluid == Fluid::co2 ? data::co2_nu_multiplier : 1.);
}

FluidProperties PropertyEvaluator::evaluate(Fluid fluid, double temperature, double pressure) {
    if (fluid == Fluid::water) check_water(temperature, pressure);
    return transport(fluid,temperature,pressure);
}

FluidProperties PropertyEvaluator::transport(Fluid fluid, double temperature, double pressure) {
    positive_state(temperature, pressure);
    FluidProperties result{};
    const auto empirical=[&](Empirical getter) {
        std::array<std::uint32_t,property_event_count> events{};
        return empirical_point(getter,temperature,pressure,events,false);
    };
    switch (fluid) {
        case Fluid::air: {
            result.rho=empirical(Empirical::air_density);
            result.mu=empirical(Empirical::air_viscosity);
            result.k=empirical(Empirical::air_conductivity);
            result.cp=empirical(Empirical::air_cp);
            break;
        }
        case Fluid::water: {
            result.rho=empirical(Empirical::water_density);
            result.mu=empirical(Empirical::water_viscosity);
            result.k=empirical(Empirical::water_conductivity);
            result.cp=empirical(Empirical::water_cp);
            break;
        }
        case Fluid::co2:
        case Fluid::sco2: {
            if (fluid == Fluid::sco2) {
            if (temperature < data::sco2_temperature_range[0] || temperature > data::sco2_temperature_range[1])
                throw std::invalid_argument(std::string("sCO2 temperature must be within ")+data::sco2_temperature_limits);
            if (pressure < data::sco2_pressure_range[0] || pressure > data::sco2_pressure_range[1])
                throw std::invalid_argument(std::string("sCO2 pressure must be within ")+data::sco2_pressure_limits);
            if (!co2_) co2_ = make_eos_state("HEOS", "CO2");
            co2_->update(CoolProp::PT_INPUTS, pressure, temperature);
            } else check_co2(temperature,pressure);
            result.rho = co2_->rhomass();
            result.mu = co2_->viscosity();
            result.k = co2_->conductivity();
            result.cp = co2_->cpmass();
            break;
        }
        default: throw std::invalid_argument("unsupported property fluid");
    }
    result.pr = result.mu * result.cp / result.k;
    for (const double value : {result.rho, result.mu, result.k, result.cp, result.pr})
        if (!std::isfinite(value) || value <= 0.)
            throw std::domain_error("nonfinite or nonpositive fluid property");
    return result;
}

double fluid_nusselt(Fluid fluid, Topology topology, double re,double pr,
                     double cell_length_m, double hydraulic_diameter_m,double sco2_multiplier) {
    nu_inputs(re,cell_length_m,hydraulic_diameter_m);
    return fluid_nusselt_ratio(fluid,topology,re,pr,hydraulic_diameter_m/cell_length_m,sco2_multiplier);
}

double fluid_nusselt_ratio(Fluid fluid, Topology topology, double re,double pr,
                           double hydraulic_to_cell_ratio,double sco2_multiplier) {
    nu_inputs(re,1.,hydraulic_to_cell_ratio);
    if (!std::isfinite(pr) || pr<=0. || !std::isfinite(sco2_multiplier) || sco2_multiplier<=0.)
        throw std::invalid_argument("Nu requires finite positive Pr and selected sCO2 multiplier");
    NuRoute route;
    switch (fluid) {
        case Fluid::air: route=NuRoute::air_direct;break;
        case Fluid::water: route=NuRoute::water;break;
        case Fluid::sco2: route=NuRoute::sco2;break;
        case Fluid::co2:
            if (re<=0.) throw std::invalid_argument("CO2 Nu requires positive Re");
            route=NuRoute::co2;break;
        default: throw std::invalid_argument("unsupported Nu fluid");
    }
    std::array<std::uint32_t,property_event_count> events{};
    const double source_re=fluid==Fluid::water || fluid==Fluid::sco2?std::max(re,1.):re;
    const double source_pr=fluid==Fluid::air?data::pr_air:pr;
    const double result=nu_point(route,topology,source_re,source_pr,1.,
        hydraulic_to_cell_ratio,sco2_multiplier,events,false);
    if (!std::isfinite(result) || result < 0.) throw std::domain_error("nonfinite or negative Nu");
    return result;
}

double PropertyEvaluator::quick_design_nu(Fluid fluid, Topology topology, double re,
                                         double cell_length_m, double hydraulic_diameter_m) {
    nu_inputs(re,cell_length_m,hydraulic_diameter_m);
    if (fluid == Fluid::co2) throw std::invalid_argument("CO2 is supported by full compute only");
    double pr=data::pr_air;
    if (fluid==Fluid::water || fluid==Fluid::sco2) {
        const auto& state=fluid==Fluid::water?data::water_nu_reference_state:data::sco2_nu_reference_state;
        pr=evaluate(fluid,state[0],state[1]).pr;
    }
    return fluid_nusselt(fluid,topology,re,pr,cell_length_m,hydraulic_diameter_m);
}

double nu_extra_roughness_factor(double re,RoughnessMode mode,double roughness_m,double diameter) {
    if (mode==RoughnessMode::baseline || mode==RoughnessMode::norris_1a) return 1.;
    if (mode!=RoughnessMode::bhatti_shah_1b) throw std::invalid_argument("unsupported roughness mode");
    if (!std::isfinite(re) || re<0. || !std::isfinite(roughness_m) || roughness_m<0.
        || !std::isfinite(diameter) || diameter<=0.) throw std::invalid_argument("invalid roughness inputs");
    return native_roughness_factor(re,roughness_m,diameter);
}

namespace {
using Number=PropertyNumber;
}  // namespace

PropertyArithmetic::PropertyArithmetic(std::array<std::uint32_t,property_event_count>& events,bool observe)
    :events_(events),observe_(observe) {}
Number PropertyArithmetic::add(Number a,Number b) {return apply(1,[&]{volatile double x=a,y=b;return x+y;});}
Number PropertyArithmetic::subtract(Number a,Number b) {return apply(2,[&]{volatile double x=a,y=b;return x-y;});}
Number PropertyArithmetic::multiply(Number a,Number b) {return apply(3,[&]{volatile double x=a,y=b;return x*y;});}
Number PropertyArithmetic::divide(Number a,Number b) {return apply(4,[&]{volatile double x=a,y=b;return x/y;});}
// A negative finite base with a noninteger exponent is outside the real domain.
// std::pow returns NaN and raises FE_INVALID, as NumPy float64 power does.
Number PropertyArithmetic::power(Number a,Number b) {return apply(5,[&]{volatile double x=a,y=b;return std::pow(x,y);});}
Number PropertyArithmetic::logarithm(Number a) {return apply(6,[&]{volatile double x=a;return std::log(x);});}
Number PropertyArithmetic::logarithm10(Number a) {return apply(9,[&]{volatile double x=a;return std::log10(x);});}
Number PropertyArithmetic::exponential(Number a) {return apply(7,[&]{volatile double x=a;return std::exp(x);});}
template<class Function> Number PropertyArithmetic::apply(std::uint32_t operation,Function function) {
    if (node_>=property_event_count) throw std::logic_error("property expression event extent exceeded");
    const auto node=node_++;
    if (!observe_) return function();
    std::feclearexcept(FE_ALL_EXCEPT);
    // The volatile result keeps the operation before the flag test in optimized builds.
    volatile double value=function();
    const int raised=std::fetestexcept(FE_INVALID|FE_DIVBYZERO|FE_OVERFLOW|FE_UNDERFLOW);
    const std::uint32_t flags=(raised&FE_INVALID?1u:0u)|(raised&FE_DIVBYZERO?2u:0u)
        |(raised&FE_OVERFLOW?4u:0u)|(raised&FE_UNDERFLOW?8u:0u);
    if (flags) events_[node]|=flags|(operation<<8);
    return value;
}
namespace {
using Calculation=PropertyArithmetic;
}  // namespace

namespace {
Number petukhov(Calculation& calc,Number re) {
    const auto& p=data::roughness_petukhov;
    const auto logarithm=calc.logarithm(re);
    const auto product=calc.multiply(p[0],logarithm);
    return calc.power(calc.subtract(product,p[1]),-2.);
}
Number haaland(Calculation& calc,Number re,Number ratio) {
    const auto& h=data::roughness_haaland;
    const auto relative=calc.divide(ratio,h[1]);
    const auto powered=calc.power(relative,h[2]);
    const auto inverse_re=calc.divide(h[3],re);
    const auto sum=calc.add(powered,inverse_re);
    const auto logarithm=calc.logarithm10(sum);
    const auto denominator=calc.multiply(-h[0],logarithm);
    return calc.power(calc.divide(1.,denominator),2.);
}
}  // namespace

PropertyNumber roughness_point(RoughnessQuantity quantity,Number first,Number second,
    std::array<std::uint32_t,property_event_count>& events,bool observe) {
    Calculation calc(events,observe);
    switch (quantity) {
    case RoughnessQuantity::petukhov:return petukhov(calc,first);
    case RoughnessQuantity::haaland:return haaland(calc,first,second);
    case RoughnessQuantity::height_ratio:return calc.divide(calc.multiply(first,1e-3),second);
    case RoughnessQuantity::friction_gain: {
        const auto rough=haaland(calc,first,second),smooth=petukhov(calc,first);
        return calc.divide(rough,smooth);
    }
    case RoughnessQuantity::extra_nu: {
        const auto gain=calc.power(first,data::roughness_nu_power);
        return calc.divide(gain,data::roughness_nu_baseline);
    }
    case RoughnessQuantity::identity:return 1.;
    }
    throw std::invalid_argument("unknown roughness quantity");
}

double native_roughness_factor(double re,double roughness_m,double diameter_m) {
    std::array<std::uint32_t,property_event_count> events{};
    Calculation calc(events,false);
    const auto smooth=petukhov(calc,re);
    // Preserve the solver's m to micrometre/mm operation order.
    const auto micrometres=calc.multiply(roughness_m,1e6);
    const auto height=calc.multiply(micrometres,1e-3);
    const auto diameter=calc.multiply(diameter_m,1000.);
    const auto ratio=calc.divide(height,diameter);
    const auto rough=haaland(calc,re,ratio);
    const auto gain=calc.divide(rough,smooth);
    const auto powered=calc.power(gain,data::roughness_nu_power);
    return calc.divide(powered,data::roughness_nu_baseline);
}

PropertyNumber empirical_point(Empirical getter,PropertyNumber temperature,PropertyNumber pressure,
    std::array<std::uint32_t,property_event_count>& events,bool observe) {
    Calculation calc(events,observe);
    switch (getter) {
    case Empirical::air_viscosity: {
        const auto& s=data::air_sutherland;
        const auto ratio=calc.divide(temperature,s[0]);
        const auto powered=calc.power(ratio,1.5);
        const auto product=calc.multiply(s[1],powered);
        const auto scale=calc.add(s[0],s[2]);
        const auto scaled=calc.multiply(product,scale);
        const auto denominator=calc.add(temperature,s[2]);
        return calc.divide(scaled,denominator);
    }
    case Empirical::air_conductivity: {
        const auto& k=data::air_conductivity;
        const auto ratio=calc.divide(temperature,k[1]);
        const auto powered=calc.power(ratio,k[2]);
        return calc.multiply(k[0],powered);
    }
    case Empirical::air_density: {
        const auto numerator=calc.multiply(pressure,data::air_molar_mass);
        const auto denominator=calc.multiply(data::gas_constant,temperature);
        return calc.divide(numerator,denominator);
    }
    case Empirical::air_cp: {
        const auto& cp=data::model_h_air;
        const auto dt=calc.subtract(temperature,cp[3]);
        const auto linear=calc.multiply(cp[1],dt);
        const auto first=calc.add(cp[0],linear);
        const auto square=calc.power(dt,2.);
        const auto quadratic=calc.multiply(cp[2],square);
        return calc.add(first,quadratic);
    }
    case Empirical::water_density: {
        const auto& r=data::water_density;
        const auto dt=calc.subtract(temperature,data::model_h_water[3]);
        const auto linear=calc.multiply(r[1],dt);
        const auto first=calc.subtract(r[0],linear);
        const auto square=calc.power(dt,2.);
        const auto quadratic=calc.multiply(r[2],square);
        return calc.subtract(first,quadratic);
    }
    case Empirical::water_viscosity: {
        const auto& m=data::water_viscosity;
        const auto shifted=calc.subtract(temperature,m[3]);
        const double denominator=std::isnan(shifted)?shifted:std::max(shifted,m[4]);
        const auto exponent=calc.divide(m[2],denominator);
        const auto powered=calc.power(m[1],exponent);
        return calc.multiply(m[0],powered);
    }
    case Empirical::water_conductivity: {
        const auto& k=data::water_conductivity;
        const auto dt=calc.subtract(temperature,data::model_h_water[3]);
        const auto product=calc.multiply(k[1],dt);
        return calc.add(k[0],product);
    }
    case Empirical::water_cp: return data::model_h_water[0];
    }
    throw std::invalid_argument("unknown empirical property");
}

PropertyNumber nu_point(NuRoute route,Topology topology,Number re,Number pr,Number cell,Number diameter,
    Number alpha,std::array<std::uint32_t,property_event_count>& events,bool observe) {
    Calculation calc(events,observe);const auto row=topology_row(topology);
    if (route==NuRoute::air_direct || route==NuRoute::air_vector) {
        const auto& co=data::nu_air[row];
        const auto pr_power=calc.power(pr,1./3.);
        const auto prefactor=calc.multiply(co[0],pr_power);
        const auto re_power=calc.power(re,co[1]);
        const auto re_product=calc.multiply(prefactor,re_power);
        const auto ratio=calc.divide(diameter,cell);
        const auto ratio_power=calc.power(ratio,co[2]);
        const auto smooth=calc.multiply(re_product,ratio_power);
        return calc.multiply(data::nu_roughness_factor,smooth);
    }
    if (route==NuRoute::water || route==NuRoute::sco2) {
        const double c=route==NuRoute::water?data::nu_water[row][0]:data::nu_sco2[row][0];
        const double a=route==NuRoute::water?data::nu_water[row][1]:data::nu_sco2[row][1];
        const auto re_power=calc.power(re,a);
        const auto prefactor=calc.multiply(c,re_power);
        const auto pr_power=calc.power(pr,1./3.);
        const auto base=calc.multiply(prefactor,pr_power);
        if (route==NuRoute::water) return base;
        const auto ratio=calc.divide(diameter,cell);
        const auto ratio_power=calc.power(ratio,data::nu_sco2[row][2]);
        const auto smooth=calc.multiply(base,ratio_power);
        return calc.multiply(alpha,smooth);
    }
    if (route!=NuRoute::co2) throw std::invalid_argument("unsupported Nu route");
    const auto& b=data::nu_co2[row];
    const auto normalized_re=calc.divide(re,1e4);const auto x=calc.logarithm(normalized_re);
    const auto normalized_pr=calc.divide(pr,2.);const auto y=calc.logarithm(normalized_pr);
    const auto ratio=calc.divide(diameter,cell);const auto normalized_ratio=calc.divide(ratio,.5);
    const auto z=calc.logarithm(normalized_ratio);
    const auto x_term=calc.multiply(b[1],x);const auto first=calc.add(b[0],x_term);
    const auto y_term=calc.multiply(b[2],y);const auto second=calc.add(first,y_term);
    const auto z_term=calc.multiply(b[3],z);const auto third=calc.add(second,z_term);
    const auto first_square=calc.multiply(b[4],x);const auto square=calc.multiply(first_square,x);
    const auto exponent=calc.add(third,square);const auto exponential=calc.exponential(exponent);
    return calc.multiply(data::co2_nu_multiplier,exponential);
}

}  // namespace tpmshx
