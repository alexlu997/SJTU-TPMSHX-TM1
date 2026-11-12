#include "tpmshx/stage_run_3d_c_api.h"
#include "stage_capture_3d.hpp"
#include "field_c_boundary.hpp"
#include "tpmshx/grid.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

namespace {
namespace boundary=tpmshx::fields::c_api;
namespace grid=tpmshx::grid;
bool overlaps(const void* a,size_t a_bytes,const void* b,size_t b_bytes) {
    if(!a_bytes || !b_bytes)return false;
    const auto first=reinterpret_cast<uintptr_t>(a),second=reinterpret_cast<uintptr_t>(b);
    return first<=second+b_bytes-1 && second<=first+a_bytes-1;
}
void flag(uint32_t value) {
    if(value>1)throw std::invalid_argument("3D stage option flags require 0 or 1");
}
size_t count(tpmshx_stage_size_option_v1 option,size_t fallback) {
    flag(option.present);return option.present?option.value:fallback;
}
double number(tpmshx_stage_double_option_v1 option,double fallback) {
    flag(option.present);return option.present?option.value:fallback;
}
uint32_t choice(tpmshx_stage_uint_option_v1 option,uint32_t fallback,uint32_t maximum=1) {
    flag(option.present);
    if(option.present && option.value>maximum)throw std::invalid_argument("invalid 3D stage resolved mode");
    return option.present?option.value:fallback;
}
struct Storage {
    const void* output;
    size_t output_size;
    char* error;
    size_t capacity;
    template<class T> void operator()(const T* value,size_t count) const {
        boundary::require_buffer(value,count);
        const auto bytes=boundary::product(count,sizeof(T));
        if(overlaps(value,bytes,error,capacity))
            throw std::invalid_argument("3D stage error storage overlaps input");
        if(overlaps(value,bytes,output,output_size))
            throw std::invalid_argument("3D stage output storage overlaps input");
    }
    void text(tpmshx_preparation_text_v1 value) const {(*this)(value.data,value.size);}
    void text(const char* value) const {
        if(value) {(*this)(value,1);(*this)(value,std::strlen(value)+1);}
    }
};
void evidence_storage(const Storage& storage,const tpmshx_preparation_flow_evidence_v3& evidence) {
    storage(evidence.ranges,evidence.range_count);
    if(evidence.range_bounds_list)storage(evidence.range_bounds_list,evidence.range_count);
    for(size_t i=0;i<evidence.range_count;++i) {
        const auto& range=evidence.ranges[i];storage(range.source,range.source_count);storage(range.shape,range.rank);
        for(size_t j=0;j<range.source_count;++j)storage.text(range.source[j]);
        for(const auto text:{range.side,range.stage,range.layout,range.label,range.quantity,range.unit})storage.text(text);
    }
    storage(evidence.warnings,evidence.warning_count);
    for(size_t i=0;i<evidence.warning_count;++i)storage.text(evidence.warnings[i]);
    storage(evidence.events,evidence.event_count);
    for(size_t i=0;i<evidence.event_count;++i) {
        storage.text(evidence.events[i].logger);storage.text(evidence.events[i].message);
    }
}
void notices_storage(const Storage& storage,const tpmshx_preparation_text_v1* notices,size_t count) {
    storage(notices,count);
    for(size_t i=0;i<count;++i)storage.text(notices[i]);
}
void input_storage(const Storage& storage,const tpmshx_full3d_input_v1* input) {
    storage(input,1);
    for(const auto value:input->widths)storage(value.data,value.size);
    for(const auto value:{input->epsilon,input->epsilon_a,input->epsilon_b,input->permeability,input->forchheimer,
            input->solid_conductivity,input->cell_length,input->area_density,input->hydraulic_diameter})
        storage(value.data,value.size);
    for(const auto& side:input->sides)
        for(const auto value:{side.inlet_opening,side.outlet_opening})storage(value.data,value.size);
    for(const auto value:input->sources)storage(value.data,value.size);
}
void saved_storage(const Storage& storage,const tpmshx_stage_saved_case_3d_v1* saved) {
    storage(saved,1);
    if(saved->abi_version!=TPMSHX_STAGE_RUN_3D_ABI_VERSION || saved->struct_size!=sizeof(*saved))
        throw std::invalid_argument("saved 3D stage ABI version or struct size is invalid");
    input_storage(storage,saved->input);storage(saved->wall_thickness_m.data,saved->wall_thickness_m.size);
    evidence_storage(storage,saved->preparation);notices_storage(storage,saved->notices,saved->notice_count);
    flag(saved->inlet_recorded);
    if(saved->range_captured) {
        storage(saved->range_captured,saved->preparation.range_count);
        for(size_t i=0;i<saved->preparation.range_count;++i)flag(saved->range_captured[i]);
    }
}
struct Prepared {
    const tpmshx_preparation_case_3d_v1* uniform=nullptr;
    const tpmshx_preparation_continuous_case_3d_v3* continuous=nullptr;
    const tpmshx_preparation_spatial_case_3d_v4* spatial=nullptr;
    const tpmshx_stage_saved_case_3d_v1* saved=nullptr;
};
const tpmshx_preparation_case_3d_v1* prepared_storage(const Storage& storage,const Prepared& source) {
    if(bool(source.uniform)+bool(source.continuous)+bool(source.spatial)+bool(source.saved)!=1)
        throw std::invalid_argument("3D stage requires exactly one prepared view");
    if(source.saved) {saved_storage(storage,source.saved);return nullptr;}
    const auto* prepared=source.uniform;
    if(source.continuous) {
        storage(source.continuous,1);
        const auto& p=*source.continuous;
        if(p.abi_version!=TPMSHX_PREPARATION_CONTINUOUS_3D_ABI_VERSION || p.struct_size!=sizeof(p))
            throw std::invalid_argument("continuous 3D stage ABI version or struct size is invalid");
        prepared=&p.prepared;
        storage(p.controls.decision_mm.data,p.controls.decision_mm.size);
        for(const auto value:{p.area_density_per_m,p.hydraulic_diameter_m,p.thermal_porosity})storage(value.data,value.size);
        evidence_storage(storage,p.flow.evidence);
    }
    if(source.spatial) {
        storage(source.spatial,1);
        const auto& p=*source.spatial;
        if(p.abi_version!=TPMSHX_PREPARATION_SPATIAL_3D_ABI_VERSION || p.struct_size!=sizeof(p))
            throw std::invalid_argument("spatial 3D stage ABI version or struct size is invalid");
        prepared=&p.prepared;storage(p.cells,p.cell_count);
        for(const auto value:{p.side_b_porosity,p.area_density_per_m,p.hydraulic_diameter_m,p.thermal_porosity})
            storage(value.data,value.size);
        evidence_storage(storage,p.flow.evidence);
    }
    storage(prepared,1);
    if(prepared->abi_version!=TPMSHX_PREPARATION_CASE_3D_ABI_VERSION || prepared->struct_size!=sizeof(*prepared))
        throw std::invalid_argument("prepared 3D stage ABI version or struct size is invalid");
    for(const auto value:prepared->widths)storage(value.data,value.size);
    for(const auto value:prepared->edges)storage(value.data,value.size);
    for(const auto value:{prepared->cell_length,prepared->wall_thickness,prepared->total_porosity,
            prepared->side_porosity,prepared->permeability,prepared->forchheimer,prepared->solid_conductivity})
        storage(value.data,value.size);
    for(const auto& side:prepared->sides) {
        for(const auto value:{side.inlet_opening,side.outlet_opening})storage(value.data,value.size);
        storage.text(side.drag_evidence.campaign);storage.text(side.drag_evidence.scope);
        storage.text(side.drag_selection.application_scope);storage.text(side.drag_selection.fluid);
        storage(side.drag_selection.calibration,side.drag_selection.calibration_count);
        for(size_t i=0;i<side.drag_selection.calibration_count;++i) {
            storage.text(side.drag_selection.calibration[i].key);storage.text(side.drag_selection.calibration[i].value);
        }
    }
    for(const auto& model:prepared->models) {
        storage.text(model.name);storage.text(model.version);storage.text(model.side);
    }
    const auto& nu=prepared->input.sco2_nu;
    for(const auto text:{nu.parameter_version,nu.source,nu.applicability,
            prepared->sco2_nu_model_version,prepared->sco2_nu_interpretation})storage.text(text);
    const auto& co2=prepared->co2;
    for(const auto text:{co2.version,co2.application_version,co2.pressure_model,
            co2.correction_source,co2.property_model,co2.common_geometry})storage.text(text);
    evidence_storage(storage,prepared->evidence);notices_storage(storage,prepared->notices,prepared->notice_count);
    return prepared;
}
void state_storage(const Storage& storage,const tpmshx_run_state_field_v1* fields,size_t count) {
    storage(fields,count);
    for(size_t i=0;i<count;++i) {
        const auto& field=fields[i];storage.text(field.name);
        if(field.type>TPMSHX_RUN_STATE_UTF8)throw std::invalid_argument("invalid 3D stage run state field type");
        storage(static_cast<const unsigned char*>(field.data),
            boundary::product(field.count,field.type<=TPMSHX_RUN_STATE_I64?8:1));
    }
}
const tpmshx_preparation_case_3d_v1* preflight(const Prepared& source,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    const Storage& storage,const tpmshx_run_state_field_v1* fields=nullptr,size_t count=0) {
    if(overlaps(storage.output,storage.output_size,storage.error,storage.capacity))
        throw std::invalid_argument("3D stage error storage overlaps output");
    const auto* prepared=prepared_storage(storage,source);
    storage(control,1);storage.text(control->result_id);storage.text(control->table_directory);
    if(request) {
        storage(request,1);
        if(request->abi_version!=TPMSHX_STAGE_RUN_3D_ABI_VERSION || request->struct_size!=sizeof(*request))
            throw std::invalid_argument("3D stage request ABI version or struct size is invalid");
        storage.text(request->convergence_mode);
        if(request->energy)storage(request->energy,1);
    }
    state_storage(storage,fields,count);return prepared;
}
tpmshx_full3d_array_v1 view(tpmshx_preparation_array_v1 array) {return {array.data,array.size};}
void extent(tpmshx_preparation_array_v1 array,size_t count) {
    if(array.size!=count)throw std::invalid_argument("prepared 3D stage array has the wrong extent");
}
grid::Port port(const tpmshx_grid_port_v1& source) {
    flag(source.active);grid::Port result{source.direction,source.active!=0,{}};
    for(size_t end=0;end<2;++end) {
        std::optional<grid::Scalar>* values[]{&result.ends[end].center,&result.ends[end].width,
            &result.ends[end].center2,&result.ends[end].width2};
        for(size_t i=0;i<4;++i) {
            flag(source.present[end][i]);
            if(source.present[end][i]) {
                const auto value=source.values[end][i];*values[i]=grid::Scalar{value.value,value.precision,value.strong};
            }
        }
    }
    return result;
}
grid::Scalar restored_mm(double value,const tpmshx_preparation_scalar_kind_v2& kind) {
    if(kind.layout>2)throw std::invalid_argument("prepared 3D scalar layout is invalid");
    const auto stored=grid::multiply({value,kind.precision,kind.strong},grid::weak(1e-3));
    return grid::multiply(stored,grid::weak(1e3));
}
struct Packed3D {
    tpmshx_full3d_input_v1 input{};
    tpmshx_stage_saved_case_3d_v1 saved{};
    std::array<std::vector<double>,2> thermal;
    bool refined=false;
    Packed3D(const Prepared& source,const tpmshx_preparation_case_3d_v1* prepared) {
        if(source.saved) {saved=*source.saved;input=*saved.input;saved.input=&input;return;}
        const auto& p=*prepared;
        if(p.input.topology>1)throw std::invalid_argument("invalid prepared 3D topology");
        const bool continuous=source.continuous!=nullptr,spatial=p.input.geometry_mode!=0;
        if((continuous && p.input.geometry_mode!=1)
            || (source.spatial && p.input.geometry_mode!=0 && p.input.geometry_mode!=2)
            || (!continuous && !source.spatial && (spatial || p.input.delta_levelset!=0.)))
            throw std::invalid_argument("3D stage preparation kind disagrees with its geometry");
        size_t cells=1;
        for(size_t axis=0;axis<3;++axis) {
            input.shape[axis]=p.widths[axis].size;input.widths[axis]=view(p.widths[axis]);
            cells=boundary::product(cells,input.shape[axis]);
        }
        if(!cells)throw std::invalid_argument("3D stage requires nonempty physical axes");
        for(const auto value:{p.total_porosity,p.side_porosity,p.permeability,p.forchheimer,
                p.solid_conductivity,p.cell_length,p.wall_thickness})extent(value,cells);
        input.epsilon=view(p.total_porosity);input.epsilon_a=view(p.side_porosity);
        input.epsilon_b=view(source.spatial?source.spatial->side_b_porosity:p.side_porosity);
        input.permeability=view(p.permeability);input.forchheimer=view(p.forchheimer);
        input.solid_conductivity=view(p.solid_conductivity);input.cell_length=view(p.cell_length);
        if(spatial) {
            const auto area=continuous?source.continuous->area_density_per_m:source.spatial->area_density_per_m;
            const auto diameter=continuous?source.continuous->hydraulic_diameter_m:source.spatial->hydraulic_diameter_m;
            extent(area,cells);extent(diameter,cells);input.area_density=view(area);input.hydraulic_diameter=view(diameter);
        } else {
            thermal[0].assign(cells,p.geometry.area_density_per_m);
            thermal[1].assign(cells,p.geometry.hydraulic_diameter_m);
            input.area_density={thermal[0].data(),cells};input.hydraulic_diameter={thermal[1].data(),cells};
        }
        const auto cell=restored_mm(p.input.cell_length_mm,p.input.kinds.cell_length);
        const auto wall=restored_mm(p.input.wall_thickness_mm,p.input.kinds.wall_thickness);
        input.reference_cell_length=grid::multiply(cell,grid::weak(1e-3)).value;
        input.reference_hydraulic_diameter=p.geometry.hydraulic_diameter_m;
        input.topology=p.input.topology;input.spatial=spatial?1:0;input.asymmetric=p.input.delta_levelset!=0.;input.solve_b=1;
        flag(p.input.port_wall_refine);refined=p.input.port_wall_refine!=0;
        if(source.spatial)flag(source.spatial->have_side_geometry);
        if(input.asymmetric && (!source.spatial || !source.spatial->have_side_geometry))
            throw std::invalid_argument("asymmetric 3D stage requires prepared side thermal geometry");
        for(size_t side=0;side<2;++side) {
            const auto& s=p.sides[side];const auto& inlet=p.input.sides[side];auto& target=input.sides[side];
            target.fluid=inlet.fluid;target.direction=static_cast<uint32_t>(inlet.port.direction);
            if(inlet.port.direction<0 || inlet.port.direction>5)
                throw std::invalid_argument("invalid prepared 3D direction");
            for(size_t axis=0;axis<3;++axis) {
                if(s.axes[axis]<0 || s.axes[axis]>2)throw std::invalid_argument("invalid prepared 3D axis");
                target.solver_axes[axis]=static_cast<uint32_t>(s.axes[axis]);
            }
            target.inlet_temperature=inlet.temperature_K;target.inlet_pressure=inlet.pressure_Pa;
            target.inlet_velocity=inlet.velocity_m_s;
            double depth=0.;const auto widths=p.widths[static_cast<size_t>(s.axes[2])];
            for(size_t i=0;i<widths.size;++i)depth+=widths.data[i];
            const auto rectangles=grid::rectangles(port(inlet.port),grid::weak(depth));
            for(size_t i=0;i<4;++i) {
                target.inlet_rectangle[i]=rectangles[i].value;target.outlet_rectangle[i]=rectangles[i+4].value;
                target.heat_transfer_geometry[i]=input.asymmetric?source.spatial->side_geometry[side][i]:1.;
            }
            target.inlet_opening=view(s.inlet_opening);target.outlet_opening=view(s.outlet_opening);
            flag(s.have_drag_application);
            target.permeability_scale=s.have_drag_application?s.drag_evidence.scale_permeability:1.;
            target.forchheimer_scale=s.have_drag_application?s.drag_evidence.scale_forchheimer:1.;
            if(p.input.sco2_nu.mode>1)throw std::invalid_argument("invalid prepared 3D Nu mode");
            target.sco2_nusselt_multiplier=p.input.sco2_nu.mode?p.input.sco2_nu.alpha[input.topology]:1.;
        }
        saved={TPMSHX_STAGE_RUN_3D_ABI_VERSION,sizeof(saved),&input,cell.value,wall.value,p.geometry.epsilon,
            p.wall_thickness,p.evidence,p.notices,p.notice_count,1,nullptr};
    }
};
struct Controls3D {
    tpmshx_full3d_control_v1 values{};
    tpmshx_energy_options_v2 energy{};
    const tpmshx_energy_options_v2* energy_pointer=nullptr;
    tpmshx_model_h_iteration_options_v1 model_h{};
    const tpmshx_model_h_iteration_options_v1* model_h_pointer=nullptr;
    Controls3D(const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1& host,
        const tpmshx_full3d_input_v1& input,bool refined) {
        const tpmshx_stage_run_request_3d_v1 empty{};const auto& r=request?*request:empty;
        const auto selected=r.energy?*r.energy:tpmshx_energy_options_v1{TPMSHX_ENERGY_TEMPERATURE_SOU,1e-8};
        tpmshx_energy_effective_settings_v1 defaults{};
        if(tpmshx_full_enthalpy_defaults_v1(3,selected.algorithm,
                input.sides[0].fluid==1 || input.sides[1].fluid==1,&defaults))
            throw std::invalid_argument("invalid native full enthalpy defaults request");
        flag(r.require_enthalpy_update_on_temperature);
        const bool strict=r.require_enthalpy_update_on_temperature || r.energy_coupled_tolerance.present
            || r.energy_equation_tolerance.present;
        model_h=r.model_h;
        if(model_h.max_iterations || model_h.temperature_tolerance || model_h.q_relative_tolerance) {
            if(strict || r.energy_iterations.present || r.energy_sweeps.present || r.energy_omega.present
                    || r.energy_update_tolerance.present)
                throw std::invalid_argument("model-h iteration controls cannot be combined with EOS controls");
            model_h_pointer=&model_h;
        }
        if(r.convergence_mode && std::strcmp(r.convergence_mode,"f2"))
            throw std::invalid_argument("convergence_mode must be 'f2'; the legacy mass/velocity exit has been retired");
        auto& c=values;
        c.max_outer=count(r.max_outer_ltne,12);c.initial_simple_iterations=count(r.max_iter_simple,2000);
        c.warm_simple_iterations=count(r.max_iter_simple,600);c.thermal_iterations=count(r.thermal_iterations,20000);
        c.outer_temperature_tolerance=number(r.outer_tol_K,.5);c.thermal_relaxation=number(r.thermal_relaxation,.7);
        c.pressure_shooting=choice(r.pressure_shooting,1);c.variable_rho_cp=choice(r.variable_rho_cp,1);
        c.conservative=choice(r.conservative,1);c.strict_mass_balance=choice(r.strict_mass_balance,1);
        c.force_cell_centered=choice(r.force_cell_centered,1);c.refined_port_energy=choice(r.refined_port_energy,refined?1:0);
        const auto cells=boundary::product(boundary::product(input.shape[0],input.shape[1]),input.shape[2]);
        const bool true_h=input.solve_b && (input.sides[0].fluid>=2 || input.sides[1].fluid>=2);
        c.red_black_energy=cells>30000 && !(selected.algorithm && true_h);
        c.sco2_local_pressure_a=choice(r.sco2_local_pressure_a,0);c.coarse_bootstrap=choice(r.coarse_bootstrap,0);
        c.coarse_iterations=count(r.coarse_iterations,200);c.roughness_mode=choice(r.roughness_mode,1,2);
        c.envelope_mode=choice(r.envelope_mode,0,2);c.roughness_height=number(r.roughness_height_m,100.*1e-6);
        flag(r.solid_seed_K.present);c.has_initial_solid_temperature=r.solid_seed_K.present;
        c.initial_solid_temperature=number(r.solid_seed_K,0.);
        c.simple={2000,1,100,number(r.simple_velocity_relaxation,.5),.2,.3,0.,287.05,.05,1,1,0,
            choice(r.adaptive_pressure_tolerance,1),choice(r.track_momentum,0),
            cells>=count(r.parallel_threshold,200000)?1u:0u,
            {number(r.mom_tol,1e-4),number(r.mass_local_tol,1e-6),number(r.mass_global_tol,1e-6),.01,1e-4,1e-3,2,5,60}};
        c.enthalpy_iterations=count(r.energy_iterations,defaults.max_iterations);
        c.enthalpy_sweeps=count(r.energy_sweeps,defaults.sweeps);c.enthalpy_omega=number(r.energy_omega,defaults.omega);
        c.enthalpy_update_tolerance=number(r.energy_update_tolerance,defaults.update_tolerance);
        c.table_directory=host.table_directory;
        energy={selected.algorithm,selected.temperature_update_tolerance,
            number(r.energy_coupled_tolerance,defaults.coupled_energy_tolerance),
            number(r.energy_equation_tolerance,defaults.equation_energy_tolerance),r.require_enthalpy_update_on_temperature};
        if((true_h || strict) && !model_h_pointer)energy_pointer=&energy;
        if(!host.cpu_threads || !host.result_id)
            throw std::invalid_argument("3D stage requires a positive CPU limit and result label");
    }
};
struct StageRun3D {
    Prepared source;
    std::unique_ptr<Packed3D> packed;
    tpmshx_full3d_control_v1 resolved;
    std::string result_id,table_directory;
    void* run=nullptr;
    StageRun3D(const Prepared& original,std::unique_ptr<Packed3D> p,const tpmshx_full3d_control_v1& controls,const char* id)
        :source(original),packed(std::move(p)),resolved(controls),result_id(id),table_directory(controls.table_directory?controls.table_directory:"") {
        resolved.table_directory=controls.table_directory?table_directory.c_str():nullptr;
    }
    ~StageRun3D() {tpmshx_full_3d_run_release_v1(&run);}
};
void lifecycle_storage(const StageRun3D* owner,const Storage& storage) {
    boundary::require_buffer(owner,1);
    if(overlaps(storage.output,storage.output_size,storage.error,storage.capacity))
        throw std::invalid_argument("3D stage error storage overlaps output");
    storage(owner,1);storage.text(owner->result_id.c_str());storage.text(owner->resolved.table_directory);
    if(owner->packed) {
        prepared_storage(storage,owner->source);
        saved_storage(storage,&owner->packed->saved);
    }
}
template<class Function> int guarded(char* error,size_t capacity,Function function) {
    if(!boundary::error_buffer_valid(error,capacity))return 1;
    bool report_safe=false;
    try {const int status=function(report_safe);if(!status)boundary::message(error,capacity,"");return status;}
    catch(const std::invalid_argument& failure) {if(report_safe)boundary::message(error,capacity,failure.what());return 1;}
    catch(const std::domain_error& failure) {if(report_safe)boundary::message(error,capacity,failure.what());return 3;}
    catch(const std::exception& failure) {if(report_safe)boundary::message(error,capacity,failure.what());return 4;}
    catch(...) {if(report_safe)boundary::message(error,capacity,"unknown native 3D stage failure");return 4;}
}
int create(const Prepared& source,const tpmshx_stage_run_request_3d_v1* request,
    const tpmshx_stage_run_control_3d_v1* control,const tpmshx_run_state_field_v1* fields,size_t count,
    bool restore,void** output,char* error,size_t capacity) {
    return guarded(error,capacity,[&](bool& report_safe) {
        boundary::require_buffer(output,1);
        const auto* prepared=preflight(source,request,control,{output,sizeof(*output),error,capacity},fields,count);
        report_safe=true;
        if(*output)throw std::invalid_argument("3D stage run output handle must be null");
        auto packed=std::make_unique<Packed3D>(source,prepared);
        Controls3D controls(request,*control,packed->input,packed->refined);
        auto owner=std::make_unique<StageRun3D>(source,std::move(packed),controls.values,control->result_id);
        const auto status=restore?tpmshx_full_3d_run_restore_v3(&owner->packed->input,&owner->resolved,
            controls.energy_pointer,controls.model_h_pointer,control->cpu_threads,&control->callbacks,fields,count,
            &owner->run,error,capacity):tpmshx_full_3d_run_create_v3(&owner->packed->input,&owner->resolved,
            controls.energy_pointer,controls.model_h_pointer,control->cpu_threads,&control->callbacks,&owner->run,error,capacity);
        if(status)return status;
        *output=owner.release();return 0;
    });
}
void empty_result(const tpmshx_stage_run_result_3d_v1& result) {
    if(result.abi_version!=TPMSHX_STAGE_RUN_3D_ABI_VERSION || result.struct_size!=sizeof(result) || result.owner)
        throw std::invalid_argument("3D stage result must be an initialized empty owner");
}
}
extern "C" {
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_create_v1(const tpmshx_preparation_case_3d_v1* uniform,
    const tpmshx_preparation_continuous_case_3d_v3* continuous,const tpmshx_preparation_spatial_case_3d_v4* spatial,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    void** output,char* error,size_t capacity) {
    return create({uniform,continuous,spatial,nullptr},request,control,nullptr,0,false,output,error,capacity);
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_restore_v1(const tpmshx_preparation_case_3d_v1* uniform,
    const tpmshx_preparation_continuous_case_3d_v3* continuous,const tpmshx_preparation_spatial_case_3d_v4* spatial,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    const tpmshx_run_state_field_v1* fields,size_t count,void** output,char* error,size_t capacity) {
    return create({uniform,continuous,spatial,nullptr},request,control,fields,count,true,output,error,capacity);
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_create_saved_v1(const tpmshx_stage_saved_case_3d_v1* saved,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    void** output,char* error,size_t capacity) {
    return create({nullptr,nullptr,nullptr,saved},request,control,nullptr,0,false,output,error,capacity);
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_restore_saved_v1(const tpmshx_stage_saved_case_3d_v1* saved,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    const tpmshx_run_state_field_v1* fields,size_t count,void** output,char* error,size_t capacity) {
    return create({nullptr,nullptr,nullptr,saved},request,control,fields,count,true,output,error,capacity);
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_advance_step_v1(void* run,uint32_t* phase,char* error,size_t capacity) {
    return guarded(error,capacity,[&](bool& report_safe) {
        boundary::require_buffer(phase,1);const auto* owner=static_cast<StageRun3D*>(run);
        lifecycle_storage(owner,{phase,sizeof(*phase),error,capacity});report_safe=true;
        return tpmshx_full_3d_run_advance_step_v1(owner->run,phase,error,capacity);
    });
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_phase_v1(const void* run,uint32_t* phase) {
    try {
        boundary::require_buffer(phase,1);const auto* owner=static_cast<const StageRun3D*>(run);
        lifecycle_storage(owner,{phase,sizeof(*phase),nullptr,0});
        return tpmshx_full_3d_run_phase_v1(owner->run,phase);
    } catch(...) {return 1;}
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_snapshot_v1(const void* run,tpmshx_run_state_v1* state,char* error,size_t capacity) {
    return guarded(error,capacity,[&](bool& report_safe) {
        boundary::require_buffer(state,1);const auto* owner=static_cast<const StageRun3D*>(run);
        lifecycle_storage(owner,{state,sizeof(*state),error,capacity});report_safe=true;
        return tpmshx_full_3d_run_snapshot_v1(owner->run,state,error,capacity);
    });
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_take_result_v1(void* run,tpmshx_stage_run_result_3d_v1* result,
    char* error,size_t capacity) {
    return guarded(error,capacity,[&](bool& report_safe) {
        boundary::require_buffer(result,1);
        auto* selected=static_cast<StageRun3D*>(run);
        lifecycle_storage(selected,{result,sizeof(*result),error,capacity});
        auto& owner=*selected;
        report_safe=true;empty_result(*result);
        if(!owner.packed)throw std::invalid_argument("3D stage result was already transferred");
        tpmshx_full3d_result_v1 raw{};
        const auto status=tpmshx_full_3d_run_take_result_v1(owner.run,&raw,error,capacity);
        if(status)return status;
        try {
            std::unique_ptr<tpmshx::stages::Capture3D,decltype(&tpmshx::stages::release_capture_3d)> captured(
                tpmshx::stages::capture_3d(owner.packed->saved,raw,owner.resolved,owner.result_id.c_str()),
                &tpmshx::stages::release_capture_3d);
            *result=tpmshx::stages::stage_view(*captured.release());owner.packed.reset();owner.source={};return 0;
        } catch(...) {tpmshx_full_3d_release_v1(&raw);throw;}
    });
}
void TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_release_run_v1(void** run) {
    if(run) {delete static_cast<StageRun3D*>(*run);*run=nullptr;}
}
void TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_release_v1(tpmshx_stage_run_result_3d_v1* result) {
    if(!result)return;
    tpmshx::stages::release_capture_3d(static_cast<tpmshx::stages::Capture3D*>(result->owner));*result={};
}
int TPMSHX_THERMAL_CALL tpmshx_run_case_3d_v1(const tpmshx_preparation_case_3d_v1* uniform,
    const tpmshx_preparation_continuous_case_3d_v3* continuous,const tpmshx_preparation_spatial_case_3d_v4* spatial,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    tpmshx_stage_run_result_3d_v1* result,char* error,size_t capacity) {
    return guarded(error,capacity,[&](bool& report_safe) {
        boundary::require_buffer(result,1);
        preflight({uniform,continuous,spatial,nullptr},request,control,{result,sizeof(*result),error,capacity});
        report_safe=true;empty_result(*result);
        void* raw_run=nullptr;
        const auto status=tpmshx_stage_run_3d_create_v1(uniform,continuous,spatial,request,control,&raw_run,error,capacity);
        if(status)return status;
        const auto release=[](StageRun3D* owner) {delete owner;};
        std::unique_ptr<StageRun3D,decltype(release)> run(static_cast<StageRun3D*>(raw_run),release);
        uint32_t phase=TPMSHX_FULL3D_CREATED;
        while(phase!=TPMSHX_FULL3D_COMPLETED && phase!=TPMSHX_FULL3D_CANCELLED) {
            const auto advanced=tpmshx_stage_run_3d_advance_step_v1(run.get(),&phase,error,capacity);
            if(advanced)return advanced;
        }
        return tpmshx_stage_run_3d_take_result_v1(run.get(),result,error,capacity);
    });
}
}
