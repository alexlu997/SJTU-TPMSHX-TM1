// Test-only bridge for the typed prepared-data full 3D driver.
#include "tpmshx/full_3d.hpp"
#include "tpmshx/full_3d_state.hpp"
#include "tpmshx/thermal_c_api.h"
#include <algorithm>
#include <cstdio>
#include <memory>
#include <stdexcept>

namespace {
struct Handle {
    tpmshx::Full3DResult result;
    std::size_t cancel_at=0,calls=0;
    bool cancel_before_thermal=false,outer_started=false;
    std::vector<double> progress,scratch;
};
bool cancelled(void* context) {
    auto& h=*static_cast<Handle*>(context);++h.calls;
    return (h.cancel_at>0 && h.calls>=h.cancel_at) || (h.cancel_before_thermal && h.outer_started);
}
void outer_iteration(void* context,std::size_t,std::size_t) {static_cast<Handle*>(context)->outer_started=true;}
void progress(void* context,double percent) {static_cast<Handle*>(context)->progress.push_back(percent);}
}
extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_full_3d_run(
    const std::size_t* shape,double** arrays,const std::size_t* sizes,
    const std::size_t* flags,const double* values,const char* tables,
    void** output,char* error,std::size_t error_size) {
    using namespace tpmshx;
    try {
        const auto v=[&](std::size_t p){return ArrayView<const double>{arrays[p],sizes[p]};};
        Full3DInput input;
        input.geometry={{shape[0],shape[1],shape[2],v(0),v(1),v(2)},v(3),v(4),v(5),v(6),v(7),v(8),v(9),v(10),v(11),
                        values[0],values[1],flags[6]!=0,flags[7]!=0};
        input.topology=static_cast<Topology>(flags[0]);input.solve_b=flags[5]!=0;
        Full3DSide* sides[]{&input.a,&input.b};
        for(std::size_t s=0;s<2;++s) {
            auto& a=*sides[s];a.fluid=static_cast<Fluid>(flags[1+s]);a.direction=static_cast<int>(flags[3+s]);
            for(std::size_t d=0;d<3;++d)a.solver_axes[d]=static_cast<int>(flags[37+3*s+d]);
            a.inlet_temperature=values[2+3*s];a.inlet_pressure=values[3+3*s];a.inlet_velocity=values[4+3*s];
            for(std::size_t d=0;d<4;++d) {
                a.inlet_rectangle[d]=values[8+8*s+d];a.outlet_rectangle[d]=values[12+8*s+d];
                a.heat_transfer_geometry[d]=values[32+4*s+d];
            }
            a.inlet_opening=v(12+2*s);a.outlet_opening=v(13+2*s);
            a.permeability_scale=values[24+2*s];a.forchheimer_scale=values[25+2*s];
            a.dispersion=values[28+s];a.sco2_nusselt_multiplier=values[30+s];
        }
        for(std::size_t s=0;s<3;++s)input.sources[s]=v(16+s);
        Full3DControl c;
        c.max_outer=flags[8];c.initial_simple_iterations=flags[9];c.warm_simple_iterations=flags[10];c.thermal_iterations=flags[11];
        c.pressure_shooting=flags[12];c.variable_rho_cp=flags[13];c.conservative=flags[14];c.strict_mass_balance=flags[15];
        c.force_cell_centered=flags[16];c.refined_port_energy=flags[17];c.red_black_energy=flags[18];
        c.sco2_local_pressure_a=flags[19];c.coarse_bootstrap=flags[20];
        c.coarse_iterations=flags[21];
        c.roughness_mode=static_cast<int>(flags[22]);c.envelope_mode=static_cast<int>(flags[23]);
        c.simple.inner_sweeps=flags[24];c.simple.pressure_rebuild_every=flags[25];c.simple.second_order_upwind=flags[26];
        c.simple.adaptive_pressure_tolerance=flags[27];c.simple.track_momentum=flags[28];
        c.simple.ordering=static_cast<Simple3DOrdering>(flags[29]);
        c.enthalpy.max_iterations=flags[30];c.enthalpy.sweeps=flags[31];
        c.simple.convergence.confirmations=flags[32];c.simple.convergence.momentum_interval=flags[33];c.simple.convergence.stall_window=flags[34];
        c.outer_temperature_tolerance=values[40];c.thermal_relaxation=values[41];
        c.roughness_height=values[42];if(flags[35])c.initial_solid_temperature=values[43];
        c.simple.alpha_velocity=values[44];c.simple.alpha_pressure=values[45];c.simple.alpha_density=values[46];
        c.simple.pressure_diagonal_drift=values[47];c.simple.convergence.momentum_tolerance=values[48];
        c.simple.convergence.local_mass_tolerance=values[49];c.simple.convergence.global_mass_tolerance=values[50];
        c.simple.convergence.backflow_maximum=values[51];c.simple.convergence.velocity_check_tolerance=values[52];
        c.simple.convergence.stall_ratio=values[53];c.enthalpy.omega=values[54];c.enthalpy.update_tolerance=values[55];
        c.enthalpy.table_directory=tables?tables:"";
        auto handle=std::make_unique<Handle>();handle->cancel_at=flags[36];
        handle->cancel_before_thermal=flags[43]!=0;c.outer_iteration=outer_iteration;
        c.cancel=cancelled;c.progress=progress;c.context=handle.get();
        if(flags[44]) {
            auto run=std::make_unique<Full3DRun>(input,c);
            run->advance();
            for(std::size_t step=1;step<flags[44];++step)run->advance();
            const auto record=export_full_3d_state(input,c,run->snapshot());run.reset();
            auto state=import_full_3d_state(input,c,record);
            if(flags[45]==1)state.temperature[0].pop_back();
            if(flags[45]==2)state.phase=Full3DPhase::failed;
            if(flags[45]==3)state.simple[0].reset();
            if(flags[45]==4)state.result.outer.front().outer_index+=1;
            run=std::make_unique<Full3DRun>(input,c,state);
            // The restored owner must not borrow mutable snapshot storage.
            state.temperature[0][0]=-1.;state.result.property_sampling.front().stage="changed";
            while(run->phase()!=Full3DPhase::completed && run->phase()!=Full3DPhase::cancelled)run->advance();
            handle->result=run->take_result();
            bool rejected=false;
            try {run->take_result();}catch(const std::logic_error&) {rejected=true;}
            if(!rejected)throw std::runtime_error("full 3D result was released twice");
        } else handle->result=solve_full_3d(input,c);
        *output=handle.release();
        if(error_size)error[0]='\0';return 0;
    } catch(const std::invalid_argument& e) {
        if(error_size)std::snprintf(error,error_size,"%s",e.what());return 1;
    } catch(const std::domain_error& e) {
        if(error_size)std::snprintf(error,error_size,"%s",e.what());return 2;
    } catch(const std::exception& e) {
        if(error_size)std::snprintf(error,error_size,"%s",e.what());return 3;
    }
}
extern "C" TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL test_full_3d_destroy(void* handle) {
    delete static_cast<Handle*>(handle);
}
extern "C" TPMSHX_THERMAL_API const double* TPMSHX_THERMAL_CALL test_full_3d_field(
    void* handle,std::size_t code,std::size_t* size) {
    const auto& r=static_cast<Handle*>(handle)->result;const std::vector<double>* field=nullptr;
    auto& scratch=static_cast<Handle*>(handle)->scratch;scratch.clear();
    if(code<3)field=&r.thermal.temperature[code];
    else if(code<5)field=&r.thermal.pressure[code-3];
    else if(code<7)field=&r.thermal.hv[code-5];
    else if(code<9)field=&r.thermal.rho_cp[code-7];
    else if(code<11)field=&r.thermal.conductivity[code-9];
    else if(code<17)field=&r.thermal.mass[(code-11)/3][(code-11)%3];
    else if(code<23)field=&r.thermal.face_velocity[(code-17)/3][(code-17)%3];
    else if(code<25)field=&r.thermal.enthalpy[code-23];
    else if(code<27)field=&r.thermal.inlet_capacity[code-25];
    else if(code>=100 && code<180) {
        const auto& f=r.flow[(code-100)/40];const auto k=(code-100)%40;
        const std::vector<double>* fields[]{&f.widths[0],&f.widths[1],&f.widths[2],&f.epsilon,&f.permeability,&f.forchheimer,
            &f.temperature,&f.viscosity,&f.effective_viscosity,&f.density,&f.u,&f.v,&f.w,&f.pressure,&f.pressure_correction,
            &f.d_u,&f.d_v,&f.d_w,&f.inlet_velocity,&f.inlet_opening,&f.outlet_opening,&f.outlet_u_fraction,&f.outlet_w_fraction,
            &f.fixed_inlet_massflux,&f.pressure_real,&f.density_real,&f.velocity_real[0],&f.velocity_real[1],&f.velocity_real[2],
            &f.face_velocity_real[0],&f.face_velocity_real[1],&f.face_velocity_real[2],&f.history.legacy,&f.history.local_mass,&f.history.global_mass};
        if(k<35)field=fields[k];
        else if(k==35) {
            for(const auto& h:f.history.momentum) {
                scratch.push_back(static_cast<double>(h.iteration));scratch.push_back(h.residual.maximum);
                for(const auto& values:{h.residual.component,h.residual.numerator,h.residual.denominator})
                    scratch.insert(scratch.end(),values.begin(),values.end());
            }
            field=&scratch;
        }
    } else if(code==200) {
        for(const auto& h:r.outer) {
            const double start[]{static_cast<double>(h.outer_index),static_cast<double>(h.thermal_iterations),h.thermal_residual,
                                 double(h.thermal_converged),double(h.coupling_converged),h.temperature_change[0],h.temperature_change[1],h.temperature_change[2],
                                 static_cast<double>(h.startup_total_iterations),static_cast<double>(h.rejected_startup_iterations.size())};
            scratch.insert(scratch.end(),std::begin(start),std::end(start));
            for(const auto& p:h.inlet_pressure) {
                const double q[]{double(p.has_value()),p?p->relative_error:0.,double(!p || p->passed)};
                scratch.insert(scratch.end(),std::begin(q),std::end(q));
            }
        }
        field=&scratch;
    } else if(code==201) field=&static_cast<Handle*>(handle)->progress;
    else if(code==203) {
        if(r.thermal.model_h) for(const auto& check:r.thermal.model_h->finishing_checks) {
            scratch.push_back(static_cast<double>(check.iterations));
            for(bool passed:check.gates) scratch.push_back(double(passed));
        }
        field=&scratch;
    }
    else if(code==202) {
        const double q[]{double(r.stop),double(r.converged),double(r.simple_ok),double(r.thermal_ok),double(r.outer_ok),double(r.finite_fields),
            double(r.envelope_ok),double(r.post_after_last_thermal),double(r.thermal.mode),double(r.thermal.outer_index),
            double(static_cast<Handle*>(handle)->calls),double(r.simple_failures.size()),
            r.pressure_drop[0],r.pressure_drop[1],r.outlet_temperature[0],r.outlet_temperature[1],r.inlet_mass[0],r.inlet_mass[1],r.duty[0],r.duty[1],
            r.maximum_mach[0],r.maximum_mach[1],r.minimum_pressure[0],r.minimum_pressure[1]};
        scratch.assign(std::begin(q),std::end(q));
        for(const auto& f:r.flow) {
            const double v[]{f.pressure_reference,double(f.last.stop),double(f.last.converged),double(f.last.iterations),
                f.last.momentum.maximum,f.last.mass.local_residual,f.last.mass.global_residual,f.last.mass.backflow_fraction,
                double(f.last.pressure_clip_hits),double(f.last.post_closure_certified)};
            scratch.insert(scratch.end(),std::begin(v),std::end(v));
        }
        field=&scratch;
    }
    *size=field?field->size():0;return field && !field->empty()?field->data():nullptr;
}
