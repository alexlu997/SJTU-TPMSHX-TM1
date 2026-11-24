#include "tpmshx/stage_run_3d_c_api.h"
#include "stage_entries.hpp"
#include "stage_capture_3d.hpp"
#include "stage_saved_models.hpp"
#include "../geometry/field_c_boundary.hpp"
#include "enthalpy_c_views.hpp"
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
void saved_storage(const Storage& storage,const tpmshx_stage_saved_case_3d_v3* saved) {
    storage(saved,1);
    if(saved->abi_version!=TPMSHX_STAGE_RUN_3D_SAVED_ABI_VERSION || saved->struct_size!=sizeof(*saved))
        throw std::invalid_argument("saved 3D stage v3 ABI version or struct size is invalid");
    input_storage(storage,saved->input);storage(saved->wall_thickness_m.data,saved->wall_thickness_m.size);
    evidence_storage(storage,saved->preparation);notices_storage(storage,saved->notices,saved->notice_count);
    flag(saved->inlet_recorded);
    if(saved->range_captured) {
        storage(saved->range_captured,saved->preparation.range_count);
        for(size_t i=0;i<saved->preparation.range_count;++i)flag(saved->range_captured[i]);
    }
    for(const auto& ref:saved->models){storage.text(ref.name);storage.text(ref.version);}
    for(const auto fluid:saved->resource_fluids)storage.text(fluid);
    storage.text(saved->resource_topology);
    for(const auto* nu:{&saved->sco2_nu,&saved->resource_nu[0],&saved->resource_nu[1]}) {
        storage.text(nu->parameter_version);storage.text(nu->source);storage.text(nu->applicability);
    }
    for(const auto& side:saved->axes)
        for(const auto width:side.widths)storage(width.data,width.size);
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
void preflight(const tpmshx_stage_saved_case_3d_v3* saved,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    const Storage& storage,const tpmshx_run_state_field_v1* fields=nullptr,size_t count=0) {
    if(overlaps(storage.output,storage.output_size,storage.error,storage.capacity))
        throw std::invalid_argument("3D stage error storage overlaps output");
    saved_storage(storage,saved);
    storage(control,1);storage.text(control->result_id);storage.text(control->table_directory);
    if(request) {
        storage(request,1);
        if(request->abi_version!=TPMSHX_STAGE_RUN_3D_ABI_VERSION || request->struct_size!=sizeof(*request))
            throw std::invalid_argument("3D stage request ABI version or struct size is invalid");
        storage.text(request->convergence_mode);
        if(request->energy)storage(request->energy,1);
    }
    state_storage(storage,fields,count);
}
tpmshx_full3d_array_v1 view(tpmshx_preparation_array_v1 array) {return {array.data,array.size};}
grid::Port port(const tpmshx_grid_port_v1& source) {
    flag(source.active);grid::Port result{source.direction,source.active!=0,{}};
    for(size_t end=0;end<2;++end) {
        std::optional<double>* values[]{&result.ends[end].center,&result.ends[end].width,
            &result.ends[end].center2,&result.ends[end].width2};
        for(size_t i=0;i<4;++i) {
            flag(source.present[end][i]);
            if(source.present[end][i])*values[i]=source.values[end][i];
        }
    }
    return result;
}
void validate_saved_3d(const tpmshx_stage_saved_case_3d_v3& saved,tpmshx_full3d_input_v1& input) {
    const auto cells=boundary::product(boundary::product(input.shape[0],input.shape[1]),input.shape[2]);
    if(!cells)throw std::invalid_argument("saved 3D grid requires positive counts");
    for(size_t axis=0;axis<3;++axis) {
        const auto widths=input.widths[axis];
        if(widths.size!=input.shape[axis])throw std::invalid_argument("prepared 3D count and grid disagree");
        double length=0.;
        for(size_t i=0;i<widths.size;++i) {
            if(!std::isfinite(widths.data[i]) || widths.data[i]<=0.)
                throw std::invalid_argument("invalid prepared grid widths");
            length+=widths.data[i];
        }
        const double target=saved.lengths_m[axis];
        if(!std::isfinite(target) || !std::isfinite(length) || std::abs(length-target)>1e-15+1e-12*std::abs(target))
            throw std::invalid_argument(std::string("prepared ")+"xyz"[axis]+" grid does not cover the physical domain");
    }
    tpmshx::stages::validate_saved_models(saved.models,saved.sco2_nu,saved.resource_nu,
        saved.resource_fluids,saved.resource_topology,{input.sides[0].fluid,input.sides[1].fluid},input.topology,true);
    for(size_t s=0;s<2;++s) {
        const auto& axes=saved.axes[s];auto& side=input.sides[s];
        const auto label=std::string("prepared fluid ")+(s?"B":"A");
        const auto direction=axes.port.direction;
        flag(axes.port.active);
        if(!axes.port.active && s && !input.solve_b)continue;
        if(!axes.port.active || direction<0 || direction>5 || side.direction!=static_cast<uint32_t>(direction)
            || side.solver_axes[1]!=static_cast<uint32_t>(direction/2))
            throw std::invalid_argument(label+" direction and axis map disagree");
        if(axes.reverse!=direction%2)throw std::invalid_argument(label+" reverse direction disagrees");
        for(size_t i=0;i<3;++i) {
            const auto axis=side.solver_axes[i];
            if(axis>2 || axes.solver_to_real[axis]!=static_cast<int32_t>(i))
                throw std::invalid_argument(label+" axis permutation disagrees with physical axes");
            const auto width=input.widths[axis];const auto copy=axes.widths[i];
            if(copy.size!=width.size || !std::equal(copy.data,copy.data+copy.size,width.data))
                throw std::invalid_argument(label+" axis widths disagree with grid");
            if(axes.counts[i]!=width.size)throw std::invalid_argument(label+" axis count disagrees with grid");
            if(axes.solver_counts[i]!=axes.counts[i] || axes.solver_lengths[i]!=axes.lengths[i]
                || axes.lengths[i]!=saved.lengths_m[axis])
                throw std::invalid_argument(label+" solver geometry and axis map disagree");
        }
        const auto cross1=axes.widths[0],cross2=axes.widths[2];
        const auto physical_port=port(axes.port);
        const auto plane_size=boundary::product(cross1.size,cross2.size);
        double depth=0.;for(size_t i=0;i<cross2.size;++i)depth+=cross2.data[i];
        const auto rectangles=grid::rectangles(physical_port,depth);
        for(size_t end=0;end<2;++end) {
            const auto mask=end?side.outlet_opening:side.inlet_opening;
            if(mask.size!=plane_size || !std::all_of(mask.data,mask.data+mask.size,
                    [](double x){return x>=0. && x<=1.;}))
                throw std::invalid_argument(std::string("invalid ")+label+" opening mask");
            auto* rect=end?side.outlet_rectangle:side.inlet_rectangle;
            for(size_t i=0;i<4;++i)rect[i]=rectangles[end*4+i];
        }
    }
    flag(saved.have_z_controls);
    if(saved.design_mode>2)throw std::invalid_argument("unsupported prepared 3D design mode");
    if(saved.design_mode==2 && !saved.have_z_controls)
        throw std::invalid_argument("continuous_xyz requires recorded 3D control inputs");
    const tpmshx_full3d_array_v1 fields[]{input.cell_length,view(saved.wall_thickness_m),input.epsilon,
        input.permeability,input.forchheimer,input.epsilon_a,input.epsilon_b,input.solid_conductivity};
    const char* names[]{"L_field_m","t_field_m","eps_arr","K_m2","cF_per_m","eps_A","eps_B","K_ss"};
    const double references[]{saved.nominal_cell_length_mm,saved.nominal_wall_thickness_mm,saved.nominal_porosity};
    for(size_t index=0;index<8;++index) {
        const auto field=fields[index];const std::string name=names[index];
        if(field.size!=cells && !(index==1 && field.size==1))throw std::invalid_argument("prepared design field "+name+" does not match the grid");
        const double expected=index<2?references[index]*1e-3:index==2?references[index]:0.;
        for(size_t i=0;i<field.size;++i) {
            const auto value=field.data[i];
            if(!std::isfinite(value) || value<=0.)throw std::invalid_argument("prepared design field "+name+" must be finite and positive");
            if((index==2 || index==5 || index==6) && value>=1.)
                throw std::invalid_argument("prepared porosity "+name+" must be below one");
            if(saved.design_mode==0 && index<3) {
                if(!std::isfinite(expected) || expected!=value)
                    throw std::invalid_argument("uniform design field "+name+" disagrees with scalar input");
            }
            if(saved.design_mode==0 && (index==3 || index==4) && value!=field.data[0])
                throw std::invalid_argument("uniform design field "+name+" must be uniform");
            if(saved.design_mode==1 && index<5 && value!=field.data[i-i%input.shape[2]])
                throw std::invalid_argument("3D design field "+name+" must be an xy extrusion");
        }
    }
}

struct Packed3D {
    tpmshx_full3d_input_v1 input{};
    tpmshx_stage_saved_case_3d_v3 saved{};
    explicit Packed3D(const tpmshx_stage_saved_case_3d_v3& source) {
        saved=source;input=*saved.input;saved.input=&input;
        validate_saved_3d(source,input);
    }
};
struct Controls3D {
    tpmshx_full3d_control_v1 values{};
    tpmshx_energy_options_v2 energy{};
    const tpmshx_energy_options_v2* energy_pointer=nullptr;
    tpmshx_model_h_iteration_options_v1 model_h{};
    const tpmshx_model_h_iteration_options_v1* model_h_pointer=nullptr;
    Controls3D(const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1& host,
        const tpmshx_full3d_input_v1& input) {
        const tpmshx_stage_run_request_3d_v1 empty{};const auto& r=request?*request:empty;
        const auto selected=r.energy ? *r.energy : tpmshx::default_stage_energy_options();
        tpmshx_energy_effective_settings_v1 defaults{};
        if(tpmshx_full_enthalpy_defaults_v1(3,selected.algorithm,
                input.sides[0].fluid==1 || input.sides[1].fluid==1,&defaults))
            throw std::invalid_argument("invalid native full enthalpy defaults request");
        tpmshx::energy_algorithm(selected);
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
        c.force_cell_centered=choice(r.force_cell_centered,1);c.refined_port_energy=choice(r.refined_port_energy,0);
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
    const tpmshx_stage_saved_case_3d_v3* source=nullptr;
    std::unique_ptr<Packed3D> packed;
    tpmshx_full3d_control_v1 resolved;
    std::string result_id,table_directory;
    void* run=nullptr;
    StageRun3D(const tpmshx_stage_saved_case_3d_v3* original,std::unique_ptr<Packed3D> p,const tpmshx_full3d_control_v1& controls,const char* id)
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
        saved_storage(storage,owner->source);
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
int create(const tpmshx_stage_saved_case_3d_v3* source,const tpmshx_stage_run_request_3d_v1* request,
    const tpmshx_stage_run_control_3d_v1* control,const tpmshx_run_state_field_v1* fields,size_t count,
    bool restore,void** output,char* error,size_t capacity) {
    return guarded(error,capacity,[&](bool& report_safe) {
        boundary::require_buffer(output,1);
        preflight(source,request,control,{output,sizeof(*output),error,capacity},fields,count);
        report_safe=true;
        if(*output)throw std::invalid_argument("3D stage run output handle must be null");
        auto packed=std::make_unique<Packed3D>(*source);
        Controls3D controls(request,*control,packed->input);
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
int run_complete(const tpmshx_stage_saved_case_3d_v3* source,const tpmshx_stage_run_request_3d_v1* request,
    const tpmshx_stage_run_control_3d_v1* control,tpmshx_stage_run_result_3d_v1* result,
    char* error,size_t capacity) {
    return guarded(error,capacity,[&](bool& report_safe) {
        boundary::require_buffer(result,1);
        preflight(source,request,control,{result,sizeof(*result),error,capacity});
        report_safe=true;empty_result(*result);
        void* raw_run=nullptr;
        const auto status=create(source,request,control,nullptr,0,false,&raw_run,error,capacity);
        if(status)return status;
        std::unique_ptr<StageRun3D> run(static_cast<StageRun3D*>(raw_run));
        const auto advanced=tpmshx_stage_run_3d_finish_v1(run.get(),error,capacity);
        if(advanced)return advanced;
        return tpmshx_stage_run_3d_take_result_v1(run.get(),result,error,capacity);
    });
}
}  // namespace

extern "C" {
uint32_t TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_abi_version(void) {
    return TPMSHX_STAGE_RUN_3D_SAVED_ABI_VERSION;
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_create_saved_v3(const tpmshx_stage_saved_case_3d_v3* saved,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    void** output,char* error,size_t capacity) {
    return create(saved,request,control,nullptr,0,false,output,error,capacity);
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_restore_saved_v3(const tpmshx_stage_saved_case_3d_v3* saved,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    const tpmshx_run_state_field_v1* fields,size_t count,void** output,char* error,size_t capacity) {
    return create(saved,request,control,fields,count,true,output,error,capacity);
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_advance_step_v1(void* run,uint32_t* phase,char* error,size_t capacity) {
    return guarded(error,capacity,[&](bool& report_safe) {
        boundary::require_buffer(phase,1);const auto* owner=static_cast<StageRun3D*>(run);
        lifecycle_storage(owner,{phase,sizeof(*phase),error,capacity});report_safe=true;
        return tpmshx_full_3d_run_advance_step_v1(owner->run,phase,error,capacity);
    });
}
int TPMSHX_THERMAL_CALL tpmshx_stage_run_3d_finish_v1(void* run,char* error,size_t capacity) {
    return guarded(error,capacity,[&](bool& report_safe) {
        auto* owner=static_cast<StageRun3D*>(run);
        lifecycle_storage(owner,{nullptr,0,error,capacity});report_safe=true;
        uint32_t phase=0;
        int status=tpmshx_full_3d_run_phase_v1(owner->run,&phase);
        while(!status && phase!=TPMSHX_FULL3D_COMPLETED && phase!=TPMSHX_FULL3D_CANCELLED)
            status=tpmshx_full_3d_run_advance_step_v1(owner->run,&phase,error,capacity);
        return status;
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
            *result=tpmshx::stages::stage_view(*captured.release());owner.packed.reset();owner.source=nullptr;return 0;
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
int TPMSHX_THERMAL_CALL tpmshx_run_saved_case_3d_v3(const tpmshx_stage_saved_case_3d_v3* saved,
    const tpmshx_stage_run_request_3d_v1* request,const tpmshx_stage_run_control_3d_v1* control,
    tpmshx_stage_run_result_3d_v1* result,char* error,size_t capacity) {
    return run_complete(saved,request,control,result,error,capacity);
}
}
