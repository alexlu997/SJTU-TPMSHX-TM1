#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/preparation_case.hpp"
#include "preparation_c_boundary.hpp"
#include "preparation_properties.hpp"

#include <algorithm>
#include <cstring>
#include <cmath>
#include <exception>
#include <memory>
#include <stdexcept>
#include <utility>
#include <type_traits>
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
struct EvidenceViews {
    std::vector<std::vector<tpmshx_preparation_text_v1>> sources;
    std::vector<tpmshx_preparation_range_v1> ranges;
    std::vector<std::uint32_t> range_bounds_list;
    std::vector<tpmshx_preparation_text_v1> warnings;
    std::vector<tpmshx_preparation_event_v1> events;

    explicit EvidenceViews(const p::PreparationEvidence& evidence) {
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
    }
};
struct Owner {
    p::PreparedCase2D value;
    EvidenceViews evidence;
    std::vector<tpmshx_preparation_text_v1> notices;
    std::array<std::vector<tpmshx_preparation_text_field_v2>,2> calibration;
    explicit Owner(p::PreparedCase2D prepared):value(std::move(prepared)),evidence(value.evidence) {
        for (const auto& notice:value.evidence.notices) notices.push_back(text(notice));
        for (std::size_t i=0;i<2;++i)
            for (const auto& item:value.sides[i].drag_evidence.calibration)
                calibration[i].push_back({text(item[0]),text(item[1])});
    }
};
struct FlowOwner {
    p::InletFlow2D value;
    EvidenceViews evidence;
    explicit FlowOwner(p::InletFlow2D flow):value(std::move(flow)),evidence(value.evidence) {}
};
struct FlowCaseOwner {
    Owner prepared;
    FlowOwner flow;
    explicit FlowCaseOwner(p::PreparedFlowCase2D value)
        :prepared(std::move(value.prepared)),flow(std::move(value.flow)) {}
};

std::size_t callback_bytes(const tpmshx_preparation_case_callbacks_v1* callbacks) {
    require_buffer(callbacks,callbacks?1:0);
    if (!callbacks) return 0;
    if (callbacks->abi_version==9) {
        require_buffer(reinterpret_cast<const tpmshx_preparation_case_callbacks_v9*>(callbacks),1);
        return sizeof(tpmshx_preparation_case_callbacks_v9);
    }
    if (callbacks->abi_version==3 || callbacks->abi_version==4) require_buffer(reinterpret_cast<const tpmshx_preparation_case_callbacks_v3*>(callbacks),1);
    else if (callbacks->abi_version==2) require_buffer(reinterpret_cast<const tpmshx_preparation_case_callbacks_v2*>(callbacks),1);
    if (callbacks->abi_version==3 || callbacks->abi_version==4) return sizeof(tpmshx_preparation_case_callbacks_v3);
    return callbacks->abi_version==2?sizeof(tpmshx_preparation_case_callbacks_v2):sizeof(*callbacks);
}
void host_callback_version(const tpmshx_preparation_case_callbacks_v1* callbacks) {
    if (!callbacks) return;
    if (callbacks->abi_version==2 || callbacks->abi_version==3 || callbacks->abi_version==4) {
        if (callbacks->struct_size!=callback_bytes(callbacks))
            throw std::invalid_argument("preparation host callback struct size is invalid");
    } else version(callbacks);
}
struct FlowCallbackContext {
    const tpmshx_preparation_case_callbacks_v1* callbacks;
    const unsigned char* result;
    std::size_t result_bytes;
    tpmshx_preparation_case_failure_v2* failure;
    char* error;
    std::size_t error_bytes;
    bool storage_safe=true;

    template<class T> void borrowed(const T* pointer,std::size_t count) const {
        require_buffer(pointer,count);
        require_disjoint(pointer,count,result,result_bytes);
        require_disjoint(pointer,count,failure,failure?1:0);
        require_disjoint(pointer,count,error,error_bytes);
    }
    void borrowed(tpmshx_preparation_text_v1 value) const {borrowed(value.data,value.size);}
    void evidence(const tpmshx_preparation_flow_evidence_v3& value) const {
        borrowed(value.ranges,value.range_count);borrowed(value.range_bounds_list,value.range_count);
        borrowed(value.warnings,value.warning_count);borrowed(value.events,value.event_count);
        for (std::size_t i=0;i<value.range_count;++i) {
            const auto& range=value.ranges[i];borrowed(range.source,range.source_count);borrowed(range.shape,range.rank);
            for (std::size_t j=0;j<range.source_count;++j) borrowed(range.source[j]);
            for (const auto item:{range.side,range.stage,range.layout,range.label,range.quantity,range.unit}) borrowed(item);
        }
        for (std::size_t i=0;i<value.warning_count;++i) borrowed(value.warnings[i]);
        for (std::size_t i=0;i<value.event_count;++i) {
            borrowed(value.events[i].logger);borrowed(value.events[i].message);
        }
    }
    void borrowed(tpmshx_preparation_array_v1 value) const {borrowed(value.data,value.size);}
    void owned(const tpmshx_preparation_case_input_2d_v2& value) const {
        for (const auto item:{value.sco2_nu.parameter_version,value.sco2_nu.source,value.sco2_nu.applicability}) borrowed(item);
    }
    void owned(const tpmshx_preparation_case_2d_v2& value) const {
        const auto& base=value.values;
        for (const auto item:{base.dx,base.dy,base.x_edges,base.y_edges,base.x_breaks,base.y_breaks,
            base.cell_length,base.wall_thickness,base.total_porosity,base.solid_conductivity,base.hydraulic_radius}) borrowed(item);
        for (const auto& side:base.sides) {
            for (const auto item:{side.cross_widths,side.stream_widths,side.row_permeability,side.row_forchheimer,
                side.permeability,side.forchheimer,side.inlet_geometry,side.outlet_geometry,
                side.inlet_profile,side.outlet_profile,side.outlet_u_fraction}) borrowed(item);
            borrowed(side.drag_evidence.campaign);borrowed(side.drag_evidence.scope);
        }
        for (const auto& model:base.models) {borrowed(model.name);borrowed(model.version);borrowed(model.side);}
        evidence({base.ranges,base.range_count,value.range_bounds_list,
            base.warnings,base.warning_count,base.events,base.event_count});
        for (const auto item:{value.sco2_nu.parameter_version,value.sco2_nu.source,value.sco2_nu.applicability,
            value.sco2_nu_model_version,value.sco2_nu_interpretation,value.co2.version,value.co2.application_version,
            value.co2.pressure_model,value.co2.correction_source,value.co2.property_model,value.co2.common_geometry}) borrowed(item);
        for (const auto& drag:value.drag) {
            borrowed(drag.application_scope);borrowed(drag.fluid);borrowed(drag.calibration,drag.calibration_count);
            for (std::size_t i=0;i<drag.calibration_count;++i) {
                borrowed(drag.calibration[i].key);borrowed(drag.calibration[i].value);
            }
        }
        borrowed(value.notices,value.notice_count);
        for (std::size_t i=0;i<value.notice_count;++i) borrowed(value.notices[i]);
    }
    void owned(const tpmshx_preparation_flow_2d_v3& value) const {owned(value.input);evidence(value.evidence);}
    void owned(const tpmshx_preparation_flow_case_2d_v3& value) const {owned(value.prepared);owned(value.flow);}
    void owned(const tpmshx_preparation_continuous_flow_2d_v4& value) const {
        owned(value.flow);borrowed(value.controls.decision_mm);
    }
    void owned(const tpmshx_preparation_continuous_case_2d_v4& value) const {
        owned(value.prepared);owned(value.flow);borrowed(value.controls.decision_mm);
        for (const auto item:{value.area_density_per_m,value.hydraulic_diameter_m,
            value.fluid_conductivity[0],value.fluid_conductivity[1]}) borrowed(item);
        for (const auto& drag:value.drag) {borrowed(drag.transfer_policy);borrowed(drag.geometry_application);}
    }
    void owned(const tpmshx_preparation_zoned_input_2d_v5& value) const {
        owned(value.values);borrowed(value.regions,value.region_count);
        for (std::size_t i=0;i<value.region_count;++i) borrowed(value.regions[i].name);
    }
    void owned(const tpmshx_preparation_zoned_case_2d_v5& value) const {
        owned(value.prepared);borrowed(value.regions,value.region_count);borrowed(value.zone_id,value.cell_count);
        for (std::size_t i=0;i<value.region_count;++i) borrowed(value.regions[i].region.name);
        for (const auto item:{value.thermal_porosity,value.area_density_per_m,value.hydraulic_diameter_m,
            value.design_area_density_per_m,value.fluid_conductivity[0],value.fluid_conductivity[1],
            value.volumetric_transfer[0],value.volumetric_transfer[1]}) borrowed(item);
    }
    void owned(const tpmshx_preparation_sigmoid_input_2d_v6& value) const {
        owned(value.values);borrowed(value.controls.decision_mm);
        for (const auto item:{value.lut.cell_mm,value.lut.wall_mm,value.lut.porosity,value.lut.area_density_per_m}) borrowed(item);
    }
    void owned(const tpmshx_preparation_sigmoid_case_2d_v6& value) const {
        owned(value.values);borrowed(value.controls.decision_mm);
    }
    void owned(const tpmshx_preparation_zoned_flow_2d_v8& value) const {owned(value.flow);owned(value.input);}
    void owned(const tpmshx_preparation_sigmoid_flow_2d_v8& value) const {owned(value.flow);owned(value.input);}
    void owned(const tpmshx_preparation_zoned_flow_case_2d_v8& value) const {owned(value.prepared);owned(value.flow);}
    void owned(const tpmshx_preparation_sigmoid_flow_case_2d_v8& value) const {owned(value.prepared);owned(value.flow);}
    void owned(const tpmshx_preparation_zoned_flow_2d_v9& value) const {owned(value.values);}
    void owned(const tpmshx_preparation_sigmoid_flow_2d_v9& value) const {owned(value.values);}
    void owned(const tpmshx_preparation_zoned_flow_case_2d_v9& value) const {owned(value.values);borrowed(value.design_pore_porosity);}
    void owned(const tpmshx_preparation_sigmoid_flow_case_2d_v9& value) const {owned(value.values);borrowed(value.design_pore_porosity);}
    void lut(const tpmshx_preparation_sigmoid_lut_view_v6& value) const {
        for (const auto item:{value.cell_mm,value.wall_mm,value.porosity,value.area_density_per_m}) borrowed(item);
    }

};
void validate_host_input(void* context,std::uint32_t stage,std::uint32_t side) {
    const auto& state=*static_cast<const FlowCallbackContext*>(context);
    const auto& callbacks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v2*>(state.callbacks);
    if (callbacks.validate_host_input && callbacks.validate_host_input(callbacks.values.context,stage,side))
        throw std::runtime_error("preparation host input callback failed");
}
void validate_grid(void* context) {validate_host_input(context,3,2);}
void emit_flow(void* context,const p::PreparationEvent& event) {
    const auto& state=*static_cast<const FlowCallbackContext*>(context);
    const auto& callbacks=*state.callbacks;const auto view=event_view(event);
    if (callbacks.event(callbacks.context,&view)) throw std::runtime_error("preparation event callback failed");
}

