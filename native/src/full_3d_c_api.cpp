#include "tpmshx/full_3d_c_api.h"
#include "closure_evidence_c_views.hpp"
#include "tpmshx/full_3d.hpp"
#include "model_h_c_views.hpp"
#include "enthalpy_c_views.hpp"
#include "simple_3d_c_views.hpp"
#include <algorithm>
#include <cstdio>
#include <memory>
#include <stdexcept>

namespace {
using namespace tpmshx;
struct Owner {
    Full3DResult result;
    std::array<std::vector<tpmshx_full3d_pressure_iteration_v1>,2> pressure;
    std::array<std::vector<double>,2> momentum;
    std::vector<tpmshx_full3d_outer_v1> outer;
    std::vector<tpmshx_model_h_check_v1> finishing;
    std::vector<std::vector<tpmshx_model_h_check_v1>> outer_finishing;
    std::vector<std::vector<const char*>> startup_reasons;
    std::vector<const char*> failures,warnings,envelope_reasons;
    std::vector<tpmshx_range_observation_v1> ranges;
    std::array<std::vector<tpmshx_full3d_bootstrap_level_v1>,2> bootstrap_levels;
    std::array<tpmshx_full3d_bootstrap_trace_v1,2> bootstrap_traces{};
};
ArrayView<const double> input(tpmshx_full3d_array_v1 a) {return {a.data,a.size};}
tpmshx_full3d_array_v1 array(const std::vector<double>& a) {return {a.data(),a.size()};}
tpmshx_full3d_pressure_state_v1 pressure(const std::optional<PressurePortState>& state) {
    tpmshx_full3d_pressure_state_v1 p{};if(!state)return p;const auto& s=*state;
    p.available=1;p.passed=s.passed;p.specified=s.specified_Pa;p.realized=s.realized_Pa;p.outlet=s.outlet_Pa;
    p.outlet_gauge=s.outlet_gauge_Pa;p.minimum=s.minimum_Pa;p.relative_error=s.relative_error;
    p.relative_tolerance=s.relative_tolerance;p.definition=s.definition.c_str();return p;
}
Full3DSide side(const tpmshx_full3d_side_v1& a) {
    if(a.fluid>2 || a.direction>5)throw std::invalid_argument("invalid full 3D fluid or direction");
    Full3DSide s;s.fluid=static_cast<Fluid>(a.fluid);s.direction=static_cast<int>(a.direction);
    for(std::size_t d=0;d<3;++d) {
        if(a.solver_axes[d]>2)throw std::invalid_argument("invalid full 3D axis");s.solver_axes[d]=static_cast<int>(a.solver_axes[d]);
    }
    s.inlet_temperature=a.inlet_temperature;s.inlet_pressure=a.inlet_pressure;s.inlet_velocity=a.inlet_velocity;
    std::copy(a.inlet_rectangle,a.inlet_rectangle+4,s.inlet_rectangle.begin());
    std::copy(a.outlet_rectangle,a.outlet_rectangle+4,s.outlet_rectangle.begin());
    s.inlet_opening=input(a.inlet_opening);s.outlet_opening=input(a.outlet_opening);
    s.permeability_scale=a.permeability_scale;s.forchheimer_scale=a.forchheimer_scale;
    s.dispersion=a.dispersion;s.sco2_nusselt_multiplier=a.sco2_nusselt_multiplier;
    std::copy(a.heat_transfer_geometry,a.heat_transfer_geometry+4,s.heat_transfer_geometry.begin());return s;
}
bool cancel(void* context) {
    const auto& c=*static_cast<const tpmshx_full3d_callbacks_v1*>(context);return c.cancel&&c.cancel(c.context)!=0;
}
void progress(void* context,double value) {
    const auto& c=*static_cast<const tpmshx_full3d_callbacks_v1*>(context);if(c.progress)c.progress(c.context,value);
}
void outer_iteration(void* context,std::size_t done,std::size_t total) {
    const auto& c=*static_cast<const tpmshx_full3d_callbacks_v1*>(context);if(c.outer_iteration)c.outer_iteration(c.context,done,total);
}
Full3DControl controls(const tpmshx_full3d_control_v1& c,const tpmshx_full3d_callbacks_v1* callbacks) {
    for(auto flag:{c.pressure_shooting,c.variable_rho_cp,c.conservative,c.strict_mass_balance,c.force_cell_centered,
        c.refined_port_energy,c.red_black_energy,c.sco2_local_pressure_a,c.coarse_bootstrap,c.outer_anderson,c.has_initial_solid_temperature,
        c.simple.ideal_gas,c.simple.massflux_inlet,c.simple.second_order_upwind,c.simple.adaptive_pressure_tolerance,c.simple.track_momentum})
        if(flag>1)throw std::invalid_argument("full 3D boolean control must be 0 or 1");
    if(c.roughness_mode>2 || c.envelope_mode>2 || c.simple.ordering>1)
        throw std::invalid_argument("invalid full 3D resolved mode");
    Full3DControl r;r.max_outer=c.max_outer;r.initial_simple_iterations=c.initial_simple_iterations;
    r.warm_simple_iterations=c.warm_simple_iterations;r.thermal_iterations=c.thermal_iterations;
    r.outer_temperature_tolerance=c.outer_temperature_tolerance;r.thermal_relaxation=c.thermal_relaxation;
    r.pressure_shooting=c.pressure_shooting;r.variable_rho_cp=c.variable_rho_cp;r.conservative=c.conservative;
    r.strict_mass_balance=c.strict_mass_balance;r.force_cell_centered=c.force_cell_centered;
    r.refined_port_energy=c.refined_port_energy;r.red_black_energy=c.red_black_energy;r.sco2_local_pressure_a=c.sco2_local_pressure_a;
    r.coarse_bootstrap=c.coarse_bootstrap;r.outer_anderson=c.outer_anderson;
    r.coarse_iterations=c.coarse_iterations;r.anderson_history=c.anderson_history;r.anderson_patience=c.anderson_patience;
    r.anderson_trust=c.anderson_trust;r.roughness_mode=static_cast<int>(c.roughness_mode);r.envelope_mode=static_cast<int>(c.envelope_mode);
    r.roughness_height=c.roughness_height;if(c.has_initial_solid_temperature)r.initial_solid_temperature=c.initial_solid_temperature;
    auto& s=r.simple;const auto& p=c.simple;
    s.max_iterations=p.max_iterations;s.inner_sweeps=p.inner_sweeps;s.pressure_rebuild_every=p.pressure_rebuild_every;
    s.alpha_velocity=p.alpha_velocity;s.alpha_pressure=p.alpha_pressure;s.alpha_density=p.alpha_density;
    s.pressure_reference_absolute=p.pressure_reference_absolute;s.gas_constant=p.gas_constant;s.pressure_diagonal_drift=p.pressure_diagonal_drift;
    s.ideal_gas=p.ideal_gas;s.massflux_inlet=p.massflux_inlet;s.second_order_upwind=p.second_order_upwind;
    s.adaptive_pressure_tolerance=p.adaptive_pressure_tolerance;s.track_momentum=p.track_momentum;
    s.ordering=static_cast<Simple3DOrdering>(p.ordering);const auto& f=p.convergence;
    s.convergence={f.momentum_tolerance,f.local_mass_tolerance,f.global_mass_tolerance,f.backflow_maximum,f.velocity_check_tolerance,
        f.stall_ratio,f.confirmations,f.momentum_interval,f.stall_window};
    r.enthalpy.max_iterations=c.enthalpy_iterations;r.enthalpy.sweeps=c.enthalpy_sweeps;r.enthalpy.omega=c.enthalpy_omega;
    r.enthalpy.update_tolerance=c.enthalpy_update_tolerance;r.enthalpy.table_directory=c.table_directory?c.table_directory:"";
    if(callbacks) {r.cancel=callbacks->cancel?cancel:nullptr;r.progress=callbacks->progress?progress:nullptr;
        r.outer_iteration=callbacks->outer_iteration?outer_iteration:nullptr;r.context=const_cast<tpmshx_full3d_callbacks_v1*>(callbacks);}
    return r;
}
tpmshx_full3d_result_v1 output(Owner& o) {
    const auto& r=o.result;const auto& e=r.thermal;tpmshx_full3d_result_v1 out{};
    out.stop=static_cast<uint32_t>(r.stop);out.converged=r.converged;out.simple_ok=r.simple_ok;out.thermal_ok=r.thermal_ok;
    out.outer_ok=r.outer_ok;out.finite_fields=r.finite_fields;out.envelope_ok=r.envelope_ok;out.post_after_last_thermal=r.post_after_last_thermal;
    out.thermal_mode=static_cast<uint32_t>(e.mode);out.thermal_outer_index=e.outer_index;
    for(std::size_t d=0;d<3;++d)out.temperature[d]=array(e.temperature[d]);
    for(std::size_t s=0;s<2;++s) {
        const auto& f=r.flow[s];auto& v=out.flow[s];
        const auto& trace=f.bootstrap_trace;auto& tv=o.bootstrap_traces[s];
        tv.available=trace.available;tv.selected=trace.selected;
        tv.policy=trace.policy.c_str();tv.decision=trace.decision.c_str();
        std::copy(trace.fine_shape.begin(),trace.fine_shape.end(),tv.fine_shape);
        tv.coarse_iteration_cap=trace.coarse_iteration_cap;tv.recursive_iteration_cap=bootstrap_recursive_iterations;
        tv.auto_cell_threshold=bootstrap_auto_cell_threshold;tv.min_coarse_axis=bootstrap_min_coarse_axis;
        for(const auto& level:trace.levels) {
            tpmshx_full3d_bootstrap_level_v1 row{};row.depth=level.depth;
            std::copy(level.fine_shape.begin(),level.fine_shape.end(),row.fine_shape);
            std::copy(level.coarse_shape.begin(),level.coarse_shape.end(),row.coarse_shape);
            row.iteration_cap=level.iteration_cap;row.charged_iterations=level.charged_iterations;
            row.solve_started=level.solve_started;row.applied=level.applied;
            row.converged=level.converged;row.child_selected=level.child_selected;row.stop=level.stop.c_str();
            o.bootstrap_levels[s].push_back(row);
            if(level.solve_started) {++tv.actual_levels;tv.started_cap_sum+=level.iteration_cap;}
            tv.total_charged_iterations+=level.charged_iterations;
        }
        tv.levels=o.bootstrap_levels[s].data();tv.level_count=o.bootstrap_levels[s].size();
        for(std::size_t d=0;d<3;++d) {v.widths[d]=array(f.widths[d]);v.velocity_real[d]=array(f.velocity_real[d]);v.face_velocity_real[d]=array(f.face_velocity_real[d]);}
        v.epsilon=array(f.epsilon);v.permeability=array(f.permeability);v.forchheimer=array(f.forchheimer);v.temperature=array(f.temperature);
        v.viscosity=array(f.viscosity);v.effective_viscosity=array(f.effective_viscosity);v.density=array(f.density);
        v.u=array(f.u);v.v=array(f.v);v.w=array(f.w);v.pressure=array(f.pressure);v.pressure_correction=array(f.pressure_correction);
        v.d_u=array(f.d_u);v.d_v=array(f.d_v);v.d_w=array(f.d_w);v.inlet_velocity=array(f.inlet_velocity);
        v.inlet_opening=array(f.inlet_opening);v.outlet_opening=array(f.outlet_opening);
        v.outlet_u_fraction=array(f.outlet_u_fraction);v.outlet_w_fraction=array(f.outlet_w_fraction);v.fixed_inlet_massflux=array(f.fixed_inlet_massflux);
        v.pressure_real=array(f.pressure_real);v.density_real=array(f.density_real);v.speed_real=array(f.speed_real);v.pressure_reference=f.pressure_reference;
        v.last=simple_3d_c_view(f.last);v.legacy=array(f.history.legacy);v.local_mass=array(f.history.local_mass);v.global_mass=array(f.history.global_mass);
        for(const auto& h:f.history.momentum) {
            auto& m=o.momentum[s];m.push_back(static_cast<double>(h.iteration));m.push_back(h.residual.maximum);
            for(const auto* values:{&h.residual.numerator,&h.residual.denominator,&h.residual.component})m.insert(m.end(),values->begin(),values->end());
        }
        v.momentum=array(o.momentum[s]);v.inlet_pressure=pressure(f.inlet_pressure);
        for(const auto& p:f.pressure_iterations)o.pressure[s].push_back({p.stage.c_str(),p.anchor_Pa,p.estimate_Pa2.value_or(0.),p.relative_error.value_or(0.),
            p.target_Pa2.value_or(0.),p.step_fraction.value_or(0.),p.estimate_Pa2.has_value(),p.relative_error.has_value(),p.target_Pa2.has_value(),
            p.step_fraction.has_value(),p.method?p.method->c_str():nullptr});
        v.pressure_iterations=o.pressure[s].data();v.pressure_iteration_count=o.pressure[s].size();
        if(f.bootstrap) {const auto& b=*f.bootstrap;v.bootstrap.available=1;v.bootstrap.applied=b.applied;v.bootstrap.converged=b.converged;
            v.bootstrap.iterations=b.iterations;std::copy(b.shape.begin(),b.shape.end(),v.bootstrap.shape);v.bootstrap.residual=b.residual;v.bootstrap.reason=b.reason.c_str();}
        if(r.anderson[s]) {const auto& a=*r.anderson[s];v.anderson={1,a.applied,a.rejected,a.resets,array(a.residuals)};}
        out.thermal_pressure[s]=array(e.pressure[s]);out.hv[s]=array(e.hv[s]);out.rho_cp[s]=array(e.rho_cp[s]);out.conductivity[s]=array(e.conductivity[s]);
        for(std::size_t d=0;d<3;++d) {out.mass[s][d]=array(e.mass[s][d]);out.face_velocity[s][d]=array(e.face_velocity[s][d]);}
        out.inlet_capacity[s]=array(e.inlet_capacity[s]);out.enthalpy[s]=array(e.enthalpy[s]);
        if(e.staggered) {const auto& p=e.staggered->projection[s];const auto& f=e.staggered->residual[s];
            out.staggered[s]={1,p.skipped,p.used_bordered_lu,p.cg_iterations,p.rhs_mean,p.residual_relative,array(f.cells),f.available,
                f.sum,f.maximum,f.exchange,f.global_ratio,f.cell_ratio};}
        out.pressure_drop[s]=r.pressure_drop[s];out.outlet_temperature[s]=r.outlet_temperature[s];out.inlet_mass[s]=r.inlet_mass[s];
        out.duty[s]=r.duty[s];out.maximum_mach[s]=r.maximum_mach[s];out.minimum_pressure[s]=r.minimum_pressure[s];
        out.solid_exchange[s]=r.solid_exchange[s];out.interior_exchange[s]=r.interior_exchange[s];out.physical_mass_in[s]=r.physical_mass_in[s];
        out.physical_mass_out[s]=r.physical_mass_out[s];out.mass_imbalance[s]=r.mass_imbalance[s];
        out.final_conductivity[s]=array(r.final_conductivity[s]);out.final_rho_cp[s]=array(r.final_rho_cp[s]);out.inlet_cp[s]=r.inlet_cp[s];
        out.nu_observations[s]=nu_observation_view(r.nu_observations[s]);
    }
    if(e.model_h) {out.has_model_h=1;model_h_c_views::volume(out.model_h,o.finishing,*e.model_h);
        out.model_h.dimension=3;out.model_h.finishing_checks=o.finishing.data();out.model_h.finishing_count=o.finishing.size();}
    if(e.true_h) {out.has_true_h=1;out.true_h=enthalpy_c_view(*e.true_h);}
    o.outer_finishing.resize(r.outer.size());o.startup_reasons.resize(r.outer.size());
    for(const auto& h:r.outer) {
        tpmshx_full3d_outer_v1 record{};record.outer_index=h.outer_index;record.thermal_iterations=h.thermal_iterations;
        record.thermal_residual=h.thermal_residual;std::copy(h.temperature_change.begin(),h.temperature_change.end(),record.temperature_change);
        for(std::size_t s=0;s<2;++s) {
            record.inlet_pressure[s]=pressure(h.inlet_pressure[s]);record.pressure_reference[s]=h.pressure_reference[s];
            std::copy(h.pressure_range[s].begin(),h.pressure_range[s].end(),record.pressure_range[s]);
        }
        record.thermal_converged=h.thermal_converged;record.coupling_converged=h.coupling_converged;
        record.rejected_startup_iterations=h.rejected_startup_iterations.data();record.rejected_startup_count=h.rejected_startup_iterations.size();
        record.startup_total_iterations=h.startup_total_iterations;
        auto& reasons=o.startup_reasons[o.outer.size()];for(const auto& reason:h.rejected_startup_reasons)reasons.push_back(reason.c_str());
        record.rejected_startup_reasons=reasons.data();
        if(h.model_h) {record.has_model_h=1;auto& checks=o.outer_finishing[o.outer.size()];
            model_h_c_views::volume(record.model_h,checks,*h.model_h);record.model_h.dimension=3;
            record.model_h.finishing_checks=checks.data();record.model_h.finishing_count=checks.size();}
        if(h.true_h) {record.has_true_h=1;record.true_h=enthalpy_c_view(*h.true_h);}
        o.outer.push_back(record);
    }
    out.outer=o.outer.data();out.outer_count=o.outer.size();
    for(const auto& f:r.simple_failures)o.failures.push_back(f.c_str());out.simple_failures=o.failures.data();out.simple_failure_count=o.failures.size();
    for(const auto& w:r.warnings)o.warnings.push_back(w.c_str());out.warnings=o.warnings.data();out.warning_count=o.warnings.size();
    for(const auto& w:r.envelope_reasons)o.envelope_reasons.push_back(w.c_str());
    out.envelope_reasons=o.envelope_reasons.data();out.envelope_reason_count=o.envelope_reasons.size();
    for(const auto& r:r.range_observations)o.ranges.push_back(range_observation_view(r));
    out.range_observations=o.ranges.data();out.range_observation_count=o.ranges.size();
    out.energy_imbalance=r.energy_imbalance;out.interior_duty=r.interior_duty;out.interior_imbalance=r.interior_imbalance;out.enthalpy_imbalance=r.enthalpy_imbalance;
    return out;
}
}
extern "C" {
uint32_t TPMSHX_THERMAL_CALL tpmshx_full_3d_abi_version(void) {return TPMSHX_FULL_3D_ABI_VERSION;}
int TPMSHX_THERMAL_CALL tpmshx_solve_full_3d_v1(const tpmshx_full3d_input_v1* in,const tpmshx_full3d_control_v1* c,
    const tpmshx_full3d_callbacks_v1* callbacks,tpmshx_full3d_result_v1* result,char* error,size_t capacity) {
    if(!error || !capacity)return 1;
    try {
        if(!in || !c || !result)throw std::invalid_argument("null full 3D API argument");
        if(in->topology>1 || in->spatial>1 || in->asymmetric>1 || in->solve_b>1)
            throw std::invalid_argument("invalid full 3D topology or flag");
        Full3DInput data;data.geometry={{in->shape[0],in->shape[1],in->shape[2],input(in->widths[0]),input(in->widths[1]),input(in->widths[2])},
            input(in->epsilon),input(in->epsilon_a),input(in->epsilon_b),input(in->permeability),input(in->forchheimer),input(in->solid_conductivity),
            input(in->cell_length),input(in->area_density),input(in->hydraulic_diameter),in->reference_cell_length,in->reference_hydraulic_diameter,
            in->spatial!=0,in->asymmetric!=0};
        data.topology=static_cast<Topology>(in->topology);data.solve_b=in->solve_b!=0;data.a=side(in->sides[0]);data.b=side(in->sides[1]);
        for(std::size_t s=0;s<3;++s)data.sources[s]=input(in->sources[s]);
        auto owner=std::make_unique<Owner>();owner->result=solve_full_3d(data,controls(*c,callbacks));auto value=output(*owner);
        value.owner=owner.release();*result=value;error[0]='\0';return 0;
    } catch(const WaterStateError& e) {std::snprintf(error,capacity,"%s",e.what());return 2;}
      catch(const std::invalid_argument& e) {std::snprintf(error,capacity,"%s",e.what());return 1;}
      catch(const std::domain_error& e) {std::snprintf(error,capacity,"%s",e.what());return 3;}
      catch(const std::exception& e) {std::snprintf(error,capacity,"%s",e.what());return 4;}
      catch(...) {std::snprintf(error,capacity,"unknown full 3D native failure");return 4;}
}
void TPMSHX_THERMAL_CALL tpmshx_full_3d_release_v1(tpmshx_full3d_result_v1* result) {
    if(result) {delete static_cast<Owner*>(result->owner);*result={};}
}
int TPMSHX_THERMAL_CALL tpmshx_full_3d_get_bootstrap_trace_v1(
    const tpmshx_full3d_result_v1* result,size_t side,tpmshx_full3d_bootstrap_trace_v1* trace) {
    if(!result || !result->owner || side>1 || !trace)return 1;
    *trace=static_cast<const Owner*>(result->owner)->bootstrap_traces[side];return 0;
}
}
