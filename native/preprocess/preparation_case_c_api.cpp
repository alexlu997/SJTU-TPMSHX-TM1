#include "tpmshx/preparation_case_c_api.h"
#include "tpmshx/preparation_case_3d_c_api.h"
#include "tpmshx/preparation_case.hpp"
#include "preparation_c_boundary.hpp"
#include "preparation_properties.hpp"
#include "../numerics/scalar_range_samples.hpp"

#include <algorithm>
#include <cfenv>
#include <cmath>
#include <cstring>
#include <exception>
#include <memory>
#include <stdexcept>
#include <type_traits>
#include <utility>
#include <vector>

namespace {
namespace p=tpmshx::preparation;
using p::c_api::require_buffer;
using p::c_api::require_disjoint;

enum class CallbackMode { inlet_query, uniform_2d, spatial_2d, three_d };

tpmshx_preparation_text_v1 text(const std::string& value) {return {value.data(),value.size()};}
tpmshx_preparation_text_v1 text(const char* value) {return {value,std::strlen(value)};}
tpmshx_preparation_array_v1 array(const std::vector<double>& value) {return {value.data(),value.size()};}
void flag(std::uint32_t value) {if (value>1) throw std::invalid_argument("preparation case flags require 0 or 1");}
template<class T> void version(const T* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION || value->struct_size!=sizeof(T))
        throw std::invalid_argument("preparation case ABI version or struct size is invalid");
}
void failure_version(const tpmshx_preparation_case_failure_v2* value) {
    require_buffer(value,1);
    if (value->abi_version!=TPMSHX_PREPARATION_FAILURE_ABI_VERSION || value->struct_size!=sizeof(*value))
        throw std::invalid_argument("preparation case failure ABI version or struct size is invalid");
}

