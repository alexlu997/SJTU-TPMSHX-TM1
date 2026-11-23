#include "tpmshx/quick_design_stage_c_api.h"
#include "tpmshx/geometry.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "tpmshx/preparation_df.hpp"
#include "tpmshx/preparation_df_data.hpp"
#include "tpmshx/preparation_flow.hpp"
#include "preparation_c_boundary.hpp"
#include "preparation_properties.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstring>
#include <locale>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace {
namespace p=tpmshx::preparation;
namespace g=tpmshx::grid;
namespace geo=tpmshx::geometry;
namespace data=tpmshx::model_coefficients;
using p::c_api::require_buffer;
using p::c_api::require_disjoint;

tpmshx_preparation_array_v1 view(const std::vector<double>& x) {return {x.data(),x.size()};}
std::string text(tpmshx_preparation_text_v1 x) {
    require_buffer(x.data,x.size);return x.size?std::string(x.data,x.size):std::string{};
}
void flag(uint32_t x) {if(x>1)throw std::invalid_argument("quick-design flags require 0 or 1");}
uint32_t topology(const std::string& x) {
    if(x=="Diamond")return 0;
    if(x=="Gyroid")return 1;
    throw std::invalid_argument("TPMS geometry supports Diamond and Gyroid only");
}
uint32_t fluid(std::string x) {
    const auto first=x.find_first_not_of(" \t\r\n\f\v"),last=x.find_last_not_of(" \t\r\n\f\v");
    x=first==std::string::npos?std::string{}:x.substr(first,last-first+1);
    std::transform(x.begin(),x.end(),x.begin(),[](unsigned char c){return static_cast<char>(std::tolower(c));});
    if(x=="air")return 0;
    if(x=="water")return 1;
    if(x=="sco2")return 2;
    if(x=="co2")return 3;
    throw std::invalid_argument("unknown quick-design fluid; known: air, co2, sco2, water");
}
const geo::PhiIndex& index(uint32_t tp) {
    if(!tp) {
        static const auto value=geo::PhiIndex::from_topology(tpmshx::Topology::diamond,data::quick_design_geometry_resolution);
        return value;
    }
    static const auto value=geo::PhiIndex::from_topology(tpmshx::Topology::gyroid,data::quick_design_geometry_resolution);
    return value;
}
tpmshx_preparation_geometry_cache_v3 packed_geometry(const geo::Geometry& x) {
    return {x.epsilon,x.epsilon_a,x.epsilon_b,x.area_density,x.hydraulic_diameter};
}
tpmshx_quick_controls_v2 controls(bool cross) {
    if(cross)return {data::quick_design_cross_dir_b,data::quick_design_cross_ny,data::quick_design_cross_nz,
        data::quick_design_cross_maxit,data::quick_design_cross_alpha,data::quick_design_cross_qtol.value_or(0.),
        data::quick_design_cross_chunk.value_or(0),data::quick_design_cross_qtol.has_value(),data::quick_design_cross_chunk.has_value()};
    return {data::quick_design_counter_dir_b,data::quick_design_counter_ny,data::quick_design_counter_nz,
        data::quick_design_counter_maxit,data::quick_design_counter_alpha,data::quick_design_counter_qtol.value_or(0.),
        data::quick_design_counter_chunk.value_or(0),data::quick_design_counter_qtol.has_value(),data::quick_design_counter_chunk.has_value()};
}
std::string general(double value) {
    std::ostringstream stream;stream.imbue(std::locale::classic());stream<<value;return stream.str();
}
// Combine the ordered events of one stage into one word. Keep the first operation code.
void combine(uint32_t& target,const std::array<uint32_t,p::property_event_count>& events) {
    for(const auto event:events) {
        if(!event)continue;
        if(!(target&0xff00u))target|=event&0xff00u;
        target|=event&0xfu;
    }
}

struct Engine {
    tpmshx_quick_input_v2 input;
    const tpmshx_quick_callbacks_v2* callbacks;
    const unsigned char* destination;size_t destination_size;
    char* error;size_t error_size;
    tpmshx_quick_prepared_v2 result{};
    std::array<std::vector<double>,3> widths,edges,initial;
    std::vector<double> epsilon,epsilon_a,conductivity;
    // Order for each side: rho, mu, k, cp, Pr.
    std::array<std::array<double,5>,2> properties{};
    std::array<double,4> sections{};
    std::array<uint32_t,2> fluids{};
    uint32_t tp=0;

