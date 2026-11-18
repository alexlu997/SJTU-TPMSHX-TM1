#include "tpmshx/property_c_api.h"
#include "preparation_properties.hpp"
#include "preparation_c_boundary.hpp"
#include <CoolProp/CoolProp.h>
#include <algorithm>
#include <initializer_list>
#include <string>
#include <vector>

namespace {
namespace p=tpmshx::preparation;
namespace c=p::c_api;
using Input=tpmshx_property_input_v1;
using Operand=tpmshx_property_operand_v1;
using Output=tpmshx_property_output_v1;
using Failure=tpmshx_property_failure_v1;
struct Range {const void* data;std::size_t count,width,alignment;bool output;};
template<class T> Range read(const T* values,std::size_t count) {return {values,count,sizeof(T),alignof(T),false};}
template<class T> Range write(T* values,std::size_t count) {return {values,count,sizeof(T),alignof(T),true};}
Range read(Input value) {return read(value.values,value.count);}
Range read(Operand value) {return read(value.real);}

template<class Function> int invoke(std::initializer_list<Range> buffers,Failure* failure,
    char* error,std::size_t size,Function function) {
    // Error storage must be safe before a boundary can write its diagnostic.
    try {
        c::require_buffer(error,size);
        if (!size) return TPMSHX_PREPARATION_INVALID;
        for (const auto& buffer:buffers) {
            const auto bytes=c::product(buffer.count,buffer.width);
            c::require_buffer(static_cast<const char*>(buffer.data),bytes);
            if (bytes && reinterpret_cast<std::uintptr_t>(buffer.data)%buffer.alignment)
                return TPMSHX_PREPARATION_INVALID;
            c::require_disjoint(error,size,static_cast<const char*>(buffer.data),bytes);
        }
        if (failure) {
            c::require_buffer(failure,1);c::require_disjoint(error,size,failure,1);
        }
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    return c::boundary(error,size,[&] {
        for (auto first=buffers.begin();first!=buffers.end();++first) if (first->output) {
            for (auto second=buffers.begin();second!=buffers.end();++second) if (first!=second)
                c::require_disjoint(static_cast<const char*>(first->data),c::product(first->count,first->width),
                    static_cast<const char*>(second->data),c::product(second->count,second->width));
            if (failure) c::require_disjoint(failure,1,static_cast<const char*>(first->data),c::product(first->count,first->width));
        }
        if (failure) for (const auto& buffer:buffers)
            c::require_disjoint(failure,1,static_cast<const char*>(buffer.data),c::product(buffer.count,buffer.width));
        try {function();}
        catch (const p::PropertyError& value) {
            if (failure) {const auto& f=value.failure;
                *failure={f.reason,f.input,f.index,f.first_t_index,f.first_p_index,
                    f.temperature,f.pressure,f.detail,f.fp};}
            throw c::StateError(value.status,value.what());
        }
        if (failure) {const p::PropertyFailure empty;
            *failure={empty.reason,empty.input,empty.index,empty.first_t_index,empty.first_p_index,
                empty.temperature,empty.pressure,empty.detail,empty.fp};}
    });
}

p::PropertyInput input(Input value) {
    c::require_buffer(value.values,value.count);
    return {{value.values,value.count},{value.kind.value,value.kind.precision,value.kind.strong},value.layout};
}
p::PropertyInput input(Operand value) {
    auto result=input(value.real);result.imaginary=value.imaginary;result.category=value.category;return result;
}
void output(Output value,std::size_t count) {
    c::require_output(value.values,value.count,count);c::require_buffer(value.imaginary,count);
    c::require_buffer(value.kind,1);c::require_buffer(value.category,1);
    c::require_output(value.events,value.event_count,p::property_event_count);
}
void ready(const p::PropertyResult& value,std::size_t count) {
    if (value.values.size()!=count || value.imaginary.size()!=count)
        throw std::runtime_error("native property result extent is incorrect");
}
void publish(const p::PropertyResult& value,Output output) {
    if (!value.values.empty()) {
        std::copy(value.values.begin(),value.values.end(),output.values);
        std::copy(value.imaginary.begin(),value.imaginary.end(),output.imaginary);
    }
    *output.kind={0.,value.kind.precision,value.kind.strong};*output.category=value.category;
    std::copy(value.events.begin(),value.events.end(),output.events);
}
void publish(const std::vector<double>& value,double* output,std::size_t count) {
    if (value.size()!=count) throw std::runtime_error("native EOS result extent is incorrect");
    if (!value.empty()) std::copy(value.begin(),value.end(),output);
}
#define OUT_RANGES(value) write((value).values,(value).count),write((value).imaginary,(value).count), \
    write((value).kind,1),write((value).category,1),write((value).events,(value).event_count)
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_property_backend_v1(
    char* version,size_t version_capacity,char* revision,size_t revision_capacity,char* error,size_t error_capacity) {
    return invoke({write(version,version_capacity),write(revision,revision_capacity)},nullptr,error,error_capacity,[&] {
        const auto v=CoolProp::get_global_param_string("version"),r=CoolProp::get_global_param_string("gitrevision");
        if (version_capacity<=v.size() || revision_capacity<=r.size())
            throw std::invalid_argument("property backend version buffer is too short");
        std::copy(v.begin(),v.end(),version);version[v.size()]='\0';
        std::copy(r.begin(),r.end(),revision);revision[r.size()]='\0';
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_empirical_v1(
    uint32_t getter,Input temperature,Input pressure,Output result,Failure* failure,char* error,size_t error_capacity) {
    const Input used_pressure=getter==2?pressure:Input{};
    return invoke({read(temperature),read(used_pressure),OUT_RANGES(result)},failure,error,error_capacity,[&] {
        if (getter>7) throw std::invalid_argument("unknown empirical getter");
        const auto count=getter==7?std::size_t{1}:temperature.count;output(result,count);
        const auto value=p::empirical(static_cast<p::Empirical>(getter),input(temperature),input(used_pressure));
        ready(value,count);publish(value,result);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_water_pt_v1(
    const double* temperature,const double* pressure,size_t count,Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(temperature,count),read(pressure,count)},failure,error,error_capacity,[&] {
        p::validate_water_pt({temperature,count},{pressure,count});
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_co2_validate_pt_v1(
    const double* temperature,const double* pressure,size_t count,Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(temperature,count),read(pressure,count)},failure,error,error_capacity,[&] {
        p::validate_co2_pt({temperature,count},{pressure,count});
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_co2_scalar_bundle_v1(
    double temperature,double pressure,double* values,size_t value_count,Failure* failure,char* error,size_t error_capacity) {
    return invoke({write(values,value_count)},failure,error,error_capacity,[&] {
        c::require_output(values,value_count,5);
        const auto value=p::co2_pt({}, {&temperature,1},{&pressure,1},true);publish(value,values,value_count);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_co2_pt_v1(
    const double* temperature,const double* pressure,size_t count,const uint32_t* keys,size_t key_count,
    double* values,size_t value_count,Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(temperature,count),read(pressure,count),read(keys,key_count),write(values,value_count)},
        failure,error,error_capacity,[&] {
        c::require_output(values,value_count,c::product(count,key_count));
        std::vector<std::uint32_t> requested;requested.reserve(key_count);
        for (size_t i=0;i<key_count;++i) {
            if (keys[i]>4) throw std::invalid_argument("unknown CO2 property key");
            requested.push_back(keys[i]);
        }
        const auto value=p::co2_pt(requested,{temperature,count},{pressure,count},false);publish(value,values,value_count);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_sco2_validate_v1(
    const double* temperature,size_t temperature_count,const double* pressure,size_t pressure_count,
    Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(temperature,temperature_count),read(pressure,pressure_count)},failure,error,error_capacity,[&] {
        p::validate_sco2({temperature,temperature_count},{pressure,pressure_count});
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_sco2_pt_v1(
    uint32_t form,const tpmshx_property_key_v1* keys,size_t key_count,const double* temperature,const double* pressure,
    size_t count,double* values,size_t value_count,Failure* failure,char* error,size_t error_capacity) {
    // Key characters are borrowed buffers too; validate them before error writes.
    try {
        c::require_buffer(keys,key_count);
        for (size_t i=0;i<key_count;++i) {
            c::require_buffer(keys[i].data,keys[i].size);
            c::require_disjoint(error,error_capacity,keys[i].data,keys[i].size);
            c::require_disjoint(values,value_count,keys[i].data,keys[i].size);
            if (failure) c::require_disjoint(failure,1,keys[i].data,keys[i].size);
        }
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    return invoke({read(keys,key_count),read(temperature,count),read(pressure,count),write(values,value_count)},
        failure,error,error_capacity,[&] {
        c::require_output(values,value_count,c::product(count,key_count));
        std::vector<std::string> requested;requested.reserve(key_count);
        for (size_t i=0;i<key_count;++i) requested.push_back(keys[i].size?std::string(keys[i].data,keys[i].size):std::string{});
        const auto value=p::sco2_pt(form,requested,{temperature,count},{pressure,count});publish(value,values,value_count);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_sco2_hp_scalar_v1(
    double enthalpy,double pressure,double* temperature,size_t temperature_count,
    Failure* failure,char* error,size_t error_capacity) {
    return invoke({write(temperature,temperature_count)},failure,error,error_capacity,[&] {
        c::require_output(temperature,temperature_count,1);
        const auto value=p::sco2_hp({&enthalpy,1},{&pressure,1},true);publish(value,temperature,temperature_count);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_sco2_hp_v1(
    const double* enthalpy,const double* pressure,size_t count,double* temperature,size_t temperature_count,
    Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(enthalpy,count),read(pressure,count),write(temperature,temperature_count)},failure,error,error_capacity,[&] {
        c::require_output(temperature,temperature_count,count);
        const auto value=p::sco2_hp({enthalpy,count},{pressure,count},false);publish(value,temperature,temperature_count);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_reynolds_v1(
    Input rho,Input speed,Input diameter,Input mu,Output result,Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(rho),read(speed),read(diameter),read(mu),OUT_RANGES(result)},failure,error,error_capacity,[&] {
        output(result,rho.count);const auto value=p::reynolds(input(rho),input(speed),input(diameter),input(mu));
        ready(value,rho.count);publish(value,result);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_prandtl_v1(
    Operand mu,Operand cp,Operand conductivity,Output result,Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(mu),read(cp),read(conductivity),OUT_RANGES(result)},failure,error,error_capacity,[&] {
        output(result,mu.real.count);const auto value=p::prandtl(input(mu),input(cp),input(conductivity));
        ready(value,mu.real.count);publish(value,result);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_surface_transfer_v1(
    Operand nu,Operand conductivity,Operand diameter,Output result,Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(nu),read(conductivity),read(diameter),OUT_RANGES(result)},failure,error,error_capacity,[&] {
        output(result,nu.real.count);const auto value=p::surface_transfer(input(nu),input(conductivity),input(diameter));
        ready(value,nu.real.count);publish(value,result);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_re_pr_v1(
    Input rho,Input mu,Input conductivity,Input cp,Input speed,Input diameter,Output re,Output pr,
    Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(rho),read(mu),read(conductivity),read(cp),read(speed),read(diameter),OUT_RANGES(re),OUT_RANGES(pr)},
        failure,error,error_capacity,[&] {
        output(re,rho.count);output(pr,rho.count);
        const auto value=p::inlet_re_pr(input(rho),input(mu),input(conductivity),input(cp),input(speed),input(diameter));
        ready(value[0],rho.count);ready(value[1],rho.count);publish(value[0],re);publish(value[1],pr);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_inlet_transfer_v1(
    Input nu,Input conductivity,Input diameter,Input area,Input epsilon,Output surface,Output volume,Output pore,
    Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(nu),read(conductivity),read(diameter),read(area),read(epsilon),
        OUT_RANGES(surface),OUT_RANGES(volume),OUT_RANGES(pore)},failure,error,error_capacity,[&] {
        output(surface,nu.count);output(volume,nu.count);output(pore,nu.count);
        const auto value=p::inlet_transfer(input(nu),input(conductivity),input(diameter),input(area),input(epsilon));
        for (const auto& item:value) ready(item,nu.count);
        publish(value[0],surface);publish(value[1],volume);publish(value[2],pore);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_volumetric_transfer_v1(
    Input surface,Input area,Output result,Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(surface),read(area),OUT_RANGES(result)},failure,error,error_capacity,[&] {
        output(result,surface.count);const auto value=p::volumetric_transfer(input(surface),input(area));
        ready(value,surface.count);publish(value,result);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_pore_conductivity_v1(
    Input epsilon,Input conductivity,Output result,Failure* failure,char* error,size_t error_capacity) {
    return invoke({read(epsilon),read(conductivity),OUT_RANGES(result)},failure,error,error_capacity,[&] {
        output(result,epsilon.count);const auto value=p::pore_conductivity(input(epsilon),input(conductivity));
        ready(value,epsilon.count);publish(value,result);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_nu_inputs_v1(
    uint32_t route,Input re,Input pr,Input cell,Input diameter,Input floor,
    Output prepared_re,double* extrema,size_t extrema_count,Failure* failure,char* error,size_t error_capacity) {
    const Input used_pr=route==4?pr:Input{},used_cell=route==4?cell:Input{},used_diameter=route==4?diameter:Input{};
    const Input used_floor=route==1?floor:Input{};
    return invoke({read(re),read(used_pr),read(used_cell),read(used_diameter),read(used_floor),
        OUT_RANGES(prepared_re),write(extrema,extrema_count)},failure,error,error_capacity,[&] {
        if (route>4) throw std::invalid_argument("unsupported Nu route");
        output(prepared_re,re.count);c::require_output(extrema,extrema_count,4);
        std::array<double,4> observed{};
        const auto value=p::nu_inputs(static_cast<p::NuRoute>(route),input(re),input(used_pr),input(used_cell),input(used_diameter),
            input(used_floor),observed);
        ready(value,re.count);publish(value,prepared_re);std::copy(observed.begin(),observed.end(),extrema);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_nu_v1(
    uint32_t route,uint32_t topology,Input re,Input pr,Input cell,Input diameter,tpmshx_grid_scalar_v1 alpha,
    Output result,Failure* failure,char* error,size_t error_capacity) {
    const Input used_cell=route==2?Input{}:cell,used_diameter=route==2?Input{}:diameter;
    return invoke({read(re),read(pr),read(used_cell),read(used_diameter),OUT_RANGES(result)},failure,error,error_capacity,[&] {
        if (route>4 || topology>1) throw std::invalid_argument("unsupported Nu route or topology");
        output(result,re.count);
        const auto value=p::nusselt(static_cast<p::NuRoute>(route),static_cast<tpmshx::Topology>(topology),
            input(re),input(pr),input(used_cell),input(used_diameter),{alpha.value,alpha.precision,alpha.strong});
        ready(value,re.count);publish(value,result);
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_roughness_v1(
    uint32_t quantity,Input first,Input second,Output result,Failure* failure,char* error,size_t error_capacity) {
    const Input a=quantity==5?Input{}:first;
    const Input b=quantity==1 || quantity==2 || quantity==3?second:Input{};
    return invoke({read(a),read(b),OUT_RANGES(result)},failure,error,error_capacity,[&] {
        if (quantity>5) throw std::invalid_argument("unknown roughness quantity");
        const auto count=quantity==5?std::size_t{1}:a.count;output(result,count);
        const auto value=p::roughness(static_cast<p::RoughnessQuantity>(quantity),input(a),input(b));
        ready(value,count);publish(value,result);
    });
}
#undef OUT_RANGES
