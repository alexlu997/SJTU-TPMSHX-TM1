#include "tpmshx/fluid_properties.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "preparation_properties.hpp"
#include "tpmshx/scalar_precision.hpp"

#include <CoolProp/AbstractState.h>
#include <CoolProp/CoolProp.h>
#include <CoolProp/Exceptions.h>

#include <algorithm>
#include <cerrno>
#include <cfenv>
#include <cmath>
#include <complex>
#include <mutex>
#include <string>
#include <type_traits>

#if defined(__APPLE__)
extern "C" void tpmshx_model_complex_log(double real,double imaginary,double* result);
#endif

namespace tpmshx {
namespace {
std::mutex factory_mutex;
}


std::unique_ptr<CoolProp::AbstractState> make_eos_state(const char* backend, const char* fluid) {
    // CoolProp lazily mutates shared fluid/table libraries during construction;
    // serialize initialization while all subsequent updates stay local.
    // ponytail: one factory lock; split initialization only if startup throughput matters.
    const std::lock_guard<std::mutex> lock(factory_mutex);
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
    const auto empirical=[&](preparation::Empirical getter) {
        std::array<std::uint32_t,preparation::property_event_count> events{};
        return preparation::empirical_point(getter,{{temperature,64,1},0.,0,1},
            {{pressure,64,1},0.,0,1},events,false).real.value;
    };
    switch (fluid) {
        case Fluid::air: {
            result.rho=empirical(preparation::Empirical::air_density);
            result.mu=empirical(preparation::Empirical::air_viscosity);
            result.k=empirical(preparation::Empirical::air_conductivity);
            result.cp=empirical(preparation::Empirical::air_cp);
            break;
        }
        case Fluid::water: {
            result.rho=empirical(preparation::Empirical::water_density);
            result.mu=empirical(preparation::Empirical::water_viscosity);
            result.k=empirical(preparation::Empirical::water_conductivity);
            result.cp=empirical(preparation::Empirical::water_cp);
            break;
        }
        case Fluid::co2:
        case Fluid::sco2: {
            if (fluid == Fluid::sco2) {
            if (temperature < data::sco2_temperature_range[0] || temperature > data::sco2_temperature_range[1])
                throw std::invalid_argument("sCO2 temperature must be within 280..700 K");
            if (pressure < data::sco2_pressure_range[0] || pressure > data::sco2_pressure_range[1])
                throw std::invalid_argument("sCO2 pressure must be within 7.9..16 MPa");
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
    preparation::NuRoute route;
    switch (fluid) {
        case Fluid::air: route=preparation::NuRoute::air_direct;break;
        case Fluid::water: route=preparation::NuRoute::water;break;
        case Fluid::sco2: route=preparation::NuRoute::sco2;break;
        case Fluid::co2:
            if (re<=0.) throw std::invalid_argument("CO2 Nu requires positive Re");
            route=preparation::NuRoute::co2;break;
        default: throw std::invalid_argument("unsupported Nu fluid");
    }
    const auto value=[](double x){return preparation::PropertyNumber{{x,64,1},0.,0,1};};
    std::array<std::uint32_t,preparation::property_event_count> events{};
    const double source_re=fluid==Fluid::water || fluid==Fluid::sco2?std::max(re,1.):re;
    const double source_pr=fluid==Fluid::air?data::pr_air:pr;
    const double result=preparation::nu_point(route,topology,value(source_re),value(source_pr),value(1.),
        value(hydraulic_to_cell_ratio),value(sco2_multiplier),events,false).real.value;
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
    return preparation::native_roughness_factor(re,roughness_m,diameter);
}

}  // namespace tpmshx

namespace tpmshx::preparation {
namespace {
namespace g=grid;
namespace precision=geometry::detail;
namespace data=model_coefficients;
using Number=PropertyNumber;

std::uint32_t result_layout(Number first,Number second) {
    if (first.layout==3 || second.layout==3) return 3;
    return first.real.strong || second.real.strong?1u:0u;
}
Number weak(double value) {return {g::weak(value),0.,0,0};}
Number floating64(double value) {return {{value,64,1},0.,0,1};}
std::complex<double> negative_real_power(double value,double exponent);
#if defined(__APPLE__) && defined(__aarch64__)
// The locked macOS arm64 CPython and NumPy quotients fuse these expressions.
constexpr bool contract_complex_quotient=true;
#else
constexpr bool contract_complex_quotient=false;
#endif

// CPython 3.13.2 _Py_c_quot keeps division after each numerator.
std::complex<double> python_complex_divide(std::complex<double> a,std::complex<double> b) {
    const double ar=a.real(),ai=a.imag(),br=b.real(),bi=b.imag();
    const double abs_br=br<0.?-br:br,abs_bi=bi<0.?-bi:bi;
    if (abs_br>=abs_bi) {
        const double ratio=bi/br;
        const double denominator=contract_complex_quotient?std::fma(bi,ratio,br):br+bi*ratio;
        const double real=contract_complex_quotient?std::fma(ai,ratio,ar):ar+ai*ratio;
        const double imaginary=contract_complex_quotient?std::fma(-ar,ratio,ai):ai-ar*ratio;
        return {real/denominator,imaginary/denominator};
    }
    if (abs_bi>=abs_br) {
        const double ratio=br/bi;
        const double denominator=contract_complex_quotient?std::fma(br,ratio,bi):br*ratio+bi;
        const double real=contract_complex_quotient?std::fma(ar,ratio,ai):ar*ratio+ai;
        const double imaginary=contract_complex_quotient?std::fma(ai,ratio,-ar):ai*ratio-ar;
        return {real/denominator,imaginary/denominator};
    }
    const auto nan=std::numeric_limits<double>::quiet_NaN();return {nan,nan};
}

// NumPy 2.5.4 complex divide uses one reciprocal in its scalar loop.
template<class Real> std::complex<Real> numpy_complex_divide(std::complex<Real> a,std::complex<Real> b) {
    const Real ar=a.real(),ai=a.imag(),br=b.real(),bi=b.imag();
    const Real abs_br=std::abs(br),abs_bi=std::abs(bi);
    if (abs_br>=abs_bi) {
        if (abs_br==Real{0} && abs_bi==Real{0}) return {ar/abs_br,ai/abs_bi};
        const Real ratio=bi/br;
        const Real denominator=contract_complex_quotient?std::fma(bi,ratio,br):br+bi*ratio;
        const Real scale=Real{1}/denominator;
        const Real real=contract_complex_quotient?std::fma(ai,ratio,ar):ar+ai*ratio;
        const Real imaginary=contract_complex_quotient?std::fma(-ar,ratio,ai):ai-ar*ratio;
        return {real*scale,imaginary*scale};
    }
    const Real ratio=br/bi;
    const Real denominator=contract_complex_quotient?std::fma(br,ratio,bi):bi+br*ratio;
    const Real scale=Real{1}/denominator;
    const Real real=contract_complex_quotient?std::fma(ar,ratio,ai):ar*ratio+ai;
    const Real imaginary=contract_complex_quotient?std::fma(ai,ratio,-ar):ai*ratio-ar;
    return {real*scale,imaginary*scale};
}

template<class Real> std::complex<Real> numpy_complex_log10(std::complex<Real> value) {
    std::complex<Real> logarithm;
#if defined(__APPLE__)
    if constexpr (std::is_same_v<Real,double>) {
        double parts[2];tpmshx_model_complex_log(value.real(),value.imag(),parts);
        logarithm={parts[0],parts[1]};
    } else logarithm=std::log(value);
#else
    logarithm=std::log(value);
#endif
    constexpr Real log10e=static_cast<Real>(0.434294481903251827651128918916605082);
    return {logarithm.real()*log10e,logarithm.imag()*log10e};
}
}  // namespace

PropertyArithmetic::PropertyArithmetic(std::array<std::uint32_t,property_event_count>& events,bool observe)
    :events_(events),observe_(observe) {}
Number PropertyArithmetic::add(Number a,Number b) {return binary(1,a,b,[](Scalar left,Scalar right){return g::add(left,right);});}
Number PropertyArithmetic::subtract(Number a,Number b) {return binary(2,a,b,[](Scalar left,Scalar right){return g::subtract(left,right);});}
Number PropertyArithmetic::multiply(Number a,Number b) {return binary(3,a,b,[](Scalar left,Scalar right){return g::multiply(left,right);});}
Number PropertyArithmetic::divide(Number a,Number b) {return binary(4,a,b,[](Scalar left,Scalar right){return g::divide(left,right);});}
Number PropertyArithmetic::power(Number a,Number b) {
        if (!a.real.strong && !b.real.strong && std::isfinite(a.real.value) && a.real.value<0.
            && std::isfinite(b.real.value) && std::floor(b.real.value)!=b.real.value) {
            if (node_>=property_event_count) throw std::logic_error("property expression event extent exceeded");
            ++node_;
            const auto value=negative_real_power(a.real.value,b.real.value);
            return {{value.real(),64,0},value.imag(),1,0};
        }
        return binary(5,a,b,[](Scalar first,Scalar second) {
            const auto bits=g::result_precision(first,second);
            const double left=precision::round_scalar(first.value,bits);
            const double right=precision::round_scalar(second.value,bits);
            if (!first.strong && !second.strong && left==0. && right<0.) {
                PropertyFailure failure;failure.fp.python_cause=1;
                throw PropertyError(3,"0.0 cannot be raised to a negative power",failure);
            }
            errno=0;
            const double value=bits==64?std::pow(left,right):
                precision::round_scalar(std::pow(static_cast<float>(left),static_cast<float>(right)),bits);
            if (!first.strong && !second.strong && std::isfinite(left) && std::isfinite(right) && std::isinf(value)) {
                PropertyFailure failure;failure.fp.python_cause=2;
                throw PropertyError(3,"(34, 'Result too large')",failure);
            }
            return Scalar{value,bits,first.strong || second.strong?1u:0u};
        });
    }
Number PropertyArithmetic::logarithm(Number a) {return binary(6,a,weak(0.),[](Scalar value,Scalar){
        return Scalar{std::log(value.value),value.precision,value.strong};});}
Number PropertyArithmetic::logarithm10(Number a) {
        if (!a.real.strong) a.real.strong=1;
        return binary(9,a,weak(0.),[](Scalar value,Scalar){
            return Scalar{std::log10(value.value),value.precision,value.strong};});
    }
Number PropertyArithmetic::exponential(Number a) {return binary(7,a,weak(0.),[](Scalar value,Scalar){
        return Scalar{std::exp(value.value),value.precision,value.strong};});}
template<class Function> Number PropertyArithmetic::binary(std::uint32_t operation,Number a,Number b,Function function) {
        auto bits=g::result_precision(a.real,b.real);
        if (a.category || b.category) bits=std::max(32u,bits);
        for (auto* operand:{&a,&b}) if (bits<64 && !operand->real.strong) {
            if (node_>=property_event_count) throw std::logic_error("property expression event extent exceeded");
            const auto cast_node=node_++;
            const double original=operand->real.value;
            const double original_imaginary=operand->imaginary;
            operand->real.value=precision::round_scalar(original,bits);
            if (operand->category) operand->imaginary=precision::round_scalar(original_imaginary,bits);
            if (observe_ && ((std::isfinite(original) && std::isinf(operand->real.value))
                || (operand->category && std::isfinite(original_imaginary) && std::isinf(operand->imaginary))))
                events_[cast_node]|=4u|(8u<<8);
        }
        if (node_>=property_event_count) throw std::logic_error("property expression event extent exceeded");
        const auto node=node_++;
        if (a.empty || b.empty) return {{0.,bits,a.real.strong || b.real.strong?1u:0u},0.,
            a.category || b.category?1u:0u,3,true};
        if (!observe_) return {function(a.real,b.real),0.,0,result_layout(a,b)};
        std::feclearexcept(FE_ALL_EXCEPT);
        Scalar value;
        double imaginary=0.;const bool complex=a.category || b.category;
        try {
            if (complex) {
                const auto bits=std::max(32u,g::result_precision(a.real,b.real));
                const bool python_complex_left=a.category && !a.real.strong && !b.category
                    && b.real.strong==1 && b.real.precision==64 && b.layout==1;
                const bool strong=!python_complex_left && (a.real.strong || b.real.strong);
                if (operation==4 && !strong && b.real.value==0. && b.imaginary==0.) {
                    PropertyFailure failure;failure.fp.python_cause=1;
                    throw PropertyError(3,"complex division by zero",failure);
                }
                if (bits==64) {
                    const std::complex<double> left{a.real.value,a.imaginary},right{b.real.value,b.imaginary};
                    std::complex<double> output;
                    if (operation==1) output=left+right;
                    else if (operation==2) output=left-right;
                    else if (operation==3) output=left*right;
                    else if (operation==4) output=strong?numpy_complex_divide(left,right):python_complex_divide(left,right);
                    else if (operation==5) output=right.imag()==0. && right.real()==2.?left*left:std::pow(left,right);
                    else if (operation==9) output=numpy_complex_log10(left);
                    else throw std::logic_error("unsupported internal complex property operation");
                    value={output.real(),64,strong?1u:0u};imaginary=output.imag();
                } else {
                    const std::complex<float> left{static_cast<float>(a.real.value),static_cast<float>(a.imaginary)};
                    const std::complex<float> right{static_cast<float>(b.real.value),static_cast<float>(b.imaginary)};
                    std::complex<float> output;
                    if (operation==1) output=left+right;
                    else if (operation==2) output=left-right;
                    else if (operation==3) output=left*right;
                    else if (operation==4) output=numpy_complex_divide(left,right);
                    else if (operation==5) output=right.imag()==0.f && right.real()==2.f?left*left:std::pow(left,right);
                    else if (operation==9) output=numpy_complex_log10(left);
                    else throw std::logic_error("unsupported internal complex property operation");
                    value={output.real(),32,1};imaginary=output.imag();
                }
            } else value=function(a.real,b.real);
        }
        catch (const PropertyError& error) {
            auto failure=error.failure;failure.fp.event_count=static_cast<std::uint32_t>(node_);
            std::copy(events_.begin(),events_.end(),failure.fp.events);
            throw PropertyError(error.status,error.what(),failure);
        }
        catch (const std::domain_error& error) {
            PropertyFailure failure;failure.fp.python_cause=1;
            failure.fp.event_count=static_cast<std::uint32_t>(node_);
            std::copy(events_.begin(),events_.end(),failure.fp.events);
            throw PropertyError(3,error.what(),failure);
        }
        const int raised=std::fetestexcept(FE_INVALID|FE_DIVBYZERO|FE_OVERFLOW|FE_UNDERFLOW);
        std::uint32_t flags=(raised&FE_INVALID?1u:0u)|(raised&FE_DIVBYZERO?2u:0u)
            |(raised&FE_OVERFLOW?4u:0u)|(raised&FE_UNDERFLOW?8u:0u);
        if (value.strong && value.precision==16) {
            const double left=precision::round_scalar(a.real.value,16),right=precision::round_scalar(b.real.value,16);
            if (std::isfinite(left) && std::isfinite(right) && std::isinf(value.value) && !(flags&2u)) flags|=4;
            if (std::isfinite(value.value) && std::abs(value.value)<0x1p-14) {
                double unrounded=value.value;
                if (operation==1) unrounded=left+right;
                if (operation==2) unrounded=left-right;
                if (operation==3) unrounded=left*right;
                if (operation==4) unrounded=left/right;
                if (operation==5) unrounded=std::pow(static_cast<float>(left),static_cast<float>(right));
                if (unrounded!=value.value) flags|=8;
            }
        }
        if (value.strong && flags) {
            const bool scalar=a.layout!=2 && b.layout!=2 && a.layout!=3 && b.layout!=3;
            events_[node]|=flags|(operation<<8)|(scalar?0x10000u:0u);
        }
        return {value,imaginary,complex?1u:0u,value.strong?result_layout(a,b):0u};
    }
namespace {
using Calculation=PropertyArithmetic;
std::complex<double> negative_real_power(double value,double exponent) {
    const double magnitude=std::pow(-value,exponent),angle=std::atan2(0.,value)*exponent;
    return {magnitude*std::cos(angle),magnitude*std::sin(angle)};
}
}  // namespace

namespace {
Number petukhov(Calculation& calc,Number re) {
    const auto& p=data::roughness_petukhov;
    const auto logarithm=calc.logarithm(re);
    const auto product=calc.multiply(weak(p[0]),logarithm);
    return calc.power(calc.subtract(product,weak(p[1])),weak(-2.));
}
Number haaland(Calculation& calc,Number re,Number ratio) {
    const auto& h=data::roughness_haaland;
    const auto relative=calc.divide(ratio,weak(h[1]));
    const auto powered=calc.power(relative,weak(h[2]));
    const auto inverse_re=calc.divide(weak(h[3]),re);
    const auto sum=calc.add(powered,inverse_re);
    const auto logarithm=calc.logarithm10(sum);
    const auto denominator=calc.multiply(weak(-h[0]),logarithm);
    return calc.power(calc.divide(weak(1.),denominator),weak(2.));
}
}  // namespace

PropertyNumber roughness_point(RoughnessQuantity quantity,Number first,Number second,
    std::array<std::uint32_t,property_event_count>& events,bool observe) {
    Calculation calc(events,observe);
    switch (quantity) {
    case RoughnessQuantity::petukhov:return petukhov(calc,first);
    case RoughnessQuantity::haaland:return haaland(calc,first,second);
    case RoughnessQuantity::height_ratio:return calc.divide(calc.multiply(first,weak(1e-3)),second);
    case RoughnessQuantity::friction_gain: {
        const auto rough=haaland(calc,first,second),smooth=petukhov(calc,first);
        return calc.divide(rough,smooth);
    }
    case RoughnessQuantity::extra_nu: {
        const auto gain=calc.power(first,weak(data::roughness_nu_power));
        return calc.divide(gain,weak(data::roughness_nu_baseline));
    }
    case RoughnessQuantity::identity:return weak(1.);
    }
    throw std::invalid_argument("unknown roughness quantity");
}

double native_roughness_factor(double re,double roughness_m,double diameter_m) {
    std::array<std::uint32_t,property_event_count> events{};
    Calculation calc(events,false);
    const auto smooth=petukhov(calc,floating64(re));
    // Preserve the solver's m to micrometre/mm operation order.
    const auto micrometres=calc.multiply(floating64(roughness_m),weak(1e6));
    const auto height=calc.multiply(micrometres,weak(1e-3));
    const auto diameter=calc.multiply(floating64(diameter_m),weak(1000.));
    const auto ratio=calc.divide(height,diameter);
    const auto rough=haaland(calc,floating64(re),ratio);
    const auto gain=calc.divide(rough,smooth);
    const auto powered=calc.power(gain,weak(data::roughness_nu_power));
    return calc.divide(powered,weak(data::roughness_nu_baseline)).real.value;
}

PropertyNumber empirical_point(Empirical getter,PropertyNumber temperature,PropertyNumber pressure,
    std::array<std::uint32_t,property_event_count>& events,bool observe) {
    Calculation calc(events,observe);
    switch (getter) {
    case Empirical::air_viscosity: {
        const auto& s=data::air_sutherland;
        const auto ratio=calc.divide(temperature,weak(s[0]));
        const auto powered=calc.power(ratio,weak(1.5));
        const auto product=calc.multiply(weak(s[1]),powered);
        const auto scale=calc.add(weak(s[0]),weak(s[2]));
        const auto scaled=calc.multiply(product,scale);
        const auto denominator=calc.add(temperature,weak(s[2]));
        return calc.divide(scaled,denominator);
    }
    case Empirical::air_conductivity: {
        const auto& k=data::air_conductivity;
        const auto ratio=calc.divide(temperature,weak(k[1]));
        const auto powered=calc.power(ratio,weak(k[2]));
        return calc.multiply(weak(k[0]),powered);
    }
    case Empirical::air_density: {
        const auto numerator=calc.multiply(pressure,weak(data::air_molar_mass));
        const auto denominator=calc.multiply(weak(data::gas_constant),temperature);
        return calc.divide(numerator,denominator);
    }
    case Empirical::air_cp: {
        const auto& cp=data::model_h_air;
        const auto dt=calc.subtract(temperature,weak(cp[3]));
        const auto linear=calc.multiply(weak(cp[1]),dt);
        const auto first=calc.add(weak(cp[0]),linear);
        const auto square=calc.power(dt,weak(2.));
        const auto quadratic=calc.multiply(weak(cp[2]),square);
        return calc.add(first,quadratic);
    }
    case Empirical::water_density: {
        const auto& r=data::water_density;
        const auto original_layout=temperature.layout;
        const auto original_empty=temperature.empty;
        temperature=floating64(temperature.real.value);temperature.layout=original_layout==3?3:2;
        temperature.empty=original_empty;
        const auto dt=calc.subtract(temperature,weak(data::model_h_water[3]));
        const auto linear=calc.multiply(weak(r[1]),dt);
        const auto first=calc.subtract(weak(r[0]),linear);
        const auto square=calc.power(dt,weak(2.));
        const auto quadratic=calc.multiply(weak(r[2]),square);
        return calc.subtract(first,quadratic);
    }
    case Empirical::water_viscosity: {
        const auto& m=data::water_viscosity;
        const auto original_layout=temperature.layout;
        const auto original_empty=temperature.empty;
        temperature=floating64(temperature.real.value);temperature.layout=original_layout==3?3:2;
        temperature.empty=original_empty;
        const auto shifted=calc.subtract(temperature,weak(m[3]));
        auto denominator=shifted;
        if (!shifted.empty) denominator.real.value=std::isnan(shifted.real.value)?shifted.real.value:std::max(shifted.real.value,m[4]);
        const auto exponent=calc.divide(weak(m[2]),denominator);
        const auto powered=calc.power(weak(m[1]),exponent);
        return calc.multiply(weak(m[0]),powered);
    }
    case Empirical::water_conductivity: {
        const auto& k=data::water_conductivity;
        const auto original_layout=temperature.layout;
        const auto original_empty=temperature.empty;
        temperature=floating64(temperature.real.value);temperature.layout=original_layout==3?3:2;
        temperature.empty=original_empty;
        const auto dt=calc.subtract(temperature,weak(data::model_h_water[3]));
        const auto product=calc.multiply(weak(k[1]),dt);
        return calc.add(weak(k[0]),product);
    }
    case Empirical::water_cp: return weak(data::model_h_water[0]);
    }
    throw std::invalid_argument("unknown empirical property");
}

PropertyNumber nu_point(NuRoute route,Topology topology,Number re,Number pr,Number cell,Number diameter,
    Number alpha,std::array<std::uint32_t,property_event_count>& events,bool observe) {
    Calculation calc(events,observe);const auto row=topology_row(topology);
    if (route==NuRoute::air_direct || route==NuRoute::air_vector) {
        const auto& co=data::nu_air[row];
        const auto pr_power=calc.power(pr,weak(1./3.));
        const auto prefactor=calc.multiply(weak(co[0]),pr_power);
        const auto re_power=calc.power(re,weak(co[1]));
        const auto re_product=calc.multiply(prefactor,re_power);
        const auto ratio=calc.divide(diameter,cell);
        const auto ratio_power=calc.power(ratio,weak(co[2]));
        const auto smooth=calc.multiply(re_product,ratio_power);
        return calc.multiply(weak(data::nu_roughness_factor),smooth);
    }
    if (route==NuRoute::water || route==NuRoute::sco2) {
        const double c=route==NuRoute::water?data::nu_water[row][0]:data::nu_sco2[row][0];
        const double a=route==NuRoute::water?data::nu_water[row][1]:data::nu_sco2[row][1];
        const auto re_power=calc.power(re,weak(a));
        const auto prefactor=calc.multiply(weak(c),re_power);
        const auto pr_power=calc.power(pr,weak(1./3.));
        const auto base=calc.multiply(prefactor,pr_power);
        if (route==NuRoute::water) return base;
        const auto ratio=calc.divide(diameter,cell);
        const auto ratio_power=calc.power(ratio,weak(data::nu_sco2[row][2]));
        const auto smooth=calc.multiply(base,ratio_power);
        return calc.multiply(alpha,smooth);
    }
    if (route!=NuRoute::co2) throw std::invalid_argument("unsupported Nu route");
    const auto& b=data::nu_co2[row];
    const auto normalized_re=calc.divide(re,weak(1e4));const auto x=calc.logarithm(normalized_re);
    const auto normalized_pr=calc.divide(pr,weak(2.));const auto y=calc.logarithm(normalized_pr);
    const auto ratio=calc.divide(diameter,cell);const auto normalized_ratio=calc.divide(ratio,weak(.5));
    const auto z=calc.logarithm(normalized_ratio);
    const auto x_term=calc.multiply(weak(b[1]),x);const auto first=calc.add(weak(b[0]),x_term);
    const auto y_term=calc.multiply(weak(b[2]),y);const auto second=calc.add(first,y_term);
    const auto z_term=calc.multiply(weak(b[3]),z);const auto third=calc.add(second,z_term);
    const auto first_square=calc.multiply(weak(b[4]),x);const auto square=calc.multiply(first_square,x);
    const auto exponent=calc.add(third,square);const auto exponential=calc.exponential(exponent);
    return calc.multiply(weak(data::co2_nu_multiplier),exponential);
}

PropertyNumber reynolds_point(Number rho,Number speed,Number diameter,Number mu,
    std::array<std::uint32_t,property_event_count>& events) {
    Calculation calc(events);
    const auto mass_speed=calc.multiply(rho,speed);
    const auto scaled=calc.multiply(mass_speed,diameter);
    return calc.divide(scaled,mu);
}
PropertyNumber prandtl_point(Number mu,Number cp,Number conductivity,
    std::array<std::uint32_t,property_event_count>& events) {
    Calculation calc(events);
    const auto capacity=calc.multiply(mu,cp);
    return calc.divide(capacity,conductivity);
}
PropertyNumber surface_transfer_point(Number nu,Number conductivity,Number diameter,
    std::array<std::uint32_t,property_event_count>& events) {
    Calculation calc(events);
    const auto scaled=calc.multiply(nu,conductivity);
    return calc.divide(scaled,diameter);
}
PropertyNumber volumetric_transfer_point(Number surface,Number area,
    std::array<std::uint32_t,property_event_count>& events) {
    Calculation calc(events);return calc.multiply(surface,area);
}
PropertyNumber pore_conductivity_point(Number epsilon,Number conductivity,
    std::array<std::uint32_t,property_event_count>& events) {
    Calculation calc(events);return calc.multiply(epsilon,conductivity);
}

std::vector<std::vector<double>> property_eos_query(const std::vector<std::string>& keys,
    const char* input,const std::vector<double>& first,const std::vector<double>& pressure,bool scalar) {
    const std::lock_guard<std::mutex> lock(factory_mutex);
    if (scalar) {
        const double value=CoolProp::PropsSI(keys.at(0),input,first.at(0),"P",pressure.at(0),"CO2");
        if (!std::isfinite(value)) throw std::runtime_error(CoolProp::get_global_param_string("errstring"));
        return {{value}};
    }
    auto result=CoolProp::PropsSImulti(keys,input,first,"P",pressure,"HEOS",{"CO2"},{1.});
    if (result.empty()) throw std::runtime_error(CoolProp::get_global_param_string("errstring"));
    return result;
}
}  // namespace tpmshx::preparation
