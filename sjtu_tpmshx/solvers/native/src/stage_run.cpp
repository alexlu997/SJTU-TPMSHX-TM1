#include "tpmshx/stage_run_c_api.h"
#include "stage_capture_2d.hpp"
#include "field_c_boundary.hpp"

#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <type_traits>
#include <vector>

namespace {
namespace boundary=tpmshx::fields::c_api;
bool overlaps(const void* a,size_t a_bytes,const void* b,size_t b_bytes) {
    if(!a_bytes || !b_bytes)return false;
    const auto first=reinterpret_cast<uintptr_t>(a),second=reinterpret_cast<uintptr_t>(b);
    return first<=second+b_bytes-1 && second<=first+a_bytes-1;
}
void flag(uint32_t value) {
    if (value>1) throw std::invalid_argument("stage run option flags require 0 or 1");
}
double number(tpmshx_stage_double_option_v1 option,double fallback,const char* name) {
    flag(option.present);
    if (!option.present) return fallback;
    if (!std::isfinite(option.value) || option.value<=0.)
        throw std::invalid_argument(std::string(name)+" must be positive and finite");
    return option.value;
}
size_t count(tpmshx_stage_size_option_v1 option,size_t fallback,size_t minimum,const char* name) {
    flag(option.present);
    if (!option.present) return fallback;
    if (option.value<minimum) throw std::invalid_argument(std::string(name)+" is below its minimum");
    return option.value;
}
void array(tpmshx_preparation_array_v1 input,size_t size) {
    boundary::require_buffer(input.data,input.size);
    if (input.size!=size) throw std::invalid_argument("prepared stage array has the wrong extent");
}
template<class Storage> void preparation_storage(const Storage& storage,
    const tpmshx_preparation_case_2d_v1*& prepared,const tpmshx_preparation_case_2d_v2*& uniform,
    const tpmshx_preparation_continuous_case_2d_v4* continuous,bool v2) {
    if(continuous) {
        storage(continuous,1);
        if(continuous->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V4 || continuous->struct_size!=sizeof(*continuous))
            throw std::invalid_argument("prepared continuous stage ABI version or struct size is invalid");
        uniform=&continuous->prepared;
        for(const auto value:{continuous->area_density_per_m,continuous->hydraulic_diameter_m,
                continuous->fluid_conductivity[0],continuous->fluid_conductivity[1]})storage(value.data,value.size);
    }
    if(v2) {
        storage(uniform,1);
        if(uniform->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION_V2 || uniform->struct_size!=sizeof(*uniform))
            throw std::invalid_argument("prepared stage v2 ABI version or struct size is invalid");
        prepared=&uniform->values;
        storage(uniform->notices,uniform->notice_count);
        for(size_t i=0;i<uniform->notice_count;++i)storage(uniform->notices[i].data,uniform->notices[i].size);
    }
    storage(prepared,1);
    if(prepared->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION || prepared->struct_size!=sizeof(*prepared))
        throw std::invalid_argument("prepared stage ABI version or struct size is invalid");
    for(const auto value:{prepared->dx,prepared->dy,prepared->total_porosity,prepared->solid_conductivity})
        storage(value.data,value.size);
    if(continuous)storage(prepared->cell_length.data,prepared->cell_length.size);
    for(const auto& side:prepared->sides)
        for(const auto value:{side.row_permeability,side.row_forchheimer,side.permeability,side.forchheimer,side.inlet_geometry,
            side.outlet_geometry,side.inlet_profile,side.outlet_profile,side.outlet_u_fraction})
            storage(value.data,value.size);
    storage(prepared->ranges,prepared->range_count);
    for(size_t i=0;i<prepared->range_count;++i) {
        const auto& range=prepared->ranges[i];storage(range.source,range.source_count);storage(range.shape,range.rank);
        for(size_t j=0;j<range.source_count;++j)storage(range.source[j].data,range.source[j].size);
        for(const auto value:{range.side,range.stage,range.layout,range.quantity,range.unit})storage(value.data,value.size);
    }
}
struct Packed2D {
    std::array<size_t,2> shape;
    std::array<std::vector<double>,6> fields;
    std::array<const double*,29> arrays;
    std::array<size_t,29> sizes;
    double depth=1.;
    tpmshx_full_2d_config_v2 config{};
    tpmshx_energy_options_v1 energy{TPMSHX_ENERGY_TEMPERATURE_SOU,1e-8};
    tpmshx_full_2d_energy_control_v4 partial_energy{};
    const tpmshx_full_2d_energy_control_v4* explicit_energy=nullptr;
    Packed2D(const tpmshx_preparation_case_2d_v1& p,const tpmshx_stage_run_request_2d_v1& request,
             const tpmshx_stage_run_control_v1& control,const tpmshx_preparation_case_2d_v2* uniform,
             const char* envelope,const tpmshx_preparation_continuous_case_2d_v4* continuous,
             const tpmshx_stage_run_request_2d_v3* partial=nullptr):shape{p.nx,p.ny} {
        if (p.abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION || p.struct_size!=sizeof(p))
            throw std::invalid_argument("prepared stage ABI version or struct size is invalid");
        if (!p.nx || !p.ny) throw std::invalid_argument("prepared stage requires nonempty physical axes");
        const auto cells=boundary::product(p.nx,p.ny);
        if (p.input.geometry_mode!=(continuous?1u:0u) || p.input.delta_levelset!=0. || p.input.df_mode>(uniform?1u:0u)
            || p.sides[0].inlet.fluid>(uniform?3u:0u) || p.sides[1].inlet.fluid>(uniform?3u:0u))
            throw std::invalid_argument(continuous?"stage run requires supported continuous symmetric preparation":
                uniform?"stage run requires supported uniform symmetric preparation":
                "stage run currently requires uniform symmetric air/air");
        array(p.dx,p.nx);array(p.dy,p.ny);array(p.total_porosity,cells);array(p.solid_conductivity,cells);
        if (p.input.topology>1) throw std::invalid_argument("stage run requires Diamond or Gyroid");
        if (request.convergence_mode && std::strcmp(request.convergence_mode,"f2")!=0)
            throw std::invalid_argument("convergence_mode must be 'f2'; the legacy mass/velocity exit has been retired");
        auto set=[&](size_t i,tpmshx_preparation_array_v1 value) {arrays[i]=value.data;sizes[i]=value.size;};
        set(0,p.dx);set(1,p.dy);arrays[2]=&depth;sizes[2]=1;
        // Preserve the saved SI design, restored mm, then transport SI order.
        const double restored_cell_mm=p.cell_length_m*1e3;
        if(continuous) {
            for(const auto value:{p.cell_length,continuous->area_density_per_m,continuous->hydraulic_diameter_m,
                    continuous->fluid_conductivity[0],continuous->fluid_conductivity[1]})array(value,cells);
            fields[4].resize(cells);fields[5].resize(cells);
            for(size_t i=0;i<cells;++i) {
                const double restored_mm=p.cell_length.data[i]*1e3;
                fields[4][i]=restored_mm*1e-3;
                fields[5][i]=(continuous->hydraulic_diameter_m.data[i]*1000.)/restored_mm;
            }
            set(3,continuous->fluid_conductivity[0]);set(4,continuous->fluid_conductivity[1]);
            set(7,continuous->area_density_per_m);set(8,continuous->hydraulic_diameter_m);
        } else {
            const double values[]{p.sides[0].properties.fluid_conductivity_W_mK,
                p.sides[1].properties.fluid_conductivity_W_mK,p.area_density_per_m,
                p.hydraulic_diameter_m,restored_cell_mm*1e-3,
                (p.hydraulic_diameter_m*1000.)/restored_cell_mm};
            for (size_t i=0;i<6;++i) fields[i].assign(cells,values[i]);
            set(3,{fields[0].data(),cells});set(4,{fields[1].data(),cells});
            set(7,{fields[2].data(),cells});set(8,{fields[3].data(),cells});
        }
        set(5,p.solid_conductivity);set(6,p.total_porosity);
        set(9,{fields[4].data(),cells});
        set(28,{fields[5].data(),cells});
        auto& c=config;
        const bool eos=p.sides[0].inlet.fluid>=2 || p.sides[1].inlet.fluid>=2;
        const bool water=p.sides[0].inlet.fluid==1 || p.sides[1].inlet.fluid==1;
        c.topology=p.input.topology;c.thermal_mode=eos?2:1;c.spatial_geometry=continuous?1:0;
        c.reference_cell_length=restored_cell_mm*1e-3;
        c.reference_porosity=p.epsilon;c.split_a=p.split_a;c.sco2_nu_multiplier=1.;
        if(uniform && eos && uniform->sco2_nu.mode)c.sco2_nu_multiplier=uniform->sco2_nu.alpha[p.input.topology];
        flag(request.solid_seed_K.present);c.have_solid_seed=request.solid_seed_K.present;
        c.solid_seed=number(request.solid_seed_K,0.,"solid_seed_K");
        flag(request.have_pressure_shooting);flag(request.pressure_shooting);
        c.pressure_shooting=request.have_pressure_shooting?request.pressure_shooting:1;
        for (size_t side=0;side<2;++side) {
            const auto& s=p.sides[side];const auto& port=s.inlet.port;
            if (port.direction<0 || port.direction>3) throw std::invalid_argument("invalid 2D stage direction");
            flag(port.uniform_inlet);
            const size_t cross=port.direction<2?p.ny:p.nx,stream=port.direction<2?p.nx:p.ny;
            array(s.row_permeability,stream);array(s.row_forchheimer,stream);
            array(s.inlet_geometry,cross);array(s.outlet_geometry,cross);
            array(s.inlet_profile,cross);array(s.outlet_profile,cross);array(s.outlet_u_fraction,cross+1);
            if(continuous) {array(s.permeability,cells);array(s.forchheimer,cells);}
            else if (s.permeability.size || s.forchheimer.size)
                throw std::invalid_argument("uniform stage run does not accept local drag fields");
            const std::array<tpmshx_preparation_array_v1,9> side_arrays{s.row_permeability,s.row_forchheimer,
                s.permeability,s.forchheimer,s.inlet_geometry,s.outlet_geometry,s.inlet_profile,s.outlet_profile,
                s.outlet_u_fraction};
            for(size_t i=0;i<9;++i)set(10+9*side+i,side_arrays[i]);
            c.sides[side]={s.inlet.fluid,static_cast<uint32_t>(port.direction),port.uniform_inlet,
                s.inlet.temperature_K,s.inlet.pressure_Pa,s.inlet.velocity_m_s,s.properties.mu,
                s.seed_permeability_m2,s.seed_forchheimer_per_m,s.inlet_bounds[0],s.inlet_bounds[1],
                s.outlet_bounds[0],s.outlet_bounds[1],0.,0.,0.,0.};
        }
        c.f2={number(request.mom_tol,1e-4,"mom_tol"),number(request.mass_local_tol,1e-6,"mass_local_tol"),
            number(request.mass_global_tol,1e-6,"mass_global_tol"),.01,1e-4,1e-3,2,5,60};
        c.simple_iterations=count(request.max_iter_simple,10000,1,"max_iter_simple");c.simple_sweeps=2;
        c.outer_iterations=count(request.max_outer_ltne,10,2,"max_outer_ltne");
        c.outer_temperature_tolerance=number(request.outer_tol_K,1.,"outer_tol_K");
        c.outer_density_tolerance=.01;c.outer_relaxation=.7;
        if(request.energy)energy=*request.energy;
        if(eos) {
            tpmshx_energy_effective_settings_v1 defaults{};
            if(tpmshx_full_enthalpy_defaults_v1(2,energy.algorithm,water?1:0,&defaults))
                throw std::invalid_argument("invalid full 2D energy defaults");
            c.thermal_iterations=defaults.max_iterations;c.enthalpy_update_tolerance=defaults.update_tolerance;
            c.thermal_chunk=3;c.thermal_q_tolerance=.1*2e-3;
        } else {
            c.thermal_iterations=water?12000:5000;c.thermal_chunk=500;c.thermal_q_tolerance=1e-3;
            c.enthalpy_update_tolerance=water?.01:.005;
        }
        c.alpha_velocity=number(request.simple_velocity_relaxation,.7,"simple_velocity_relaxation");
        if(c.alpha_velocity>1.)throw std::invalid_argument("simple_velocity_relaxation must be in (0, 1]");
        c.alpha_pressure=.3;c.alpha_density=.3;c.gas_constant=287.05;c.cf_anisotropy=0.;
        c.massflux_inlet=1;c.close_outlet_on_exit=1;c.envelope_mode=envelope?envelope:"raise";c.table_directory=control.table_directory;
        if(request.explicit_energy && !eos)
            throw std::invalid_argument("explicit full 2D energy controls require the existing true-h route");
        explicit_energy=request.explicit_energy;
        if(partial) {
            flag(partial->require_enthalpy_update_on_temperature);
            for(const auto present:{partial->energy_iterations.present,partial->energy_sweeps.present,
                    partial->energy_omega.present,partial->energy_update_tolerance.present,
                    partial->energy_coupled_tolerance.present,partial->energy_equation_tolerance.present})flag(present);
            if(partial->energy_iterations.present || partial->energy_sweeps.present || partial->energy_omega.present
                || partial->energy_update_tolerance.present || partial->energy_coupled_tolerance.present
                || partial->energy_equation_tolerance.present || partial->require_enthalpy_update_on_temperature) {
                if(explicit_energy)throw std::invalid_argument("conflicting full energy options");
                if(!eos)throw std::invalid_argument("explicit full 2D energy controls require the existing true-h route");
                tpmshx_energy_effective_settings_v1 defaults{};
                if(tpmshx_full_enthalpy_defaults_v1(2,energy.algorithm,water?1:0,&defaults))
                    throw std::invalid_argument("invalid full 2D energy defaults");
                partial_energy={count(partial->energy_iterations,defaults.max_iterations,1,"energy_iterations"),
                    count(partial->energy_sweeps,defaults.sweeps,0,"energy_sweeps"),
                    number(partial->energy_omega,defaults.omega,"energy_omega"),
                    number(partial->energy_update_tolerance,defaults.update_tolerance,"energy_update_tolerance"),
                    {energy.algorithm,energy.temperature_update_tolerance,
                     number(partial->energy_coupled_tolerance,defaults.coupled_energy_tolerance,"energy_coupled_tolerance"),
                     number(partial->energy_equation_tolerance,defaults.equation_energy_tolerance,"energy_equation_tolerance"),
                     partial->require_enthalpy_update_on_temperature}};
                explicit_energy=&partial_energy;
            }
        }
    }
};
struct StageRun2D {
    void* run=nullptr;
    const tpmshx_preparation_case_2d_v1* prepared;
    const tpmshx_preparation_case_2d_v2* uniform;
    const tpmshx_preparation_continuous_case_2d_v4* continuous;
    tpmshx_full_2d_config_v2 config;
    std::string result_id,table_directory,envelope_mode;
    StageRun2D(const tpmshx_preparation_case_2d_v1* p,const tpmshx_preparation_case_2d_v2* u,
        const tpmshx_preparation_continuous_case_2d_v4* spatial,const tpmshx_full_2d_config_v2& c,const char* id)
        :prepared(p),uniform(u),continuous(spatial),config(c),result_id(id),
        table_directory(c.table_directory?c.table_directory:""),envelope_mode(c.envelope_mode?c.envelope_mode:"") {
        config.table_directory=c.table_directory?table_directory.c_str():nullptr;
        config.envelope_mode=c.envelope_mode?envelope_mode.c_str():nullptr;
    }
    ~StageRun2D() {tpmshx_full_2d_run_release_v1(&run);}
};
struct StartRun {
    const tpmshx_stage_run_request_2d_v3* request;
    void** output;
    const tpmshx_run_state_field_v1* fields=nullptr;
    size_t count=0;
    bool restore=false;
};
}

