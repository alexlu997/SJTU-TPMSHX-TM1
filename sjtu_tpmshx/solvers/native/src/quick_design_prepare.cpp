#include "tpmshx/quick_design_stage_c_api.h"
#include "tpmshx/geometry.hpp"
#include "tpmshx/grid.hpp"
#include "tpmshx/preparation_df.hpp"
#include "tpmshx/preparation_flow.hpp"
#include "preparation_c_boundary.hpp"
#include "preparation_properties.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <memory>
#include <string>
#include <sstream>
#include <vector>

namespace {
namespace p=tpmshx::preparation;
namespace g=tpmshx::grid;
using p::c_api::require_buffer;
using p::c_api::require_disjoint;

void flag(uint32_t value) {
    if(value>1)throw std::invalid_argument("quick-design flags require 0 or 1");
}
void positive(double value,const char* name) {
    if(!std::isfinite(value) || value<=0.)
        throw std::invalid_argument(std::string("quick-design ")+name+" must be finite and positive");
}
template<class T> void version(const T* value) {
    require_buffer(value,1);
    if(value->abi_version!=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION || value->struct_size!=sizeof(T))
        throw std::invalid_argument("quick-design stage ABI version or struct size is invalid");
}
tpmshx_preparation_array_v1 array(const std::vector<double>& values) {
    return {values.data(),values.size()};
}
const tpmshx::geometry::PhiIndex& index(uint32_t topology) {
    if(topology==TPMSHX_DIAMOND) {
        static const auto value=tpmshx::geometry::PhiIndex::from_topology(tpmshx::Topology::diamond,128);
        return value;
    }
    static const auto value=tpmshx::geometry::PhiIndex::from_topology(tpmshx::Topology::gyroid,128);
    return value;
}
struct Owner {
    std::array<std::vector<double>,3> widths,edges,initial;
    std::vector<double> epsilon,epsilon_a,conductivity;
    tpmshx_quick_prepared_v1 value{};