std::string cache_text(tpmshx_preparation_text_v1 value) {
    require_buffer(value.data,value.size);
    return value.size?std::string(value.data,value.size):std::string{};
}
tpmshx_preparation_geometry_cache_v3 geometry_view(const tpmshx::geometry::Geometry& value) {
    return {value.epsilon,value.epsilon_a,value.epsilon_b,value.area_density,value.hydraulic_diameter};
}
tpmshx::geometry::Geometry cache_geometry(const tpmshx_preparation_geometry_cache_v3& value) {
    return {value.epsilon,value.epsilon_a,value.epsilon_b,value.area_density_per_m,value.hydraulic_diameter_m};
}
p::PreparationRangeSample cache_sample(const tpmshx_preparation_range_sample_v1& value) {
    flag(value.have_finite);
    if (value.nonfinite>value.size || value.low>value.size || value.high>value.size
        || (value.have_finite && (!std::isfinite(value.minimum) || !std::isfinite(value.maximum)
            || value.minimum>value.maximum || value.minimum_index>=value.size || value.maximum_index>=value.size)))
        throw std::invalid_argument("cached inlet range sample is invalid");
    return {value.have_finite!=0,value.minimum,value.maximum,value.minimum_index,value.maximum_index,
            value.low,value.high,value.size,value.nonfinite};
}
p::PreparationEvidence cache_evidence(const tpmshx_preparation_flow_evidence_v3& value,std::size_t max_rank=2) {
    require_buffer(value.ranges,value.range_count);require_buffer(value.range_bounds_list,value.range_count);
    require_buffer(value.warnings,value.warning_count);
    if (value.event_count) throw std::invalid_argument("cached inlet evidence cannot contain live events");
    p::PreparationEvidence output;
    for (std::size_t i=0;i<value.range_count;++i) {
        const auto& item=value.ranges[i];require_buffer(item.source,item.source_count);require_buffer(item.shape,item.rank);
        if (!item.source_count || item.rank>max_rank) throw std::invalid_argument("cached inlet range shape is invalid");
        p::PreparationRange range;
        for (std::size_t n=0;n<item.source_count;++n) range.source.push_back(cache_text(item.source[n]));
        range.side=cache_text(item.side);range.stage=cache_text(item.stage);range.layout=cache_text(item.layout);
        range.label=cache_text(item.label);range.quantity=cache_text(item.quantity);range.unit=cache_text(item.unit);
        range.bounds={item.bounds[0],item.bounds[1]};
        if (item.rank) range.shape.assign(item.shape,item.shape+item.rank);
        range.sample=cache_sample(item.sample);range.last=cache_sample(item.last);
        flag(value.range_bounds_list[i]);range.bounds_list=value.range_bounds_list[i]!=0;
        output.ranges.push_back(std::move(range));
    }
    for (std::size_t i=0;i<value.warning_count;++i) output.warnings.push_back(cache_text(value.warnings[i]));
    return output;
}
bool geometry_cache(void* context,bool publish,tpmshx::geometry::Geometry& values) {
    auto& state=*static_cast<FlowCallbackContext*>(context);
    const auto& callbacks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v3*>(state.callbacks);
    if (!callbacks.geometry_cache) return false;
    auto view=geometry_view(values);std::uint32_t hit=0;
    if (callbacks.geometry_cache(callbacks.values.values.context,publish?1u:0u,&view,&hit))
        throw std::runtime_error("preparation geometry cache callback failed");
    flag(hit);
    if (!publish && hit) values=cache_geometry(view);
    return hit!=0;
}
tpmshx_preparation_inlet_cache_v3 inlet_cache_view(const p::PreparationInletCache& values,const EvidenceViews& evidence) {
    const auto& props=values.properties;
    tpmshx_preparation_inlet_cache_v3 view{};view.geometry=geometry_view(values.geometry);
    view.properties={props.rho,props.mu,props.k_f,props.cp,props.pr,props.re,props.nu,
        props.permeability_m2,props.forchheimer_per_m,props.pressure_gradient_Pa_m,
        props.surface_transfer_W_m2K,props.fluid_conductivity_W_mK,props.solid_conductivity_W_mK};
    for (std::size_t i=0;i<13;++i) view.kinds[i]=kind(values.kinds[i]);
    view.evidence={evidence.ranges.data(),evidence.ranges.size(),evidence.range_bounds_list.data(),
        evidence.warnings.data(),evidence.warnings.size(),nullptr,0};
    return view;
}
void copy_inlet_cache(const tpmshx_preparation_inlet_cache_v3& view,p::PreparationInletCache& values,std::size_t max_rank) {
    values.geometry=cache_geometry(view.geometry);const auto& q=view.properties;
    values.properties={q.rho,q.mu,q.k_f,q.cp,q.pr,q.re,q.nu,q.permeability_m2,q.forchheimer_per_m,
        q.pressure_gradient_Pa_m,q.surface_transfer_W_m2K,q.fluid_conductivity_W_mK,q.solid_conductivity_W_mK};
    for (std::size_t i=0;i<13;++i) {
        const auto tag=view.kinds[i];
        if ((tag.precision!=16 && tag.precision!=32 && tag.precision!=64) || tag.strong>1 || tag.layout>2
            || (!tag.strong && (tag.precision!=64 || tag.layout)) || (tag.strong && !tag.layout))
            throw std::invalid_argument("cached inlet scalar tags are invalid");
        values.kinds[i]=kind(tag);
    }
    values.evidence=cache_evidence(view.evidence,max_rank);
}
bool inlet_cache(void* context,bool publish,std::uint32_t side,const p::InletInput2D& inlet,
                 p::ScalarKind velocity_kind,p::PreparationInletCache& values) {
    auto& state=*static_cast<FlowCallbackContext*>(context);
    const auto& callbacks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v3*>(state.callbacks);
    if (!callbacks.inlet_cache) return false;
    const auto inlet_input=inlet_view(inlet);
    EvidenceViews evidence(values.evidence);auto view=inlet_cache_view(values,evidence);
    std::uint32_t hit=0;
    state.storage_safe=false;
    const auto status=callbacks.inlet_cache(callbacks.values.values.context,publish?1u:0u,side,&inlet_input,kind(velocity_kind),&view,&hit);
    state.evidence(view.evidence);state.storage_safe=true;
    if (status) throw std::runtime_error("preparation inlet cache callback failed");
    flag(hit);
    if (!publish && hit) copy_inlet_cache(view,values,2);
    return hit!=0;
}