    Engine(const tpmshx_quick_input_v2& source,const tpmshx_quick_callbacks_v2* hooks,
           const void* output,size_t output_size,char* message,size_t capacity)
        :input(source),callbacks(hooks),destination(static_cast<const unsigned char*>(output)),
         destination_size(output_size),error(message),error_size(capacity) {
        result.abi_version=2;result.struct_size=sizeof(result);
        if(!input.have_height)input.values[TPMSHX_QUICK_HEIGHT]=input.values[TPMSHX_QUICK_SPAN];
    }
    template<class T> void safe(const T* values,size_t count) const {
        require_buffer(values,count);
        require_disjoint(destination,destination_size,values,count);
        require_disjoint(error,error_size,values,count);
    }
    void validate_full() {
        if(input.warm_start)for(size_t side=0;side<3;++side) {
            const auto source=input.initial[side];safe(source.data,source.size);
            for(size_t n=0;n<source.size;++n)if(!std::isfinite(source.data[n]))
                throw std::invalid_argument("design external warm start contains a non-finite temperature");
        }
        const auto arrangement=text(input.arrangement),mode=text(input.property_mode);
        if((arrangement!="cross" && arrangement!="counter") || (mode!="const" && mode!="mean"))
            throw std::invalid_argument("unsupported quick-design arrangement or property model");
        constexpr const char* names[]{"l","t","s","Lx","height","k_s","tol","mdot_h","mdot_c",
                                     "T_in_h","T_in_c","P_in_h","P_in_c"};
        for(uint32_t n=0;n<TPMSHX_QUICK_VALUE_COUNT;++n)
            if(!(std::isfinite(input.values[n]) && input.values[n]>0.))
                throw std::invalid_argument(std::string("quick-design ")+names[n]+" must be finite and positive");
        result.controls=controls(arrangement=="cross");
        result.shape[0]=data::quick_design_nx;result.shape[1]=result.controls.ny;result.shape[2]=result.controls.nz;
        if(input.warm_start)for(size_t n=0;n<3;++n) {
            if(input.initial_shape[n]!=result.shape[n] || input.initial[n].size!=cells())
                throw std::invalid_argument("quick-design warm start must match the prepared grid");
            initial[n].assign(input.initial[n].data,input.initial[n].data+input.initial[n].size);
            result.initial[n]=view(initial[n]);
        }
    }
    size_t cells() const {return p::c_api::product(p::c_api::product(result.shape[0],result.shape[1]),result.shape[2]);}
    void prepare_geometry(bool full) {
        tp=topology(text(input.topology));
        uint32_t hit=0;
        if(callbacks && callbacks->geometry_cache && callbacks->geometry_cache(callbacks->context,0,&result.geometry,&hit))
            throw p::c_api::StateError(TPMSHX_QUICK_HOST_FAILURE,"quick-design geometry cache lookup failed");
        flag(hit);
        if(!hit) {
            const auto model=geo::calibration(static_cast<tpmshx::Topology>(tp));
            result.geometry=packed_geometry(geo::standard_geometry(index(tp),model,
                input.values[TPMSHX_QUICK_CELL],input.values[TPMSHX_QUICK_WALL]));
            if(callbacks && callbacks->geometry_cache && callbacks->geometry_cache(callbacks->context,1,&result.geometry,&hit))
                throw p::c_api::StateError(TPMSHX_QUICK_HOST_FAILURE,"quick-design geometry cache publication failed");
        }
        material(false,full);
    }
    // The final solid field uses chi=1. The nominal call checks the selected chi.
    double material(bool final,bool full=true) {
        const double k_s=full?input.values[TPMSHX_QUICK_CONDUCTIVITY]:data::quick_design_k_s;
        const auto chi=final?std::optional<double>{1.}:input.have_chi?std::optional<double>{input.chi}:std::nullopt;
        const auto model=geo::calibration(static_cast<tpmshx::Topology>(tp));
        return geo::solid_conductivity(model.solid_tortuosity,result.geometry.epsilon,k_s,chi);
    }
    void grid() {
        constexpr uint32_t slots[]{TPMSHX_QUICK_LENGTH,TPMSHX_QUICK_SPAN,TPMSHX_QUICK_HEIGHT};
        for(uint32_t axis=0;axis<3;++axis) {
            widths[axis]=g::uniform(result.shape[axis],input.values[slots[axis]]);
            edges[axis]=g::cumulative_widths({widths[axis].data(),widths[axis].size()});
            result.widths[axis]=view(widths[axis]);result.edges[axis]=view(edges[axis]);
        }
    }
    [[noreturn]] void state_failure(const p::PropertyError& problem,uint32_t side) {
        std::string message=problem.what();
        if(problem.status==TPMSHX_PREPARATION_WATER_STATE) {
            const auto t=input.values[TPMSHX_QUICK_TEMPERATURE_A+side],pressure=input.values[TPMSHX_QUICK_PRESSURE_A+side];
            message="quick-design properties: water index=(), T="+general(t)+" K, P_abs="+general(pressure)+" Pa: "+message;
        }
        throw p::c_api::StateError(problem.status,message);
    }
    template<class Function> auto property_call(Function function,uint32_t side) {
        try {return function();}catch(const p::PropertyError& problem){state_failure(problem,side);}
    }
    std::vector<double> eos_values(uint32_t side,uint32_t at,double t,double pressure) {
        const auto kind=fluids[side];const size_t expected=kind==3?5u:1u;
        std::array<double,5> stored{};size_t count=0;uint32_t hit=0;
        if(callbacks && callbacks->eos_cache) {
            if(callbacks->eos_cache(callbacks->context,0,kind,at,t,pressure,stored.data(),stored.size(),&count,&hit))
                throw p::c_api::StateError(TPMSHX_QUICK_HOST_FAILURE,"quick-design EOS cache lookup failed");
            flag(hit);
            if(hit) {
                if(count!=expected)throw std::invalid_argument("Quick EOS cache extent is incorrect");
                return {stored.begin(),stored.begin()+static_cast<std::ptrdiff_t>(count)};
            }
        }
        constexpr const char* keys[]{"D","V","L","C"};
        auto values=property_call([&]{
            if(kind==3)return p::co2_pt({},{&t,1},{&pressure,1},true);
            p::validate_sco2({&t,1},{&pressure,1});
            return p::sco2_pt(0,{keys[at]},{&t,1},{&pressure,1});
        },side);
        if(values.size()!=expected)throw std::runtime_error("Quick EOS result extent is incorrect");
        if(callbacks && callbacks->eos_cache) {
            std::copy(values.begin(),values.end(),stored.begin());count=values.size();
            if(callbacks->eos_cache(callbacks->context,1,kind,at,t,pressure,stored.data(),stored.size(),&count,&hit))
                throw p::c_api::StateError(TPMSHX_QUICK_HOST_FAILURE,"quick-design EOS cache publication failed");
        }
        return values;
    }
    void prepare_properties(uint32_t side) {
        fluids[side]=fluid(text(input.fluids[side]));
        const double t=input.values[TPMSHX_QUICK_TEMPERATURE_A+side],pressure=input.values[TPMSHX_QUICK_PRESSURE_A+side];
        if(fluids[side]==1) property_call([&]{p::validate_water_pt({&t,1},{&pressure,1});return 0;},side);
        if(fluids[side]==3) property_call([&]{p::validate_co2_pt({&t,1},{&pressure,1});return 0;},side);
        constexpr uint32_t air_getters[]{2,0,1,3};
        for(uint32_t at=0;at<4;++at) {
            if(fluids[side]<2) {
                const auto getter=static_cast<p::Empirical>(fluids[side]?4+at:air_getters[at]);
                if(const auto range=p::empirical_range(getter);range.label) {
                    if(result.range_count>=TPMSHX_QUICK_RANGE_CAPACITY)
                        throw std::logic_error("Quick range record capacity is exceeded");
                    result.ranges[result.range_count++]={range.label,side,{range.bounds[0],range.bounds[1]},t};
                }
                const auto output=property_call([&]{return p::empirical(getter,{{&t,1}},{{&pressure,1}});},side);
                combine(result.floating_events[side*2],output.events);properties[side][at]=output.values.at(0);
            } else {
                const auto values=eos_values(side,at,t,pressure);
                properties[side][at]=fluids[side]==3?values.at(at):values.at(0);
            }
        }
        const auto& q=properties[side];
        const auto pr=property_call([&]{return p::prandtl({{&q[1],1}},{{&q[3],1}},{{&q[2],1}});},side);
        combine(result.floating_events[side*2+1],pr.events);properties[side][4]=pr.values.at(0);
    }
    void pressure_fractions() {
        prepare_properties(0);prepare_properties(1);
        const bool cross=text(input.arrangement)=="cross";
        sections=p::quick_design_sections(result.geometry.epsilon_a,input.values[TPMSHX_QUICK_SPAN],
            input.values[TPMSHX_QUICK_LENGTH],input.values[TPMSHX_QUICK_HEIGHT],cross);
        for(uint32_t side=0;side<2;++side) {
            const bool air=fluids[side]==0;const auto& q=properties[side];
            const auto flow=p::quick_design_flow(input.values[TPMSHX_QUICK_MASS_A+side],sections[side*2],air?0.:q[0],air);
            const double length=sections[side*2+1];
            const double cell=input.values[TPMSHX_QUICK_CELL],wall=input.values[TPMSHX_QUICK_WALL];
            result.inlet_pressure[side]=property_call([&]{return air?
                p::df_compressible(tp,cell,wall,flow[0],input.values[TPMSHX_QUICK_TEMPERATURE_A+side],
                    input.values[TPMSHX_QUICK_PRESSURE_A+side],q[1],length,input.strict!=0):
                p::df_incompressible(tp,cell,wall,flow[1],q[0],q[1],length);},side);
        }
        for(uint32_t side=0;side<2;++side)
            result.fractions[side]=p::relative_pressure(result.inlet_pressure[side].dP_Pa,
                input.values[TPMSHX_QUICK_PRESSURE_A+side]);
    }
    void run(bool full) {
        if(full)validate_full();
        prepare_geometry(full);
        if(full)grid();
        pressure_fractions();
        if(!full)return;
        epsilon.assign(cells(),result.geometry.epsilon);epsilon_a.assign(cells(),result.geometry.epsilon_a);
        conductivity.assign(cells(),material(true));
        result.epsilon=view(epsilon);result.epsilon_a=view(epsilon_a);result.solid_conductivity=view(conductivity);
        result.cell_length_m=input.values[TPMSHX_QUICK_CELL]/1000.;
        result.wall_thickness_m=input.values[TPMSHX_QUICK_WALL]/1000.;
    }
};

