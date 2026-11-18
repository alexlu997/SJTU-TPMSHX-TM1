#include "preparation_properties.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "tpmshx/scalar_precision.hpp"
#include <CoolProp/AbstractState.h>
#include <CoolProp/CoolProp.h>
#include <algorithm>
#include <cfenv>
#include <cmath>
#include <sstream>

namespace tpmshx::preparation {
namespace {
namespace g=grid;
namespace data=model_coefficients;
constexpr auto absent=std::numeric_limits<std::size_t>::max();
class FloatingEnvironment {
public:
    FloatingEnvironment() {std::fegetenv(&environment_);}
    ~FloatingEnvironment() {std::fesetenv(&environment_);}
private:
    std::fenv_t environment_;
};
void check_input(PropertyInput input,std::size_t count) {
    if (input.values.size!=count) throw std::invalid_argument("property input element count is incorrect");
    g::checked({0.,input.kind.precision,input.kind.strong});
    if (input.layout>3 || (!input.kind.strong && input.layout) || (input.kind.strong && !input.layout))
        throw std::invalid_argument("property input layout does not match its scalar kind");
    if (input.category>1 || (input.category && (input.layout>1 || input.kind.strong>1
        || (input.kind.precision!=32 && input.kind.precision!=64))))
        throw std::invalid_argument("property complex operands require a supported scalar layout");
}
PropertyNumber point(PropertyInput input,std::size_t index) {
    return {{input.values[index],input.kind.precision,input.kind.strong},input.imaginary,input.category,input.layout};
}
PropertyNumber empty_point(PropertyInput input) {
    return {{input.kind.value,input.kind.precision,input.kind.strong},input.imaginary,input.category,input.layout,input.layout==3};
}
Scalar floating_type(Scalar kind) {return {0.,g::result_precision(kind,g::weak(0.)),kind.strong?1u:0u};}
PropertyResult result(std::size_t count,Scalar kind) {
    PropertyResult output;output.values.resize(count);output.imaginary.assign(count,0.);output.kind=kind;return output;
}
void store(PropertyResult& output,std::size_t index,PropertyNumber number) {
    if (!index) {output.kind={0.,number.real.precision,number.real.strong};output.category=number.category;}
    if (number.real.precision!=output.kind.precision || number.real.strong!=output.kind.strong
        || number.category!=output.category) throw std::runtime_error("property result type varies within one array");
    output.values[index]=number.real.value;output.imaginary[index]=number.imaginary;
}
std::vector<double> values(ArrayView<const double> input) {
    return input.size?std::vector<double>(input.data,input.data+input.size):std::vector<double>{};
}
void paired(ArrayView<const double> first,ArrayView<const double> second) {
    if (first.size!=second.size) throw std::invalid_argument("property paired element counts differ");
}
PropertyFailure failure_at(std::size_t index,ArrayView<const double> temperature,ArrayView<const double> pressure,
    std::uint32_t reason) {
    PropertyFailure failure;failure.reason=reason;failure.index=index;
    if (index<temperature.size) failure.temperature=temperature[index];
    if (index<pressure.size) failure.pressure=pressure[index];
    return failure;
}
std::string number(double value) {std::ostringstream stream;stream<<value;return stream.str();}
template<class Function> PropertyResult unary_binary(PropertyInput first,PropertyInput second,Function function) {
    FloatingEnvironment environment;
    check_input(first,first.values.size);check_input(second,first.values.size);
    auto output=result(first.values.size,{0.,g::result_precision(first.kind,second.kind),
        first.kind.strong || second.kind.strong?1u:0u});
    for (std::size_t i=0;i<first.values.size;++i) store(output,i,function(point(first,i),point(second,i),output.events));
    return output;
}
}  // namespace

PropertyResult empirical(Empirical getter,PropertyInput temperature,PropertyInput pressure) {
    FloatingEnvironment environment;
    const auto count=temperature.values.size;check_input(temperature,count);
    Scalar kind=floating_type(temperature.kind);
    if (getter==Empirical::air_density) {
        check_input(pressure,count);const auto numerator=floating_type(pressure.kind);
        kind={0.,g::result_precision(numerator,kind),numerator.strong || kind.strong?1u:0u};
    }
    if (getter>=Empirical::water_density) kind={0.,64,1};
    if (getter==Empirical::water_cp) kind=g::weak(0.);
    const auto required=getter==Empirical::water_cp?std::size_t{1}:count;
    auto output=result(required,kind);
    if (!required) {
        const auto p=getter==Empirical::air_density?empty_point(pressure):PropertyNumber{g::weak(0.),0.,0,0};
        const auto value=empirical_point(getter,empty_point(temperature),p,output.events);
        output.kind={0.,value.real.precision,value.real.strong};output.category=value.category;
    }
    for (std::size_t i=0;i<required;++i) {
        const auto t=getter==Empirical::water_cp?PropertyNumber{g::weak(0.),0.,0,0}:point(temperature,i);
        const auto p=getter==Empirical::air_density?point(pressure,i):PropertyNumber{g::weak(0.),0.,0,0};
        store(output,i,empirical_point(getter,t,p,output.events));
    }
    return output;
}

PropertyResult roughness(RoughnessQuantity quantity,PropertyInput first,PropertyInput second) {
    FloatingEnvironment environment;
    const auto count=quantity==RoughnessQuantity::identity?std::size_t{1}:first.values.size;
    if (quantity!=RoughnessQuantity::identity) check_input(first,count);
    const bool paired=quantity==RoughnessQuantity::haaland || quantity==RoughnessQuantity::height_ratio
        || quantity==RoughnessQuantity::friction_gain;
    if (paired) check_input(second,count);
    auto output=result(count,g::weak(0.));
    const auto unused=PropertyNumber{g::weak(0.),0.,0,0};
    if (!count) {
        const auto value=roughness_point(quantity,empty_point(first),paired?empty_point(second):unused,output.events);
        output.kind={0.,value.real.precision,value.real.strong};output.category=value.category;
    }
    for (std::size_t i=0;i<count;++i) {
        const auto a=quantity==RoughnessQuantity::identity?unused:point(first,i);
        store(output,i,roughness_point(quantity,a,paired?point(second,i):unused,output.events));
    }
    return output;
}

PropertyResult nu_inputs(NuRoute route,PropertyInput re,PropertyInput pr,PropertyInput cell,
    PropertyInput diameter,PropertyInput floor,std::array<double,4>& extrema) {
    FloatingEnvironment environment;const auto count=re.values.size;check_input(re,count);
    const double nan=std::numeric_limits<double>::quiet_NaN();extrema={nan,nan,nan,nan};
    if (route==NuRoute::co2) {
        for (auto value:{pr,cell,diameter}) check_input(value,count);
        if (!count) throw PropertyError(3,"CO2 closure inputs must be finite and positive");
        for (auto value:{re,pr,cell,diameter}) for (std::size_t i=0;i<count;++i)
            if (!std::isfinite(value.values[i]) || value.values[i]<=0.)
                throw PropertyError(3,"CO2 closure inputs must be finite and positive");
    }
    Scalar kind=re.kind;
    if (route==NuRoute::air_direct || route==NuRoute::air_vector || route==NuRoute::co2)
        kind={0.,64,route==NuRoute::air_direct && re.layout!=3?0u:1u};
    if (route==NuRoute::water || route==NuRoute::sco2)
        kind={0.,g::result_precision(re.kind,g::weak(1.)),1};
    if (route==NuRoute::air_vector) check_input(floor,count);
    auto output=result(count,kind);
    for (std::size_t i=0;i<count;++i) {
        double value=re.values[i];
        if (route==NuRoute::water || route==NuRoute::sco2) {
            value=geometry::detail::round_scalar(value,kind.precision);
            if (!std::isnan(value)) value=std::max(value,1.);
        } else if (route==NuRoute::air_vector) {
            const auto lower=floor.values[i];
            value=std::isnan(value)?value:(std::isnan(lower)?lower:(value>lower?value:lower));
#if defined(__aarch64__) || defined(_M_ARM64)
            // NumPy's AArch64 FMAX returns +0 for mixed zero signs.
            if (re.values[i]==0. && lower==0.)
                value=std::signbit(re.values[i]) && std::signbit(lower)?-0.:0.;
#endif
        }
        output.values[i]=value;
    }
    if (count) {
        extrema[0]=extrema[1]=output.values[0];
        for (auto value:output.values) {
            if (std::isnan(value)) {extrema[0]=extrema[1]=nan;break;}
            extrema[0]=std::min(extrema[0],value);extrema[1]=std::max(extrema[1],value);
        }
        if (route==NuRoute::co2) {
            extrema[2]=extrema[3]=pr.values[0];
            for (std::size_t i=1;i<count;++i) {
                extrema[2]=std::min(extrema[2],pr.values[i]);extrema[3]=std::max(extrema[3],pr.values[i]);
            }
        }
    }
    return output;
}
PropertyResult nusselt(NuRoute route,Topology topology,PropertyInput re,PropertyInput pr,
    PropertyInput cell,PropertyInput diameter,Scalar alpha) {
    FloatingEnvironment environment;const auto count=re.values.size;
    check_input(re,count);check_input(pr,count);
    if (route!=NuRoute::water) {check_input(cell,count);check_input(diameter,count);}
    alpha=route==NuRoute::sco2?g::checked(alpha):g::weak(1.);
    const auto combine=[](Scalar first,Scalar second) {
        return Scalar{0.,g::result_precision(first,second),first.strong || second.strong?1u:0u};
    };
    auto kind=combine(floating_type(re.kind),floating_type(pr.kind));
    if (route!=NuRoute::water) kind=combine(kind,combine(diameter.kind,cell.kind));
    if (route==NuRoute::sco2) kind=combine(kind,alpha);
    if (route==NuRoute::co2) kind={0.,64,1};
    auto output=result(count,kind);
    if (!count) {
        const auto unused=PropertyNumber{g::weak(1.),0.,0,0};
        const auto c=route==NuRoute::water?unused:empty_point(cell),d=route==NuRoute::water?unused:empty_point(diameter);
        const auto value=nu_point(route,topology,empty_point(re),empty_point(pr),c,d,
            {alpha,0.,0,alpha.strong?1u:0u},output.events);
        output.kind={0.,value.real.precision,value.real.strong};output.category=value.category;
    }
    for (std::size_t i=0;i<count;++i) {
        const auto unused=PropertyNumber{g::weak(1.),0.,0,0};
        const auto c=route==NuRoute::water?unused:point(cell,i),d=route==NuRoute::water?unused:point(diameter,i);
        const auto a=PropertyNumber{alpha,0.,0,alpha.strong?1u:0u};
        store(output,i,nu_point(route,topology,point(re,i),point(pr,i),c,d,a,output.events));
    }
    return output;
}

PropertyResult reynolds(PropertyInput rho,PropertyInput speed,PropertyInput diameter,PropertyInput mu) {
    FloatingEnvironment environment;
    const auto count=rho.values.size;for (auto input:{rho,speed,diameter,mu}) check_input(input,count);
    auto type=Scalar{0.,g::result_precision(rho.kind,speed.kind),rho.kind.strong || speed.kind.strong?1u:0u};
    type={0.,g::result_precision(type,diameter.kind),type.strong || diameter.kind.strong?1u:0u};
    type={0.,g::result_precision(type,mu.kind),type.strong || mu.kind.strong?1u:0u};
    auto output=result(count,type);
    for (std::size_t i=0;i<count;++i)
        store(output,i,reynolds_point(point(rho,i),point(speed,i),point(diameter,i),point(mu,i),output.events));
    return output;
}
PropertyResult prandtl(PropertyInput mu,PropertyInput cp,PropertyInput k) {
    const auto count=mu.values.size;
    for (auto input:{mu,cp,k}) check_input(input,count);
    FloatingEnvironment environment;
    const Scalar product{0.,g::result_precision(mu.kind,cp.kind),mu.kind.strong || cp.kind.strong?1u:0u};
    auto pr=result(count,{0.,g::result_precision(product,k.kind),product.strong || k.kind.strong?1u:0u});
    if (!count) {
        const auto value=prandtl_point(empty_point(mu),empty_point(cp),empty_point(k),pr.events);
        pr.kind={0.,value.real.precision,value.real.strong};pr.category=value.category;
    }
    for (std::size_t i=0;i<count;++i) store(pr,i,prandtl_point(point(mu,i),point(cp,i),point(k,i),pr.events));
    return pr;
}
PropertyResult surface_transfer(PropertyInput nu,PropertyInput k,PropertyInput diameter) {
    FloatingEnvironment environment;const auto count=nu.values.size;
    for (auto input:{nu,k,diameter}) check_input(input,count);
    const Scalar product{0.,g::result_precision(nu.kind,k.kind),nu.kind.strong || k.kind.strong?1u:0u};
    auto output=result(count,{0.,g::result_precision(product,diameter.kind),product.strong || diameter.kind.strong?1u:0u});
    if (!count) {
        const auto value=surface_transfer_point(empty_point(nu),empty_point(k),empty_point(diameter),output.events);
        output.kind={0.,value.real.precision,value.real.strong};output.category=value.category;
    }
    for (std::size_t i=0;i<count;++i)
        store(output,i,surface_transfer_point(point(nu,i),point(k,i),point(diameter,i),output.events));
    return output;
}
std::array<PropertyResult,2> inlet_re_pr(PropertyInput rho,PropertyInput mu,PropertyInput k,
    PropertyInput cp,PropertyInput speed,PropertyInput diameter) {
    auto re=reynolds(rho,speed,diameter,mu),pr=prandtl(mu,cp,k);
    return {std::move(re),std::move(pr)};
}
PropertyResult volumetric_transfer(PropertyInput surface,PropertyInput area) {
    return unary_binary(surface,area,volumetric_transfer_point);
}
PropertyResult pore_conductivity(PropertyInput epsilon,PropertyInput conductivity) {
    return unary_binary(epsilon,conductivity,pore_conductivity_point);
}
std::array<PropertyResult,3> inlet_transfer(PropertyInput nu,PropertyInput k,PropertyInput diameter,
    PropertyInput area,PropertyInput epsilon) {
    const auto count=nu.values.size;
    for (auto input:{area,epsilon}) check_input(input,count);
    auto surface=surface_transfer(nu,k,diameter);
    const PropertyInput hsf{{surface.values.data(),count},surface.kind,
        nu.layout==3 || k.layout==3 || diameter.layout==3?3u:(surface.kind.strong?1u:0u)};
    auto volume=volumetric_transfer(hsf,area),conductivity=pore_conductivity(epsilon,k);
    return {std::move(surface),std::move(volume),std::move(conductivity)};
}

void validate_water_pt(ArrayView<const double> temperature,ArrayView<const double> pressure) {
    paired(temperature,pressure);
    if (!temperature.size) throw PropertyError(10,"requires finite positive K and Pa(abs)");
    for (std::size_t i=0;i<temperature.size;++i)
        if (!std::isfinite(temperature[i]) || !std::isfinite(pressure[i]) || temperature[i]<=0. || pressure[i]<=0.)
            throw PropertyError(10,"requires finite positive K and Pa(abs)",failure_at(i,temperature,pressure,1));
    std::unique_ptr<CoolProp::AbstractState> state;
    for (std::size_t i=0;i<temperature.size;++i) {
        try {detail::check_water_pt(state,temperature[i],pressure[i]);}
        catch (const WaterStateError& error) {
            throw PropertyError(10,error.what(),failure_at(i,temperature,pressure,error.eos_failure?7u:6u));
        }
        catch (const std::exception& error) {throw PropertyError(10,error.what(),failure_at(i,temperature,pressure,7));}
    }
}
void validate_co2_pt(ArrayView<const double> temperature,ArrayView<const double> pressure) {
    paired(temperature,pressure);
    const char* basic="CO2 requires finite positive temperature [K] and pressure [Pa(abs)]";
    if (!temperature.size) throw PropertyError(11,basic);
    for (std::size_t i=0;i<temperature.size;++i)
        if (!std::isfinite(temperature[i]) || !std::isfinite(pressure[i]) || temperature[i]<=0. || pressure[i]<=0.)
            throw PropertyError(11,basic,failure_at(i,temperature,pressure,1));
    const auto state=make_eos_state("HEOS","CO2");
    for (std::size_t i=0;i<temperature.size;++i) if (temperature[i]<=state->Ttriple())
        throw PropertyError(11,"CO2 at/below its triple-point temperature is outside this fluid model",
            failure_at(i,temperature,pressure,5));
}
void validate_sco2(ArrayView<const double> temperature,ArrayView<const double> pressure) {
    PropertyFailure failure;
    for (std::size_t i=0;i<temperature.size;++i) if (!std::isfinite(temperature[i])) {failure.first_t_index=i;break;}
    for (std::size_t i=0;i<pressure.size;++i) if (!std::isfinite(pressure[i])) {failure.first_p_index=i;break;}
    std::string message;
    if (failure.first_t_index!=absent || failure.first_p_index!=absent) {failure.reason=1;message="sCO2 state must be finite";}
    else {
        for (std::size_t i=0;i<temperature.size;++i)
            if (temperature[i]<data::sco2_temperature_range[0] || temperature[i]>data::sco2_temperature_range[1]) {
                failure.reason=3;failure.first_t_index=i;message="sCO2 temperature must be within 280..700 K";break;
            }
        if (message.empty()) for (std::size_t i=0;i<pressure.size;++i)
            if (pressure[i]<data::sco2_pressure_range[0] || pressure[i]>data::sco2_pressure_range[1]) {
                failure.reason=4;failure.first_p_index=i;message="sCO2 pressure must be within 7.9..16 MPa";break;
            }
    }
    if (message.empty()) return;
    if (failure.first_t_index!=absent) failure.temperature=temperature[failure.first_t_index];
    if (failure.first_p_index!=absent) failure.pressure=pressure[failure.first_p_index];
    if (temperature.size==pressure.size) {
        failure.index=std::min(failure.first_t_index,failure.first_p_index);
        failure.temperature=temperature[failure.index];failure.pressure=pressure[failure.index];
    }
    throw PropertyError(12,message,failure);
}
std::vector<double> co2_pt(const std::vector<std::uint32_t>& requested,
    ArrayView<const double> temperature,ArrayView<const double> pressure,bool scalar_bundle) {
    static const std::array<std::string,5> allowed{{"D","V","L","C","H"}};
    validate_co2_pt(temperature,pressure);
    std::vector<std::string> keys;
    if (scalar_bundle) {
        if (temperature.size!=1) throw std::invalid_argument("CO2 scalar bundle needs one state");
        keys.assign(allowed.begin(),allowed.end());
    } else for (auto key:requested) {
        if (key>=allowed.size()) throw std::invalid_argument("unknown CO2 property key");
        keys.push_back(allowed[key]);
    }
    const auto property_count=keys.size();keys.push_back("Phase");
    try {
        const auto queried=property_eos_query(keys,"T",values(temperature),values(pressure),false);
        if (queried.size()!=temperature.size) throw std::runtime_error("CO2 query state extent is incorrect");
        std::vector<double> output(property_count*temperature.size);
        for (std::size_t i=0;i<temperature.size;++i) {
            if (queried[i].size()!=keys.size()) throw std::runtime_error("CO2 query key extent is incorrect");
            const double phase=queried[i].back();
            bool valid=phase==CoolProp::iphase_liquid || phase==CoolProp::iphase_gas
                || phase==CoolProp::iphase_supercritical || phase==CoolProp::iphase_supercritical_gas
                || phase==CoolProp::iphase_supercritical_liquid;
            for (std::size_t j=0;j<keys.size();++j)
                valid=valid && std::isfinite(queried[i][j]) && (j==property_count || keys[j]=="H" || queried[i][j]>0.);
            if (!valid) {
                auto failure=failure_at(i,temperature,pressure,6);failure.detail=phase;
                throw PropertyError(11,"unsupported/nonfinite state at T="+number(temperature[i])+" K, P_abs="
                    +number(pressure[i])+" Pa; phase code="+number(phase),failure);
            }
            for (std::size_t j=0;j<property_count;++j) output[j*temperature.size+i]=queried[i][j];
        }
        return output;
    } catch (const std::exception& error) {
        const auto* typed=dynamic_cast<const PropertyError*>(&error);
        throw PropertyError(11,"CO2 requires a stable single-phase PT state; saturation, two-phase and critical-point states are unsupported. "
            +std::string(error.what()),typed?typed->failure:PropertyFailure{});
    }
}
std::vector<double> sco2_pt(std::uint32_t form,const std::vector<std::string>& keys,
    ArrayView<const double> temperature,ArrayView<const double> pressure) {
    paired(temperature,pressure);validate_sco2(temperature,pressure);
    if (form>2 || ((form==0 || form==1) && keys.size()!=1) || (form==0 && temperature.size!=1))
        throw std::invalid_argument("sCO2 query form is invalid");
    if (!temperature.size) return {};
    try {
        const auto queried=property_eos_query(keys,"T",values(temperature),values(pressure),form==0);
        if (queried.size()!=temperature.size) throw std::runtime_error("sCO2 query state extent is incorrect");
        std::vector<double> output(temperature.size*keys.size());
        for (std::size_t i=0;i<temperature.size;++i) {
            if (queried[i].size()!=keys.size()) throw std::runtime_error("sCO2 query key extent is incorrect");
            for (std::size_t j=0;j<keys.size();++j) output[j*temperature.size+i]=queried[i][j];
        }
        return output;
    } catch (const std::exception& error) {throw PropertyError(12,error.what());}
}
std::vector<double> sco2_hp(ArrayView<const double> enthalpy,ArrayView<const double> pressure,bool scalar) {
    paired(enthalpy,pressure);
    if (scalar && enthalpy.size!=1) throw std::invalid_argument("scalar HP query needs one state");
    for (std::size_t i=0;i<pressure.size;++i) {
        const bool bad=scalar?!(data::sco2_pressure_range[0]<=pressure[i] && pressure[i]<=data::sco2_pressure_range[1]):
            pressure[i]<data::sco2_pressure_range[0] || pressure[i]>data::sco2_pressure_range[1];
        if (bad) {PropertyFailure failure;failure.reason=4;failure.index=i;failure.pressure=pressure[i];
            throw PropertyError(12,"sCO2 pressure must be within 7.9..16 MPa",failure);}
    }
    if (!enthalpy.size) return {};
    std::vector<double> output;
    try {
        const auto queried=property_eos_query({"T"},"H",values(enthalpy),values(pressure),scalar);
        if (queried.size()!=enthalpy.size) throw std::runtime_error("HP query state extent is incorrect");
        output.reserve(enthalpy.size);
        for (const auto& row:queried) {
            if (row.size()!=1) throw std::runtime_error("HP query key extent is incorrect");
            output.push_back(row[0]);
        }
    } catch (const std::exception& error) {throw PropertyError(12,error.what());}
    validate_sco2({output.data(),output.size()},pressure);return output;
}
}  // namespace tpmshx::preparation
