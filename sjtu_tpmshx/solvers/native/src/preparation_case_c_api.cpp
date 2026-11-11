#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/preparation_case.hpp"
#include "preparation_c_boundary.hpp"
#include "preparation_properties.hpp"

#include <algorithm>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {
namespace p=tpmshx::preparation;
using p::c_api::require_buffer;
using p::c_api::require_disjoint;

tpmshx_preparation_text_v1 text(const std::string& value) {return {value.data(),value.size()};}
tpmshx_preparation_array_v1 array(const std::vector<double>& value) {return {value.data(),value.size()};}
void flag(std::uint32_t value) {if (value>1) throw std::invalid_argument("preparation case flags require 0 or 1");}
template<class T> void version(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case ABI version or struct size is invalid");
}

p::PortInput2D port(const tpmshx_preparation_port_2d_v1& source) {
    flag(source.uniform_inlet);
    return {source.direction,source.inlet_center_m,source.inlet_width_m,
            source.outlet_center_m,source.outlet_width_m,source.uniform_inlet!=0};
}
p::InletInput2D inlet(const tpmshx_preparation_inlet_2d_v1& source) {
    flag(source.have_mass_flow);
    return {static_cast<tpmshx::Fluid>(source.fluid),source.velocity_m_s,source.temperature_K,
            source.pressure_Pa,port(source.port),source.have_mass_flow?std::optional<double>(source.mass_flow_kg_s):std::nullopt};
}
p::CaseInput2D input(const tpmshx_preparation_case_input_2d_v1& source) {
    flag(source.port_wall_refine);flag(source.have_physical_depth);
    return {{source.length_m,source.height_m,source.requested_nx,source.requested_ny,source.port_wall_refine!=0},
        {static_cast<tpmshx::Topology>(source.topology),source.cell_length_mm,source.wall_thickness_mm,
         source.solid_conductivity_W_mK,source.delta_levelset},
        {inlet(source.sides[0]),inlet(source.sides[1])},
        source.have_physical_depth?std::optional<double>(source.physical_depth_m):std::nullopt,
        source.geometry_mode,source.df_mode};
}
p::PreparationOptions options(const tpmshx_preparation_case_options_v1* source) {
    if (!source) return {};
    flag(source->have_chi);flag(source->allow_extrapolation);
    return {source->have_chi?std::optional<double>(source->chi):std::nullopt,source->allow_extrapolation!=0};
}
tpmshx_preparation_inlet_2d_v1 inlet_view(const p::InletInput2D& source) {
    const auto& port=source.port;
    return {static_cast<std::uint32_t>(source.fluid),source.velocity_m_s,source.temperature_K,source.pressure_Pa,
        {port.direction,port.inlet_center_m,port.inlet_width_m,port.outlet_center_m,port.outlet_width_m,
         port.uniform_inlet?1u:0u},source.mass_flow_kg_s?1u:0u,source.mass_flow_kg_s.value_or(0.)};
}
tpmshx_preparation_range_sample_v1 sample(const p::PreparationRangeSample& value) {
    return {value.have_finite?1u:0u,value.minimum,value.maximum,value.minimum_index,value.maximum_index,
            value.low,value.high,value.size,value.nonfinite};
}
tpmshx_preparation_event_v1 event_view(const p::PreparationEvent& value) {
    return {static_cast<std::uint32_t>(value.kind),text(value.logger),text(value.message),value.floating_event};
}
struct Owner {
    p::PreparedCase2D value;
    std::vector<std::vector<tpmshx_preparation_text_v1>> sources;
    std::vector<tpmshx_preparation_range_v1> ranges;
    std::vector<tpmshx_preparation_text_v1> warnings;
    std::vector<tpmshx_preparation_event_v1> events;

    explicit Owner(p::PreparedCase2D prepared):value(std::move(prepared)) {
        const auto& evidence=value.evidence;
        sources.resize(evidence.ranges.size());ranges.reserve(evidence.ranges.size());
        for (std::size_t i=0;i<evidence.ranges.size();++i) {
            const auto& range=evidence.ranges[i];
            for (const auto& source:range.source) sources[i].push_back(text(source));
            ranges.push_back({sources[i].data(),sources[i].size(),text(range.side),text(range.stage),text(range.layout),
                text(range.label),text(range.quantity),text(range.unit),{range.bounds[0],range.bounds[1]},
                range.shape.data(),range.shape.size(),sample(range.sample),sample(range.last)});
        }
        for (const auto& warning:evidence.warnings) warnings.push_back(text(warning));
        for (const auto& event:evidence.events) events.push_back(event_view(event));
    }
};

void emit(void* context,const p::PreparationEvent& event) {
    const auto& callbacks=*static_cast<const tpmshx_preparation_case_callbacks_v1*>(context);
    const auto view=event_view(event);
    if (callbacks.event(callbacks.context,&view)) throw std::runtime_error("preparation event callback failed");
}

