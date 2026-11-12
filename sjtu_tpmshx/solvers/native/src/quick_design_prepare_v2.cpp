#include "tpmshx/quick_design_stage_c_api.h"
#include "tpmshx/geometry.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "tpmshx/preparation_df.hpp"
#include "tpmshx/preparation_flow.hpp"
#include "preparation_c_boundary.hpp"
#include "preparation_properties.hpp"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstring>
#include <memory>
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
using Request=tpmshx_quick_host_request_v2;
using Scalar=tpmshx_grid_scalar_v1;

Scalar packed(g::Scalar x) {return {x.value,x.precision,x.strong};}
g::Scalar scalar(Scalar x) {return g::checked({x.value,x.precision,x.strong});}
Scalar weak(double value) {return {value,64,0};}
tpmshx_preparation_array_v1 view(const std::vector<double>& x) {return {x.data(),x.size()};}
std::string text(tpmshx_preparation_text_v1 x) {
    require_buffer(x.data,x.size);return x.size?std::string(x.data,x.size):std::string{};
}
tpmshx_preparation_text_v1 text(const std::string& x) {return {x.data(),x.size()};}
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

struct Engine {
    tpmshx_quick_input_v2 input;
    const tpmshx_quick_callbacks_v2* callbacks;
    const unsigned char* destination;size_t destination_size;
    char* error;size_t error_size;
    tpmshx_quick_prepared_v2 result{};
    std::array<std::vector<double>,3> widths,edges,initial;
    std::vector<double> epsilon,epsilon_a,conductivity;
    std::array<std::array<p::PropertyResult,5>,2> properties;
    std::array<Scalar,4> sections{};
    std::array<std::array<Scalar,2>,2> flow{};
    std::array<uint32_t,2> fluids{};
    uint32_t tp=0;

