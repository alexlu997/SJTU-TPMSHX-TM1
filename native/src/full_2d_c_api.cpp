#include "tpmshx/full_2d_c_api.h"
#include "tpmshx/full_2d.hpp"
#include "model_h_c_views.hpp"
#include "enthalpy_c_views.hpp"
#include "simple_2d_c_views.hpp"
#include "closure_evidence_c_views.hpp"
#include <Exceptions.h>
#include <memory>

namespace {
using namespace tpmshx;
using Array=tpmshx_model_h_array_v1;
using Vector=std::vector<double>;
Array array(const Vector& x) { return {x.data(),x.size()}; }
struct Owner {
    Full2DResult result;
    Vector dx,dy,epsilon;
    std::array<Vector,2> inlet,outlet,momentum;
    std::array<std::vector<tpmshx_model_h_check_v1>,2> finishing;
    std::array<std::vector<tpmshx_full_2d_pressure_iteration_v2>,2> pressure;
    std::array<std::vector<const char*>,2> envelope;
    std::vector<tpmshx_full_2d_outer_v2> outer;
    std::vector<tpmshx_energy_result_v1> energy_outer;
    std::vector<tpmshx_range_observation_v1> ranges;
};
void flag(uint32_t value) {
    if (value>1) throw std::invalid_argument("full2D flags must be zero or one");
}
bool cancel(void* context) {
    const auto* cb=static_cast<const tpmshx_full_2d_callbacks_v2*>(context);
    return cb && cb->cancel && cb->cancel(cb->context)!=0;
}
void progress(void* context,std::size_t iteration,std::size_t total) {
    const auto* cb=static_cast<const tpmshx_full_2d_callbacks_v2*>(context);
    if (cb && cb->progress) cb->progress(cb->context,iteration,total);
}
void residual(void* context,std::size_t side,std::size_t iteration,double value) {
    const auto* cb=static_cast<const tpmshx_full_2d_callbacks_v2*>(context);
    if (cb && cb->residual) cb->residual(cb->context,side,iteration,value);
}
void thermal(tpmshx_full_2d_thermal_v2& o,Owner& owner,const Full2DThermalState& t,
             std::size_t stage,Full2DThermalMode mode) {
    o.mode=static_cast<uint32_t>(mode);
    std::visit([&](const auto& r) {
        o.stop=static_cast<uint32_t>(r.stop); o.iterations=r.iterations; o.residual=r.residual; o.q_b=r.q_b;
    },t.result);
    for (std::size_t k=0;k<3;++k) o.temperature[k]=array(t.temperature[k]);
    for (std::size_t k=0;k<2;++k) {
        o.hv[k]=array(t.hv[k]); o.conductivity[k]=array(t.conductivity[k]); o.pressure[k]=array(t.pressure[k]);
        o.rho_cp[k]=array(t.rho_cp[k]); o.mass_x[k]=array(t.mass_x[k]); o.mass_y[k]=array(t.mass_y[k]);
        o.inlet_capacity[k]=array(t.inlet_capacity[k]);
    }
    o.solid_conductivity=array(t.solid_conductivity); o.enthalpy[0]=array(t.h_a); o.enthalpy[1]=array(t.h_b);
    if (const auto* m=std::get_if<ModelHResult2D>(&t.result)) {
        model_h_c_views::plane(o.model_h,owner.finishing[stage],*m);
        o.model_h.finishing_checks=owner.finishing[stage].data(); o.model_h.finishing_count=owner.finishing[stage].size();
    } else if (const auto* h=std::get_if<EnthalpyResult>(&t.result)) o.true_h=enthalpy_c_view(*h);
}
void fill(tpmshx_full_2d_result_v2& o,Owner& owner,const Full2DProblem& p) {
    const auto& r=owner.result;
    o.cancelled=r.cancelled; o.iterations=r.iterations;
    if (r.cancelled) return;
    o.converged=r.converged; o.outer_converged=r.outer_converged; o.post_after_last_thermal=r.post_after_last_thermal;
    o.simple_ok=r.simple_ok; o.thermal_ok=r.thermal_ok; o.envelope_ok=r.envelope_ok;
    o.pair_balance_ok=r.pair_balance_ok; o.model_balance_ok=r.model_balance_ok;
    owner.dx.assign(p.grid.dx.data,p.grid.dx.data+p.grid.dx.size);
    owner.dy.assign(p.grid.dy.data,p.grid.dy.data+p.grid.dy.size);
    owner.epsilon.assign(p.total_porosity.data,p.total_porosity.data+p.total_porosity.size);
    for (std::size_t side=0;side<2;++side) {
        const auto& f=r.flow[side]; auto& d=o.flow[side];
#define COPY_ARRAY(name) d.name=array(f.name)
        COPY_ARRAY(dx); COPY_ARRAY(dy); COPY_ARRAY(u); COPY_ARRAY(v); COPY_ARRAY(pressure); COPY_ARRAY(pressure_correction);
        COPY_ARRAY(d_u); COPY_ARRAY(d_v); COPY_ARRAY(density); COPY_ARRAY(inlet_velocity); COPY_ARRAY(viscosity);
        COPY_ARRAY(effective_viscosity); COPY_ARRAY(temperature); COPY_ARRAY(epsilon); COPY_ARRAY(uc); COPY_ARRAY(vc);
        COPY_ARRAY(absolute_pressure); COPY_ARRAY(mass_x); COPY_ARRAY(mass_y);
#undef COPY_ARRAY
        d.reference_pressure=f.reference_pressure; d.taper_flux_scale=f.taper_flux_scale;
        d.result=simple_2d_c_view(f.result,f.massflux_target);
        d.history[0]=array(f.history.legacy); d.history[1]=array(f.history.local_mass); d.history[2]=array(f.history.global_mass);
        for (const auto& h:f.history.momentum) {
            owner.momentum[side].push_back(static_cast<double>(h.iteration)); owner.momentum[side].push_back(h.residual.maximum);
            for (const auto& values:{h.residual.numerator,h.residual.denominator,h.residual.component})
                owner.momentum[side].insert(owner.momentum[side].end(),values.begin(),values.begin()+2);
        }
        d.history[3]=array(owner.momentum[side]);
        if (f.pressure_state) {
            const auto& s=*f.pressure_state;
            d.inlet_pressure={1,static_cast<uint32_t>(s.passed),s.specified_Pa,s.realized_Pa,s.outlet_Pa,
                s.outlet_gauge_Pa,s.minimum_Pa,s.relative_error,s.relative_tolerance,s.definition.c_str()};
        }
        for (const auto& h:f.pressure_iterations) owner.pressure[side].push_back({h.stage.c_str(),h.anchor_Pa,
            static_cast<uint32_t>(h.estimate_Pa2.has_value()),static_cast<uint32_t>(h.relative_error.has_value()),
            static_cast<uint32_t>(h.target_Pa2.has_value()),static_cast<uint32_t>(h.step_fraction.has_value()),
            h.estimate_Pa2.value_or(0.),h.relative_error.value_or(0.),h.target_Pa2.value_or(0.),h.step_fraction.value_or(0.),
            h.method?h.method->c_str():nullptr});
        d.pressure_iterations=owner.pressure[side].data(); d.pressure_iteration_count=owner.pressure[side].size();
        d.envelope_valid=r.envelope[side].valid;
        for (const auto& reason:r.envelope[side].reasons) owner.envelope[side].push_back(reason.c_str());
        d.envelope_reasons=owner.envelope[side].data(); d.envelope_reason_count=owner.envelope[side].size();
        o.density[side]=array(r.density[side]); o.viscosity[side]=array(r.viscosity[side]); o.rho_cp[side]=array(r.rho_cp[side]);
        o.pressure_drop[side]=r.pressure_drop[side]; o.outlet_temperature[side]=r.outlet_temperature[side];
        o.inlet_mass[side]=r.inlet_mass[side]; o.duty[side]=r.duty[side];
        const auto& s=p.sides[side];
        owner.inlet[side].assign(s.inlet_profile.data,s.inlet_profile.data+s.inlet_profile.size);
        owner.outlet[side].assign(s.outlet_profile.data,s.outlet_profile.data+s.outlet_profile.size);
    }
    thermal(o.main,owner,r.thermal,0,p.thermal_mode);
    o.main.nx=p.grid.nx; o.main.ny=p.grid.ny; o.main.dx=array(owner.dx); o.main.dy=array(owner.dy);
    o.main.epsilon=array(owner.epsilon);
    for (std::size_t side=0;side<2;++side) {
        o.main.uc[side]=array(r.flow[side].uc); o.main.vc[side]=array(r.flow[side].vc);
        o.main.inlet_profile[side]=array(owner.inlet[side]); o.main.outlet_profile[side]=array(owner.outlet[side]);
    }
    if (r.refined) {
        const auto& f=*r.refined;
        o.have_fine=1; o.fine_accepted=f.accepted; o.fine_extrapolated=f.extrapolated; o.fine_warning=f.warning;
        thermal(o.fine,owner,f.thermal,1,p.thermal_mode);
        o.fine.nx=f.dx.size(); o.fine.ny=f.dy.size(); o.fine.dx=array(f.dx); o.fine.dy=array(f.dy); o.fine.epsilon=array(f.epsilon);
        for (std::size_t side=0;side<2;++side) {
            o.fine.uc[side]=array(f.uc[side]); o.fine.vc[side]=array(f.vc[side]);
            o.fine.inlet_profile[side]=array(f.inlet_profile[side]); o.fine.outlet_profile[side]=array(f.outlet_profile[side]);
            o.fine_duty[side]=f.duty[side]; o.extrapolated_duty[side]=f.extrapolated_duty[side];
        }
    }
    for (const auto& h:r.outer_history) {
        owner.outer.push_back({h.iteration,h.thermal_iterations,
        static_cast<uint32_t>(h.thermal_converged),static_cast<uint32_t>(h.outer_converged),
        {h.relative_density_change[0],h.relative_density_change[1]},
        {h.temperature_change[0],h.temperature_change[1],h.temperature_change[2]}});
        owner.energy_outer.push_back({static_cast<uint32_t>(h.enthalpy_algorithm.value_or(EnthalpyAlgorithm::legacy_h_fou)),
            h.thermal_temperature_update.has_value()?1u:0u,h.thermal_temperature_update.value_or(0.),
            h.thermal_picard_relaxation.value_or(1.)});
    }
    o.outer_history=owner.outer.data(); o.outer_history_count=owner.outer.size();
    o.q_total=r.q_total; o.q_solid=r.q_solid; o.energy_imbalance=r.energy_imbalance;
    for (std::size_t side=0;side<2;++side) o.nu_observations[side]=nu_observation_view(r.nu_observations[side]);
    for (const auto& record:r.range_observations) owner.ranges.push_back(range_observation_view(record));
    o.range_observations=owner.ranges.data(); o.range_observation_count=owner.ranges.size();
}
int solve(
    const size_t* shape,const double* const* arrays,const size_t* sizes,
    const tpmshx_full_2d_config_v2* config,const tpmshx_energy_options_v1* energy,
    const tpmshx_full_2d_callbacks_v2* callbacks,
    tpmshx_full_2d_result_v2* result,char* error,size_t error_capacity) {
    if (!error || !error_capacity) return 1;
    try {
        if (!shape || !arrays || !sizes || !config || !result) throw std::invalid_argument("null full2D argument");
        const auto& c=*config;
        for (auto value:{c.asymmetric,c.have_solid_seed,c.pressure_shooting,c.red_black,c.spatial_geometry,
                        c.massflux_inlet,c.close_outlet_on_exit}) flag(value);
        const auto v=[&](std::size_t i) { return ArrayView<const double>{arrays[i],sizes[i]}; };
        Full2DProblem p{}; p.grid={shape[0],shape[1],1,v(0),v(1),v(2)};
        p.fluid_conductivity={v(3),v(4)}; p.solid_conductivity=v(5); p.total_porosity=v(6);
        p.area_density=v(7); p.hydraulic_diameter=v(8); p.cell_length=v(9);
        p.nu_geometry_ratio=v(28);
        p.topology=static_cast<Topology>(c.topology); p.thermal_mode=static_cast<Full2DThermalMode>(c.thermal_mode);
        p.asymmetric=c.asymmetric; p.reference_cell_length=c.reference_cell_length; p.reference_porosity=c.reference_porosity;
        p.split_a=c.split_a; p.sco2_nu_multiplier=c.sco2_nu_multiplier;
        p.spatial_geometry=c.spatial_geometry;
        if (c.have_solid_seed) p.initial_solid_temperature=c.solid_seed;
        for (std::size_t side=0;side<2;++side) {
            const auto& s=c.sides[side]; flag(s.uniform_inlet); const std::size_t a=10+9*side;
            p.sides[side]={static_cast<Fluid>(s.fluid),static_cast<int>(s.direction),
                s.inlet_temperature,s.inlet_pressure,s.inlet_velocity,s.initial_viscosity,s.seed_permeability,s.seed_forchheimer,
                v(a),v(a+1),v(a+2),v(a+3),v(a+4),v(a+5),v(a+6),v(a+7),v(a+8),
                s.inlet_lo,s.inlet_hi,s.outlet_lo,s.outlet_hi,s.uniform_inlet!=0,
                s.side_area_density,s.side_hydraulic_diameter,s.reference_area_density,s.reference_hydraulic_diameter};
        }
        Full2DControl control{};
        control.flow={c.simple_iterations,c.simple_sweeps,c.alpha_velocity,c.alpha_pressure,c.alpha_density,0.,c.gas_constant,
            c.cf_anisotropy,true,c.massflux_inlet!=0,c.close_outlet_on_exit!=0,
            {c.f2.momentum_tolerance,c.f2.local_mass_tolerance,c.f2.global_mass_tolerance,c.f2.backflow_maximum,
             c.f2.velocity_check_tolerance,c.f2.stall_ratio,c.f2.confirmations,c.f2.momentum_interval,c.f2.stall_window}};
        control.outer_iterations=c.outer_iterations; control.thermal_iterations=c.thermal_iterations; control.thermal_chunk=c.thermal_chunk;
        control.outer_temperature_tolerance=c.outer_temperature_tolerance; control.outer_density_tolerance=c.outer_density_tolerance;
        control.outer_relaxation=c.outer_relaxation; control.thermal_q_tolerance=c.thermal_q_tolerance;
        control.enthalpy_update_tolerance=c.enthalpy_update_tolerance; control.pressure_shooting=c.pressure_shooting;
        control.thermal_red_black=c.red_black; control.envelope_mode=c.envelope_mode?c.envelope_mode:"raise";
        control.table_directory=c.table_directory?c.table_directory:"";
        if(energy) {
            control.enthalpy_algorithm=energy_algorithm(*energy);
            control.temperature_update_tolerance=energy->temperature_update_tolerance;
        }
        control.cancel=cancel; control.progress=progress; control.residual=residual;
        control.context=const_cast<tpmshx_full_2d_callbacks_v2*>(callbacks);
        auto owner=std::make_unique<Owner>(); owner->result=solve_full_2d(p,control);
        tpmshx_full_2d_result_v2 out{}; fill(out,*owner,p);
        out.owner=owner.release(); *result=out; error[0]='\0'; return 0;
    } catch (const WaterStateError& e) { std::snprintf(error,error_capacity,"%s",e.what()); return 2; }
    catch (const ChokedFlowError& e) { std::snprintf(error,error_capacity,"%s",e.what()); return 4; }
    catch (const CoolProp::CoolPropBaseError& e) { std::snprintf(error,error_capacity,"%s",e.what()); return 1; }
    catch (const std::invalid_argument& e) { std::snprintf(error,error_capacity,"%s",e.what()); return 1; }
    catch (const std::domain_error& e) { std::snprintf(error,error_capacity,"%s",e.what()); return 3; }
    catch (const std::exception& e) { std::snprintf(error,error_capacity,"%s",e.what()); return 5; }
    catch (...) { std::snprintf(error,error_capacity,"unexpected full2D native exception"); return 5; }
}
tpmshx_full_2d_energy_state_v1 energy_state(const Full2DThermalState& state) {
    tpmshx_full_2d_energy_state_v1 out{};
    const auto* e=std::get_if<EnthalpyResult>(&state.result);
    if(!e)return out;
    out.energy=energy_c_view(*e);
    out.available=e->stop!=EnthalpyStop::cancelled && e->algorithm!=EnthalpyAlgorithm::legacy_h_fou
        && e->final_audit.has_value();
    if(out.available)for(std::size_t s=0;s<2;++s) {
        out.actual_conductivity[s]=array(state.actual_conductivity[s]);
        for(std::size_t f=0;f<6;++f)out.boundary_power[s][f]=array(state.enthalpy_boundary_power[s][f]);
    }
    return out;
}
} // namespace
extern "C" uint32_t TPMSHX_THERMAL_CALL tpmshx_full_2d_abi_version(void) { return TPMSHX_FULL_2D_ABI_VERSION; }
extern "C" int TPMSHX_THERMAL_CALL tpmshx_solve_full_2d_v2(
    const size_t* shape,const double* const* arrays,const size_t* sizes,
    const tpmshx_full_2d_config_v2* config,const tpmshx_full_2d_callbacks_v2* callbacks,
    tpmshx_full_2d_result_v2* result,char* error,size_t capacity) {
    return solve(shape,arrays,sizes,config,nullptr,callbacks,result,error,capacity);
}
extern "C" int TPMSHX_THERMAL_CALL tpmshx_solve_full_2d_v3(
    const size_t* shape,const double* const* arrays,const size_t* sizes,
    const tpmshx_full_2d_config_v2* config,const tpmshx_energy_options_v1* energy,
    const tpmshx_full_2d_callbacks_v2* callbacks,tpmshx_full_2d_result_v2* result,char* error,size_t capacity) {
    if(!energy) {if(error&&capacity)std::snprintf(error,capacity,"missing conservative energy options");return 1;}
    return solve(shape,arrays,sizes,config,energy,callbacks,result,error,capacity);
}
extern "C" void TPMSHX_THERMAL_CALL tpmshx_full_2d_release_v2(tpmshx_full_2d_result_v2* result) {
    if (!result) return;
    delete static_cast<Owner*>(result->owner); *result={};
}
extern "C" int TPMSHX_THERMAL_CALL tpmshx_full_2d_get_energy_evidence_v1(
    const tpmshx_full_2d_result_v2* result,tpmshx_full_2d_energy_evidence_v1* evidence) {
    if(!result || !result->owner || !evidence)return 1;
    const auto& owner=*static_cast<const Owner*>(result->owner);
    tpmshx_full_2d_energy_evidence_v1 out{};
    if(!owner.result.cancelled) {
        out.main=energy_state(owner.result.thermal);
        if(owner.result.refined)out.fine=energy_state(owner.result.refined->thermal);
        out.outer=owner.energy_outer.data();out.outer_count=owner.energy_outer.size();
    }
    *evidence=out;return 0;
}