tpmshx_preparation_case_2d_v1 view(Owner& owner,const tpmshx_preparation_case_input_2d_v1& original) {
    const auto& value=owner.value;
    const auto& grid=value.grid;
    const auto& geometry=value.uniform_geometry.geometry;
    tpmshx_preparation_case_2d_v1 result{};
    result.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;result.struct_size=sizeof(result);
    result.input=original;
    result.options={TPMSHX_PREPARATION_CASE_ABI_VERSION,sizeof(result.options),value.options.chi_override?1u:0u,
                    value.options.allow_extrapolation?1u:0u,value.options.chi_override.value_or(0.)};
    result.nx=grid.nx;result.ny=grid.ny;
    result.dx=array(grid.dx);result.dy=array(grid.dy);result.x_edges=array(grid.x_edges);result.y_edges=array(grid.y_edges);
    result.x_breaks=array(grid.x_breaks);result.y_breaks=array(grid.y_breaks);
    result.epsilon=geometry.epsilon;result.epsilon_a=geometry.epsilon_a;result.epsilon_b=geometry.epsilon_b;
    result.area_density_per_m=geometry.area_density;result.hydraulic_diameter_m=geometry.hydraulic_diameter;
    result.uniform_solid_conductivity=value.uniform_geometry.solid_conductivity;
    result.hydraulic_radius_m=value.hydraulic_radius_m;result.cell_length_m=value.cell_length_m;
    result.wall_thickness_m=value.wall_thickness_m;result.split_a=value.split_a;
    result.cell_length=array(value.cell_length);result.wall_thickness=array(value.wall_thickness);
    result.total_porosity=array(value.total_porosity);result.solid_conductivity=array(value.solid_conductivity);
    result.hydraulic_radius=array(value.hydraulic_radius);
    for (std::size_t i=0;i<2;++i) {
        const auto& side=value.sides[i];const auto& props=side.properties;auto& target=result.sides[i];
        target.inlet=inlet_view(side.inlet);
        target.properties={props.rho,props.mu,props.k_f,props.cp,props.pr,props.re,props.nu,
            props.permeability_m2,props.forchheimer_per_m,props.pressure_gradient_Pa_m,
            props.surface_transfer_W_m2K,props.fluid_conductivity_W_mK,props.solid_conductivity_W_mK};
        target.seed_permeability_m2=side.seed_permeability_m2;target.seed_forchheimer_per_m=side.seed_forchheimer_per_m;
        target.cross_widths=array(side.cross_widths);target.stream_widths=array(side.stream_widths);
        target.row_permeability=array(side.row_permeability);target.row_forchheimer=array(side.row_forchheimer);
        target.permeability=array(side.permeability);target.forchheimer=array(side.forchheimer);
        target.inlet_geometry=array(side.inlet_geometry);target.outlet_geometry=array(side.outlet_geometry);
        target.inlet_profile=array(side.inlet_profile);target.outlet_profile=array(side.outlet_profile);
        target.outlet_u_fraction=array(side.outlet_u_fraction);
        std::copy(side.inlet_bounds.begin(),side.inlet_bounds.end(),target.inlet_bounds);
        std::copy(side.outlet_bounds.begin(),side.outlet_bounds.end(),target.outlet_bounds);
        const auto& drag=side.drag_evidence;
        target.drag_evidence={drag.base_permeability,drag.base_forchheimer,drag.applied_permeability,
            drag.applied_forchheimer,drag.scale_permeability,drag.scale_forchheimer,text(drag.campaign),text(drag.scope)};
    }
    for (std::size_t i=0;i<4;++i) {
        const auto& model=value.evidence.models[i];result.models[i]={text(model.name),text(model.version),text(model.side)};
    }
    result.ranges=owner.ranges.data();result.range_count=owner.ranges.size();
    result.warnings=owner.warnings.data();result.warning_count=owner.warnings.size();
    result.events=owner.events.data();result.event_count=owner.events.size();result.owner=&owner;
    return result;
}
}  // namespace

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v1(void) {
    return TPMSHX_PREPARATION_CASE_ABI_VERSION;
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_case_2d_v1(
    const tpmshx_preparation_case_input_2d_v1* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_case_2d_v1* result,
    char* error,size_t capacity) {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,capacity)) return TPMSHX_PREPARATION_INVALID;
    // Check aliases before the boundary can write an error through them.
    try {
        require_disjoint(error,capacity,source,source?1:0);
        require_disjoint(error,capacity,selected,selected?1:0);
        require_disjoint(error,capacity,callbacks,callbacks?1:0);
        require_disjoint(error,capacity,result,result?1:0);
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    return p::c_api::boundary(error,capacity,[&] {
        version(source);version(result);
        if (selected) version(selected);
        if (callbacks) version(callbacks);
        require_disjoint(source,1,result,1);
        require_disjoint(selected,selected?1:0,result,1);
        require_disjoint(callbacks,callbacks?1:0,result,1);
        if (result->owner) throw std::invalid_argument("release the previous prepared case before reusing its result");
        const p::PreparationCallbacks sink{callbacks && callbacks->event?emit:nullptr,
                                          const_cast<tpmshx_preparation_case_callbacks_v1*>(callbacks)};
        try {
            auto owner=std::make_unique<Owner>(p::prepare_case_2d(input(*source),options(selected),sink));
            const auto prepared=view(*owner,*source);*result=prepared;owner.release();
        } catch (const p::PropertyError& failure) {
            throw p::c_api::StateError(failure.status,failure.what());
        }
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_case_2d_release_v1(tpmshx_preparation_case_2d_v1* result) {
    if (!result) return;
    delete static_cast<Owner*>(result->owner);*result={};
}