    Engine(const tpmshx_quick_input_v2& source,const tpmshx_quick_callbacks_v2* hooks,
           const void* output,size_t output_size,char* message,size_t capacity)
        :input(source),callbacks(hooks),destination(static_cast<const unsigned char*>(output)),
         destination_size(output_size),error(message),error_size(capacity) {
        result.abi_version=2;result.struct_size=sizeof(result);
        if(!input.have_height)input.values[TPMSHX_QUICK_HEIGHT]=input.values[TPMSHX_QUICK_SPAN];
    }
    bool hosted() const {return callbacks && callbacks->raw_objects;}
    void call(Request& request) {
        if(callbacks && callbacks->host && callbacks->host(callbacks->context,&request))
            throw p::c_api::StateError(TPMSHX_QUICK_HOST_FAILURE,"quick-design host operation failed");
    }
    Request request(uint32_t operation,uint32_t side=0,uint32_t at=0) {
        Request value{};value.operation=operation;value.side=side;value.index=at;return value;
    }
    void notify(uint32_t operation,uint32_t side=0,uint32_t at=0) {
        auto value=request(operation,side,at);call(value);
    }
    template<class T> void safe(const T* values,size_t count) const {
        require_buffer(values,count);
        require_disjoint(destination,destination_size,values,count);
        require_disjoint(error,error_size,values,count);
    }
    p::PropertyInput property(tpmshx_property_input_v1 value,double imaginary=0.,uint32_t category=0) const {
        safe(value.values,value.count);
        return {{value.values,value.count},scalar(value.kind),value.layout,imaginary,category};
    }
    tpmshx_property_input_v1 scalar_property(Scalar& value) const {
        return {&value.value,1,value,value.strong?1u:0u};
    }
    [[noreturn]] void property_failure(const p::PropertyError& problem,uint32_t side,uint32_t phase,uint32_t at) {
        const auto& f=problem.failure;
        tpmshx_property_failure_v1 failure{f.reason,f.input,f.index,f.first_t_index,f.first_p_index,
            f.temperature,f.pressure,f.detail,f.fp};
        auto value=request(TPMSHX_QUICK_FAILURE,side,at);
        value.flags[0]=fluids[side];value.flags[1]=phase;value.failure=&failure;
        value.status=problem.status;const std::string message=problem.what();value.text=text(message);call(value);
        throw p::c_api::StateError(problem.status,message);
    }
    template<class Function> auto property_call(Function function,uint32_t side,uint32_t phase,uint32_t at) {
        try {return function();}catch(const p::PropertyError& problem){property_failure(problem,side,phase,at);}
    }
    void validate_full() {
        notify(TPMSHX_QUICK_WARM_CHECK);
        if(!hosted() && input.warm_start)for(size_t side=0;side<3;++side) {
            const auto source=input.initial[side];safe(source.data,source.size);
            for(size_t n=0;n<source.size;++n)if(!std::isfinite(source.data[n]))
                throw std::invalid_argument("design external warm start contains a non-finite temperature");
        }
        auto labels=request(TPMSHX_QUICK_LABEL_CHECK);call(labels);
        if(!hosted() && ((text(input.arrangement)!="cross" && text(input.arrangement)!="counter") ||
           (text(input.property_mode)!="const" && text(input.property_mode)!="mean")))
            throw std::invalid_argument("unsupported quick-design arrangement or property model");
        notify(TPMSHX_QUICK_POSITIVE_SNAPSHOT);
        constexpr const char* names[]{"l","t","s","Lx","height","k_s","tol","mdot_h","mdot_c",
                                     "T_in_h","T_in_c","P_in_h","P_in_c"};
        for(uint32_t n=0;n<TPMSHX_QUICK_VALUE_COUNT;++n) {
            auto check=request(TPMSHX_QUICK_POSITIVE_CHECK,0,n);
            check.flags[0]=std::isfinite(input.values[n].value) && input.values[n].value>0.;call(check);
            if(!check.flags[0])throw std::invalid_argument(std::string("quick-design ")+names[n]+" must be finite and positive");
        }
        auto shape=request(TPMSHX_QUICK_SHAPE_CHECK);shape.flags[0]=text(input.arrangement)=="cross";call(shape);
        flag(shape.flags[0]);result.controls=controls(shape.flags[0]);
        result.shape[0]=data::quick_design_nx;result.shape[1]=result.controls.ny;result.shape[2]=result.controls.nz;
        if(!hosted() && input.warm_start)for(size_t n=0;n<3;++n) {
            if(input.initial_shape[n]!=result.shape[n] || input.initial[n].size!=cells())
                throw std::invalid_argument("quick-design warm start must match the prepared grid");
            initial[n].assign(input.initial[n].data,input.initial[n].data+input.initial[n].size);
            result.initial[n]=view(initial[n]);
        }
    }
    size_t cells() const {return p::c_api::product(p::c_api::product(result.shape[0],result.shape[1]),result.shape[2]);}
    void prepare_geometry(bool full) {
        if(!hosted())tp=topology(text(input.topology));
        uint32_t hit=0;
        if(callbacks && callbacks->geometry_cache && callbacks->geometry_cache(callbacks->context,0,&result.geometry,&hit))
            throw p::c_api::StateError(TPMSHX_QUICK_HOST_FAILURE,"quick-design geometry cache lookup failed");
        flag(hit);
        if(!hit) {
            auto pack=request(TPMSHX_QUICK_GEOMETRY_PACK);
            pack.scalars[0]=input.values[TPMSHX_QUICK_CELL];pack.scalars[1]=input.values[TPMSHX_QUICK_WALL];
            pack.flags[0]=tp;
            pack.flags[1]=pack.scalars[0].strong==1?pack.scalars[0].precision:64;
            pack.flags[2]=g::result_precision(scalar(pack.scalars[1]),scalar(pack.scalars[0]));call(pack);
            tp=pack.flags[0];if(tp>1)throw std::invalid_argument("invalid Quick geometry topology");
            const auto model=geo::calibration(static_cast<tpmshx::Topology>(tp));
            result.geometry=packed_geometry(geo::standard_geometry(index(tp),model,pack.scalars[0].value,
                pack.scalars[1].value,pack.flags[1],pack.flags[2]));
            if(callbacks && callbacks->geometry_cache && callbacks->geometry_cache(callbacks->context,1,&result.geometry,&hit))
                throw p::c_api::StateError(TPMSHX_QUICK_HOST_FAILURE,"quick-design geometry cache publication failed");
        }
        material(false,full);
    }
    double material(bool final,bool full=true) {
        auto pack=request(TPMSHX_QUICK_MATERIAL_PACK,0,final);
        pack.geometry=&result.geometry;pack.flags[0]=tp;pack.flags[1]=final?1:input.have_chi;
        pack.scalars[0]=full?input.values[TPMSHX_QUICK_CONDUCTIVITY]:weak(data::quick_design_k_s);
        pack.scalars[1]=weak(final?1.:input.chi);pack.flags[2]=pack.scalars[0].strong==1?pack.scalars[0].precision:64;
        call(pack);tp=pack.flags[0];if(tp>1)throw std::invalid_argument("invalid Quick material topology");
        flag(pack.flags[1]);
        const auto model=geo::calibration(static_cast<tpmshx::Topology>(tp));
        const auto value=geo::solid_conductivity(model.solid_tortuosity,result.geometry.epsilon,pack.scalars[0].value,
            pack.flags[1]?std::optional<double>{pack.scalars[1].value}:std::nullopt,pack.flags[2]);
        if(final)result.solid_precision=pack.flags[2];return value;
    }
    void grid() {
        constexpr uint32_t slots[]{TPMSHX_QUICK_LENGTH,TPMSHX_QUICK_SPAN,TPMSHX_QUICK_HEIGHT};
        for(uint32_t axis=0;axis<3;++axis) {
            auto pack=request(TPMSHX_QUICK_WIDTH_PACK,0,axis);pack.scalars[0]=input.values[slots[axis]];
            pack.flags[0]=pack.scalars[0].strong==1?pack.scalars[0].precision:64;call(pack);
            widths[axis]=g::uniform(result.shape[axis],scalar(pack.scalars[0]));
            for(auto& value:widths[axis])value=g::checked({value,pack.flags[0],1}).value;
            edges[axis]=g::cumulative_widths({widths[axis].data(),widths[axis].size()},pack.flags[0]);
            result.widths[axis]=view(widths[axis]);result.edges[axis]=view(edges[axis]);result.width_precision[axis]=pack.flags[0];
        }
    }
    void observe_property(uint32_t side,uint32_t at) {
        auto& output=properties[side][at];auto observation=request(TPMSHX_QUICK_PROPERTY_RESULT,side,at);
        observation.flags[0]=fluids[side];observation.property_values=view(output.values);
        observation.property_kind=packed(output.kind);observation.property_category=output.category;
        observation.property_imaginary=view(output.imaginary);
        observation.floating_events=output.events.data();observation.floating_event_count=output.events.size();call(observation);
    }
    void prepare_properties(uint32_t side) {
        auto entry=request(TPMSHX_QUICK_PROPERTY_ENTRY,side);entry.text=input.fluids[side];call(entry);
        fluids[side]=fluid(text(entry.text));
        auto temperature=input.values[TPMSHX_QUICK_TEMPERATURE_A+side];
        auto pressure=input.values[TPMSHX_QUICK_PRESSURE_A+side];
        if(fluids[side]==1) {
            auto check=request(TPMSHX_QUICK_STATE_PACK,side,0);check.flags[0]=fluids[side];
            check.property_inputs[0]=scalar_property(temperature);check.property_inputs[1]=scalar_property(pressure);call(check);
            const auto first=property(check.property_inputs[0]),second=property(check.property_inputs[1]);
            property_call([&]{p::validate_water_pt(first.values,second.values);return 0;},side,0,0);
        }
        constexpr uint32_t air_getters[]{2,0,1,3};
        constexpr const char* eos_keys[]{"D","V","L","C"};
        for(uint32_t at=0;at<4;++at) {
            auto pack=request(TPMSHX_QUICK_PROPERTY_PACK,side,at);pack.flags[0]=fluids[side];
            pack.property_inputs[0]=scalar_property(temperature);pack.property_inputs[1]=scalar_property(pressure);
            if(fluids[side]==1) {pack.property_inputs[0].kind={temperature.value,64,1};pack.property_inputs[0].layout=2;}
            call(pack);
            const auto first=property(pack.property_inputs[0]),second=property(pack.property_inputs[1]);
            auto& output=properties[side][at];
            if(fluids[side]<2) {
                output=property_call([&]{return p::empirical(static_cast<p::Empirical>(fluids[side]?4+at:air_getters[at]),first,second);},side,1,at);
            } else {
                property_call([&]{if(fluids[side]==3)p::validate_co2_pt(first.values,second.values);
                    else p::validate_sco2(first.values,second.values);return 0;},side,fluids[side]==3?2:4,at);
                auto query=request(TPMSHX_QUICK_STATE_PACK,side,at+1);query.flags[0]=fluids[side];query.flags[1]=1;
                query.property_inputs[0]=pack.property_inputs[0];query.property_inputs[1]=pack.property_inputs[1];call(query);
                const auto t=property(query.property_inputs[0]),pr=property(query.property_inputs[1]);
                output.values=property_call([&]{
                    if(fluids[side]==3) {
                        auto queried=p::co2_pt({at},t.values,pr.values,query.flags[1]!=0);
                        return query.flags[1]?std::vector<double>{queried.at(at)}:queried;
                    }
                    return p::sco2_pt(query.flags[1]?0:1,{eos_keys[at]},t.values,pr.values);
                },side,fluids[side]==3?3:5,at);
                output.kind={0.,64,query.flags[1]?0u:1u};
            }
            observe_property(side,at);
        }
        auto pack=request(TPMSHX_QUICK_PRANDTL_PACK,side,4);
        constexpr uint32_t order[]{1,3,2};
        for(uint32_t n=0;n<3;++n) {
            auto& value=properties[side][order[n]];
            pack.property_inputs[n]={value.values.data(),value.values.size(),packed(value.kind),value.kind.strong?1u:0u};
        }
        call(pack);
        const auto mu=property(pack.property_inputs[0],pack.imaginary_inputs[0],pack.categories[0]);
        const auto cp=property(pack.property_inputs[1],pack.imaginary_inputs[1],pack.categories[1]);
        const auto k=property(pack.property_inputs[2],pack.imaginary_inputs[2],pack.categories[2]);
        properties[side][4]=property_call([&]{return p::prandtl(mu,cp,k);},side,6,4);observe_property(side,4);
    }
    void pressure_fractions() {
        prepare_properties(0);prepare_properties(1);
        auto pack=request(TPMSHX_QUICK_SECTIONS_PACK);
        pack.scalars[0]=weak(result.geometry.epsilon_a);pack.scalars[1]=input.values[TPMSHX_QUICK_SPAN];
        pack.scalars[2]=input.values[TPMSHX_QUICK_LENGTH];pack.scalars[3]=input.values[TPMSHX_QUICK_HEIGHT];
        pack.flags[0]=text(input.arrangement)=="cross";call(pack);flag(pack.flags[0]);
        const auto values=p::quick_design_sections(scalar(pack.scalars[0]),scalar(pack.scalars[1]),
            scalar(pack.scalars[2]),scalar(pack.scalars[3]),pack.flags[0]);
        for(size_t n=0;n<4;++n)sections[n]=packed(values[n]);
        auto section_result=request(TPMSHX_QUICK_SECTIONS_RESULT);
        std::copy(sections.begin(),sections.end(),std::begin(section_result.scalars));call(section_result);
        for(uint32_t side=0;side<2;++side) {
            notify(TPMSHX_QUICK_PRESSURE_ENTRY,side);
            auto args=request(TPMSHX_QUICK_FLOW_PACK,side);
            args.scalars[0]=input.values[TPMSHX_QUICK_MASS_A+side];args.scalars[1]=sections[side*2];
            args.flags[0]=text(input.fluids[side])=="air";
            args.scalars[2]=hosted() || args.flags[0]?weak(0.):packed({properties[side][0].values.at(0),
                properties[side][0].kind.precision,properties[side][0].kind.strong});call(args);flag(args.flags[0]);
            const auto value=p::quick_design_flow(scalar(args.scalars[0]),scalar(args.scalars[1]),scalar(args.scalars[2]),args.flags[0]);
            flow[side]={packed(value[0]),packed(value[1])};
            auto produced=request(TPMSHX_QUICK_FLOW_RESULT,side);produced.flags[0]=args.flags[0];
            produced.scalars[0]=flow[side][0];produced.scalars[1]=flow[side][1];call(produced);
            auto compare=request(TPMSHX_QUICK_PRESSURE_COMPARE,side);compare.flags[0]=text(input.fluids[side])=="air";call(compare);flag(compare.flags[0]);
            const bool air=compare.flags[0];auto pressure=request(TPMSHX_QUICK_PRESSURE_PACK,side);
            pressure.flags[0]=air;pressure.flags[1]=tp;pressure.flags[2]=input.strict;
            pressure.scalars[0]=air?flow[side][0]:flow[side][1];
            pressure.scalars[1]=hosted()?weak(0.):air?input.values[TPMSHX_QUICK_TEMPERATURE_A+side]:packed({properties[side][0].values.at(0),properties[side][0].kind.precision,properties[side][0].kind.strong});
            pressure.scalars[2]=hosted()?weak(0.):air?input.values[TPMSHX_QUICK_PRESSURE_A+side]:packed({properties[side][1].values.at(0),properties[side][1].kind.precision,properties[side][1].kind.strong});
            pressure.scalars[3]=hosted()?weak(0.):air?packed({properties[side][1].values.at(0),properties[side][1].kind.precision,properties[side][1].kind.strong}):sections[side*2+1];
            pressure.scalars[4]=sections[side*2+1];pressure.scalars[5]=input.values[TPMSHX_QUICK_CELL];
            pressure.property_kind=input.values[TPMSHX_QUICK_WALL];call(pressure);flag(pressure.flags[2]);
            result.inlet_pressure[side]=property_call([&]{return air?
                p::df_compressible_typed(pressure.flags[1],pressure.scalars[5].value,pressure.property_kind.value,
                    scalar(pressure.scalars[0]),scalar(pressure.scalars[1]),scalar(pressure.scalars[2]),
                    scalar(pressure.scalars[3]),scalar(pressure.scalars[4]),pressure.flags[2]):
                p::df_incompressible_typed(pressure.flags[1],pressure.scalars[5].value,pressure.property_kind.value,
                    scalar(pressure.scalars[0]),scalar(pressure.scalars[1]),scalar(pressure.scalars[2]),scalar(pressure.scalars[3]));},side,7,0);
            auto observation=request(TPMSHX_QUICK_PRESSURE_RESULT,side);observation.flags[0]=air;
            observation.pressure=&result.inlet_pressure[side];call(observation);
        }
        for(uint32_t side=0;side<2;++side) {
            auto args=request(TPMSHX_QUICK_FRACTION_PACK,side);const auto& pressure=result.inlet_pressure[side];
            args.scalars[0]={pressure.dP_Pa,pressure.precision,pressure.strong};
            args.scalars[1]=input.values[TPMSHX_QUICK_PRESSURE_A+side];call(args);
            result.fractions[side]=packed(p::relative_pressure(scalar(args.scalars[0]),scalar(args.scalars[1])));
        }
    }
    void run(bool full) {
        if(full)validate_full();
        prepare_geometry(full);
        if(full){grid();notify(TPMSHX_QUICK_OPERATING_SNAPSHOT);}
        pressure_fractions();
        if(!full)return;
        notify(TPMSHX_QUICK_CONFIG_SNAPSHOT);
        epsilon.assign(cells(),result.geometry.epsilon);epsilon_a.assign(cells(),result.geometry.epsilon_a);
        conductivity.assign(cells(),material(true));
        result.epsilon=view(epsilon);result.epsilon_a=view(epsilon_a);result.solid_conductivity=view(conductivity);
        for(uint32_t at=0;at<2;++at) {
            auto pack=request(TPMSHX_QUICK_UNIT_PACK,0,at);pack.scalars[0]=input.values[at];call(pack);
            auto converted=pack.flags[0]?weak(0.):packed(g::divide(scalar(pack.scalars[0]),g::weak(1000.)));
            auto observation=request(TPMSHX_QUICK_UNIT_RESULT,0,at);observation.flags[0]=pack.flags[0];observation.scalars[0]=converted;call(observation);
            (at?result.wall_thickness_m:result.cell_length_m)=converted;
        }
        notify(TPMSHX_QUICK_FINAL_SNAPSHOT);
    }
};

template<class T>void version(const T* value) {
    require_buffer(value,1);
    if(value->abi_version!=2 || value->struct_size!=sizeof(T))throw std::invalid_argument("quick-design v2 ABI version or struct size is invalid");
}
template<class T>void buffers(const tpmshx_quick_input_v2* input,const tpmshx_quick_callbacks_v2* callbacks,T* output,char* error,size_t capacity) {
    require_disjoint(error,capacity,input,input?1:0);require_disjoint(error,capacity,output,output?1:0);
    require_disjoint(error,capacity,callbacks,callbacks?1:0);version(input);version(output);if(callbacks) {
        version(callbacks);flag(callbacks->raw_objects);
        if(callbacks->raw_objects && !callbacks->host)throw std::invalid_argument("Quick raw objects require a host operation callback");
    }
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
        std::copy(std::begin(owner.result.inlet_pressure),std::end(owner.result.inlet_pressure),std::begin(value.inlet_pressure));*output=value;
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_quick_prepared_release_v2(tpmshx_quick_prepared_v2* output) {
    if(!output)return;delete static_cast<Engine*>(output->owner);*output={};
}