namespace {
int run(const tpmshx_preparation_case_2d_v1* prepared,
    const tpmshx_stage_run_request_2d_v1* request,const tpmshx_stage_run_control_v1* control,
    tpmshx_stage_run_result_2d_v1* result,char* error,size_t capacity,
    const tpmshx_preparation_case_2d_v2* uniform,const tpmshx_stage_run_request_2d_v2* request_v2,bool v2,
    const tpmshx_preparation_continuous_case_2d_v4* continuous,const StartRun* start=nullptr) {
    if(!boundary::error_buffer_valid(error,capacity))return 1;
    tpmshx_full_2d_result_v2 raw{};
    bool report_safe=false;
    try {
        if(start)boundary::require_buffer(start->output,1);
        else boundary::require_buffer(result,1);
        const void* output=start?static_cast<void*>(start->output):result;
        const size_t output_size=start?sizeof(*start->output):sizeof(*result);
        if(overlaps(output,output_size,error,capacity)) {
            report_safe=false;throw std::invalid_argument("stage run error storage overlaps output");
        }
        const auto storage=[&](const auto* value,size_t count) {
            using Element=std::remove_cv_t<std::remove_pointer_t<decltype(value)>>;
            boundary::require_buffer(value,count);
            const auto bytes=boundary::product(count,sizeof(Element));
            if(overlaps(value,bytes,error,capacity)) {
                report_safe=false;throw std::invalid_argument("stage run error storage overlaps input or output");
            }
            if(overlaps(value,bytes,output,output_size))
                throw std::invalid_argument("stage run output overlaps input");
        };
        if(start) {
            if(bool(uniform)==bool(continuous))throw std::invalid_argument("stage run requires exactly one prepared view");
            if(start->request) {
                storage(start->request,1);
                if(start->request->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION_V3
                    || start->request->struct_size!=sizeof(*start->request))
                    throw std::invalid_argument("stage run request v3 ABI version or struct size is invalid");
                request_v2=&start->request->values;
            }
            storage(start->fields,start->count);
            for(size_t i=0;i<start->count;++i) {
                const auto& field=start->fields[i];storage(field.name,1);storage(field.name,std::strlen(field.name)+1);
                if(field.type>TPMSHX_RUN_STATE_UTF8)throw std::invalid_argument("invalid stage run state field type");
                const auto bytes=boundary::product(field.count,field.type<=TPMSHX_RUN_STATE_I64?8:1);
                storage(static_cast<const unsigned char*>(field.data),bytes);
            }
        }
        preparation_storage(storage,prepared,uniform,continuous,v2);
        if(v2 && request_v2) {
            storage(request_v2,1);
            if(request_v2->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION_V2 || request_v2->struct_size!=sizeof(*request_v2))
                throw std::invalid_argument("stage run request v2 ABI version or struct size is invalid");
            request=&request_v2->values;
        }
        storage(control,1);
        if(request) {
            storage(request,1);
            if(request->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || request->struct_size!=sizeof(*request))
                throw std::invalid_argument("stage run request ABI version or struct size is invalid");
        }
        if(request && request->energy)storage(request->energy,1);
        if(request && request->explicit_energy)storage(request->explicit_energy,1);
        const auto text_storage=[&](const char* value) {
            if(value) {storage(value,1);storage(value,std::strlen(value)+1);}
        };
        text_storage(control->result_id);text_storage(control->table_directory);
        if(request)text_storage(request->convergence_mode);
        if(request_v2)text_storage(request_v2->envelope_mode);
        report_safe=true;

        if(start && *start->output)throw std::invalid_argument("stage run output handle must be null");
        if(!start && (result->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || result->struct_size!=sizeof(*result) || result->owner))
            throw std::invalid_argument("stage run output must be an initialized empty owner");
        if(!control->cpu_threads || !control->result_id)
            throw std::invalid_argument("stage run requires a positive CPU limit and result label");
        tpmshx_stage_run_request_2d_v1 defaults{};
        defaults.abi_version=TPMSHX_STAGE_RUN_ABI_VERSION;defaults.struct_size=sizeof(defaults);
        if(request) {
            boundary::require_buffer(request,1);
            if(request->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || request->struct_size!=sizeof(*request))
                throw std::invalid_argument("stage run request ABI version or struct size is invalid");
        }
        const auto& selected=request?*request:defaults;
        Packed2D packed(*prepared,selected,*control,uniform,request_v2?request_v2->envelope_mode:nullptr,continuous,
            start?start->request:nullptr);
        const auto& h=selected.model_h;
        const auto* model_h=(h.max_iterations || h.temperature_tolerance || h.q_relative_tolerance)?&h:nullptr;
        const auto* energy=model_h || packed.explicit_energy?selected.energy:&packed.energy;
        if(packed.explicit_energy==&packed.partial_energy)energy=nullptr;
        if(start) {
            auto owner=std::make_unique<StageRun2D>(prepared,uniform,continuous,packed.config,control->result_id);
            const auto status=start->restore?tpmshx_full_2d_run_restore_v2(
                packed.shape.data(),packed.arrays.data(),packed.sizes.data(),&packed.config,energy,
                packed.explicit_energy,model_h,control->cpu_threads,&control->callbacks,
                start->fields,start->count,&owner->run,error,capacity):tpmshx_full_2d_run_create_v2(
                packed.shape.data(),packed.arrays.data(),packed.sizes.data(),&packed.config,energy,
                packed.explicit_energy,model_h,control->cpu_threads,&control->callbacks,&owner->run,error,capacity);
            if(status)return status;
            *start->output=owner.release();return 0;
        }
        const auto status=tpmshx_solve_full_2d_v6(packed.shape.data(),packed.arrays.data(),packed.sizes.data(),
            &packed.config,energy,packed.explicit_energy,model_h,
            control->cpu_threads,&control->callbacks,&raw,error,capacity);
        if(status)return status;
        if(raw.cancelled) {
            tpmshx_full_2d_release_v2(&raw);boundary::message(error,capacity,"compute cancelled by user");return v2?6:4;
        }
        std::unique_ptr<tpmshx::stages::Capture2D,decltype(&tpmshx::stages::release_capture_2d)> owner(
            tpmshx::stages::capture_2d(*prepared,raw,packed.config,control->result_id,uniform),
            &tpmshx::stages::release_capture_2d);
        *result=tpmshx::stages::stage_view(*owner.release());
        boundary::message(error,capacity,"");return 0;
    } catch(const std::invalid_argument& failure) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,failure.what());return 1;
    } catch(const std::bad_alloc&) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,"stage run allocation failed");return v2?5:2;
    } catch(const std::exception& failure) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,failure.what());return v2?5:3;
    } catch(...) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,"unknown native stage run failure");return v2?5:3;
    }
}
}
extern "C" int tpmshx_run_case_2d_v1(const tpmshx_preparation_case_2d_v1* prepared,
    const tpmshx_stage_run_request_2d_v1* request,const tpmshx_stage_run_control_v1* control,
    tpmshx_stage_run_result_2d_v1* result,char* error,size_t capacity) {
    return run(prepared,request,control,result,error,capacity,nullptr,nullptr,false,nullptr);
}
extern "C" int tpmshx_run_case_2d_v2(const tpmshx_preparation_case_2d_v2* prepared,
    const tpmshx_stage_run_request_2d_v2* request,const tpmshx_stage_run_control_v1* control,
    tpmshx_stage_run_result_2d_v1* result,char* error,size_t capacity) {
    return run(nullptr,nullptr,control,result,error,capacity,prepared,request,true,nullptr);
}
extern "C" int tpmshx_run_case_2d_v3(const tpmshx_preparation_continuous_case_2d_v4* prepared,
    const tpmshx_stage_run_request_2d_v2* request,const tpmshx_stage_run_control_v1* control,
    tpmshx_stage_run_result_2d_v1* result,char* error,size_t capacity) {
    if(!prepared)return 1;
    return run(nullptr,nullptr,control,result,error,capacity,nullptr,request,true,prepared);
}
extern "C" void tpmshx_stage_run_2d_release_v1(tpmshx_stage_run_result_2d_v1* result) {
    if(!result)return;
    tpmshx::stages::release_capture_2d(static_cast<tpmshx::stages::Capture2D*>(result->owner));
    *result={};
}
extern "C" int tpmshx_stage_run_2d_create_v1(const tpmshx_preparation_case_2d_v2* prepared,
    const tpmshx_preparation_continuous_case_2d_v4* continuous,const tpmshx_stage_run_request_2d_v3* request,
    const tpmshx_stage_run_control_v1* control,void** output,char* error,size_t capacity) {
    const StartRun start{request,output};
    return run(nullptr,nullptr,control,nullptr,error,capacity,prepared,nullptr,true,continuous,&start);
}
extern "C" int tpmshx_stage_run_2d_restore_v1(const tpmshx_preparation_case_2d_v2* prepared,
    const tpmshx_preparation_continuous_case_2d_v4* continuous,const tpmshx_stage_run_request_2d_v3* request,
    const tpmshx_stage_run_control_v1* control,const tpmshx_run_state_field_v1* fields,size_t count,
    void** output,char* error,size_t capacity) {
    const StartRun start{request,output,fields,count,true};
    return run(nullptr,nullptr,control,nullptr,error,capacity,prepared,nullptr,true,continuous,&start);
}
extern "C" int tpmshx_stage_run_2d_advance_step_v1(void* run,uint32_t* phase,char* error,size_t capacity) {
    return tpmshx_full_2d_run_advance_step_v1(run?static_cast<StageRun2D*>(run)->run:nullptr,phase,error,capacity);
}
extern "C" int tpmshx_stage_run_2d_phase_v1(const void* run,uint32_t* phase) {
    return tpmshx_full_2d_run_phase_v1(run?static_cast<const StageRun2D*>(run)->run:nullptr,phase);
}
extern "C" int tpmshx_stage_run_2d_snapshot_v1(const void* run,tpmshx_run_state_v1* state,char* error,size_t capacity) {
    return tpmshx_full_2d_run_snapshot_v1(run?static_cast<const StageRun2D*>(run)->run:nullptr,state,error,capacity);
}
extern "C" int tpmshx_stage_run_2d_take_result_v1(void* run,
    tpmshx_stage_run_result_2d_v1* result,char* error,size_t capacity) {
    if(!boundary::error_buffer_valid(error,capacity))return 1;
    tpmshx_full_2d_result_v2 raw{};
    bool report_safe=false;
    try {
        boundary::require_buffer(result,1);boundary::require_buffer(static_cast<StageRun2D*>(run),1);
        if(overlaps(result,sizeof(*result),error,capacity) || overlaps(run,sizeof(StageRun2D),error,capacity)
            || overlaps(run,sizeof(StageRun2D),result,sizeof(*result)))return 1;
        auto& owner=*static_cast<StageRun2D*>(run);
        uint32_t phase=0;
        const auto phase_status=tpmshx_full_2d_run_phase_v1(owner.run,&phase);
        if(phase_status)return phase_status;
        if(owner.prepared) {
            const auto storage=[&](const auto* value,size_t count) {
                using Element=std::remove_cv_t<std::remove_pointer_t<decltype(value)>>;
                boundary::require_buffer(value,count);
                const auto bytes=boundary::product(count,sizeof(Element));
                if(overlaps(value,bytes,error,capacity) || overlaps(value,bytes,result,sizeof(*result)))
                    throw std::invalid_argument("stage result storage overlaps preparation");
            };
            preparation_storage(storage,owner.prepared,owner.uniform,owner.continuous,true);
        }
        report_safe=true;
        if(result->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || result->struct_size!=sizeof(*result) || result->owner)
            throw std::invalid_argument("stage run output must be an initialized empty owner");
        if(phase==TPMSHX_FULL2D_CANCELLED) {
            boundary::message(error,capacity,"compute cancelled by user");return 6;
        }
        const auto status=tpmshx_full_2d_run_take_result_v1(owner.run,&raw,error,capacity);
        if(status)return status;
        std::unique_ptr<tpmshx::stages::Capture2D,decltype(&tpmshx::stages::release_capture_2d)> captured(
            tpmshx::stages::capture_2d(*owner.prepared,raw,owner.config,owner.result_id.c_str(),owner.uniform),
            &tpmshx::stages::release_capture_2d);
        *result=tpmshx::stages::stage_view(*captured.release());
        owner.prepared=nullptr;owner.uniform=nullptr;owner.continuous=nullptr;
        boundary::message(error,capacity,"");return 0;
    } catch(const std::invalid_argument& failure) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,failure.what());return 1;
    } catch(const std::exception& failure) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,failure.what());return 5;
    } catch(...) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,"unknown native stage capture failure");return 5;
    }
}
extern "C" void tpmshx_stage_run_2d_release_run_v1(void** run) {
    if(run) {delete static_cast<StageRun2D*>(*run);*run=nullptr;}
}