    explicit Owner(const tpmshx_quick_input_v1& input) {
        flag(input.warm_start);
        // External warm temperatures are checked before the operating point.
        if(input.warm_start)for(size_t side=0;side<3;++side) {
            const auto source=input.initial[side];require_buffer(source.data,source.size);
            for(size_t n=0;n<source.size;++n)if(!std::isfinite(source.data[n])) {
                if(!input.initial_shape[1] || !input.initial_shape[2])
                    throw std::invalid_argument("quick-design warm start must match the prepared grid");
                const size_t yz=p::c_api::product(input.initial_shape[1],input.initial_shape[2]);
                const char* names[]{"A","B","solid"};
                std::ostringstream text;
                text<<"design external warm start: "<<names[side]<<" temperature index=("<<n/yz<<", "
                    <<(n/input.initial_shape[2])%input.initial_shape[1]<<", "<<n%input.initial_shape[2]
                    <<"), T="<<source.data[n]<<" K is non-finite";
                throw std::invalid_argument(text.str());
            }
        }
        if(input.arrangement>TPMSHX_COUNTER || input.property_mode>TPMSHX_MEAN)
            throw std::invalid_argument("unsupported quick-design arrangement or property model");
        flag(input.have_height);flag(input.have_solid_conductivity);flag(input.have_tolerance);
        const double height=input.have_height?input.height_m:input.span_m;
        const double conductivity_s=input.have_solid_conductivity?input.solid_conductivity_W_mK:16.;
        const double tolerance=input.have_tolerance?input.tolerance:1e-5;
        positive(input.cell_length_mm,"l");positive(input.wall_thickness_mm,"t");
        positive(input.span_m,"s");positive(input.length_m,"Lx");positive(height,"height");
        positive(conductivity_s,"k_s");positive(tolerance,"tol");
        positive(input.sides[0].mass_flow_kg_s,"mdot_h");positive(input.sides[1].mass_flow_kg_s,"mdot_c");
        positive(input.sides[0].temperature_K,"T_in_h");positive(input.sides[1].temperature_K,"T_in_c");
        positive(input.sides[0].pressure_Pa,"P_in_h");positive(input.sides[1].pressure_Pa,"P_in_c");
        const bool cross=input.arrangement==TPMSHX_CROSS;
        value.shape[0]=60;value.shape[1]=cross?40:1;value.shape[2]=cross?1:2;
        const size_t cells=value.shape[0]*value.shape[1]*value.shape[2];
        if(input.warm_start) {
            for(size_t axis=0;axis<3;++axis)if(input.initial_shape[axis]!=value.shape[axis])
                throw std::invalid_argument("quick-design warm start must match the prepared grid");
            for(const auto source:input.initial)if(source.size!=cells)
                throw std::invalid_argument("quick-design warm start must match the prepared grid");
        }
        if(input.topology>TPMSHX_GYROID)
            throw std::invalid_argument("TPMS geometry supports Diamond and Gyroid only");
        const auto model=tpmshx::geometry::calibration(static_cast<tpmshx::Topology>(input.topology));
        const auto geo=tpmshx::geometry::standard_geometry(index(input.topology),model,
            input.cell_length_mm,input.wall_thickness_mm);
        const double lengths[]{input.length_m,input.span_m,height};
        for(size_t axis=0;axis<3;++axis) {
            widths[axis]=g::uniform(value.shape[axis],g::weak(lengths[axis]));
            edges[axis]=g::cumulative_widths({widths[axis].data(),widths[axis].size()});
            value.widths[axis]=array(widths[axis]);value.edges[axis]=array(edges[axis]);
            if(input.warm_start)initial[axis].assign(input.initial[axis].data,input.initial[axis].data+cells);
            value.initial[axis]=array(initial[axis]);
        }
        epsilon.assign(cells,geo.epsilon);epsilon_a.assign(cells,geo.epsilon_a);
        conductivity.assign(cells,tpmshx::geometry::solid_conductivity(model.solid_tortuosity,geo.epsilon,conductivity_s,1.));
        value.epsilon=array(epsilon);value.epsilon_a=array(epsilon_a);value.solid_conductivity=array(conductivity);
        auto& c=value.resolved;
        c.topology=input.topology;c.arrangement=input.arrangement;c.property_mode=input.property_mode;c.warm_start=input.warm_start;
        c.length=input.length_m;c.span=input.span_m;c.height=height;c.cell_length=input.cell_length_mm/1000.;
        c.area_density=geo.area_density;c.hydraulic_diameter=geo.hydraulic_diameter;
        value.wall_thickness_m=input.wall_thickness_mm/1000.;
        value.solid_conductivity_W_mK=conductivity_s;value.tolerance=tolerance;value.geometry_resolution=128;
        c.max_iterations=cross?8000:20000;c.chunk_iterations=cross?100:250;
        c.q_relative_tolerance=cross?1e-4:std::max(tolerance*10.,1e-4);c.alpha=cross?.7:.3;
        tpmshx::PropertyEvaluator evaluator;
        std::array<tpmshx::FluidProperties,2> properties;
        for(size_t side=0;side<2;++side) {
            const auto& source=input.sides[side];
            if(source.fluid>TPMSHX_SCO2)throw std::invalid_argument("Quick Design supports air, water and sco2 only");
            try {properties[side]=evaluator.evaluate(static_cast<tpmshx::Fluid>(source.fluid),source.temperature_K,source.pressure_Pa);}
            catch(const tpmshx::WaterStateError& failure) {
                throw p::c_api::StateError(TPMSHX_PREPARATION_WATER_STATE,
                    std::string("quick-design properties: ")+failure.what());
            }
        }
        const auto sections=p::quick_design_sections(g::weak(geo.epsilon_a),g::weak(input.span_m),
            g::weak(input.length_m),g::weak(height),cross);
        for(size_t side=0;side<2;++side) {
            const auto& source=input.sides[side];const auto& props=properties[side];
            const bool air=source.fluid==TPMSHX_AIR;
            const auto flow=p::quick_design_flow(g::weak(source.mass_flow_kg_s),sections[side*2],
                g::weak(air?0.:props.rho),air);
            auto& pressure=value.inlet_pressure[side];
            pressure=air?p::df_compressible_typed(input.topology,input.cell_length_mm,input.wall_thickness_mm,
                flow[0],g::weak(source.temperature_K),g::weak(source.pressure_Pa),g::weak(props.mu),sections[side*2+1],false)
                :p::df_incompressible_typed(input.topology,input.cell_length_mm,input.wall_thickness_mm,
                flow[1],g::weak(props.rho),g::weak(props.mu),sections[side*2+1]);
            c.sides[side]={source.fluid,source.temperature_K,source.pressure_Pa,source.mass_flow_kg_s,
                p::relative_pressure(g::weak(pressure.dP_Pa),g::weak(source.pressure_Pa)).value};
        }
        value.abi_version=TPMSHX_QUICK_DESIGN_STAGE_ABI_VERSION;value.struct_size=sizeof(value);value.owner=this;
        value.input=input;
        for(size_t axis=0;axis<3;++axis)value.input.initial[axis]=value.initial[axis];
    }
};
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_quick_design_v1(
    const tpmshx_quick_input_v1* input,tpmshx_quick_prepared_v1* result,char* error,size_t capacity) {
    if(!tpmshx::fields::c_api::error_buffer_valid(error,capacity))return TPMSHX_PREPARATION_INVALID;
    try {
        require_disjoint(error,capacity,input,input?1:0);require_disjoint(error,capacity,result,result?1:0);
        require_buffer(input,1);
        if(input->warm_start)for(const auto source:input->initial)require_disjoint(error,capacity,source.data,source.size);
    } catch(...) {return TPMSHX_PREPARATION_INVALID;}
    return p::c_api::boundary(error,capacity,[&] {
        version(input);version(result);require_disjoint(input,1,result,1);
        if(input->warm_start)for(const auto source:input->initial)require_disjoint(result,1,source.data,source.size);
        if(result->owner)throw std::invalid_argument("release the previous quick-design prepared owner before reuse");
        auto owner=std::make_unique<Owner>(*input);*result=owner->value;owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_quick_prepared_release_v1(tpmshx_quick_prepared_v1* result) {
    if(!result)return;
    delete static_cast<Owner*>(result->owner);*result={};
}