tpmshx_preparation_geometry_key_v9 geometry_key_view(const p::PreparationGeometryKey& value) {
    return {static_cast<std::uint32_t>(value.topology),value.cell_length_mm,value.wall_thickness_mm,
        kind(value.cell_kind),kind(value.wall_kind)};
}
tpmshx_preparation_inlet_key_v9 inlet_key_view(const p::PreparationInletKey& value) {
    tpmshx_preparation_inlet_key_v9 output{};
    output.geometry=geometry_key_view(value.geometry);output.fluid=static_cast<std::uint32_t>(value.fluid);
    output.velocity_m_s=value.velocity_m_s;output.temperature_K=value.temperature_K;output.pressure_Pa=value.pressure_Pa;
    output.kinds={kind(value.kinds.velocity),kind(value.kinds.temperature),kind(value.kinds.pressure)};
    output.have_sco2_nu=value.sco2_nu?1u:0u;output.co2_geometry=value.co2_geometry?1u:0u;
    if (value.sco2_nu) {
        const auto& nu=*value.sco2_nu;output.sco2_nu.mode=nu.mode;
        for (std::size_t i=0;i<2;++i) {
            output.sco2_nu.have_alpha[i]=nu.alpha[i]?1u:0u;output.sco2_nu.alpha[i]=nu.alpha[i].value_or(0.);
        }
        output.sco2_nu.parameter_version=text(nu.parameter_version);output.sco2_nu.source=text(nu.source);
        output.sco2_nu.applicability=text(nu.applicability);
    }
    return output;
}
bool geometry_cache_at(void* context,bool publish,const p::PreparationGeometryKey& key,tpmshx::geometry::Geometry& values) {
    auto& state=*static_cast<FlowCallbackContext*>(context);
    const auto& callbacks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v9*>(state.callbacks);
    const auto probe=geometry_key_view(key);auto view=geometry_view(values);std::uint32_t hit=0;
    if (callbacks.geometry_cache_at(callbacks.values.values.values.context,publish?1u:0u,&probe,&view,&hit))
        throw std::runtime_error("preparation typed geometry cache callback failed");
    flag(hit);if (!publish && hit) values=cache_geometry(view);return hit!=0;
}
bool inlet_cache_at(void* context,bool publish,const p::PreparationInletKey& key,p::PreparationInletCache& values) {
    auto& state=*static_cast<FlowCallbackContext*>(context);
    const auto& callbacks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v9*>(state.callbacks);
    const auto probe=inlet_key_view(key);EvidenceViews evidence(values.evidence);
    auto view=inlet_cache_view(values,evidence);std::uint32_t hit=0;
    state.storage_safe=false;
    const auto status=callbacks.inlet_cache_at(callbacks.values.values.values.context,publish?1u:0u,&probe,&view,&hit);
    state.evidence(view.evidence);state.storage_safe=true;
    if (status) throw std::runtime_error("preparation typed inlet cache callback failed");
    flag(hit);if (!publish && hit) copy_inlet_cache(view,values,3);return hit!=0;
}
bool sigmoid_lut_cache(void* context,bool publish,tpmshx::Topology topology,std::size_t resolution,p::SigmoidLUT2D& values) {
    auto& state=*static_cast<FlowCallbackContext*>(context);
    const auto& callbacks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v9*>(state.callbacks);
    tpmshx_preparation_sigmoid_lut_view_v6 view{array(values.cell_mm),array(values.wall_mm),
        array(values.porosity),array(values.area_density),values.porosity_fast,values.area_fast};
    std::uint32_t hit=0;state.storage_safe=false;
    const auto status=callbacks.sigmoid_lut_cache(callbacks.values.values.values.context,publish?1u:0u,
        static_cast<std::uint32_t>(topology),resolution,&view,&hit);
    state.lut(view);state.storage_safe=true;
    if (status) throw std::runtime_error("preparation sigmoid LUT cache callback failed");
    flag(hit);
    if (!publish && hit) {
        flag(view.porosity_fast);flag(view.area_fast);
        const auto copy=[](tpmshx_preparation_array_v1 item) {
            return item.size?std::vector<double>(item.data,item.data+item.size):std::vector<double>{};
        };
        values={copy(view.cell_mm),copy(view.wall_mm),copy(view.porosity),copy(view.area_density_per_m),
            view.porosity_fast,view.area_fast};
    }
    return hit!=0;
}

void observe_range(void* context,const p::PreparationRange& range,bool cached,std::optional<double> scalar) {
    const auto& state=*static_cast<const FlowCallbackContext*>(context);
    const auto& callbacks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v3*>(state.callbacks);
    if (!callbacks.observe_range) return;
    p::PreparationEvidence evidence;evidence.ranges.push_back(range);EvidenceViews views(evidence);
    if (callbacks.observe_range(callbacks.values.values.context,cached?1u:0u,&views.ranges.front(),
        range.bounds_list?1u:0u,scalar?1u:0u,scalar.value_or(0.)))
        throw std::runtime_error("preparation range observation callback failed");
}
void observe_notice(void* context,std::uint32_t kind,std::uint32_t side,double value,const std::string& message) {
    const auto& state=*static_cast<const FlowCallbackContext*>(context);
    const auto& callbacks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v3*>(state.callbacks);
    if (callbacks.observe_notice && callbacks.observe_notice(callbacks.values.values.context,kind,side,value,text(message)))
        throw std::runtime_error("preparation notice observation callback failed");
}

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
    result.ranges=owner.evidence.ranges.data();result.range_count=owner.evidence.ranges.size();
    result.warnings=owner.evidence.warnings.data();result.warning_count=owner.evidence.warnings.size();
    result.events=owner.evidence.events.data();result.event_count=owner.evidence.events.size();result.owner=&owner;
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
    output.range_bounds_list=owner.evidence.range_bounds_list.data();
    return output;
}
template<class T> void version3(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3 || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case v3 ABI version or struct size is invalid");
}
p::InletFlowRequest2D input(const tpmshx_preparation_flow_input_2d_v3& source) {
    p::InletFlowRequest2D output;output.input=input(source.values);
    output.physical_depth_kind=kind(source.physical_depth_kind);
    for (std::size_t i=0;i<2;++i) output.target_kinds[i]=kind(source.target_kinds[i]);
    flag(source.have_explicit_targets);
    if (source.have_explicit_targets) output.explicit_targets=std::array<double,2>{source.explicit_targets_kg_s[0],source.explicit_targets_kg_s[1]};
    return output;
}
tpmshx_preparation_case_input_2d_v2 resolved_input(const p::CaseInput2D& value,
    const tpmshx_preparation_case_input_2d_v2& source) {
    auto output=source;output.kinds=kinds(value.kinds);
    for (std::size_t i=0;i<2;++i) output.values.sides[i]=inlet_view(value.sides[i]);
    const auto& nu=value.sco2_nu;
    output.sco2_nu.parameter_version=text(nu.parameter_version);output.sco2_nu.source=text(nu.source);
    output.sco2_nu.applicability=text(nu.applicability);return output;
}
tpmshx_preparation_flow_2d_v3 view(FlowOwner& owner,const tpmshx_preparation_case_input_2d_v2& source) {
    tpmshx_preparation_flow_2d_v3 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;output.struct_size=sizeof(output);
    output.input=resolved_input(owner.value.input,source);output.have_capacities=owner.value.have_capacities?1u:0u;
    for (std::size_t i=0;i<2;++i) {
        const auto capacity=owner.value.capacities[i],speed=owner.value.speeds[i];
        output.capacities[i]={capacity.value,capacity.precision,capacity.strong};
        output.speeds[i]={speed.value,speed.precision,speed.strong};
    }
    const auto& evidence=owner.evidence;
    output.evidence={evidence.ranges.data(),evidence.ranges.size(),evidence.range_bounds_list.data(),
        evidence.warnings.data(),evidence.warnings.size(),evidence.events.data(),evidence.events.size()};
    output.owner=&owner;return output;
}