template<class T>void version(const T* value) {
    require_buffer(value,1);
    if(value->abi_version!=2 || value->struct_size!=sizeof(T))throw std::invalid_argument("quick-design v2 ABI version or struct size is invalid");
}
template<class T>void buffers(const tpmshx_quick_input_v2* input,const tpmshx_quick_callbacks_v2* callbacks,T* output,char* error,size_t capacity) {
    require_disjoint(error,capacity,input,input?1:0);require_disjoint(error,capacity,output,output?1:0);
    require_disjoint(error,capacity,callbacks,callbacks?1:0);version(input);version(output);
    if(callbacks)version(callbacks);
    require_disjoint(input,1,output,1);require_disjoint(callbacks,callbacks?1:0,output,1);
    for(auto value:{input->topology,input->arrangement,input->property_mode,input->fluids[0],input->fluids[1]}) {
        require_disjoint(error,capacity,value.data,value.size);require_disjoint(output,1,value.data,value.size);
    }
    flag(input->have_height);flag(input->have_chi);flag(input->strict);flag(input->warm_start);
    if(input->warm_start)for(auto value:input->initial) {
        require_disjoint(error,capacity,value.data,value.size);require_disjoint(output,1,value.data,value.size);
    }
}
template<class T,class Function>int boundary(const tpmshx_quick_input_v2* input,const tpmshx_quick_callbacks_v2* callbacks,
    T* output,char* error,size_t capacity,Function operation) {
    if(!tpmshx::fields::c_api::error_buffer_valid(error,capacity))return TPMSHX_PREPARATION_INVALID;
    try {buffers(input,callbacks,output,error,capacity);}catch(...){return TPMSHX_PREPARATION_INVALID;}
    return p::c_api::boundary(error,capacity,operation);
}
} // namespace

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_quick_design_v2(
    const tpmshx_quick_input_v2* input,const tpmshx_quick_callbacks_v2* callbacks,
    tpmshx_quick_prepared_v2* output,char* error,size_t capacity) {
    return boundary(input,callbacks,output,error,capacity,[&]{
        if(output->owner)throw std::invalid_argument("release the previous Quick prepared owner before reuse");
        auto owner=std::make_unique<Engine>(*input,callbacks,output,sizeof(*output),error,capacity);
        owner->run(true);owner->result.owner=owner.get();*output=owner->result;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_quick_pressure_fractions_v2(
    const tpmshx_quick_input_v2* input,const tpmshx_quick_callbacks_v2* callbacks,
    tpmshx_quick_pressure_v2* output,char* error,size_t capacity) {
    return boundary(input,callbacks,output,error,capacity,[&]{
        Engine owner(*input,callbacks,output,sizeof(*output),error,capacity);owner.run(false);
        tpmshx_quick_pressure_v2 value{};value.abi_version=2;value.struct_size=sizeof(value);
        std::copy(std::begin(owner.result.fractions),std::end(owner.result.fractions),std::begin(value.fractions));
        std::copy(std::begin(owner.result.inlet_pressure),std::end(owner.result.inlet_pressure),std::begin(value.inlet_pressure));
        std::copy(std::begin(owner.result.floating_events),std::end(owner.result.floating_events),std::begin(value.floating_events));
        std::copy(std::begin(owner.result.ranges),std::end(owner.result.ranges),std::begin(value.ranges));
        value.range_count=owner.result.range_count;*output=value;
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_quick_prepared_release_v2(tpmshx_quick_prepared_v2* output) {
    if(!output)return;delete static_cast<Engine*>(output->owner);*output={};
}
