#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/preparation_case.hpp"
#include "preparation_c_boundary.hpp"
#include "preparation_properties.hpp"

#include <algorithm>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <utility>
#include <vector>

namespace {
namespace p=tpmshx::preparation;
using p::c_api::require_buffer;
using p::c_api::require_disjoint;

tpmshx_preparation_text_v1 text(const std::string& value) {return {value.data(),value.size()};}
tpmshx_preparation_text_v1 text(const char* value) {return {value,std::strlen(value)};}
tpmshx_preparation_array_v1 array(const std::vector<double>& value) {return {value.data(),value.size()};}
void flag(std::uint32_t value) {if (value>1) throw std::invalid_argument("preparation case flags require 0 or 1");}
template<class T> void version(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case ABI version or struct size is invalid");
}
template<class T> void version2(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2 || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case v2 ABI version or struct size is invalid");
}
p::ScalarKind kind(const tpmshx_preparation_scalar_kind_v2& value) {return {value.precision,value.strong,value.layout};}
tpmshx_preparation_scalar_kind_v2 kind(const p::ScalarKind& value) {return {value.precision,value.strong,value.layout};}
p::CaseScalarKinds kinds(const tpmshx_preparation_case_kinds_v2& value) {
    p::CaseScalarKinds output;
    output.cell_length=kind(value.cell_length);output.wall_thickness=kind(value.wall_thickness);
    output.solid_conductivity=kind(value.solid_conductivity);
    for (std::size_t i=0;i<2;++i) output.sides[i]={kind(value.sides[i].velocity),kind(value.sides[i].temperature),kind(value.sides[i].pressure)};
    return output;
}
tpmshx_preparation_case_kinds_v2 kinds(const p::CaseScalarKinds& value) {
    tpmshx_preparation_case_kinds_v2 output{};
    output.cell_length=kind(value.cell_length);output.wall_thickness=kind(value.wall_thickness);
    output.solid_conductivity=kind(value.solid_conductivity);
    for (std::size_t i=0;i<2;++i) output.sides[i]={kind(value.sides[i].velocity),kind(value.sides[i].temperature),kind(value.sides[i].pressure)};
    return output;
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
    p::CaseInput2D output{};
    output.grid={source.length_m,source.height_m,source.requested_nx,source.requested_ny,source.port_wall_refine!=0};
    output.geometry={static_cast<tpmshx::Topology>(source.topology),source.cell_length_mm,source.wall_thickness_mm,
                     source.solid_conductivity_W_mK,source.delta_levelset};
    output.sides={inlet(source.sides[0]),inlet(source.sides[1])};
    output.physical_depth_m=source.have_physical_depth?std::optional<double>(source.physical_depth_m):std::nullopt;
    output.geometry_mode=source.geometry_mode;output.df_mode=source.df_mode;
    return output;
}
p::CaseInput2D input(const tpmshx_preparation_case_input_2d_v2& source) {
    auto output=input(source.values);output.kinds=kinds(source.kinds);
    const auto& nu=source.sco2_nu;
    output.sco2_nu.mode=nu.mode;
    for (std::size_t i=0;i<2;++i) {flag(nu.have_alpha[i]);if(nu.have_alpha[i])output.sco2_nu.alpha[i]=nu.alpha[i];}
    const auto copied=[](tpmshx_preparation_text_v1 value) {
        require_buffer(value.data,value.size);return value.size?std::string(value.data,value.size):std::string{};
    };
    output.sco2_nu.parameter_version=copied(nu.parameter_version);output.sco2_nu.source=copied(nu.source);
    output.sco2_nu.applicability=copied(nu.applicability);
    return output;
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
    std::vector<std::uint32_t> range_bounds_list;
    std::vector<tpmshx_preparation_text_v1> warnings;
    std::vector<tpmshx_preparation_event_v1> events;
    std::vector<tpmshx_preparation_text_v1> notices;
    std::array<std::vector<tpmshx_preparation_text_field_v2>,2> calibration;

    explicit Owner(p::PreparedCase2D prepared):value(std::move(prepared)) {
        const auto& evidence=value.evidence;
        sources.resize(evidence.ranges.size());ranges.reserve(evidence.ranges.size());
        for (std::size_t i=0;i<evidence.ranges.size();++i) {
            const auto& range=evidence.ranges[i];
            range_bounds_list.push_back(range.bounds_list?1u:0u);
            for (const auto& source:range.source) sources[i].push_back(text(source));
            ranges.push_back({sources[i].data(),sources[i].size(),text(range.side),text(range.stage),text(range.layout),
                text(range.label),text(range.quantity),text(range.unit),{range.bounds[0],range.bounds[1]},
                range.shape.data(),range.shape.size(),sample(range.sample),sample(range.last)});
        }
        for (const auto& warning:evidence.warnings) warnings.push_back(text(warning));
        for (const auto& event:evidence.events) events.push_back(event_view(event));
        for (const auto& notice:evidence.notices) notices.push_back(text(notice));
        for (std::size_t i=0;i<2;++i)
            for (const auto& item:value.sides[i].drag_evidence.calibration)
                calibration[i].push_back({text(item[0]),text(item[1])});
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
tpmshx_preparation_case_2d_v2 view(Owner& owner,const tpmshx_preparation_case_input_2d_v2& original) {
    const auto& value=owner.value;const auto& evidence=value.evidence;
    tpmshx_preparation_case_2d_v2 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;output.struct_size=sizeof(output);
    output.values=view(owner,original.values);output.input_kinds=kinds(value.input.kinds);
    for (std::size_t i=0;i<5;++i) output.field_kinds[i]=kind(value.field_kinds[i]);
    for (std::size_t i=0;i<2;++i) {
        for (std::size_t j=0;j<13;++j) output.property_kinds[i][j]=kind(value.sides[i].property_kinds[j]);
        const auto& drag=value.sides[i].drag_evidence;auto& target=output.drag[i];
        target.have_selection=drag.selection?1u:0u;if(drag.selection)target.selection=*drag.selection;
        target.application_scope=text(drag.application_scope);target.fluid=text(drag.fluid);
        target.calibration=owner.calibration[i].data();target.calibration_count=owner.calibration[i].size();
    }
    const auto& nu=value.input.sco2_nu;auto& selected=output.sco2_nu;selected.mode=nu.mode;
    for (std::size_t i=0;i<2;++i) {selected.have_alpha[i]=nu.alpha[i]?1u:0u;selected.alpha[i]=nu.alpha[i].value_or(0.);}
    selected.parameter_version=text(nu.parameter_version);selected.source=text(nu.source);selected.applicability=text(nu.applicability);
    output.sco2_nu_model_version=text(evidence.sco2_nu_model_version);
    output.sco2_nu_interpretation=text(nu.mode?"Total C_eff times the CFD base, applied once; not measured local Nu":"");
    for (std::size_t i=0;i<2;++i) std::copy(evidence.sco2_nu_coefficients[i].begin(),evidence.sco2_nu_coefficients[i].end(),output.sco2_nu_coefficients[i]);
    auto& co2=output.co2;co2.active=evidence.co2_geometry?1u:0u;
    if (co2.active) {
        for (std::size_t i=0;i<2;++i) co2.sides[i]=value.input.sides[i].fluid==tpmshx::Fluid::co2?1u:0u;
        co2.version=text(evidence.co2_version);co2.application_version=text(evidence.co2_application_version);
        co2.pressure_model=text(evidence.models[3].version);co2.pressure_multiplier=evidence.co2_pressure_multiplier;
        co2.scale_K=evidence.co2_drag_factors.K;co2.scale_F=evidence.co2_drag_factors.cF;
        co2.nu_multiplier=co2.nu_floor_multiplier=evidence.co2_nu_multiplier;
        co2.correction_source=text("fixed user-specified factors; not fitted experimental evidence");
        co2.property_model=text("HEOS::CO2; single-phase; low-Mach momentum adapter");
        co2.common_geometry=text("single-side CFD geometry assigned symmetrically to both sides");
        std::copy(evidence.co2_re_range.begin(),evidence.co2_re_range.end(),co2.re_range);
        std::copy(evidence.co2_pr_range.begin(),evidence.co2_pr_range.end(),co2.pr_range);
    }
    output.notices=owner.notices.data();output.notice_count=owner.notices.size();
    output.range_bounds_list=owner.range_bounds_list.data();
    return output;
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
            auto owner=std::make_unique<Owner>(p::prepare_case_2d(input(*source),options(selected),sink,p::CaseScope::air_cfd_v1));
            const auto prepared=view(*owner,*source);*result=prepared;owner.release();
        } catch (const p::PreparationError& failure) {
            throw p::c_api::StateError(failure.status,failure.what());
        } catch (const p::PropertyError& failure) {
            throw p::c_api::StateError(failure.status,failure.what());
        }
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_case_2d_release_v1(tpmshx_preparation_case_2d_v1* result) {
    if (!result) return;
    delete static_cast<Owner*>(result->owner);*result={};
}

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v2(void) {
    return TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_case_2d_v2(
    const tpmshx_preparation_case_input_2d_v2* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_case_2d_v2* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,capacity)) return TPMSHX_PREPARATION_INVALID;
    try {
        require_disjoint(error,capacity,source,source?1:0);require_disjoint(error,capacity,result,result?1:0);
        require_disjoint(error,capacity,selected,selected?1:0);require_disjoint(error,capacity,callbacks,callbacks?1:0);
        require_disjoint(error,capacity,failure,failure?1:0);
        if (source) for (const auto value:{source->sco2_nu.parameter_version,source->sco2_nu.source,source->sco2_nu.applicability})
            require_disjoint(error,capacity,value.data,value.size);
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    return p::c_api::boundary(error,capacity,[&] {
        version2(source);version(&source->values);version2(result);version2(failure);
        if(selected)version(selected);if(callbacks)version(callbacks);
        require_disjoint(source,1,result,1);require_disjoint(source,1,failure,1);require_disjoint(result,1,failure,1);
        require_disjoint(selected,selected?1:0,result,1);require_disjoint(selected,selected?1:0,failure,1);
        require_disjoint(callbacks,callbacks?1:0,result,1);require_disjoint(callbacks,callbacks?1:0,failure,1);
        for (const auto value:{source->sco2_nu.parameter_version,source->sco2_nu.source,source->sco2_nu.applicability}) {
            require_disjoint(value.data,value.size,result,1);require_disjoint(value.data,value.size,failure,1);
        }
        *failure={};failure->abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;failure->struct_size=sizeof(*failure);failure->side=2;
        try {
            if (result->values.owner) throw std::invalid_argument("release the previous prepared case before reusing its result");
            const p::PreparationCallbacks sink{callbacks && callbacks->event?emit:nullptr,
                const_cast<tpmshx_preparation_case_callbacks_v1*>(callbacks)};
            auto owner=std::make_unique<Owner>(p::prepare_case_2d(input(*source),options(selected),sink));
            const auto prepared=view(*owner,*source);*result=prepared;owner.release();
        } catch (const p::PreparationError& problem) {
            failure->kind=problem.kind;failure->side=problem.side;
            failure->have_property=problem.have_property?1u:0u;failure->property=problem.property;
            failure->cause_count=static_cast<std::uint32_t>(std::min(problem.causes.size(),std::size_t{2}));
            for (std::size_t i=0;i<failure->cause_count;++i) {
                failure->causes[i].kind=problem.causes[i].kind;
                tpmshx::fields::c_api::message(failure->causes[i].message,sizeof(failure->causes[i].message),problem.causes[i].message.c_str());
            }
            throw p::c_api::StateError(problem.status,problem.what());
        } catch (const p::PropertyError& problem) {
            const auto& value=problem.failure;failure->kind=problem.status==3?3u:1u;failure->have_property=1;
            failure->property={value.reason,value.input,value.index,value.first_t_index,value.first_p_index,
                value.temperature,value.pressure,value.detail,value.fp};
            throw p::c_api::StateError(problem.status,problem.what());
        } catch (const std::invalid_argument&) {failure->kind=1;throw;}
        catch (...) {failure->kind=3;throw;}
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_case_2d_release_v2(tpmshx_preparation_case_2d_v2* result) {
    if (!result) return;
    delete static_cast<Owner*>(result->values.owner);*result={};
}
