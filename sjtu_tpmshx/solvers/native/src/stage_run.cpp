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
struct Packed2D {
    std::array<size_t,2> shape;
    std::array<std::vector<double>,6> uniform;
    std::array<const double*,29> arrays;
    std::array<size_t,29> sizes;
    double depth=1.;
    tpmshx_full_2d_config_v2 config{};
    tpmshx_energy_options_v1 energy{TPMSHX_ENERGY_TEMPERATURE_SOU,1e-8};
    Packed2D(const tpmshx_preparation_case_2d_v1& p,const tpmshx_stage_run_request_2d_v1& request,
             const tpmshx_stage_run_control_v1& control):shape{p.nx,p.ny} {
        if (p.abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION || p.struct_size!=sizeof(p))
            throw std::invalid_argument("prepared stage ABI version or struct size is invalid");
        if (!p.nx || !p.ny) throw std::invalid_argument("prepared stage requires nonempty physical axes");
        const auto cells=boundary::product(p.nx,p.ny);
        if (p.input.geometry_mode || p.input.df_mode || p.input.delta_levelset!=0.
            || p.sides[0].inlet.fluid || p.sides[1].inlet.fluid)
            throw std::invalid_argument("stage run currently requires uniform symmetric air/air");
        array(p.dx,p.nx);array(p.dy,p.ny);array(p.total_porosity,cells);array(p.solid_conductivity,cells);
        if (p.input.topology>1) throw std::invalid_argument("stage run requires Diamond or Gyroid");
        if (request.convergence_mode && std::strcmp(request.convergence_mode,"f2")!=0)
            throw std::invalid_argument("convergence_mode must be 'f2'; the legacy mass/velocity exit has been retired");
        auto set=[&](size_t i,tpmshx_preparation_array_v1 value) {arrays[i]=value.data;sizes[i]=value.size;};
        set(0,p.dx);set(1,p.dy);arrays[2]=&depth;sizes[2]=1;
        // Preserve the saved SI design, restored mm, then transport SI order.
        const double restored_cell_mm=p.cell_length_m*1e3;
        const double values[]{p.sides[0].properties.fluid_conductivity_W_mK,
            p.sides[1].properties.fluid_conductivity_W_mK,p.area_density_per_m,
            p.hydraulic_diameter_m,restored_cell_mm*1e-3,
            (p.hydraulic_diameter_m*1000.)/restored_cell_mm};
        for (size_t i=0;i<6;++i) uniform[i].assign(cells,values[i]);
        set(3,{uniform[0].data(),cells});set(4,{uniform[1].data(),cells});
        set(5,p.solid_conductivity);set(6,p.total_porosity);
        for (size_t i=0;i<3;++i) set(7+i,{uniform[2+i].data(),cells});
        set(28,{uniform[5].data(),cells});
        auto& c=config;
        c.topology=p.input.topology;c.thermal_mode=1;c.reference_cell_length=restored_cell_mm*1e-3;
        c.reference_porosity=p.epsilon;c.split_a=p.split_a;c.sco2_nu_multiplier=1.;
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
            if (s.permeability.size || s.forchheimer.size)
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
        c.thermal_iterations=5000;c.thermal_chunk=500;c.thermal_q_tolerance=1e-3;c.enthalpy_update_tolerance=.005;
        c.alpha_velocity=number(request.simple_velocity_relaxation,.7,"simple_velocity_relaxation");
        if(c.alpha_velocity>1.)throw std::invalid_argument("simple_velocity_relaxation must be in (0, 1]");
        c.alpha_pressure=.3;c.alpha_density=.3;c.gas_constant=287.05;c.cf_anisotropy=0.;
        c.massflux_inlet=1;c.close_outlet_on_exit=1;c.envelope_mode="raise";c.table_directory=control.table_directory;
        if(request.energy)energy=*request.energy;
        if(request.explicit_energy)throw std::invalid_argument("explicit full 2D energy controls require the existing true-h route");
    }
};
}