template<class T> void version4(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4 || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case v4 ABI version or struct size is invalid");
}
const tpmshx_preparation_flow_input_2d_v3& flow_source(const tpmshx_preparation_flow_input_2d_v3& value) {return value;}
const tpmshx_preparation_flow_input_2d_v3& flow_source(const tpmshx_preparation_continuous_input_2d_v4& value) {return value.values;}
p::InletFlowRequest2D input(const tpmshx_preparation_continuous_input_2d_v4& source) {
    auto output=input(source.values);const auto& controls=source.controls;flag(controls.symmetric_y);
    p::ContinuousControls2D value;
    value.nx=controls.n_ctrl_x;value.ny=controls.n_ctrl_y;value.order=controls.spline_order;
    value.symmetric_y=controls.symmetric_y!=0;
    std::copy_n(controls.L_bounds_mm,2,value.cell_bounds_mm.begin());
    std::copy_n(controls.t_bounds_mm,2,value.wall_bounds_mm.begin());
    if (controls.decision_mm.size) value.decision_mm.assign(
        controls.decision_mm.data,controls.decision_mm.data+controls.decision_mm.size);
    output.input.continuous=std::move(value);return output;
}
template<class T> void version5(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V5 || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case v5 ABI version or struct size is invalid");
}
template<class T> void version6(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V6 || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case v6 ABI version or struct size is invalid");
}
template<class T> void version8(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8 || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case v8 ABI version or struct size is invalid");
}
template<class T> void version9(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9 || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case v9 ABI version or struct size is invalid");
}
const tpmshx_preparation_case_input_2d_v2& case_source(const tpmshx_preparation_flow_input_2d_v3& value) {return value.values;}
const tpmshx_preparation_case_input_2d_v2& case_source(const tpmshx_preparation_continuous_input_2d_v4& value) {return value.values.values;}
const tpmshx_preparation_case_input_2d_v2& case_source(const tpmshx_preparation_zoned_input_2d_v5& value) {return value.values;}
const tpmshx_preparation_case_input_2d_v2& case_source(const tpmshx_preparation_sigmoid_input_2d_v6& value) {return value.values.values;}
const tpmshx_preparation_zoned_input_2d_v5& zone_source(const tpmshx_preparation_zoned_input_2d_v5& value) {return value;}
const tpmshx_preparation_zoned_input_2d_v5& zone_source(const tpmshx_preparation_sigmoid_input_2d_v6& value) {return value.values;}
const tpmshx_preparation_case_input_2d_v2& case_source(const tpmshx_preparation_zoned_flow_input_2d_v8& value) {return value.values.values;}
const tpmshx_preparation_case_input_2d_v2& case_source(const tpmshx_preparation_sigmoid_flow_input_2d_v8& value) {return value.values.values.values;}
const tpmshx_preparation_zoned_input_2d_v5& zone_source(const tpmshx_preparation_zoned_flow_input_2d_v8& value) {return value.values;}
const tpmshx_preparation_zoned_input_2d_v5& zone_source(const tpmshx_preparation_sigmoid_flow_input_2d_v8& value) {return value.values.values;}
const tpmshx_preparation_sigmoid_input_2d_v6& sigmoid_source(const tpmshx_preparation_sigmoid_input_2d_v6& value) {return value;}
const tpmshx_preparation_sigmoid_input_2d_v6& sigmoid_source(const tpmshx_preparation_sigmoid_flow_input_2d_v8& value) {return value.values;}
const tpmshx_preparation_case_input_2d_v2& case_source(const tpmshx_preparation_zoned_flow_input_2d_v9& value) {return case_source(value.values);}
const tpmshx_preparation_case_input_2d_v2& case_source(const tpmshx_preparation_sigmoid_flow_input_2d_v9& value) {return case_source(value.values);}
const tpmshx_preparation_zoned_input_2d_v5& zone_source(const tpmshx_preparation_zoned_flow_input_2d_v9& value) {return zone_source(value.values);}
const tpmshx_preparation_zoned_input_2d_v5& zone_source(const tpmshx_preparation_sigmoid_flow_input_2d_v9& value) {return zone_source(value.values);}
const tpmshx_preparation_sigmoid_input_2d_v6& sigmoid_source(const tpmshx_preparation_sigmoid_flow_input_2d_v9& value) {return value.values.values;}
p::ZonedInput2D input(const tpmshx_preparation_zoned_input_2d_v5& source) {
    p::ZonedInput2D output;output.input=input(source.values);output.kind=source.kind;output.axis=source.axis;
    for (std::size_t i=0;i<source.region_count;++i) {
        const auto& item=source.regions[i];p::ZoneRegion2D region;
        region.name=cache_text(item.name);region.cell_length_mm=item.cell_length_mm;region.wall_thickness_mm=item.wall_thickness_mm;
        region.cell_kind=kind(item.cell_kind);region.wall_kind=kind(item.wall_kind);
        for (std::size_t j=0;j<4;++j) region.bounds[j]={item.bounds[j].value,item.bounds[j].precision,item.bounds[j].strong};
        output.regions.push_back(std::move(region));
    }
    return output;
}
p::ZonedInput2D input(const tpmshx_preparation_sigmoid_input_2d_v6& source) {
    auto output=input(source.values);p::SigmoidInput2D sigmoid;
    const auto copy=[](tpmshx_preparation_array_v1 values) {
        return values.size?std::vector<double>(values.data,values.data+values.size):std::vector<double>{};
    };
    sigmoid.controls.decision_mm=copy(source.controls.decision_mm);
    const auto scalar=[](tpmshx_grid_scalar_v1 value) {return tpmshx::grid::Scalar{value.value,value.precision,value.strong};};
    sigmoid.controls.inlet_transition=scalar(source.controls.inlet_transition);
    sigmoid.controls.outlet_transition=scalar(source.controls.outlet_transition);
    sigmoid.lut.cell_mm=copy(source.lut.cell_mm);sigmoid.lut.wall_mm=copy(source.lut.wall_mm);
    sigmoid.lut.porosity=copy(source.lut.porosity);sigmoid.lut.area_density=copy(source.lut.area_density_per_m);
    sigmoid.lut.porosity_fast=source.lut.porosity_fast;sigmoid.lut.area_fast=source.lut.area_fast;
    output.sigmoid=std::move(sigmoid);return output;
}
template<class Source> p::ZonedFlowRequest2D zoned_flow_input(const Source& source) {
    p::ZonedFlowRequest2D output;output.input=input(source.values);
    output.physical_depth_kind=kind(source.physical_depth_kind);
    for (std::size_t i=0;i<2;++i) output.target_kinds[i]=kind(source.target_kinds[i]);
    flag(source.have_explicit_targets);
    if (source.have_explicit_targets)
        output.explicit_targets=std::array<double,2>{source.explicit_targets_kg_s[0],source.explicit_targets_kg_s[1]};
    return output;
}
p::ZonedFlowRequest2D input(const tpmshx_preparation_zoned_flow_input_2d_v8& source) {return zoned_flow_input(source);}
p::ZonedFlowRequest2D input(const tpmshx_preparation_sigmoid_flow_input_2d_v8& source) {return zoned_flow_input(source);}
p::SpatialModel2D spatial_model(const tpmshx_preparation_spatial_model_2d_v9& value) {
    flag(value.allow_geometry_extrapolation);flag(value.load_default_lut);
    return {kind(value.solid_conductivity_kind),value.allow_geometry_extrapolation!=0,value.load_default_lut!=0};
}
tpmshx_preparation_spatial_model_2d_v9 spatial_model(const p::SpatialModel2D& value) {
    return {kind(value.solid_conductivity_kind),value.allow_geometry_extrapolation?1u:0u,value.load_default_lut?1u:0u};
}
p::ZonedFlowRequest2D input(const tpmshx_preparation_zoned_flow_input_2d_v9& source) {
    auto output=input(source.values);output.input.spatial_model=spatial_model(source.model);return output;
}
p::ZonedFlowRequest2D input(const tpmshx_preparation_sigmoid_flow_input_2d_v9& source) {
    auto output=input(source.values);output.input.spatial_model=spatial_model(source.model);return output;
}
tpmshx_preparation_zone_region_v5 zone_region_view(const p::ZoneRegion2D& source) {
    tpmshx_preparation_zone_region_v5 output{};
    output.name=text(source.name);output.cell_length_mm=source.cell_length_mm;
    output.wall_thickness_mm=source.wall_thickness_mm;
    output.cell_kind=kind(source.cell_kind);output.wall_kind=kind(source.wall_kind);
    for (std::size_t i=0;i<4;++i) output.bounds[i]={source.bounds[i].value,source.bounds[i].precision,source.bounds[i].strong};
    return output;
}
tpmshx_preparation_sigmoid_controls_2d_v6 sigmoid_controls_view(const p::SigmoidControls2D& controls) {
    const auto scalar=[](tpmshx::grid::Scalar value) {return tpmshx_grid_scalar_v1{value.value,value.precision,value.strong};};
    return {array(controls.decision_mm),scalar(controls.inlet_transition),scalar(controls.outlet_transition)};
}
tpmshx_preparation_sigmoid_lut_view_v6 sigmoid_lut_view(const p::SigmoidLUT2D& lut) {
    return {array(lut.cell_mm),array(lut.wall_mm),array(lut.porosity),array(lut.area_density),lut.porosity_fast,lut.area_fast};
}
struct ZonedOwner {
    Owner prepared;
    p::PreparedZonedCase2D value;
    std::vector<tpmshx_preparation_zone_values_v5> regions;
    explicit ZonedOwner(p::PreparedZonedCase2D result):prepared(std::move(result.prepared)),value(std::move(result)) {
        regions.reserve(value.regions.size());
        for (const auto& item:value.regions) {
            tpmshx_preparation_zone_values_v5 view{};view.region=zone_region_view(item.region);
            view.geometry=geometry_view(item.geometry.geometry);view.solid_conductivity=item.geometry.solid_conductivity;
            for (std::size_t i=0;i<2;++i) {
                const auto& q=item.properties[i];view.property_geometry[i]=geometry_view(item.property_geometry[i]);
                view.properties[i]={q.rho,q.mu,q.k_f,q.cp,q.pr,q.re,q.nu,q.permeability_m2,q.forchheimer_per_m,
                    q.pressure_gradient_Pa_m,q.surface_transfer_W_m2K,q.fluid_conductivity_W_mK,q.solid_conductivity_W_mK};
                for (std::size_t j=0;j<13;++j) view.property_kinds[i][j]=kind(item.property_kinds[i][j]);
            }
            regions.push_back(view);
        }
    }
};
tpmshx_preparation_zoned_case_2d_v5 zoned_view(ZonedOwner& owner,const tpmshx_preparation_case_input_2d_v2& source) {
    tpmshx_preparation_zoned_case_2d_v5 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V5;output.struct_size=sizeof(output);
    output.prepared=view(owner.prepared,source);output.prepared.values.owner=nullptr;
    const auto& values=owner.value;const auto& prepared=owner.prepared.value;
    output.kind=values.kind;output.axis=values.axis;output.regions=owner.regions.data();output.region_count=owner.regions.size();
    output.zone_id=values.zone_id.data();output.cell_count=values.zone_id.size();
    output.thermal_porosity=array(values.thermal_porosity);output.area_density_per_m=array(prepared.area_density);
    output.hydraulic_diameter_m=array(prepared.hydraulic_diameter);output.design_area_density_per_m=array(values.design_area_density);
    for (std::size_t i=0;i<2;++i) {
        output.fluid_conductivity[i]=array(prepared.fluid_conductivity[i]);
        output.volumetric_transfer[i]=array(values.volumetric_transfer[i]);
    }
    output.owner=&owner;return output;
}
tpmshx_preparation_sigmoid_case_2d_v6 sigmoid_view(ZonedOwner& owner,const tpmshx_preparation_case_input_2d_v2& source) {
    tpmshx_preparation_sigmoid_case_2d_v6 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V6;output.struct_size=sizeof(output);
    output.values=zoned_view(owner,source);output.values.owner=nullptr;
    output.controls=sigmoid_controls_view(*owner.value.sigmoid);output.owner=&owner;return output;
}
struct ZonedFlowOwner {
    FlowOwner flow;
    p::ZonedInput2D input;
    std::vector<tpmshx_preparation_zone_region_v5> regions;
    explicit ZonedFlowOwner(p::ZonedInletFlow2D result):flow(std::move(result.flow)),input(std::move(result.input)) {
        regions.reserve(input.regions.size());
        for (const auto& region:input.regions) regions.push_back(zone_region_view(region));
    }
};
struct ZonedFlowCaseOwner {
    ZonedOwner prepared;
    ZonedFlowOwner flow;
    explicit ZonedFlowCaseOwner(p::PreparedZonedFlowCase2D result)
        :prepared(std::move(result.prepared)),flow(std::move(result.flow)) {}
};
tpmshx_preparation_zoned_flow_2d_v8 zoned_flow_view(ZonedFlowOwner& owner,const tpmshx_preparation_zoned_input_2d_v5& source) {
    tpmshx_preparation_zoned_flow_2d_v8 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
    output.flow=view(owner.flow,source.values);output.flow.owner=nullptr;
    output.input=source;output.input.values=output.flow.input;
    output.input.kind=owner.input.kind;output.input.axis=owner.input.axis;
    output.input.regions=owner.regions.data();output.input.region_count=owner.regions.size();
    output.owner=&owner;return output;
}
tpmshx_preparation_sigmoid_flow_2d_v8 sigmoid_flow_view(ZonedFlowOwner& owner,const tpmshx_preparation_sigmoid_input_2d_v6& source) {
    tpmshx_preparation_sigmoid_flow_2d_v8 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
    const auto zones=zoned_flow_view(owner,source.values);output.flow=zones.flow;
    output.input=source;output.input.values=zones.input;
    output.input.controls=sigmoid_controls_view(owner.input.sigmoid->controls);
    output.input.lut=sigmoid_lut_view(owner.input.sigmoid->lut);
    output.owner=&owner;return output;
}
tpmshx_preparation_zoned_flow_2d_v9 zoned_flow_view(ZonedFlowOwner& owner,const tpmshx_preparation_zoned_flow_input_2d_v9& source) {
    tpmshx_preparation_zoned_flow_2d_v9 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    output.values=zoned_flow_view(owner,source.values.values);output.values.owner=nullptr;
    output.model=spatial_model(*owner.input.spatial_model);output.owner=&owner;return output;
}
tpmshx_preparation_zoned_flow_case_2d_v9 zoned_flow_view(ZonedFlowCaseOwner& owner,const tpmshx_preparation_zoned_flow_input_2d_v9& source) {
    tpmshx_preparation_zoned_flow_case_2d_v9 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    auto& nested=output.values;nested.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;nested.struct_size=sizeof(nested);
    const auto resolved=resolved_input(owner.prepared.prepared.value.input,case_source(source));
    nested.prepared=zoned_view(owner.prepared,resolved);nested.prepared.owner=nullptr;
    nested.flow=zoned_flow_view(owner.flow,source.values.values);nested.flow.owner=nullptr;
    output.design_pore_porosity=array(owner.prepared.value.design_pore_porosity);
    output.model=spatial_model(*owner.flow.input.spatial_model);output.owner=&owner;return output;
}
tpmshx_preparation_sigmoid_flow_2d_v9 sigmoid_flow_view(ZonedFlowOwner& owner,const tpmshx_preparation_sigmoid_flow_input_2d_v9& source) {
    tpmshx_preparation_sigmoid_flow_2d_v9 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    output.values=sigmoid_flow_view(owner,source.values.values);output.values.owner=nullptr;
    output.model=spatial_model(*owner.input.spatial_model);output.owner=&owner;return output;
}
tpmshx_preparation_sigmoid_flow_case_2d_v9 sigmoid_flow_view(ZonedFlowCaseOwner& owner,const tpmshx_preparation_sigmoid_flow_input_2d_v9& source) {
    tpmshx_preparation_sigmoid_flow_case_2d_v9 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;output.struct_size=sizeof(output);
    auto& nested=output.values;nested.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;nested.struct_size=sizeof(nested);
    const auto resolved=resolved_input(owner.prepared.prepared.value.input,case_source(source));
    nested.prepared=sigmoid_view(owner.prepared,resolved);nested.prepared.owner=nullptr;
    nested.flow=sigmoid_flow_view(owner.flow,source.values.values);nested.flow.owner=nullptr;
    output.design_pore_porosity=array(owner.prepared.value.design_pore_porosity);
    output.model=spatial_model(*owner.flow.input.spatial_model);output.owner=&owner;return output;
}
tpmshx_preparation_continuous_controls_2d_v4 controls_view(const p::CaseInput2D& input) {
    const auto& controls=*input.continuous;
    return {controls.nx,controls.ny,controls.order,controls.symmetric_y?1u:0u,
        {controls.cell_bounds_mm[0],controls.cell_bounds_mm[1]},
        {controls.wall_bounds_mm[0],controls.wall_bounds_mm[1]},array(controls.decision_mm)};
}
tpmshx_preparation_grid_kinds_2d_v7 weak_grid() {
    tpmshx_preparation_grid_kinds_2d_v7 output{};
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V7;output.struct_size=sizeof(output);
    for (auto& value:output.lengths) value.precision=64;
    for (auto& side:output.ports) for (auto& value:side) value.precision=64;
    return output;
}
void grid_kinds(p::CaseInput2D& input,const tpmshx_preparation_grid_kinds_2d_v7& source) {
    const auto scalar=[](const tpmshx_preparation_scalar_kind_v2& value) {
        if (value.layout!=(value.strong?1u:0u))
            throw std::invalid_argument("preparation grid tags require scalar layout");
        tpmshx::grid::checked({0.,value.precision,value.strong});return kind(value);
    };
    for (std::size_t i=0;i<2;++i) {
        input.grid.kinds[i]=scalar(source.lengths[i]);
        for (std::size_t j=0;j<4;++j) input.sides[i].port.kinds[j]=scalar(source.ports[i][j]);
    }
}
template<class Source,class Result,class Function> int flow_boundary(
    const Source* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,Result* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity,Function function) {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,capacity)) return TPMSHX_PREPARATION_INVALID;
    // Check inputs and an existing result before error or failure writes.
    FlowCallbackContext context{callbacks,reinterpret_cast<const unsigned char*>(result),sizeof(Result),failure,error,capacity};
    const auto* callback_data=reinterpret_cast<const unsigned char*>(callbacks);
    std::size_t callback_count=0;
    try {
        require_buffer(result,result?1:0);
        if (result && result->owner) context.owned(*result);
        require_buffer(grid,1);
        callback_count=callback_bytes(callbacks);require_buffer(source,source?1:0);
        require_disjoint(grid,1,error,capacity);require_disjoint(grid,1,source,source?1:0);
        require_disjoint(grid,1,result,result?1:0);require_disjoint(grid,1,failure,failure?1:0);
        require_disjoint(grid,1,selected,selected?1:0);require_disjoint(grid,1,callback_data,callback_count);
        require_disjoint(error,capacity,source,source?1:0);require_disjoint(error,capacity,result,result?1:0);
        require_disjoint(error,capacity,selected,selected?1:0);require_disjoint(error,capacity,callback_data,callback_count);
        require_disjoint(error,capacity,failure,failure?1:0);
        if constexpr (std::is_same_v<Source,tpmshx_preparation_continuous_input_2d_v4>) {
            if (source) {
                const auto values=source->controls.decision_mm;
                require_disjoint(grid,1,values.data,values.size);
                require_disjoint(error,capacity,values.data,values.size);require_buffer(values.data,values.size);
                require_disjoint(values.data,values.size,result,result?1:0);
                require_disjoint(values.data,values.size,failure,failure?1:0);
            }
        }
        if constexpr (std::is_same_v<Source,tpmshx_preparation_sigmoid_input_2d_v6>
            || std::is_same_v<Source,tpmshx_preparation_sigmoid_flow_input_2d_v8>
            || std::is_same_v<Source,tpmshx_preparation_sigmoid_flow_input_2d_v9>) {
            if (source) for (const auto values:{sigmoid_source(*source).controls.decision_mm,sigmoid_source(*source).lut.cell_mm,
                    sigmoid_source(*source).lut.wall_mm,sigmoid_source(*source).lut.porosity,sigmoid_source(*source).lut.area_density_per_m}) {
                require_disjoint(grid,1,values.data,values.size);
                require_disjoint(error,capacity,values.data,values.size);require_buffer(values.data,values.size);
                require_disjoint(values.data,values.size,result,result?1:0);
                require_disjoint(values.data,values.size,failure,failure?1:0);
            }
        }
        if constexpr (std::is_same_v<Source,tpmshx_preparation_zoned_input_2d_v5>
            || std::is_same_v<Source,tpmshx_preparation_sigmoid_input_2d_v6>
            || std::is_same_v<Source,tpmshx_preparation_zoned_flow_input_2d_v8>
            || std::is_same_v<Source,tpmshx_preparation_sigmoid_flow_input_2d_v8>
            || std::is_same_v<Source,tpmshx_preparation_zoned_flow_input_2d_v9>
            || std::is_same_v<Source,tpmshx_preparation_sigmoid_flow_input_2d_v9>) {
            if (source) {
                const auto& zones=zone_source(*source);
                require_disjoint(grid,1,zones.regions,zones.region_count);
                require_disjoint(error,capacity,zones.regions,zones.region_count);
                require_buffer(zones.regions,zones.region_count);
                require_disjoint(zones.regions,zones.region_count,result,result?1:0);
                require_disjoint(zones.regions,zones.region_count,failure,failure?1:0);
                for (std::size_t i=0;i<zones.region_count;++i) {
                    const auto name=zones.regions[i].name;
                    require_disjoint(grid,1,name.data,name.size);
                    require_disjoint(error,capacity,name.data,name.size);require_buffer(name.data,name.size);
                    require_disjoint(name.data,name.size,result,result?1:0);
                    require_disjoint(name.data,name.size,failure,failure?1:0);
                }
            }
        }
        if (source) for (const auto value:{case_source(*source).sco2_nu.parameter_version,
            case_source(*source).sco2_nu.source,case_source(*source).sco2_nu.applicability}) {
            require_disjoint(grid,1,value.data,value.size);
            require_disjoint(error,capacity,value.data,value.size);require_buffer(value.data,value.size);
            require_disjoint(value.data,value.size,result,result?1:0);
            require_disjoint(value.data,value.size,failure,failure?1:0);
        }
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    tpmshx_preparation_case_failure_v2 staged_failure{};
    bool failure_ready=false;std::exception_ptr saved_exception;
    try {
        if (grid->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V7 || grid->struct_size!=sizeof(*grid))
            throw std::invalid_argument("preparation grid v7 ABI version or struct size is invalid");
        if constexpr (std::is_same_v<Source,tpmshx_preparation_zoned_flow_input_2d_v9>
            || std::is_same_v<Source,tpmshx_preparation_sigmoid_flow_input_2d_v9>) {
            version9(source);version9(result);version8(&source->values);version5(&zone_source(*source));
            if constexpr (std::is_same_v<Source,tpmshx_preparation_sigmoid_flow_input_2d_v9>) version6(&source->values.values);
            if (callbacks) {
                if (callbacks->abi_version==9) {
                    if (callbacks->struct_size!=sizeof(tpmshx_preparation_case_callbacks_v9))
                        throw std::invalid_argument("preparation host callback struct size is invalid");
                    const auto& hooks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v9*>(callbacks);
                    if (hooks.values.geometry_cache || hooks.values.inlet_cache)
                        throw std::invalid_argument("preparation v9 callbacks require typed cache hooks");
                } else version(callbacks);
            }
        } else if constexpr (std::is_same_v<Source,tpmshx_preparation_zoned_flow_input_2d_v8>
            || std::is_same_v<Source,tpmshx_preparation_sigmoid_flow_input_2d_v8>) {
            version8(source);version8(result);version5(&zone_source(*source));
            if constexpr (std::is_same_v<Source,tpmshx_preparation_sigmoid_flow_input_2d_v8>) version6(&source->values);
            if(callbacks)version(callbacks);
        } else if constexpr (std::is_same_v<Source,tpmshx_preparation_zoned_input_2d_v5>
            || std::is_same_v<Source,tpmshx_preparation_sigmoid_input_2d_v6>) {
            if constexpr (std::is_same_v<Source,tpmshx_preparation_sigmoid_input_2d_v6>) {
                version6(source);version6(result);version5(&source->values);
            } else {version5(source);version5(result);}
            if(callbacks)version(callbacks);
        } else {
            if constexpr (std::is_same_v<Source,tpmshx_preparation_continuous_input_2d_v4>) {version4(source);version4(result);}
            else {version3(source);version3(result);}
            version3(&flow_source(*source));host_callback_version(callbacks);
        }
        const auto& base=case_source(*source);version2(&base);version(&base.values);
        version2(failure);
        if(selected)version(selected);
        require_disjoint(source,1,result,1);require_disjoint(source,1,failure,1);require_disjoint(result,1,failure,1);
        require_disjoint(selected,selected?1:0,result,1);require_disjoint(selected,selected?1:0,failure,1);
        require_disjoint(callback_data,callback_count,result,1);require_disjoint(callback_data,callback_count,failure,1);
        staged_failure.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2;
        staged_failure.struct_size=sizeof(staged_failure);staged_failure.side=2;failure_ready=true;
        try {
            if (result->owner) throw std::invalid_argument("release the previous flow result before reusing its result");
            p::PreparationCallbacks sink{callbacks && callbacks->event?emit_flow:nullptr,&context,
                callbacks && callbacks->abi_version>=2?validate_host_input:nullptr,
                callbacks && callbacks->abi_version>=3?geometry_cache:nullptr,
                callbacks && callbacks->abi_version>=3?inlet_cache:nullptr,
                callbacks && callbacks->abi_version>=3?observe_range:nullptr,
                callbacks && callbacks->abi_version>=3?observe_notice:nullptr,
                callbacks && (callbacks->abi_version==4 || callbacks->abi_version==9)?validate_grid:nullptr};
            if (callbacks && callbacks->abi_version==9) {
                const auto& hooks=*reinterpret_cast<const tpmshx_preparation_case_callbacks_v9*>(callbacks);
                sink.geometry_cache=nullptr;sink.inlet_cache=nullptr;
                sink.geometry_cache_at=hooks.geometry_cache_at?geometry_cache_at:nullptr;
                sink.inlet_cache_at=hooks.inlet_cache_at?inlet_cache_at:nullptr;
                sink.sigmoid_lut_cache=hooks.sigmoid_lut_cache?sigmoid_lut_cache:nullptr;
            }
            auto request=input(*source);
            if constexpr (std::is_same_v<decltype(request),p::ZonedFlowRequest2D>) grid_kinds(request.input.input,*grid);
            else grid_kinds(request.input,*grid);
            function(request,options(selected),sink);
        } catch (const p::PreparationError& problem) {
            staged_failure.kind=problem.kind;staged_failure.side=problem.side;
            staged_failure.have_property=problem.have_property?1u:0u;staged_failure.property=problem.property;
            staged_failure.cause_count=static_cast<std::uint32_t>(std::min(problem.causes.size(),std::size_t{2}));
            for (std::size_t i=0;i<staged_failure.cause_count;++i) {
                staged_failure.causes[i].kind=problem.causes[i].kind;
                tpmshx::fields::c_api::message(staged_failure.causes[i].message,sizeof(staged_failure.causes[i].message),problem.causes[i].message.c_str());
            }
            throw p::c_api::StateError(problem.status,problem.what());
        } catch (const p::PropertyError& problem) {
            const auto& value=problem.failure;staged_failure.kind=problem.status==3?3u:1u;staged_failure.have_property=1;
            staged_failure.property={value.reason,value.input,value.index,value.first_t_index,value.first_p_index,
                value.temperature,value.pressure,value.detail,value.fp};
            throw p::c_api::StateError(problem.status,problem.what());
        } catch (const std::invalid_argument&) {staged_failure.kind=1;throw;}
        catch (...) {staged_failure.kind=3;throw;}
    } catch (...) {saved_exception=std::current_exception();}
    if (!context.storage_safe) return TPMSHX_PREPARATION_INVALID;
    return p::c_api::boundary(error,capacity,[&] {
        if (failure_ready) *failure=staged_failure;
        if (saved_exception) std::rethrow_exception(saved_exception);
    });
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

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v3(void) {
    return TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_inlet_mass_capacities_2d_v7(
    const tpmshx_preparation_flow_input_2d_v3* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_flow_2d_v3* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        if (request.explicit_targets) throw std::invalid_argument("capacity query does not accept explicit targets");
        auto owner=std::make_unique<FlowOwner>(p::prepare_inlet_mass_capacities_2d(
            request.input,request.physical_depth_kind,options,sink));
        const auto prepared=view(*owner,source->values);*result=prepared;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_resolve_inlet_flow_2d_v7(
    const tpmshx_preparation_flow_input_2d_v3* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_flow_2d_v3* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowOwner>(p::resolve_inlet_flow_2d(request,options,sink));
        const auto prepared=view(*owner,source->values);*result=prepared;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_flow_case_2d_v7(
    const tpmshx_preparation_flow_input_2d_v3* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_flow_case_2d_v3* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowCaseOwner>(p::prepare_flow_case_2d(request,options,sink));
        tpmshx_preparation_flow_case_2d_v3 prepared{};
        prepared.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V3;prepared.struct_size=sizeof(prepared);
        const auto resolved=resolved_input(owner->prepared.value.input,source->values);
        prepared.prepared=view(owner->prepared,resolved);prepared.prepared.values.owner=nullptr;
        prepared.flow=view(owner->flow,source->values);prepared.flow.owner=nullptr;
        prepared.owner=owner.get();*result=prepared;owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_flow_2d_release_v3(tpmshx_preparation_flow_2d_v3* result) {
    if (!result) return;
    delete static_cast<FlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_flow_case_2d_release_v3(tpmshx_preparation_flow_case_2d_v3* result) {
    if (!result) return;
    delete static_cast<FlowCaseOwner*>(result->owner);*result={};
}

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v4(void) {
    return TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_continuous_inlet_mass_capacities_2d_v7(
    const tpmshx_preparation_continuous_input_2d_v4* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_continuous_flow_2d_v4* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        if (request.explicit_targets) throw std::invalid_argument("capacity query does not accept explicit targets");
        auto owner=std::make_unique<FlowOwner>(p::prepare_inlet_mass_capacities_2d(
            request.input,request.physical_depth_kind,options,sink));
        tpmshx_preparation_continuous_flow_2d_v4 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;output.struct_size=sizeof(output);
        output.flow=view(*owner,source->values.values);output.flow.owner=nullptr;
        output.controls=controls_view(owner->value.input);output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_resolve_continuous_inlet_flow_2d_v7(
    const tpmshx_preparation_continuous_input_2d_v4* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_continuous_flow_2d_v4* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowOwner>(p::resolve_inlet_flow_2d(request,options,sink));
        tpmshx_preparation_continuous_flow_2d_v4 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;output.struct_size=sizeof(output);
        output.flow=view(*owner,source->values.values);output.flow.owner=nullptr;
        output.controls=controls_view(owner->value.input);output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_continuous_flow_case_2d_v7(
    const tpmshx_preparation_continuous_input_2d_v4* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_continuous_case_2d_v4* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowCaseOwner>(p::prepare_flow_case_2d(request,options,sink));
        tpmshx_preparation_continuous_case_2d_v4 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4;output.struct_size=sizeof(output);
        const auto& prepared=owner->prepared.value;
        output.prepared=view(owner->prepared,resolved_input(prepared.input,source->values.values));
        output.prepared.values.owner=nullptr;output.flow=view(owner->flow,source->values.values);output.flow.owner=nullptr;
        output.controls=controls_view(prepared.input);output.area_density_per_m=array(prepared.area_density);
        output.hydraulic_diameter_m=array(prepared.hydraulic_diameter);
        for (std::size_t i=0;i<2;++i) {
            output.fluid_conductivity[i]=array(prepared.fluid_conductivity[i]);
            const auto& evidence=prepared.sides[i].drag_evidence;auto& drag=output.drag[i];
            drag.transfer_policy=text(evidence.transfer_policy);drag.geometry_application=text(evidence.geometry_application);
            drag.have_reference_geometry=evidence.reference_geometry_mm?1u:0u;
            if (evidence.reference_geometry_mm) std::copy_n(evidence.reference_geometry_mm->begin(),2,drag.reference_geometry_mm);
        }
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_continuous_flow_2d_release_v4(
    tpmshx_preparation_continuous_flow_2d_v4* result) {
    if (!result) return;
    delete static_cast<FlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_continuous_case_2d_release_v4(
    tpmshx_preparation_continuous_case_2d_v4* result) {
    if (!result) return;
    delete static_cast<FlowCaseOwner*>(result->owner);*result={};
}

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v5(void) {
    return TPMSHX_PREPARATION_CASE_ABI_VERSION_V5;
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_zoned_case_2d_v7(
    const tpmshx_preparation_zoned_input_2d_v5* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_zoned_case_2d_v5* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedOwner>(p::prepare_zoned_case_2d(request,options,sink));
        *result=zoned_view(*owner,source->values);owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_zoned_case_2d_release_v5(tpmshx_preparation_zoned_case_2d_v5* result) {
    if (!result) return;
    delete static_cast<ZonedOwner*>(result->owner);*result={};
}

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v6(void) {
    return TPMSHX_PREPARATION_CASE_ABI_VERSION_V6;
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_lut_create_v6(
    uint32_t topology,size_t cell_nodes,size_t wall_nodes,size_t resolution,
    tpmshx_preparation_sigmoid_lut_v6* result,char* error,size_t capacity) {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,capacity)) return TPMSHX_PREPARATION_INVALID;
    try {require_disjoint(error,capacity,result,result?1:0);} catch (...) {return TPMSHX_PREPARATION_INVALID;}
    return p::c_api::boundary(error,capacity,[&] {
        version6(result);
        if (result->owner) throw std::invalid_argument("release the previous sigmoid LUT before reusing its result");
        auto owner=std::make_unique<p::SigmoidLUT2D>(p::build_sigmoid_lut_2d(
            static_cast<tpmshx::Topology>(topology),cell_nodes,wall_nodes,resolution));
        tpmshx_preparation_sigmoid_lut_v6 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V6;output.struct_size=sizeof(output);
        output.values=sigmoid_lut_view(*owner);
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_lut_release_v6(tpmshx_preparation_sigmoid_lut_v6* result) {
    if (!result) return;
    delete static_cast<p::SigmoidLUT2D*>(result->owner);*result={};
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_sigmoid_case_2d_v7(
    const tpmshx_preparation_sigmoid_input_2d_v6* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_sigmoid_case_2d_v6* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedOwner>(p::prepare_zoned_case_2d(request,options,sink));
        *result=sigmoid_view(*owner,source->values.values);owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_case_2d_release_v6(tpmshx_preparation_sigmoid_case_2d_v6* result) {
    if (!result) return;
    delete static_cast<ZonedOwner*>(result->owner);*result={};
}

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v7(void) {
    return TPMSHX_PREPARATION_CASE_ABI_VERSION_V7;
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_inlet_mass_capacities_2d_v3(
    const tpmshx_preparation_flow_input_2d_v3* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_flow_2d_v3* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    const auto grid=weak_grid();
    return tpmshx_prepare_inlet_mass_capacities_2d_v7(source,&grid,selected,callbacks,result,failure,error,capacity);
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_resolve_inlet_flow_2d_v3(
    const tpmshx_preparation_flow_input_2d_v3* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_flow_2d_v3* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    const auto grid=weak_grid();
    return tpmshx_resolve_inlet_flow_2d_v7(source,&grid,selected,callbacks,result,failure,error,capacity);
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_flow_case_2d_v3(
    const tpmshx_preparation_flow_input_2d_v3* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_flow_case_2d_v3* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    const auto grid=weak_grid();
    return tpmshx_prepare_flow_case_2d_v7(source,&grid,selected,callbacks,result,failure,error,capacity);
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_inlet_mass_capacities_2d_v4(
    const tpmshx_preparation_continuous_input_2d_v4* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_continuous_flow_2d_v4* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    const auto grid=weak_grid();
    return tpmshx_prepare_continuous_inlet_mass_capacities_2d_v7(source,&grid,selected,callbacks,result,failure,error,capacity);
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_resolve_inlet_flow_2d_v4(
    const tpmshx_preparation_continuous_input_2d_v4* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_continuous_flow_2d_v4* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    const auto grid=weak_grid();
    return tpmshx_resolve_continuous_inlet_flow_2d_v7(source,&grid,selected,callbacks,result,failure,error,capacity);
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_flow_case_2d_v4(
    const tpmshx_preparation_continuous_input_2d_v4* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_continuous_case_2d_v4* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    const auto grid=weak_grid();
    return tpmshx_prepare_continuous_flow_case_2d_v7(source,&grid,selected,callbacks,result,failure,error,capacity);
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_zoned_case_2d_v5(
    const tpmshx_preparation_zoned_input_2d_v5* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_zoned_case_2d_v5* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    const auto grid=weak_grid();
    return tpmshx_prepare_zoned_case_2d_v7(source,&grid,selected,callbacks,result,failure,error,capacity);
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_sigmoid_case_2d_v6(
    const tpmshx_preparation_sigmoid_input_2d_v6* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_sigmoid_case_2d_v6* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    const auto grid=weak_grid();
    return tpmshx_prepare_sigmoid_case_2d_v7(source,&grid,selected,callbacks,result,failure,error,capacity);
}

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v8(void) {
    return TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_zoned_inlet_mass_capacities_2d_v8(
    const tpmshx_preparation_zoned_flow_input_2d_v8* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_zoned_flow_2d_v8* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        if (request.explicit_targets) throw std::invalid_argument("capacity query does not accept explicit targets");
        auto owner=std::make_unique<ZonedFlowOwner>(p::prepare_zoned_inlet_mass_capacities_2d(
            request.input,request.physical_depth_kind,options,sink));
        *result=zoned_flow_view(*owner,source->values);owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_resolve_zoned_inlet_flow_2d_v8(
    const tpmshx_preparation_zoned_flow_input_2d_v8* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_zoned_flow_2d_v8* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowOwner>(p::resolve_zoned_inlet_flow_2d(request,options,sink));
        *result=zoned_flow_view(*owner,source->values);owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_zoned_flow_case_2d_v8(
    const tpmshx_preparation_zoned_flow_input_2d_v8* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_zoned_flow_case_2d_v8* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowCaseOwner>(p::prepare_zoned_flow_case_2d(request,options,sink));
        tpmshx_preparation_zoned_flow_case_2d_v8 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
        const auto resolved=resolved_input(owner->prepared.prepared.value.input,case_source(*source));
        output.prepared=zoned_view(owner->prepared,resolved);output.prepared.owner=nullptr;
        output.flow=zoned_flow_view(owner->flow,source->values);output.flow.owner=nullptr;
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_zoned_flow_2d_release_v8(
    tpmshx_preparation_zoned_flow_2d_v8* result) {
    if (!result) return;
    delete static_cast<ZonedFlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_zoned_flow_case_2d_release_v8(
    tpmshx_preparation_zoned_flow_case_2d_v8* result) {
    if (!result) return;
    delete static_cast<ZonedFlowCaseOwner*>(result->owner);*result={};
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_sigmoid_inlet_mass_capacities_2d_v8(
    const tpmshx_preparation_sigmoid_flow_input_2d_v8* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_sigmoid_flow_2d_v8* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        if (request.explicit_targets) throw std::invalid_argument("capacity query does not accept explicit targets");
        auto owner=std::make_unique<ZonedFlowOwner>(p::prepare_zoned_inlet_mass_capacities_2d(
            request.input,request.physical_depth_kind,options,sink));
        *result=sigmoid_flow_view(*owner,source->values);owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_resolve_sigmoid_inlet_flow_2d_v8(
    const tpmshx_preparation_sigmoid_flow_input_2d_v8* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_sigmoid_flow_2d_v8* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowOwner>(p::resolve_zoned_inlet_flow_2d(request,options,sink));
        *result=sigmoid_flow_view(*owner,source->values);owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_sigmoid_flow_case_2d_v8(
    const tpmshx_preparation_sigmoid_flow_input_2d_v8* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_sigmoid_flow_case_2d_v8* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowCaseOwner>(p::prepare_zoned_flow_case_2d(request,options,sink));
        tpmshx_preparation_sigmoid_flow_case_2d_v8 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION_V8;output.struct_size=sizeof(output);
        const auto resolved=resolved_input(owner->prepared.prepared.value.input,case_source(*source));
        output.prepared=sigmoid_view(owner->prepared,resolved);output.prepared.owner=nullptr;
        output.flow=sigmoid_flow_view(owner->flow,source->values);output.flow.owner=nullptr;
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_flow_2d_release_v8(
    tpmshx_preparation_sigmoid_flow_2d_v8* result) {
    if (!result) return;
    delete static_cast<ZonedFlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_flow_case_2d_release_v8(
    tpmshx_preparation_sigmoid_flow_case_2d_v8* result) {
    if (!result) return;
    delete static_cast<ZonedFlowCaseOwner*>(result->owner);*result={};
}

extern "C" uint32_t TPMSHX_PREPARATION_CALL tpmshx_preparation_case_abi_version_v9(void) {
    return TPMSHX_PREPARATION_CASE_ABI_VERSION_V9;
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_zoned_inlet_mass_capacities_2d_v9(
    const tpmshx_preparation_zoned_flow_input_2d_v9* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_zoned_flow_2d_v9* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        if (request.explicit_targets) throw std::invalid_argument("capacity query does not accept explicit targets");
        auto owner=std::make_unique<ZonedFlowOwner>(p::prepare_zoned_inlet_mass_capacities_2d(request.input,request.physical_depth_kind,options,sink));
        *result=zoned_flow_view(*owner,*source);owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_resolve_zoned_inlet_flow_2d_v9(
    const tpmshx_preparation_zoned_flow_input_2d_v9* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_zoned_flow_2d_v9* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowOwner>(p::resolve_zoned_inlet_flow_2d(request,options,sink));
        *result=zoned_flow_view(*owner,*source);owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_zoned_flow_case_2d_v9(
    const tpmshx_preparation_zoned_flow_input_2d_v9* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_zoned_flow_case_2d_v9* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowCaseOwner>(p::prepare_zoned_flow_case_2d(request,options,sink));
        *result=zoned_flow_view(*owner,*source);owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_zoned_flow_2d_release_v9(
    tpmshx_preparation_zoned_flow_2d_v9* result) {
    if (!result) return;
    delete static_cast<ZonedFlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_zoned_flow_case_2d_release_v9(
    tpmshx_preparation_zoned_flow_case_2d_v9* result) {
    if (!result) return;
    delete static_cast<ZonedFlowCaseOwner*>(result->owner);*result={};
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_sigmoid_inlet_mass_capacities_2d_v9(
    const tpmshx_preparation_sigmoid_flow_input_2d_v9* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_sigmoid_flow_2d_v9* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        if (request.explicit_targets) throw std::invalid_argument("capacity query does not accept explicit targets");
        auto owner=std::make_unique<ZonedFlowOwner>(p::prepare_zoned_inlet_mass_capacities_2d(request.input,request.physical_depth_kind,options,sink));
        *result=sigmoid_flow_view(*owner,*source);owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_resolve_sigmoid_inlet_flow_2d_v9(
    const tpmshx_preparation_sigmoid_flow_input_2d_v9* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_sigmoid_flow_2d_v9* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowOwner>(p::resolve_zoned_inlet_flow_2d(request,options,sink));
        *result=sigmoid_flow_view(*owner,*source);owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_prepare_sigmoid_flow_case_2d_v9(
    const tpmshx_preparation_sigmoid_flow_input_2d_v9* source,const tpmshx_preparation_grid_kinds_2d_v7* grid,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_case_callbacks_v1* callbacks,tpmshx_preparation_sigmoid_flow_case_2d_v9* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,grid,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowCaseOwner>(p::prepare_zoned_flow_case_2d(request,options,sink));
        *result=sigmoid_flow_view(*owner,*source);owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_flow_2d_release_v9(
    tpmshx_preparation_sigmoid_flow_2d_v9* result) {
    if (!result) return;
    delete static_cast<ZonedFlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_flow_case_2d_release_v9(
    tpmshx_preparation_sigmoid_flow_case_2d_v9* result) {
    if (!result) return;
    delete static_cast<ZonedFlowCaseOwner*>(result->owner);*result={};
}