std::string cache_text(tpmshx_preparation_text_v1 value) {
    require_buffer(value.data,value.size);
    return value.size?std::string(value.data,value.size):std::string{};
}
p::Sco2NuSelection nu_input(const tpmshx_preparation_sco2_nu_v2& source) {
    p::Sco2NuSelection value;value.mode=source.mode;
    for (std::size_t i=0;i<2;++i) {flag(source.have_alpha[i]);if(source.have_alpha[i])value.alpha[i]=source.alpha[i];}
    value.parameter_version=cache_text(source.parameter_version);value.source=cache_text(source.source);
    value.applicability=cache_text(source.applicability);return value;
}
tpmshx_preparation_sco2_nu_v2 nu_view(const p::Sco2NuSelection& nu) {
    tpmshx_preparation_sco2_nu_v2 selected{};selected.mode=nu.mode;
    for (std::size_t i=0;i<2;++i) {selected.have_alpha[i]=nu.alpha[i]?1u:0u;selected.alpha[i]=nu.alpha[i].value_or(0.);}
    selected.parameter_version=text(nu.parameter_version);selected.source=text(nu.source);selected.applicability=text(nu.applicability);
    return selected;
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
    output.sco2_nu=nu_input(source.sco2_nu);
    return output;
}
p::PreparationOptions options(const tpmshx_preparation_case_options_v1* source) {
    if (!source) return {};
    if (source->have_chi>2) throw std::invalid_argument("invalid chi selection tag");
    flag(source->allow_extrapolation);
    return {source->have_chi==1?std::optional<double>(source->chi):std::nullopt,source->allow_extrapolation!=0,source->have_chi==2};
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
template<class Prepared> struct CaseOwner {
    Prepared value;
    EvidenceViews evidence;
    std::vector<tpmshx_preparation_text_v1> notices;
    std::array<std::vector<tpmshx_preparation_text_field_v2>,2> calibration;
    explicit CaseOwner(Prepared prepared):value(std::move(prepared)),evidence(value.evidence) {
        for (const auto& notice:value.evidence.notices) notices.push_back(text(notice));
        for (std::size_t i=0;i<2;++i)
            for (const auto& item:value.sides[i].drag_evidence.calibration)
                calibration[i].push_back({text(item[0]),text(item[1])});
    }
};
using Owner=CaseOwner<p::PreparedCase2D>;
std::vector<tpmshx_preparation_grid_cell_3d_v4> grid_cells_view(const p::CaseInput3D& input) {
    std::vector<tpmshx_preparation_grid_cell_3d_v4> cells(input.grid_cells.size());
    for (std::size_t i=0;i<cells.size();++i) {
        const auto& source=input.grid_cells[i];auto& target=cells[i];
        for (std::size_t j=0;j<4;++j) target.bounds[j]=source.bounds[j];
        target.cell_length_mm=source.cell_length_mm;target.wall_thickness_mm=source.wall_thickness_mm;
    }
    return cells;
}
struct Owner3D : CaseOwner<p::PreparedCase3D> {
    std::vector<tpmshx_preparation_grid_cell_3d_v4> cells;
    explicit Owner3D(p::PreparedCase3D prepared):CaseOwner(std::move(prepared)),cells(grid_cells_view(value.input)) {}
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

void validate_callbacks(const tpmshx_preparation_callbacks_v2* callbacks,CallbackMode mode) {
    if (!callbacks) return;
    if (callbacks->abi_version!=TPMSHX_PREPARATION_CALLBACK_ABI_VERSION || callbacks->struct_size!=sizeof(*callbacks))
        throw std::invalid_argument("invalid preparation callback version or size");
    flag(callbacks->validate_grid_stage);
    if (callbacks->validate_grid_stage && !callbacks->validate_host_input)
        throw std::invalid_argument("validate_grid_stage requires validate_host_input");
    const bool has_untyped=callbacks->inlet_cache;
    const bool has_keyed=callbacks->inlet_cache_at || callbacks->sigmoid_lut_cache;
    if (has_untyped && has_keyed)
        throw std::invalid_argument("preparation callbacks cannot mix untyped and keyed cache hooks");
    switch (mode) {
        case CallbackMode::inlet_query:
            if (has_untyped || has_keyed)
                throw std::invalid_argument("inlet query callbacks cannot supply cache hooks");
            if (callbacks->validate_grid_stage)
                throw std::invalid_argument("inlet query callbacks cannot enable validate_grid_stage");
            break;
        case CallbackMode::uniform_2d:
            if (has_keyed)
                throw std::invalid_argument("uniform and continuous 2D callbacks accept untyped cache hooks only");
            break;
        case CallbackMode::spatial_2d:
            if (has_untyped)
                throw std::invalid_argument("spatial 2D callbacks require keyed cache hooks");
            break;
        case CallbackMode::three_d:
            if (has_untyped || callbacks->sigmoid_lut_cache)
                throw std::invalid_argument("3D host callbacks require keyed inlet cache hooks");
            if (callbacks->validate_grid_stage)
                throw std::invalid_argument("3D host callbacks cannot enable validate_grid_stage");
            break;
    }
}

struct FlowOutputStorage {
    const unsigned char* result;
    std::size_t result_bytes;
    tpmshx_preparation_case_failure_v2* failure;
    char* error;
    std::size_t error_bytes;

    template<class T> void borrowed(const T* pointer,std::size_t count) const {
        require_buffer(pointer,count);
        require_disjoint(pointer,count,result,result_bytes);
        require_disjoint(pointer,count,failure,failure?1:0);
        require_disjoint(pointer,count,error,error_bytes);
    }
    void borrowed(tpmshx_preparation_text_v1 value) const {borrowed(value.data,value.size);}
    void borrowed(tpmshx_preparation_array_v1 value) const {borrowed(value.data,value.size);}
    template<class Evidence> void evidence(const Evidence& value) const {
        borrowed(value.ranges,value.range_count);
        borrowed(value.range_bounds_list,value.range_count);
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
    void owned(const tpmshx_preparation_case_input_2d_v1& value) const {
        for (const auto item:{value.sco2_nu.parameter_version,value.sco2_nu.source,value.sco2_nu.applicability}) borrowed(item);
    }
    void owned(const tpmshx_preparation_case_2d_v1& value) const {
        owned(value.input);
        for (const auto item:{value.dx,value.dy,value.x_edges,value.y_edges,value.x_breaks,value.y_breaks,
            value.cell_length,value.wall_thickness,value.total_porosity,value.solid_conductivity,value.hydraulic_radius}) borrowed(item);
        for (const auto& side:value.sides) {
            for (const auto item:{side.cross_widths,side.stream_widths,side.row_permeability,side.row_forchheimer,
                side.permeability,side.forchheimer,side.inlet_geometry,side.outlet_geometry,
                side.inlet_profile,side.outlet_profile,side.outlet_u_fraction}) borrowed(item);
            borrowed(side.drag_evidence.campaign);borrowed(side.drag_evidence.scope);
        }
        for (const auto& model:value.models) {borrowed(model.name);borrowed(model.version);borrowed(model.side);}
        evidence(value);
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
    void owned(const tpmshx_preparation_flow_2d_v1& value) const {owned(value.input);evidence(value.evidence);}
    void owned(const tpmshx_preparation_2d_uniform_flow_v1& value) const {owned(value.flow);}
    void owned(const tpmshx_preparation_2d_uniform_case_v1& value) const {owned(value.prepared);owned(value.flow);}
    void owned(const tpmshx_preparation_2d_continuous_flow_v1& value) const {
        owned(value.flow);borrowed(value.controls.decision_mm);
    }
    void owned(const tpmshx_preparation_2d_continuous_case_v1& value) const {
        owned(value.prepared);owned(value.flow);borrowed(value.controls.decision_mm);
        for (const auto item:{value.area_density_per_m,value.hydraulic_diameter_m,
            value.fluid_conductivity[0],value.fluid_conductivity[1],value.design_pore_porosity}) borrowed(item);
        for (const auto& drag:value.drag) {borrowed(drag.transfer_policy);borrowed(drag.geometry_application);}
    }
    void lut(const tpmshx_preparation_sigmoid_lut_view_v6& value) const {
        for (const auto item:{value.cell_mm,value.wall_mm,value.porosity,value.area_density_per_m}) borrowed(item);
    }
    void owned(const tpmshx_preparation_sigmoid_lut_v7& value) const {
        for (const auto item:{value.cell_mm,value.wall_mm,value.porosity,value.area_density_per_m}) borrowed(item);
    }
    void owned_regions(const tpmshx_preparation_zone_region_v5* regions,std::size_t count) const {
        borrowed(regions,count);
        for (std::size_t i=0;i<count;++i) borrowed(regions[i].name);
    }
    template<class SpatialCase> void owned_spatial_case(const SpatialCase& value) const {
        owned(value.prepared);owned(value.flow);
        borrowed(value.regions,value.region_count);borrowed(value.zone_id,value.cell_count);
        for (std::size_t i=0;i<value.region_count;++i) borrowed(value.regions[i].region.name);
        for (const auto item:{value.thermal_porosity,value.area_density_per_m,value.hydraulic_diameter_m,
            value.design_area_density_per_m,value.design_pore_porosity,
            value.fluid_conductivity[0],value.fluid_conductivity[1],
            value.volumetric_transfer[0],value.volumetric_transfer[1]}) borrowed(item);
    }
    void owned(const tpmshx_preparation_2d_zoned_flow_v1& value) const {
        owned(value.flow);owned_regions(value.regions,value.region_count);
    }
    void owned(const tpmshx_preparation_2d_zoned_case_v1& value) const {owned_spatial_case(value);}
    void owned(const tpmshx_preparation_2d_sigmoid_flow_v1& value) const {
        owned(value.flow);owned_regions(value.regions,value.region_count);
        borrowed(value.controls.decision_mm);lut(value.lut);
    }
    void owned(const tpmshx_preparation_2d_sigmoid_case_v1& value) const {
        owned_spatial_case(value);borrowed(value.controls.decision_mm);lut(value.lut);
    }
    void owned(const tpmshx_preparation_2d_stripe_case_v1& value) const {
        owned_spatial_case(value);borrowed(value.region_hydraulic_radii_m);
    }
    void owned(const tpmshx_preparation_case_input_3d_v1& value) const {
        for (const auto item:{value.sco2_nu.parameter_version,value.sco2_nu.source,value.sco2_nu.applicability}) borrowed(item);
    }
    void owned(const tpmshx_preparation_case_3d_v1& value) const {
        owned(value.input);
        for (const auto item:value.widths) borrowed(item);
        for (const auto item:value.edges) borrowed(item);
        for (const auto item:{value.cell_length,value.wall_thickness,value.total_porosity,value.side_porosity,
            value.permeability,value.forchheimer,value.solid_conductivity}) borrowed(item);
        for (const auto& side:value.sides) {
            borrowed(side.inlet_opening);borrowed(side.outlet_opening);
            borrowed(side.drag_evidence.campaign);borrowed(side.drag_evidence.scope);
            const auto& drag=side.drag_selection;
            borrowed(drag.application_scope);borrowed(drag.fluid);borrowed(drag.calibration,drag.calibration_count);
            for (std::size_t i=0;i<drag.calibration_count;++i) {
                borrowed(drag.calibration[i].key);borrowed(drag.calibration[i].value);
            }
        }
        for (const auto& model:value.models) {borrowed(model.name);borrowed(model.version);borrowed(model.side);}
        evidence(value.evidence);
        for (const auto item:{value.sco2_nu_model_version,value.sco2_nu_interpretation,value.co2.version,value.co2.application_version,
            value.co2.pressure_model,value.co2.correction_source,value.co2.property_model,value.co2.common_geometry}) borrowed(item);
        borrowed(value.notices,value.notice_count);
        for (std::size_t i=0;i<value.notice_count;++i) borrowed(value.notices[i]);
    }
    void owned(const tpmshx_preparation_flow_3d_v1& value) const {owned(value.input);evidence(value.evidence);}
    void owned(const tpmshx_preparation_3d_continuous_flow_v1& value) const {
        owned(value.flow);borrowed(value.controls.decision_mm);
    }
    void owned(const tpmshx_preparation_3d_continuous_case_v1& value) const {
        owned(value.prepared);owned(value.flow);borrowed(value.controls.decision_mm);
        for (const auto item:{value.area_density_per_m,value.hydraulic_diameter_m,value.thermal_porosity}) borrowed(item);
        for (const auto& drag:value.drag) {borrowed(drag.transfer_policy);borrowed(drag.geometry_application);}
    }
    void owned(const tpmshx_preparation_3d_spatial_flow_v1& value) const {
        owned(value.flow);borrowed(value.cells,value.cell_count);
    }
    void owned(const tpmshx_preparation_3d_spatial_case_v1& value) const {
        owned(value.prepared);owned(value.flow);borrowed(value.cells,value.cell_count);
        for (const auto item:{value.side_b_porosity,value.area_density_per_m,value.hydraulic_diameter_m,value.thermal_porosity}) borrowed(item);
    }
};

struct FlowCallbackContext {
    const tpmshx_preparation_callbacks_v2* callbacks;
    FlowOutputStorage storage;
    bool storage_safe=true;
};
void validate_host_input(void* context,std::uint32_t stage,std::uint32_t side) {
    const auto& state=*static_cast<const FlowCallbackContext*>(context);
    const auto& callbacks=*state.callbacks;
    if (callbacks.validate_host_input && callbacks.validate_host_input(callbacks.context,stage,side))
        throw std::runtime_error("preparation host input callback failed");
}
void validate_grid(void* context) {validate_host_input(context,3,2);}
void emit_flow(void* context,const p::PreparationEvent& event) {
    const auto& state=*static_cast<const FlowCallbackContext*>(context);
    const auto& callbacks=*state.callbacks;const auto view=event_view(event);
    if (callbacks.event(callbacks.context,&view)) throw std::runtime_error("preparation event callback failed");
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
tpmshx_preparation_inlet_cache_v3 inlet_cache_view(const p::PreparationInletCache& values,const EvidenceViews& evidence) {
    const auto& props=values.properties;
    tpmshx_preparation_inlet_cache_v3 view{};view.geometry=geometry_view(values.geometry);
    view.properties={props.rho,props.mu,props.k_f,props.cp,props.pr,props.re,props.nu,
        props.permeability_m2,props.forchheimer_per_m,props.pressure_gradient_Pa_m,
        props.surface_transfer_W_m2K,props.fluid_conductivity_W_mK,props.solid_conductivity_W_mK};
    view.evidence={evidence.ranges.data(),evidence.ranges.size(),evidence.range_bounds_list.data(),
        evidence.warnings.data(),evidence.warnings.size(),nullptr,0};
    return view;
}
void copy_inlet_cache(const tpmshx_preparation_inlet_cache_v3& view,p::PreparationInletCache& values,std::size_t max_rank) {
    values.geometry=cache_geometry(view.geometry);const auto& q=view.properties;
    values.properties={q.rho,q.mu,q.k_f,q.cp,q.pr,q.re,q.nu,q.permeability_m2,q.forchheimer_per_m,
        q.pressure_gradient_Pa_m,q.surface_transfer_W_m2K,q.fluid_conductivity_W_mK,q.solid_conductivity_W_mK};
    values.evidence=cache_evidence(view.evidence,max_rank);
}
bool inlet_cache(void* context,bool publish,std::uint32_t side,const p::InletInput2D& inlet,
                 p::PreparationInletCache& values) {
    auto& state=*static_cast<FlowCallbackContext*>(context);
    const auto& callbacks=*state.callbacks;
    if (!callbacks.inlet_cache) return false;
    const auto inlet_input=inlet_view(inlet);
    EvidenceViews evidence(values.evidence);auto view=inlet_cache_view(values,evidence);
    std::uint32_t hit=0;
    state.storage_safe=false;
    const auto status=callbacks.inlet_cache(callbacks.context,publish?1u:0u,side,&inlet_input,&view,&hit);
    state.storage.evidence(view.evidence);state.storage_safe=true;
    if (status) throw std::runtime_error("preparation inlet cache callback failed");
    flag(hit);
    if (!publish && hit) copy_inlet_cache(view,values,2);
    return hit!=0;
}

tpmshx_preparation_geometry_key_v9 geometry_key_view(const p::PreparationGeometryKey& value) {
    return {static_cast<std::uint32_t>(value.topology),value.cell_length_mm,value.wall_thickness_mm};
}
tpmshx_preparation_inlet_key_v9 inlet_key_view(const p::PreparationInletKey& value) {
    tpmshx_preparation_inlet_key_v9 output{};
    output.geometry=geometry_key_view(value.geometry);output.fluid=static_cast<std::uint32_t>(value.fluid);
    output.velocity_m_s=value.velocity_m_s;output.temperature_K=value.temperature_K;output.pressure_Pa=value.pressure_Pa;
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
bool inlet_cache_at(void* context,bool publish,const p::PreparationInletKey& key,p::PreparationInletCache& values) {
    auto& state=*static_cast<FlowCallbackContext*>(context);
    const auto& callbacks=*state.callbacks;
    const auto probe=inlet_key_view(key);EvidenceViews evidence(values.evidence);
    auto view=inlet_cache_view(values,evidence);std::uint32_t hit=0;
    state.storage_safe=false;
    const auto status=callbacks.inlet_cache_at(callbacks.context,publish?1u:0u,&probe,&view,&hit);
    state.storage.evidence(view.evidence);state.storage_safe=true;
    if (status) throw std::runtime_error("preparation typed inlet cache callback failed");
    flag(hit);if (!publish && hit) copy_inlet_cache(view,values,3);return hit!=0;
}
bool sigmoid_lut_cache(void* context,bool publish,tpmshx::Topology topology,std::size_t resolution,p::SigmoidLUT2D& values) {
    auto& state=*static_cast<FlowCallbackContext*>(context);
    const auto& callbacks=*state.callbacks;
    tpmshx_preparation_sigmoid_lut_view_v6 view{array(values.cell_mm),array(values.wall_mm),
        array(values.porosity),array(values.area_density),values.porosity_fast,values.area_fast};
    std::uint32_t hit=0;state.storage_safe=false;
    const auto status=callbacks.sigmoid_lut_cache(callbacks.context,publish?1u:0u,
        static_cast<std::uint32_t>(topology),resolution,&view,&hit);
    state.storage.lut(view);state.storage_safe=true;
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
    const auto& callbacks=*state.callbacks;
    if (!callbacks.observe_range) return;
    p::PreparationEvidence evidence;evidence.ranges.push_back(range);EvidenceViews views(evidence);
    if (callbacks.observe_range(callbacks.context,cached?1u:0u,&views.ranges.front(),
        range.bounds_list?1u:0u,scalar?1u:0u,scalar.value_or(0.)))
        throw std::runtime_error("preparation range observation callback failed");
}
void observe_notice(void* context,std::uint32_t kind,std::uint32_t side,double value,const std::string& message) {
    const auto& state=*static_cast<const FlowCallbackContext*>(context);
    const auto& callbacks=*state.callbacks;
    if (callbacks.observe_notice && callbacks.observe_notice(callbacks.context,kind,side,value,text(message)))
        throw std::runtime_error("preparation notice observation callback failed");
}

p::PreparationCallbacks make_sink(const tpmshx_preparation_callbacks_v2* callbacks,FlowCallbackContext& context) {
    if (!callbacks) return {};
    return {
        callbacks->event?emit_flow:nullptr,
        &context,
        callbacks->validate_host_input?validate_host_input:nullptr,
        callbacks->inlet_cache?inlet_cache:nullptr,
        callbacks->observe_range?observe_range:nullptr,
        callbacks->observe_notice?observe_notice:nullptr,
        callbacks->validate_grid_stage?validate_grid:nullptr,
        callbacks->inlet_cache_at?inlet_cache_at:nullptr,
        callbacks->sigmoid_lut_cache?sigmoid_lut_cache:nullptr,
    };
}

template<class Prepared,class View> void model_view(const Prepared& value,View& output) {
    const auto& evidence=value.evidence;const auto& nu=value.input.sco2_nu;
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
}
tpmshx_preparation_case_input_2d_v1 resolved_input(const p::CaseInput2D& value,
    const tpmshx_preparation_case_input_2d_v1& source) {
    auto output=source;
    for (std::size_t i=0;i<2;++i) output.sides[i]=inlet_view(value.sides[i]);
    output.sco2_nu=nu_view(value.sco2_nu);
    return output;
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
        auto& sel=result.drag[i];
        sel.have_selection=drag.selection?1u:0u;if(drag.selection)sel.selection=*drag.selection;
        sel.application_scope=text(drag.application_scope);sel.fluid=text(drag.fluid);
        sel.calibration=owner.calibration[i].data();sel.calibration_count=owner.calibration[i].size();
    }
    for (std::size_t i=0;i<4;++i) {
        const auto& model=value.evidence.models[i];result.models[i]={text(model.name),text(model.version),text(model.side)};
    }
    result.ranges=owner.evidence.ranges.data();result.range_count=owner.evidence.ranges.size();
    result.range_bounds_list=owner.evidence.range_bounds_list.data();
    result.warnings=owner.evidence.warnings.data();result.warning_count=owner.evidence.warnings.size();
    result.events=owner.evidence.events.data();result.event_count=owner.evidence.events.size();
    result.sco2_nu=nu_view(value.input.sco2_nu);model_view(value,result);
    result.notices=owner.notices.data();result.notice_count=owner.notices.size();
    return result;
}
tpmshx_preparation_flow_2d_v1 flow_view(FlowOwner& owner,const tpmshx_preparation_case_input_2d_v1& source) {
    tpmshx_preparation_flow_2d_v1 output{};
    output.input=resolved_input(owner.value.input,source);
    output.have_capacities=owner.value.have_capacities?1u:0u;
    for (std::size_t i=0;i<2;++i) {
        output.capacities[i]=owner.value.capacities[i];output.speeds[i]=owner.value.speeds[i];
    }
    const auto& evidence=owner.evidence;
    output.evidence={evidence.ranges.data(),evidence.ranges.size(),evidence.range_bounds_list.data(),
        evidence.warnings.data(),evidence.warnings.size(),evidence.events.data(),evidence.events.size()};
    return output;
}
tpmshx_preparation_thermal_sides_2d_v10 thermal_sides(const p::PreparedCase2D& input) {
    tpmshx_preparation_thermal_sides_2d_v10 output{};
    if (input.thermal_sides) {
        output.have_side_geometry=1;
        for (std::size_t side=0;side<2;++side) {
            const auto& value=(*input.thermal_sides)[side];
            const double fields[]{value.area,value.diameter,value.reference_area,value.reference_diameter};
            std::copy_n(fields,4,output.side_geometry[side]);
        }
    }
    return output;
}
tpmshx_preparation_continuous_controls_2d_v4 controls_view(const p::CaseInput2D& input) {
    const auto& controls=*input.continuous;
    return {controls.nx,controls.ny,controls.order,controls.symmetric_y?1u:0u,
        {controls.cell_bounds_mm[0],controls.cell_bounds_mm[1]},
        {controls.wall_bounds_mm[0],controls.wall_bounds_mm[1]},array(controls.decision_mm)};
}
p::InletFlowRequest2D input(const tpmshx_preparation_2d_uniform_input_v1& source) {
    p::InletFlowRequest2D output;output.input=input(source.input);
    flag(source.have_explicit_targets);
    if (source.have_explicit_targets) output.explicit_targets=std::array<double,2>{source.explicit_targets_kg_s[0],source.explicit_targets_kg_s[1]};
    return output;
}
p::InletFlowRequest2D input(const tpmshx_preparation_2d_continuous_input_v1& source) {
    p::InletFlowRequest2D output;output.input=input(source.input);
    flag(source.have_explicit_targets);
    if (source.have_explicit_targets) output.explicit_targets=std::array<double,2>{source.explicit_targets_kg_s[0],source.explicit_targets_kg_s[1]};
    const auto& controls=source.controls;flag(controls.symmetric_y);
    p::ContinuousControls2D value;
    value.nx=controls.n_ctrl_x;value.ny=controls.n_ctrl_y;value.order=controls.spline_order;
    value.symmetric_y=controls.symmetric_y!=0;
    std::copy_n(controls.L_bounds_mm,2,value.cell_bounds_mm.begin());
    std::copy_n(controls.t_bounds_mm,2,value.wall_bounds_mm.begin());
    if (controls.decision_mm.size) value.decision_mm.assign(
        controls.decision_mm.data,controls.decision_mm.data+controls.decision_mm.size);
    output.input.continuous=std::move(value);return output;
}
p::SpatialModel2D spatial_model(const tpmshx_preparation_spatial_model_2d_v9& value) {
    flag(value.allow_geometry_extrapolation);flag(value.load_default_lut);
    return {value.solid_conductivity_W_mK,value.allow_geometry_extrapolation!=0,value.load_default_lut!=0};
}
tpmshx_preparation_spatial_model_2d_v9 spatial_model(const p::SpatialModel2D& value) {
    return {value.solid_conductivity_W_mK,value.allow_geometry_extrapolation?1u:0u,value.load_default_lut?1u:0u};
}
template<class Source> p::ZonedFlowRequest2D spatial_request(const Source& source) {
    p::ZonedFlowRequest2D output;
    output.input.input=input(source.input);
    output.input.kind=source.kind;output.input.axis=source.axis;
    for (std::size_t i=0;i<source.region_count;++i) {
        const auto& item=source.regions[i];p::ZoneRegion2D region;
        region.name=cache_text(item.name);region.cell_length_mm=item.cell_length_mm;region.wall_thickness_mm=item.wall_thickness_mm;
        for (std::size_t j=0;j<4;++j) region.bounds[j]=item.bounds[j];
        output.input.regions.push_back(std::move(region));
    }
    flag(source.have_explicit_targets);
    if (source.have_explicit_targets)
        output.explicit_targets=std::array<double,2>{source.explicit_targets_kg_s[0],source.explicit_targets_kg_s[1]};
    output.input.spatial_model=spatial_model(source.model);
    return output;
}
p::ZonedFlowRequest2D input(const tpmshx_preparation_2d_zoned_input_v1& source) {return spatial_request(source);}
p::ZonedFlowRequest2D input(const tpmshx_preparation_2d_sigmoid_input_v1& source) {
    auto output=spatial_request(source);
    p::SigmoidInput2D sigmoid;
    const auto copy=[](tpmshx_preparation_array_v1 values) {
        return values.size?std::vector<double>(values.data,values.data+values.size):std::vector<double>{};
    };
    sigmoid.controls.decision_mm=copy(source.controls.decision_mm);
    sigmoid.controls.inlet_transition=source.controls.inlet_transition;
    sigmoid.controls.outlet_transition=source.controls.outlet_transition;
    sigmoid.lut.cell_mm=copy(source.lut.cell_mm);sigmoid.lut.wall_mm=copy(source.lut.wall_mm);
    sigmoid.lut.porosity=copy(source.lut.porosity);sigmoid.lut.area_density=copy(source.lut.area_density_per_m);
    sigmoid.lut.porosity_fast=source.lut.porosity_fast;sigmoid.lut.area_fast=source.lut.area_fast;
    output.input.sigmoid=std::move(sigmoid);return output;
}
tpmshx_preparation_zone_region_v5 zone_region_view(const p::ZoneRegion2D& source) {
    tpmshx_preparation_zone_region_v5 output{};
    output.name=text(source.name);output.cell_length_mm=source.cell_length_mm;
    output.wall_thickness_mm=source.wall_thickness_mm;
    for (std::size_t i=0;i<4;++i) output.bounds[i]=source.bounds[i];
    return output;
}
tpmshx_preparation_sigmoid_controls_2d_v6 sigmoid_controls_view(const p::SigmoidControls2D& controls) {
    return {array(controls.decision_mm),controls.inlet_transition,controls.outlet_transition};
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
            }
            regions.push_back(view);
        }
    }
};
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
    std::vector<double> region_hydraulic_radii_m;
    explicit ZonedFlowCaseOwner(p::PreparedZonedFlowCase2D result)
        :prepared(std::move(result.prepared)),flow(std::move(result.flow)) {}
};
template<class Result> void fill_spatial_case_common(
    Result& output,ZonedFlowCaseOwner& owner,const tpmshx_preparation_case_input_2d_v1& source) {
    output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
    const auto resolved=resolved_input(owner.prepared.prepared.value.input,source);
    output.prepared=view(owner.prepared.prepared,resolved);
    output.flow=flow_view(owner.flow.flow,source);
    const auto& values=owner.prepared.value;
    const auto& prepared=owner.prepared.prepared.value;
    output.kind=values.kind;output.axis=values.axis;
    output.regions=owner.prepared.regions.data();output.region_count=owner.prepared.regions.size();
    output.zone_id=values.zone_id.data();output.cell_count=values.zone_id.size();
    output.thermal_porosity=array(values.thermal_porosity);
    output.area_density_per_m=array(prepared.area_density);
    output.hydraulic_diameter_m=array(prepared.hydraulic_diameter);
    output.design_area_density_per_m=array(values.design_area_density);
    output.design_pore_porosity=array(values.design_pore_porosity);
    for (std::size_t i=0;i<2;++i) {
        output.fluid_conductivity[i]=array(prepared.fluid_conductivity[i]);
        output.volumetric_transfer[i]=array(values.volumetric_transfer[i]);
    }
    output.model=spatial_model(*owner.flow.input.spatial_model);
    output.thermal=thermal_sides(prepared);
    output.owner=&owner;
}

template<class Source,class Result,class Function> int flow_boundary(
    const Source* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,Result* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity,
    Function function,bool offset_scope=false) {
    constexpr bool is_spatial=std::is_same_v<Source,tpmshx_preparation_2d_zoned_input_v1>
        || std::is_same_v<Source,tpmshx_preparation_2d_sigmoid_input_v1>;
    if (!tpmshx::fields::c_api::error_buffer_valid(error,capacity)) return TPMSHX_PREPARATION_INVALID;
    const FlowOutputStorage storage{reinterpret_cast<const unsigned char*>(result),
        result?sizeof(*result):0,failure,error,capacity};
    try {
        require_buffer(result,result?1:0);
        require_buffer(source,source?1:0);
        require_buffer(callbacks,callbacks?1:0);
        require_disjoint(error,capacity,source,source?1:0);require_disjoint(error,capacity,result,result?1:0);
        require_disjoint(error,capacity,selected,selected?1:0);require_disjoint(error,capacity,callbacks,callbacks?1:0);
        require_disjoint(error,capacity,failure,failure?1:0);
        require_disjoint(source,source?1:0,result,result?1:0);require_disjoint(source,source?1:0,failure,failure?1:0);
        require_disjoint(result,result?1:0,failure,failure?1:0);
        require_disjoint(selected,selected?1:0,result,result?1:0);require_disjoint(selected,selected?1:0,failure,failure?1:0);
        require_disjoint(callbacks,callbacks?1:0,result,result?1:0);require_disjoint(callbacks,callbacks?1:0,failure,failure?1:0);
        if (result && result->owner) storage.owned(*result);
        if constexpr (std::is_same_v<Source,tpmshx_preparation_2d_continuous_input_v1>) {
            if (source) {
                const auto values=source->controls.decision_mm;
                require_disjoint(error,capacity,values.data,values.size);require_buffer(values.data,values.size);
                require_disjoint(values.data,values.size,result,result?1:0);
                require_disjoint(values.data,values.size,failure,failure?1:0);
            }
        }
        if constexpr (std::is_same_v<Source,tpmshx_preparation_2d_sigmoid_input_v1>) {
            if (source) for (const auto values:{source->controls.decision_mm,source->lut.cell_mm,
                    source->lut.wall_mm,source->lut.porosity,source->lut.area_density_per_m}) {
                require_disjoint(error,capacity,values.data,values.size);require_buffer(values.data,values.size);
                require_disjoint(values.data,values.size,result,result?1:0);
                require_disjoint(values.data,values.size,failure,failure?1:0);
            }
        }
        if constexpr (is_spatial) {
            if (source) {
                require_disjoint(error,capacity,source->regions,source->region_count);
                require_buffer(source->regions,source->region_count);
                require_disjoint(source->regions,source->region_count,result,result?1:0);
                require_disjoint(source->regions,source->region_count,failure,failure?1:0);
                for (std::size_t i=0;i<source->region_count;++i) {
                    const auto name=source->regions[i].name;
                    require_disjoint(error,capacity,name.data,name.size);require_buffer(name.data,name.size);
                    require_disjoint(name.data,name.size,result,result?1:0);
                    require_disjoint(name.data,name.size,failure,failure?1:0);
                }
            }
        }
        if (source) for (const auto value:{source->input.sco2_nu.parameter_version,
            source->input.sco2_nu.source,source->input.sco2_nu.applicability}) {
            require_disjoint(error,capacity,value.data,value.size);require_buffer(value.data,value.size);
            require_disjoint(value.data,value.size,result,result?1:0);
            require_disjoint(value.data,value.size,failure,failure?1:0);
        }
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    FlowCallbackContext context{callbacks,storage};
    tpmshx_preparation_case_failure_v2 staged_failure{};
    bool failure_ready=false;std::exception_ptr saved_exception;
    try {
        version(source);version(&source->input);version(result);
        failure_version(failure);
        if (selected) version(selected);
        validate_callbacks(callbacks,is_spatial?CallbackMode::spatial_2d:CallbackMode::uniform_2d);
        staged_failure.abi_version=TPMSHX_PREPARATION_FAILURE_ABI_VERSION;
        staged_failure.struct_size=sizeof(staged_failure);staged_failure.side=2;failure_ready=true;
        try {
            if (result->owner) throw std::invalid_argument("release the previous flow result before reusing its result");
            const auto sink=make_sink(callbacks,context);
            auto request=input(*source);
            if constexpr (std::is_same_v<decltype(request),p::ZonedFlowRequest2D>) {
                request.input.input.offset_scope=offset_scope;
            } else request.input.offset_scope=offset_scope;
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

tpmshx::grid::Port port(const tpmshx_grid_port_v1& source) {
    flag(source.active);tpmshx::grid::Port value{source.direction,source.active!=0,{}};
    for (std::size_t i=0;i<2;++i) {
        std::optional<double>* fields[]{&value.ends[i].center,&value.ends[i].width,
            &value.ends[i].center2,&value.ends[i].width2};
        for (std::size_t j=0;j<4;++j) {flag(source.present[i][j]);if(source.present[i][j])*fields[j]=source.values[i][j];}
    }
    return value;
}
tpmshx_grid_port_v1 port_view(const tpmshx::grid::Port& source) {
    tpmshx_grid_port_v1 value{};value.direction=source.direction;value.active=source.active?1u:0u;
    for (std::size_t i=0;i<2;++i) {
        const std::optional<double> fields[]{source.ends[i].center,source.ends[i].width,
            source.ends[i].center2,source.ends[i].width2};
        for (std::size_t j=0;j<4;++j) if (fields[j]) {value.present[i][j]=1;value.values[i][j]=*fields[j];}
    }
    return value;
}
p::CaseInput3D input(const tpmshx_preparation_case_input_3d_v1& source) {
    p::CaseInput3D output{};flag(source.port_wall_refine);
    for (std::size_t i=0;i<3;++i) {output.grid.lengths[i]=source.lengths_m[i];output.grid.counts[i]=source.counts[i];}
    output.grid.max_cells=source.max_cells;output.grid.port_wall_refine=source.port_wall_refine!=0;
    output.geometry={static_cast<tpmshx::Topology>(source.topology),source.cell_length_mm,source.wall_thickness_mm,
        source.solid_conductivity_W_mK,source.delta_levelset};
    for (std::size_t i=0;i<2;++i) {
        const auto& side=source.sides[i];flag(side.have_mass_flow);
        output.sides[i]={static_cast<tpmshx::Fluid>(side.fluid),side.velocity_m_s,side.temperature_K,side.pressure_Pa,
            port(side.port),side.have_mass_flow?std::optional<double>(side.mass_flow_kg_s):std::nullopt};
    }
    output.geometry_mode=source.geometry_mode;output.df_mode=source.df_mode;
    output.sco2_nu=nu_input(source.sco2_nu);return output;
}
tpmshx_preparation_case_input_3d_v1 resolved_input(const p::CaseInput3D& value,
    const tpmshx_preparation_case_input_3d_v1& source) {
    auto output=source;output.sco2_nu=nu_view(value.sco2_nu);
    for (std::size_t i=0;i<3;++i) output.lengths_m[i]=value.grid.lengths[i];
    for (std::size_t i=0;i<2;++i) {
        auto& target=output.sides[i];const auto& inlet=value.sides[i];
        target.velocity_m_s=inlet.velocity_m_s;target.have_mass_flow=inlet.mass_flow_kg_s?1u:0u;
        target.mass_flow_kg_s=inlet.mass_flow_kg_s.value_or(0.);target.port=port_view(inlet.port);
    }
    return output;
}
struct FlowOwner3D {
    p::InletFlow3D value;
    EvidenceViews evidence;
    std::vector<tpmshx_preparation_grid_cell_3d_v4> cells;
    explicit FlowOwner3D(p::InletFlow3D flow):value(std::move(flow)),evidence(value.evidence),cells(grid_cells_view(value.input)) {}
};
struct FlowCaseOwner3D {
    Owner3D prepared;
    FlowOwner3D flow;
    explicit FlowCaseOwner3D(p::PreparedFlowCase3D value)
        :prepared(std::move(value.prepared)),flow(std::move(value.flow)) {}
};
p::InletFlowRequest3D input(const tpmshx_preparation_3d_continuous_input_v1& source) {
    p::InletFlowRequest3D output;output.input=input(source.input);
    flag(source.have_explicit_targets);
    if (source.have_explicit_targets) output.explicit_targets=std::array<double,2>{source.explicit_targets_kg_s[0],source.explicit_targets_kg_s[1]};
    const auto& controls=source.controls;
    flag(controls.symmetric_y);flag(controls.have_ctrl_z);
    p::ContinuousControls3D value;
    value.nx=controls.n_ctrl_x;value.ny=controls.n_ctrl_y;value.order=controls.spline_order;
    if (controls.have_ctrl_z) value.nz=controls.n_ctrl_z;
    value.symmetric_y=controls.symmetric_y!=0;
    std::copy_n(controls.L_bounds_mm,2,value.cell_bounds_mm.begin());
    std::copy_n(controls.t_bounds_mm,2,value.wall_bounds_mm.begin());
    if (controls.decision_mm.size) value.decision_mm.assign(
        controls.decision_mm.data,controls.decision_mm.data+controls.decision_mm.size);
    output.input.continuous=std::move(value);return output;
}
p::InletFlowRequest3D input(const tpmshx_preparation_3d_spatial_input_v1& source) {
    p::InletFlowRequest3D output;output.input=input(source.input);
    flag(source.have_explicit_targets);
    if (source.have_explicit_targets) output.explicit_targets=std::array<double,2>{source.explicit_targets_kg_s[0],source.explicit_targets_kg_s[1]};
    output.input.grid_cells.resize(source.cell_count);
    for (std::size_t i=0;i<source.cell_count;++i) {
        const auto& cell=source.cells[i];auto& target=output.input.grid_cells[i];
        for (std::size_t j=0;j<4;++j) target.bounds[j]=cell.bounds[j];
        target.cell_length_mm=cell.cell_length_mm;target.wall_thickness_mm=cell.wall_thickness_mm;
    }
    return output;
}
tpmshx_preparation_continuous_controls_3d_v3 controls_view(const p::CaseInput3D& input) {
    const auto& controls=*input.continuous;
    return {controls.nx,controls.ny,controls.nz.value_or(1),controls.nz?1u:0u,
        controls.order,controls.symmetric_y?1u:0u,
        {controls.cell_bounds_mm[0],controls.cell_bounds_mm[1]},
        {controls.wall_bounds_mm[0],controls.wall_bounds_mm[1]},array(controls.decision_mm)};
}
tpmshx_preparation_flow_3d_v1 flow_view(FlowOwner3D& owner,const tpmshx_preparation_case_input_3d_v1& source) {
    tpmshx_preparation_flow_3d_v1 output{};
    output.input=resolved_input(owner.value.input,source);output.have_capacities=owner.value.have_capacities?1u:0u;
    for (std::size_t i=0;i<2;++i) {
        output.capacities[i]=owner.value.capacities[i];output.speeds[i]=owner.value.speeds[i];
    }
    const auto& evidence=owner.evidence;
    output.evidence={evidence.ranges.data(),evidence.ranges.size(),evidence.range_bounds_list.data(),
        evidence.warnings.data(),evidence.warnings.size(),evidence.events.data(),evidence.events.size()};
    return output;
}
tpmshx_preparation_case_3d_v1 view(Owner3D& owner,const tpmshx_preparation_case_input_3d_v1& source) {
    tpmshx_preparation_case_3d_v1 output{};output.abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;output.struct_size=sizeof(output);
    const auto& value=owner.value;output.input=source;output.input.sco2_nu=nu_view(value.input.sco2_nu);
    output.options={TPMSHX_PREPARATION_CASE_ABI_VERSION,sizeof(output.options),value.options.chi_override?1u:0u,
        value.options.allow_extrapolation?1u:0u,value.options.chi_override.value_or(0.)};
    for (std::size_t i=0;i<3;++i) {
        output.input.lengths_m[i]=value.input.grid.lengths[i];
        output.widths[i]=array(value.widths[i]);output.edges[i]=array(value.edges[i]);
    }
    output.geometry=geometry_view(value.uniform_geometry.geometry);
    output.uniform_solid_conductivity=value.uniform_geometry.solid_conductivity;
    output.cell_length=array(value.cell_length);output.wall_thickness=array(value.wall_thickness);
    output.total_porosity=array(value.total_porosity);output.side_porosity=array(value.side_porosity);
    output.permeability=array(value.permeability);output.forchheimer=array(value.forchheimer);
    output.solid_conductivity=array(value.solid_conductivity);
    for (std::size_t i=0;i<2;++i) {
        output.input.sides[i].port=port_view(value.input.sides[i].port);
        const auto& side=value.sides[i];auto& target=output.sides[i];
        std::copy(side.axes.begin(),side.axes.end(),target.axes);
        target.inlet_opening=array(side.openings[0]);target.outlet_opening=array(side.openings[1]);
        target.rho=side.properties[0];target.mu=side.properties[1];target.cp=side.properties[2];target.k_f=side.properties[3];
        target.have_drag_application=side.have_drag_application?1u:0u;
        const auto& drag=side.drag_evidence;
        target.drag_evidence={drag.base_permeability,drag.base_forchheimer,drag.applied_permeability,
            drag.applied_forchheimer,drag.scale_permeability,drag.scale_forchheimer,text(drag.campaign),text(drag.scope)};
        target.drag_selection.have_selection=drag.selection?1u:0u;if(drag.selection)target.drag_selection.selection=*drag.selection;
        target.drag_selection.application_scope=text(drag.application_scope);target.drag_selection.fluid=text(drag.fluid);
        target.drag_selection.calibration=owner.calibration[i].data();target.drag_selection.calibration_count=owner.calibration[i].size();
    }
    for (std::size_t i=0;i<4;++i) {
        const auto& model=value.evidence.models[i];output.models[i]={text(model.name),text(model.version),text(model.side)};
    }
    output.evidence={owner.evidence.ranges.data(),owner.evidence.ranges.size(),owner.evidence.range_bounds_list.data(),
        owner.evidence.warnings.data(),owner.evidence.warnings.size(),owner.evidence.events.data(),owner.evidence.events.size()};
    model_view(value,output);output.notices=owner.notices.data();output.notice_count=owner.notices.size();
    return output;
}

template<class Source,class Result,class Function> int boundary_3d(
    const Source* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,Result* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity,Function function) {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,capacity)) return TPMSHX_PREPARATION_INVALID;
    const FlowOutputStorage storage{reinterpret_cast<const unsigned char*>(result),
        result?sizeof(*result):0,failure,error,capacity};
    try {
        require_buffer(source,source?1:0);require_buffer(result,result?1:0);require_buffer(failure,failure?1:0);
        require_buffer(selected,selected?1:0);require_buffer(callbacks,callbacks?1:0);
        require_disjoint(error,capacity,source,source?1:0);require_disjoint(error,capacity,result,result?1:0);
        require_disjoint(error,capacity,selected,selected?1:0);require_disjoint(error,capacity,callbacks,callbacks?1:0);
        require_disjoint(error,capacity,failure,failure?1:0);
        require_disjoint(source,source?1:0,result,result?1:0);require_disjoint(source,source?1:0,failure,failure?1:0);
        require_disjoint(result,result?1:0,failure,failure?1:0);
        require_disjoint(selected,selected?1:0,result,result?1:0);require_disjoint(selected,selected?1:0,failure,failure?1:0);
        require_disjoint(callbacks,callbacks?1:0,result,result?1:0);require_disjoint(callbacks,callbacks?1:0,failure,failure?1:0);
        if (result && result->owner) storage.owned(*result);
        if constexpr (std::is_same_v<Source,tpmshx_preparation_3d_continuous_input_v1>) {
            if (source) {
                const auto values=source->controls.decision_mm;
                require_buffer(values.data,values.size);require_disjoint(error,capacity,values.data,values.size);
                require_disjoint(values.data,values.size,result,result?1:0);
                require_disjoint(values.data,values.size,failure,failure?1:0);
            }
        }
        if constexpr (std::is_same_v<Source,tpmshx_preparation_3d_spatial_input_v1>) {
            if (source) {
                require_buffer(source->cells,source->cell_count);
                require_disjoint(error,capacity,source->cells,source->cell_count);
                require_disjoint(source->cells,source->cell_count,result,result?1:0);
                require_disjoint(source->cells,source->cell_count,failure,failure?1:0);
            }
        }
        if (source) for (const auto value:{source->input.sco2_nu.parameter_version,source->input.sco2_nu.source,source->input.sco2_nu.applicability}) {
            require_buffer(value.data,value.size);require_disjoint(error,capacity,value.data,value.size);
            require_disjoint(value.data,value.size,result,result?1:0);require_disjoint(value.data,value.size,failure,failure?1:0);
        }
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    FlowCallbackContext context{callbacks,storage};
    tpmshx_preparation_case_failure_v2 staged_failure{};
    bool failure_ready=false;std::exception_ptr saved_exception;
    try {
        version(source);version(&source->input);version(result);
        failure_version(failure);
        if (selected) version(selected);
        validate_callbacks(callbacks,CallbackMode::three_d);
        staged_failure.abi_version=TPMSHX_PREPARATION_FAILURE_ABI_VERSION;
        staged_failure.struct_size=sizeof(staged_failure);staged_failure.side=2;failure_ready=true;
        try {
            if (result->owner) throw std::invalid_argument("release the previous prepared case before reusing its result");
            const auto sink=make_sink(callbacks,context);
            function(input(*source),options(selected),sink);
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
            if (problem.cause_offset!=std::string::npos) {
                staged_failure.cause_count=1;staged_failure.causes[0].kind=1;
                tpmshx::fields::c_api::message(staged_failure.causes[0].message,sizeof(staged_failure.causes[0].message),
                    problem.what()+problem.cause_offset);
            }
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

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_collect_range_v1(
    tpmshx_preparation_array_v1 values,double lower,double upper,tpmshx_preparation_range_sample_v1* output,
    char* error,size_t capacity) {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,capacity)) return TPMSHX_PREPARATION_INVALID;
    try {
        require_disjoint(error,capacity,values.data,values.size);
        require_disjoint(error,capacity,output,1);
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    return p::c_api::boundary(error,capacity,[&] {
        require_disjoint(values.data,values.size,output,1);
        std::fenv_t environment;
        std::fegetenv(&environment);
        const auto sample=tpmshx::detail::collect_range<tpmshx_preparation_range_sample_v1>(values.size,
            [&](std::size_t index) {return values.data[index];},lower,upper);
        std::fesetenv(&environment);
        *output=sample;
    });
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_query_inlet_properties_v2(
    const tpmshx_preparation_inlet_query_input_v1* source,
    const tpmshx_preparation_callbacks_v2* callbacks,
    tpmshx_preparation_inlet_query_result_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,capacity)) return TPMSHX_PREPARATION_INVALID;
    const FlowOutputStorage storage{reinterpret_cast<const unsigned char*>(result),result?sizeof(*result):0,failure,error,capacity};
    try {
        require_buffer(result,result?1:0);require_buffer(failure,failure?1:0);
        storage.borrowed(source,source?1:0);storage.borrowed(callbacks,callbacks?1:0);
        require_disjoint(result,result?1:0,failure,failure?1:0);
        require_disjoint(result,result?1:0,error,capacity);require_disjoint(failure,failure?1:0,error,capacity);
        if (source) for (const auto text:{source->inlet.sco2_nu.parameter_version,
                source->inlet.sco2_nu.source,source->inlet.sco2_nu.applicability}) storage.borrowed(text);
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    FlowCallbackContext context{callbacks,storage};
    tpmshx_preparation_case_failure_v2 staged_failure{};
    tpmshx_preparation_inlet_query_result_v1 staged_result{};
    bool failure_ready=false;std::exception_ptr saved_exception;
    try {
        version(source);version(result);failure_version(failure);
        validate_callbacks(callbacks,CallbackMode::inlet_query);
        staged_failure.abi_version=TPMSHX_PREPARATION_FAILURE_ABI_VERSION;
        staged_failure.struct_size=sizeof(staged_failure);
        staged_failure.side=2;failure_ready=true;
        try {
            const auto& key=source->inlet;
            flag(key.have_sco2_nu);flag(key.co2_geometry);flag(source->exact_co2_drag);
            p::InletPropertyQuery request;
            request.inlet.geometry={static_cast<tpmshx::Topology>(key.geometry.topology),
                key.geometry.cell_length_mm,key.geometry.wall_thickness_mm};
            request.inlet.fluid=static_cast<tpmshx::Fluid>(key.fluid);
            request.inlet.velocity_m_s=key.velocity_m_s;request.inlet.temperature_K=key.temperature_K;
            request.inlet.pressure_Pa=key.pressure_Pa;
            request.inlet.co2_geometry=key.co2_geometry!=0;
            if (key.have_sco2_nu) request.inlet.sco2_nu=nu_input(key.sco2_nu);
            request.hydraulic_diameter_m=source->hydraulic_diameter_m;request.epsilon_a=source->epsilon_a;
            request.exact_co2_drag=source->exact_co2_drag!=0;
            const auto sink=make_sink(callbacks,context);
            const auto values=p::query_inlet_properties(request,sink);
            staged_result.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;staged_result.struct_size=sizeof(staged_result);
            for (std::size_t i=0;i<values.size();++i) staged_result.values[i]=values[i];
        } catch (const p::PropertyError& problem) {
            const auto& value=problem.failure;staged_failure.kind=problem.status==3?3u:1u;staged_failure.have_property=1;
            staged_failure.property={value.reason,value.input,value.index,value.first_t_index,value.first_p_index,
                value.temperature,value.pressure,value.detail,value.fp};
            throw p::c_api::StateError(problem.status,problem.what());
        } catch (const std::invalid_argument&) {staged_failure.kind=1;throw;}
        catch (...) {staged_failure.kind=3;throw;}
    } catch (...) {saved_exception=std::current_exception();}
    return p::c_api::boundary(error,capacity,[&] {
        if (failure_ready) *failure=staged_failure;
        if (saved_exception) std::rethrow_exception(saved_exception);
        *result=staged_result;
    });
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_lut_create_v7(
    uint32_t topology,size_t cell_nodes,size_t wall_nodes,size_t resolution,
    tpmshx_preparation_sigmoid_lut_v7* result,char* error,size_t capacity) {
    if (!tpmshx::fields::c_api::error_buffer_valid(error,capacity)) return TPMSHX_PREPARATION_INVALID;
    const FlowOutputStorage storage{reinterpret_cast<const unsigned char*>(result),
        result?sizeof(*result):0,nullptr,error,capacity};
    try {
        require_buffer(result,result?1:0);
        if (result && result->owner) storage.owned(*result);
        require_disjoint(error,capacity,result,result?1:0);
    } catch (...) {return TPMSHX_PREPARATION_INVALID;}
    return p::c_api::boundary(error,capacity,[&] {
        version(result);
        if (result->owner) throw std::invalid_argument("release the previous sigmoid LUT before reusing its result");
        auto owner=std::make_unique<p::SigmoidLUT2D>(p::build_sigmoid_lut_2d(
            static_cast<tpmshx::Topology>(topology),cell_nodes,wall_nodes,resolution));
        tpmshx_preparation_sigmoid_lut_v7 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        output.cell_mm=array(owner->cell_mm);output.wall_mm=array(owner->wall_mm);
        output.porosity=array(owner->porosity);output.area_density_per_m=array(owner->area_density);
        output.porosity_fast=owner->porosity_fast;output.area_fast=owner->area_fast;
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_sigmoid_lut_release_v7(tpmshx_preparation_sigmoid_lut_v7* result) {
    if (!result) return;
    delete static_cast<p::SigmoidLUT2D*>(result->owner);*result={};
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_capacities_v1(
    const tpmshx_preparation_2d_uniform_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_uniform_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        if (request.explicit_targets) throw std::invalid_argument("capacity query does not accept explicit targets");
        auto owner=std::make_unique<FlowOwner>(p::prepare_inlet_mass_capacities_2d(request.input,options,sink));
        tpmshx_preparation_2d_uniform_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(*owner,source->input);output.owner=owner.get();
        *result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_resolve_flow_v1(
    const tpmshx_preparation_2d_uniform_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_uniform_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowOwner>(p::resolve_inlet_flow_2d(request,options,sink));
        tpmshx_preparation_2d_uniform_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(*owner,source->input);output.owner=owner.get();
        *result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_prepare_case_v1(
    const tpmshx_preparation_2d_uniform_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_uniform_case_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowCaseOwner>(p::prepare_flow_case_2d(request,options,sink));
        tpmshx_preparation_2d_uniform_case_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        const auto resolved=resolved_input(owner->prepared.value.input,source->input);
        output.prepared=view(owner->prepared,resolved);
        output.flow=flow_view(owner->flow,source->input);
        output.thermal=thermal_sides(owner->prepared.value);
        output.owner=owner.get();*result=output;owner.release();
    },true);
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_flow_release_v1(tpmshx_preparation_2d_uniform_flow_v1* result) {
    if (!result) return;
    delete static_cast<FlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_uniform_case_release_v1(tpmshx_preparation_2d_uniform_case_v1* result) {
    if (!result) return;
    delete static_cast<FlowCaseOwner*>(result->owner);*result={};
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_capacities_v1(
    const tpmshx_preparation_2d_continuous_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_continuous_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        if (request.explicit_targets) throw std::invalid_argument("capacity query does not accept explicit targets");
        auto owner=std::make_unique<FlowOwner>(p::prepare_inlet_mass_capacities_2d(request.input,options,sink));
        tpmshx_preparation_2d_continuous_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(*owner,source->input);output.controls=controls_view(owner->value.input);
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_resolve_flow_v1(
    const tpmshx_preparation_2d_continuous_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_continuous_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowOwner>(p::resolve_inlet_flow_2d(request,options,sink));
        tpmshx_preparation_2d_continuous_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(*owner,source->input);output.controls=controls_view(owner->value.input);
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_prepare_case_v1(
    const tpmshx_preparation_2d_continuous_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_continuous_case_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowCaseOwner>(p::prepare_flow_case_2d(request,options,sink));
        tpmshx_preparation_2d_continuous_case_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        const auto& prepared=owner->prepared.value;
        output.prepared=view(owner->prepared,resolved_input(prepared.input,source->input));
        output.flow=flow_view(owner->flow,source->input);
        output.controls=controls_view(prepared.input);
        output.area_density_per_m=array(prepared.area_density);
        output.hydraulic_diameter_m=array(prepared.hydraulic_diameter);
        output.design_pore_porosity=array(prepared.design_pore_porosity);
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
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_flow_release_v1(
    tpmshx_preparation_2d_continuous_flow_v1* result) {
    if (!result) return;
    delete static_cast<FlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_continuous_case_release_v1(
    tpmshx_preparation_2d_continuous_case_v1* result) {
    if (!result) return;
    delete static_cast<FlowCaseOwner*>(result->owner);*result={};
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_capacities_v1(
    const tpmshx_preparation_2d_zoned_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_zoned_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowOwner>(p::prepare_zoned_inlet_mass_capacities_2d(request.input,options,sink));
        tpmshx_preparation_2d_zoned_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(owner->flow,source->input);
        output.kind=owner->input.kind;output.axis=owner->input.axis;
        output.regions=owner->regions.data();output.region_count=owner->regions.size();
        output.model=spatial_model(*owner->input.spatial_model);
        output.owner=owner.get();*result=output;owner.release();
    },true);
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_resolve_flow_v1(
    const tpmshx_preparation_2d_zoned_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_zoned_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowOwner>(p::resolve_zoned_inlet_flow_2d(request,options,sink));
        tpmshx_preparation_2d_zoned_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(owner->flow,source->input);
        output.kind=owner->input.kind;output.axis=owner->input.axis;
        output.regions=owner->regions.data();output.region_count=owner->regions.size();
        output.model=spatial_model(*owner->input.spatial_model);
        output.owner=owner.get();*result=output;owner.release();
    },true);
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_prepare_case_v1(
    const tpmshx_preparation_2d_zoned_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_zoned_case_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowCaseOwner>(p::prepare_zoned_flow_case_2d(request,options,sink));
        tpmshx_preparation_2d_zoned_case_v1 output{};
        fill_spatial_case_common(output,*owner,source->input);
        *result=output;owner.release();
    },true);
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_flow_release_v1(tpmshx_preparation_2d_zoned_flow_v1* result) {
    if (!result) return;
    delete static_cast<ZonedFlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_zoned_case_release_v1(tpmshx_preparation_2d_zoned_case_v1* result) {
    if (!result) return;
    delete static_cast<ZonedFlowCaseOwner*>(result->owner);*result={};
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_capacities_v1(
    const tpmshx_preparation_2d_sigmoid_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_sigmoid_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowOwner>(p::prepare_zoned_inlet_mass_capacities_2d(request.input,options,sink));
        tpmshx_preparation_2d_sigmoid_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(owner->flow,source->input);
        output.kind=owner->input.kind;output.axis=owner->input.axis;
        output.regions=owner->regions.data();output.region_count=owner->regions.size();
        output.controls=sigmoid_controls_view(owner->input.sigmoid->controls);
        output.lut=sigmoid_lut_view(owner->input.sigmoid->lut);
        output.model=spatial_model(*owner->input.spatial_model);
        output.owner=owner.get();*result=output;owner.release();
    },true);
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_resolve_flow_v1(
    const tpmshx_preparation_2d_sigmoid_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_sigmoid_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowOwner>(p::resolve_zoned_inlet_flow_2d(request,options,sink));
        tpmshx_preparation_2d_sigmoid_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(owner->flow,source->input);
        output.kind=owner->input.kind;output.axis=owner->input.axis;
        output.regions=owner->regions.data();output.region_count=owner->regions.size();
        output.controls=sigmoid_controls_view(owner->input.sigmoid->controls);
        output.lut=sigmoid_lut_view(owner->input.sigmoid->lut);
        output.model=spatial_model(*owner->input.spatial_model);
        output.owner=owner.get();*result=output;owner.release();
    },true);
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_prepare_case_v1(
    const tpmshx_preparation_2d_sigmoid_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_sigmoid_case_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<ZonedFlowCaseOwner>(p::prepare_zoned_flow_case_2d(request,options,sink));
        tpmshx_preparation_2d_sigmoid_case_v1 output{};
        fill_spatial_case_common(output,*owner,source->input);
        output.controls=sigmoid_controls_view(*owner->prepared.value.sigmoid);
        output.lut=sigmoid_lut_view(owner->flow.input.sigmoid->lut);
        *result=output;owner.release();
    },true);
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_flow_release_v1(tpmshx_preparation_2d_sigmoid_flow_v1* result) {
    if (!result) return;
    delete static_cast<ZonedFlowOwner*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_sigmoid_case_release_v1(tpmshx_preparation_2d_sigmoid_case_v1* result) {
    if (!result) return;
    delete static_cast<ZonedFlowCaseOwner*>(result->owner);*result={};
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_stripe_prepare_case_v1(
    const tpmshx_preparation_2d_zoned_input_v1* source,
    const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_2d_stripe_case_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return flow_boundary(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        if (request.input.kind!=0) throw std::invalid_argument("preparation requires stripe regions");
        auto owner=std::make_unique<ZonedFlowCaseOwner>(p::prepare_zoned_flow_case_2d(request,options,sink));
        const auto& regions=owner->prepared.value.regions;
        auto& radii=owner->region_hydraulic_radii_m;
        radii.reserve(regions.size());
        for (const auto& zone:regions) radii.push_back(tpmshx::geometry::hydraulic_radius(zone.property_geometry[0].hydraulic_diameter));
        tpmshx_preparation_2d_stripe_case_v1 output{};
        fill_spatial_case_common(output,*owner,source->input);
        output.region_hydraulic_radii_m=array(radii);
        *result=output;owner.release();
    },true);
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_2d_stripe_case_release_v1(tpmshx_preparation_2d_stripe_case_v1* result) {
    if (!result) return;
    delete static_cast<ZonedFlowCaseOwner*>(result->owner);*result={};
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_capacities_v1(
    const tpmshx_preparation_3d_continuous_input_v1* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_3d_continuous_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return boundary_3d(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowOwner3D>(p::prepare_inlet_mass_capacities_3d(request.input,options,sink));
        tpmshx_preparation_3d_continuous_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(*owner,source->input);
        output.controls=controls_view(owner->value.input);output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_resolve_flow_v1(
    const tpmshx_preparation_3d_continuous_input_v1* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_3d_continuous_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return boundary_3d(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowOwner3D>(p::resolve_inlet_flow_3d(request,options,sink));
        tpmshx_preparation_3d_continuous_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(*owner,source->input);
        output.controls=controls_view(owner->value.input);output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_prepare_case_v1(
    const tpmshx_preparation_3d_continuous_input_v1* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_3d_continuous_case_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return boundary_3d(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowCaseOwner3D>(p::prepare_flow_case_3d(request,options,sink));
        tpmshx_preparation_3d_continuous_case_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;output.struct_size=sizeof(output);
        const auto& prepared=owner->prepared.value;
        output.prepared=view(owner->prepared,resolved_input(prepared.input,source->input));
        output.flow=flow_view(owner->flow,source->input);
        output.controls=controls_view(prepared.input);output.area_density_per_m=array(prepared.area_density);
        output.hydraulic_diameter_m=array(prepared.hydraulic_diameter);output.thermal_porosity=array(prepared.thermal_porosity);
        for (std::size_t i=0;i<2;++i) {
            const auto& evidence=prepared.sides[i].drag_evidence;auto& drag=output.drag[i];
            drag.transfer_policy=text(evidence.transfer_policy);drag.geometry_application=text(evidence.geometry_application);
            drag.have_reference_geometry=evidence.reference_geometry_mm?1u:0u;
            if (evidence.reference_geometry_mm) std::copy_n(evidence.reference_geometry_mm->begin(),2,drag.reference_geometry_mm);
        }
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_flow_release_v1(
    tpmshx_preparation_3d_continuous_flow_v1* result) {
    if (!result) return;
    delete static_cast<FlowOwner3D*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_continuous_case_release_v1(
    tpmshx_preparation_3d_continuous_case_v1* result) {
    if (!result) return;
    delete static_cast<FlowCaseOwner3D*>(result->owner);*result={};
}

extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_capacities_v1(
    const tpmshx_preparation_3d_spatial_input_v1* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_3d_spatial_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return boundary_3d(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowOwner3D>(p::prepare_inlet_mass_capacities_3d(
            request.input,options,sink,p::CaseScope3D::spatial_v4));
        tpmshx_preparation_3d_spatial_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(*owner,source->input);
        output.cells=owner->cells.data();output.cell_count=owner->cells.size();
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_resolve_flow_v1(
    const tpmshx_preparation_3d_spatial_input_v1* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_3d_spatial_flow_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return boundary_3d(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowOwner3D>(p::resolve_inlet_flow_3d(
            request,options,sink,p::CaseScope3D::spatial_v4));
        tpmshx_preparation_3d_spatial_flow_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;output.struct_size=sizeof(output);
        output.flow=flow_view(*owner,source->input);
        output.cells=owner->cells.data();output.cell_count=owner->cells.size();
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" int TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_prepare_case_v1(
    const tpmshx_preparation_3d_spatial_input_v1* source,const tpmshx_preparation_case_options_v1* selected,
    const tpmshx_preparation_callbacks_v2* callbacks,tpmshx_preparation_3d_spatial_case_v1* result,
    tpmshx_preparation_case_failure_v2* failure,char* error,size_t capacity) {
    return boundary_3d(source,selected,callbacks,result,failure,error,capacity,[&](const auto& request,const auto& options,const auto& sink) {
        auto owner=std::make_unique<FlowCaseOwner3D>(p::prepare_flow_case_3d(
            request,options,sink,p::CaseScope3D::spatial_v4));
        tpmshx_preparation_3d_spatial_case_v1 output{};
        output.abi_version=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION;output.struct_size=sizeof(output);
        const auto& prepared=owner->prepared.value;
        output.prepared=view(owner->prepared,resolved_input(prepared.input,source->input));
        output.flow=flow_view(owner->flow,source->input);
        output.cells=owner->prepared.cells.data();output.cell_count=owner->prepared.cells.size();
        output.side_b_porosity=array(prepared.side_b_porosity.empty()?prepared.side_porosity:prepared.side_b_porosity);
        output.area_density_per_m=array(prepared.area_density);output.hydraulic_diameter_m=array(prepared.hydraulic_diameter);
        output.thermal_porosity=array(prepared.thermal_porosity);output.split_a=prepared.thermal_sides.split_a;
        output.have_side_geometry=prepared.thermal_sides.sides?1u:0u;
        if (prepared.thermal_sides.sides) for (std::size_t i=0;i<2;++i) {
            const auto& side=(*prepared.thermal_sides.sides)[i];
            output.side_geometry[i][0]=side.area;output.side_geometry[i][1]=side.diameter;
            output.side_geometry[i][2]=side.reference_area;output.side_geometry[i][3]=side.reference_diameter;
        }
        output.owner=owner.get();*result=output;owner.release();
    });
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_flow_release_v1(
    tpmshx_preparation_3d_spatial_flow_v1* result) {
    if (!result) return;
    delete static_cast<FlowOwner3D*>(result->owner);*result={};
}
extern "C" void TPMSHX_PREPARATION_CALL tpmshx_preparation_3d_spatial_case_release_v1(
    tpmshx_preparation_3d_spatial_case_v1* result) {
    if (!result) return;
    delete static_cast<FlowCaseOwner3D*>(result->owner);*result={};
}