extern "C" int tpmshx_run_case_2d_v1(const tpmshx_preparation_case_2d_v1* prepared,
    const tpmshx_stage_run_request_2d_v1* request,const tpmshx_stage_run_control_v1* control,
    tpmshx_stage_run_result_2d_v1* result,char* error,size_t capacity) {
    if(!boundary::error_buffer_valid(error,capacity))return 1;
    tpmshx_full_2d_result_v2 raw{};
    bool report_safe=true;
    try {
        const auto storage=[&](const auto* value,size_t count) {
            using Element=std::remove_cv_t<std::remove_pointer_t<decltype(value)>>;
            boundary::require_buffer(value,count);
            const auto bytes=boundary::product(count,sizeof(Element));
            if(overlaps(value,bytes,error,capacity)) {
                report_safe=false;throw std::invalid_argument("stage run error storage overlaps input or output");
            }
            if(value!=static_cast<const void*>(result) && overlaps(value,bytes,result,sizeof(*result)))
                throw std::invalid_argument("stage run output overlaps input");
        };
        storage(result,1);storage(prepared,1);storage(control,1);
        if(prepared->abi_version!=TPMSHX_PREPARATION_CASE_ABI_VERSION || prepared->struct_size!=sizeof(*prepared))
            throw std::invalid_argument("prepared stage ABI version or struct size is invalid");
        if(request) {
            storage(request,1);
            if(request->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || request->struct_size!=sizeof(*request))
                throw std::invalid_argument("stage run request ABI version or struct size is invalid");
        }
        for(const auto value:{prepared->dx,prepared->dy,prepared->total_porosity,prepared->solid_conductivity})
            storage(value.data,value.size);
        for(const auto& side:prepared->sides)
            for(const auto value:{side.row_permeability,side.row_forchheimer,side.inlet_geometry,
                side.outlet_geometry,side.inlet_profile,side.outlet_profile,side.outlet_u_fraction})
                storage(value.data,value.size);
        storage(prepared->ranges,prepared->range_count);
        for(size_t i=0;i<prepared->range_count;++i) {
            const auto& range=prepared->ranges[i];storage(range.source,range.source_count);storage(range.shape,range.rank);
            for(size_t j=0;j<range.source_count;++j)storage(range.source[j].data,range.source[j].size);
            for(const auto value:{range.side,range.stage,range.layout,range.quantity,range.unit})storage(value.data,value.size);
        }
        if(request && request->energy)storage(request->energy,1);

        boundary::require_buffer(prepared,1);boundary::require_buffer(control,1);boundary::require_buffer(result,1);
        if(result->abi_version!=TPMSHX_STAGE_RUN_ABI_VERSION || result->struct_size!=sizeof(*result) || result->owner)
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
        Packed2D packed(*prepared,selected,*control);
        const auto& h=selected.model_h;
        const auto* model_h=(h.max_iterations || h.temperature_tolerance || h.q_relative_tolerance)?&h:nullptr;
        const auto status=tpmshx_solve_full_2d_v6(packed.shape.data(),packed.arrays.data(),packed.sizes.data(),
            &packed.config,model_h?selected.energy:&packed.energy,nullptr,model_h,
            control->cpu_threads,&control->callbacks,&raw,error,capacity);
        if(status)return status;
        if(raw.cancelled) {
            tpmshx_full_2d_release_v2(&raw);boundary::message(error,capacity,"compute cancelled by user");return 4;
        }
        std::unique_ptr<tpmshx::stages::Capture2D,decltype(&tpmshx::stages::release_capture_2d)> owner(
            tpmshx::stages::capture_2d(*prepared,raw,packed.config,control->result_id),
            &tpmshx::stages::release_capture_2d);
        *result=tpmshx::stages::stage_view(*owner.release());
        boundary::message(error,capacity,"");return 0;
    } catch(const std::invalid_argument& failure) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,failure.what());return 1;
    } catch(const std::bad_alloc&) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,"stage run allocation failed");return 2;
    } catch(const std::exception& failure) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,failure.what());return 3;
    } catch(...) {
        tpmshx_full_2d_release_v2(&raw);if(report_safe)boundary::message(error,capacity,"unknown native stage run failure");return 3;
    }
}
extern "C" void tpmshx_stage_run_2d_release_v1(tpmshx_stage_run_result_2d_v1* result) {
    if(!result)return;
    tpmshx::stages::release_capture_2d(static_cast<tpmshx::stages::Capture2D*>(result->owner));
    *result={};
}
