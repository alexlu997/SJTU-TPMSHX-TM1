// Qualification-only bridge. Prepared inputs are borrowed; no Python callback
// performs numerical work. JSON includes every typed coarse result field.
#include "tpmshx/full_2d.hpp"
#include "tpmshx/thermal_c_api.h"

#include <cmath>
#include <atomic>
#include <cstdio>
#include <iomanip>
#include <memory>
#include <sstream>
#include <type_traits>

namespace {
using namespace tpmshx;
struct Json {
    std::ostringstream out;
    std::vector<bool> first;
    Json() { out<<std::setprecision(17); }
    void object() { out<<'{';first.push_back(true); }
    void end() { out<<'}';first.pop_back(); }
    void value(const std::string& s) {
        out<<'"';
        for(char c:s) {
            if(c=='"' || c=='\\') out<<'\\'<<c;
            else if(c=='\n') out<<"\\n";
            else if(c=='\r') out<<"\\r";
            else if(c=='\t') out<<"\\t";
            else out<<c;
        }
        out<<'"';
    }
    void value(const char* s) { value(std::string(s)); }
    void value(bool b) { out<<(b?"true":"false"); }
    void value(double n) {
        if(std::isnan(n)) out<<"NaN";
        else if(std::isinf(n)) out<<(n<0?"-Infinity":"Infinity");
        else out<<n;
    }
    template<class T,std::enable_if_t<std::is_integral_v<T> && !std::is_same_v<T,bool>,int> =0>
    void value(T n) {out<<n;}
    template<class T> void value(const std::vector<T>& values) {
        out<<'[';for(std::size_t i=0;i<values.size();++i) {if(i)out<<',';value(values[i]);}out<<']';
    }
    template<class T,std::size_t N> void value(const std::array<T,N>& values) {
        out<<'[';for(std::size_t i=0;i<N;++i) {if(i)out<<',';value(values[i]);}out<<']';
    }
    template<class T> void value(const std::optional<T>& v) {if(v)value(*v);else out<<"null";}
    void key(const char* k) {if(!first.back())out<<',';first.back()=false;value(k);out<<':';}
    template<class T> void field(const char* k,const T& v) {key(k);value(v);}
};
void write(Json& j,const PressurePortState& s) {
    j.object();
    j.field("specified_Pa",s.specified_Pa);j.field("realized_Pa",s.realized_Pa);
    j.field("outlet_Pa",s.outlet_Pa);j.field("outlet_gauge_Pa",s.outlet_gauge_Pa);j.field("minimum_Pa",s.minimum_Pa);
    j.field("relative_error",s.relative_error);j.field("relative_tolerance",s.relative_tolerance);
    j.field("passed",s.passed);j.field("definition",s.definition);j.end();
}
void write(Json& j,const std::vector<PressureIteration>& values) {
    j.out<<'[';
    for(std::size_t i=0;i<values.size();++i) {
        if(i)j.out<<',';const auto& s=values[i];j.object();j.field("stage",s.stage);j.field("anchor_Pa",s.anchor_Pa);
        if(s.estimate_Pa2)j.field("estimate_Pa2",*s.estimate_Pa2);
        if(s.relative_error)j.field("relative_error",*s.relative_error);
        if(s.target_Pa2)j.field("target_Pa2",*s.target_Pa2);
        if(s.step_fraction)j.field("step_fraction",*s.step_fraction);
        if(s.method)j.field("method",*s.method);
        j.end();
    }
    j.out<<']';
}
void write(Json& j,const SimpleMomentumResidual& s) {
    j.object();j.field("numerator",s.numerator);j.field("denominator",s.denominator);
    j.field("component",s.component);j.field("maximum",s.maximum);j.end();
}
void write(Json& j,const Simple2DResult& s) {
    j.object();j.field("stop",static_cast<int>(s.stop));j.field("converged",s.converged);
    j.field("post_closure_measured",s.post_closure_measured);j.field("post_closure_certified",s.post_closure_certified);
    j.field("iterations",s.iterations);j.field("pressure_clip_hits",s.pressure_clip_hits);
    j.field("legacy_residual",s.legacy_residual);j.key("momentum");write(j,s.momentum);
    j.key("mass");j.object();j.field("local_residual",s.mass.local_residual);j.field("mass_in",s.mass.mass_in);
    j.field("mass_out",s.mass.mass_out);j.field("global_residual",s.mass.global_residual);
    j.field("backflow_fraction",s.mass.backflow_fraction);j.field("counted_cells",s.mass.counted_cells);j.end();
    const auto& p=s.linear;j.key("linear");j.object();j.field("success",p.success);j.field("method",p.method);
    j.field("exit",p.exit);j.field("amg_exit",p.amg_exit);j.field("rebuild_reason",p.rebuild_reason);j.field("detail",p.detail);
    j.field("x",p.x);j.field("iterations",p.iterations);j.field("rebuild_count",p.rebuild_count);
    j.field("hierarchy_bytes",p.hierarchy_bytes);j.field("superlu_info",p.superlu_info);
    j.field("rhs_scale",p.rhs_scale);j.field("relative_residual",p.relative_residual);
    j.field("absolute_residual",p.absolute_residual);j.field("iterative_relative_residual",p.iterative_relative_residual);
    j.field("pin_max_abs",p.pin_max_abs);j.field("diagonal_drift",p.diagonal_drift);
    j.field("build_seconds",p.build_seconds);j.field("solve_seconds",p.solve_seconds);j.end();j.end();
}
void write(Json& j,const Full2DFlow& f) {
    j.object();
#define FIELD(name) j.field(#name,f.name)
    FIELD(dx);FIELD(dy);FIELD(u);FIELD(v);FIELD(pressure);FIELD(pressure_correction);FIELD(d_u);FIELD(d_v);
    FIELD(density);FIELD(inlet_velocity);FIELD(viscosity);FIELD(effective_viscosity);FIELD(temperature);FIELD(epsilon);
    FIELD(reference_pressure);FIELD(taper_flux_scale);FIELD(massflux_target);FIELD(uc);FIELD(vc);FIELD(absolute_pressure);FIELD(mass_x);FIELD(mass_y);
#undef FIELD
    j.key("result");write(j,f.result);j.key("pressure_state");if(f.pressure_state)write(j,*f.pressure_state);else j.out<<"null";
    j.key("pressure_iterations");write(j,f.pressure_iterations);
    j.key("history");j.object();j.field("legacy",f.history.legacy);j.field("local_mass",f.history.local_mass);
    j.field("global_mass",f.history.global_mass);j.key("momentum");j.out<<'[';
    for(std::size_t i=0;i<f.history.momentum.size();++i) {
        if(i)j.out<<',';j.object();j.field("iteration",f.history.momentum[i].iteration);
        j.key("residual");write(j,f.history.momentum[i].residual);j.end();
    }
    j.out<<']';j.end();j.end();
}
void write(Json& j,const ModelHSideAudit2D& a) {
    j.object();
#define FIELD(name) j.field(#name,a.name)
    FIELD(q_advective);FIELD(inlet_conduction);FIELD(exchange);FIELD(residual_sum);FIELD(residual_max);
    FIELD(linearized_sum);FIELD(linearized_max);FIELD(defect_sum);FIELD(defect_max);FIELD(mass_net);FIELD(mass_local_max);
    FIELD(mass_in);FIELD(mass_out);FIELD(normalization);FIELD(cell_ratio);FIELD(unknown_inflow_faces);
    FIELD(boundary_mass_out);FIELD(boundary_h_out);FIELD(h_faces);FIELD(inlet_conduction_faces);FIELD(residual);
    FIELD(linearization_defect);FIELD(cp_coefficients);
#undef FIELD
    j.end();
}
void write(Json& j,const ModelHAudit2D& a) {
    j.object();j.key("sides");j.out<<'[';write(j,a.sides[0]);j.out<<',';write(j,a.sides[1]);j.out<<']';
#define FIELD(name) j.field(#name,a.name)
    FIELD(solid_residual);FIELD(solid_sum);FIELD(solid_max);FIELD(solid_cell_ratio);FIELD(residual_sum);FIELD(telescoping_error);
    FIELD(net_boundary_in);FIELD(denominator);FIELD(energy_imbalance);FIELD(solid_imbalance);
    FIELD(boundary_complete);FIELD(finite);FIELD(energy_ok);FIELD(solid_ok);FIELD(equations_ok);FIELD(passed);
#undef FIELD
    j.end();
}
void write(Json& j,const ModelHResult2D& r) {
    j.object();j.field("mode","model_h");j.field("stop",static_cast<int>(r.stop));j.field("iterations",r.iterations);
    j.field("residual",r.residual);j.field("q_b",r.q_b);j.field("audit_available",r.audit_available);
    j.key("audit");if(r.audit_available)write(j,r.audit);else j.out<<"null";
    j.field("last_a",r.last_a);j.field("last_b",r.last_b);j.key("finishing_checks");j.out<<'[';
    for(std::size_t i=0;i<r.finishing_checks.size();++i) {
        if(i)j.out<<',';const auto& c=r.finishing_checks[i];j.object();j.field("iterations",c.iterations);
        j.field("passed",c.passed);j.field("equations_ok",c.equations_ok);j.end();
    }
    j.out<<']';j.end();
}
void write(Json& j,const TemperatureResult& r) {
    j.object();j.field("mode","temperature");j.field("stop",static_cast<int>(r.stop));j.field("iterations",r.iterations);
    j.field("residual",r.residual);j.field("q_b",r.q_b);j.end();
}
void write(Json& j,const EnthalpyResult& r) {
    j.object();j.field("mode","true_h");j.field("stop",static_cast<int>(r.stop));j.field("iterations",r.iterations);
    j.field("residual",r.residual);j.field("q_a",r.q_a);j.field("q_b",r.q_b);j.field("energy_imbalance",r.energy_imbalance);
    j.field("inlet_enthalpy",r.inlet_enthalpy);j.field("last_clips",std::array<std::uint64_t,2>{r.last_clips.a,r.last_clips.b});
    j.field("total_clips",std::array<std::uint64_t,2>{r.total_clips.a,r.total_clips.b});
    j.field("used_bicubic",r.used_bicubic);j.field("heos_polish",r.heos_polish);
    j.key("final_audit");
    if(r.final_audit) {
        const auto& a=*r.final_audit;j.object();
        j.field("q_a",a.q_a);j.field("q_b",a.q_b);j.field("net",a.net);j.field("solid_abs_sum",a.solid_abs_sum);
        j.field("denominator",a.denominator);j.field("coupled_ratio",a.coupled_ratio);
        j.field("fluid_abs_sum",std::array<double,2>{a.fluid_abs_sum[0],a.fluid_abs_sum[1]});
        j.field("fluid_cell_max",std::array<double,2>{a.fluid_cell_max[0],a.fluid_cell_max[1]});
        j.field("equation_ratio",a.equation_ratio);j.field("fluid_equations_computed",a.fluid_equations_computed);
        j.end();
    } else j.out<<"null";
    j.end();
}
void write(Json& j,const Full2DThermalState& t) {
    j.object();
#define FIELD(name) j.field(#name,t.name)
    FIELD(temperature);FIELD(hv);FIELD(conductivity);FIELD(pressure);FIELD(rho_cp);FIELD(mass_x);FIELD(mass_y);
    FIELD(inlet_capacity);FIELD(solid_conductivity);FIELD(h_a);FIELD(h_b);
#undef FIELD
    j.key("result");std::visit([&](const auto& value){write(j,value);},t.result);j.end();
}
std::string result_json(const Full2DResult& r) {
    Json j;j.object();j.field("cancelled",r.cancelled);j.field("outer_converged",r.outer_converged);
    j.field("post_after_last_thermal",r.post_after_last_thermal);j.field("iterations",r.iterations);
    j.key("flow");j.out<<'[';write(j,r.flow[0]);j.out<<',';write(j,r.flow[1]);j.out<<']';
    j.key("thermal");write(j,r.thermal);
    j.key("outer_history");j.out<<'[';
    for(std::size_t i=0;i<r.outer_history.size();++i) {
        if(i)j.out<<',';const auto& h=r.outer_history[i];j.object();j.field("iteration",h.iteration);
        j.field("thermal_iterations",h.thermal_iterations);j.field("thermal_converged",h.thermal_converged);
        j.field("outer_converged",h.outer_converged);j.field("relative_density_change",h.relative_density_change);
        j.field("temperature_change",h.temperature_change);j.end();
    }
    j.out<<']';j.key("envelope");j.out<<'[';
    for(std::size_t i=0;i<2;++i) {if(i)j.out<<',';j.object();j.field("valid",r.envelope[i].valid);j.field("reasons",r.envelope[i].reasons);j.end();}
    j.out<<']';j.field("density",r.density);j.field("viscosity",r.viscosity);j.field("rho_cp",r.rho_cp);
    j.field("converged",r.converged);j.field("simple_ok",r.simple_ok);j.field("thermal_ok",r.thermal_ok);
    j.field("envelope_ok",r.envelope_ok);j.field("pair_balance_ok",r.pair_balance_ok);j.field("model_balance_ok",r.model_balance_ok);
    j.field("pressure_drop",r.pressure_drop);j.field("outlet_temperature",r.outlet_temperature);j.field("inlet_mass",r.inlet_mass);
    j.field("duty",r.duty);j.field("q_total",r.q_total);j.field("q_solid",r.q_solid);j.field("energy_imbalance",r.energy_imbalance);
    j.key("refined");
    if(r.refined) {
        const auto& f=*r.refined;j.object();
        j.field("dx",f.dx);j.field("dy",f.dy);j.field("epsilon",f.epsilon);j.field("uc",f.uc);j.field("vc",f.vc);
        j.field("inlet_profile",f.inlet_profile);j.field("outlet_profile",f.outlet_profile);j.key("thermal");write(j,f.thermal);
        j.field("accepted",f.accepted);j.field("extrapolated",f.extrapolated);j.field("warning",f.warning);
        j.field("duty",f.duty);j.field("extrapolated_duty",f.extrapolated_duty);j.end();
    } else j.out<<"null";
    j.end();
    return j.out.str();
}
struct Handle {std::string result;std::size_t cancel_at=0;std::atomic<std::size_t> calls{0};};
bool cancelled(void* context) {auto& h=*static_cast<Handle*>(context);return ++h.calls>=h.cancel_at && h.cancel_at>0;}
}

extern "C" TPMSHX_THERMAL_API int TPMSHX_THERMAL_CALL test_full_2d_run(
    const std::size_t* shape,const double* const* arrays,const std::size_t* sizes,
    const std::size_t* flags,const double* values,const char* tables,const char* envelope,int full,
    void** output,char* error,std::size_t error_size) {
    using namespace tpmshx;*output=nullptr;
    try {
        const auto v=[&](std::size_t i){return ArrayView<const double>{arrays[i],sizes[i]};};
        Full2DProblem p{};p.grid={shape[0],shape[1],1,v(0),v(1),v(2)};
        p.fluid_conductivity={v(3),v(4)};p.solid_conductivity=v(5);p.total_porosity=v(6);
        p.area_density=v(7);p.hydraulic_diameter=v(8);p.cell_length=v(9);
        p.nu_geometry_ratio=v(28);
        p.topology=static_cast<Topology>(flags[0]);p.thermal_mode=static_cast<Full2DThermalMode>(flags[1]);
        p.asymmetric=flags[6]!=0;p.spatial_geometry=flags[23]!=0;
        p.reference_cell_length=values[0];p.reference_porosity=values[1];
        p.split_a=values[2];p.sco2_nu_multiplier=values[3];if(flags[7])p.initial_solid_temperature=values[4];
        for(std::size_t side=0;side<2;++side) {
            auto& s=p.sides[side];const auto a=10+9*side,b=5+14*side;
            s.fluid=static_cast<Fluid>(flags[2+side]);s.direction=static_cast<int>(flags[4+side]);
            s.uniform_inlet=flags[8+side]!=0;s.inlet_temperature=values[b];s.inlet_pressure=values[b+1];
            s.inlet_velocity=values[b+2];s.initial_viscosity=values[b+3];s.seed_permeability=values[b+4];s.seed_forchheimer=values[b+5];
            s.inlet_lo=values[b+6];s.inlet_hi=values[b+7];s.outlet_lo=values[b+8];s.outlet_hi=values[b+9];
            s.side_area_density=values[b+10];s.side_hydraulic_diameter=values[b+11];
            s.reference_area_density=values[b+12];s.reference_hydraulic_diameter=values[b+13];
            s.row_permeability=v(a);s.row_forchheimer=v(a+1);s.permeability=v(a+2);s.forchheimer=v(a+3);
            s.inlet_geometry=v(a+4);s.outlet_geometry=v(a+5);s.inlet_profile=v(a+6);s.outlet_profile=v(a+7);s.outlet_u_fraction=v(a+8);
        }
        Full2DControl c{};c.pressure_shooting=flags[10]!=0;c.thermal_red_black=flags[11]!=0;
        c.flow.massflux_inlet=flags[12]!=0;c.flow.close_outlet_on_exit=flags[13]!=0;
        c.flow.max_iterations=flags[14];c.flow.inner_sweeps=flags[15];c.outer_iterations=flags[16];
        c.thermal_iterations=flags[17];c.thermal_chunk=flags[18];
        c.flow.convergence.confirmations=flags[19];c.flow.convergence.momentum_interval=flags[20];
        c.flow.convergence.stall_window=flags[21];
        c.flow.alpha_velocity=values[33];c.flow.alpha_pressure=values[34];c.flow.alpha_density=values[35];
        c.flow.gas_constant=values[36];c.flow.cf_anisotropy=values[37];
        c.flow.convergence.momentum_tolerance=values[38];c.flow.convergence.local_mass_tolerance=values[39];
        c.flow.convergence.global_mass_tolerance=values[40];c.flow.convergence.backflow_maximum=values[41];
        c.flow.convergence.velocity_check_tolerance=values[42];c.flow.convergence.stall_ratio=values[43];
        c.outer_temperature_tolerance=values[44];c.outer_density_tolerance=values[45];c.outer_relaxation=values[46];
        c.thermal_q_tolerance=values[47];c.enthalpy_update_tolerance=values[48];
        c.table_directory=tables?tables:"";c.envelope_mode=envelope?envelope:"raise";
        auto h=std::make_unique<Handle>();h->cancel_at=flags[22];c.cancel=cancelled;c.context=h.get();
        h->result=result_json(full?solve_full_2d(p,c):solve_full_2d_coarse(p,c));*output=h.release();
        if(error_size)error[0]='\0';return 0;
    } catch(const ChokedFlowError& e) {if(error_size)std::snprintf(error,error_size,"%s",e.what());return 4;}
    catch(const std::invalid_argument& e) {if(error_size)std::snprintf(error,error_size,"%s",e.what());return 1;}
    catch(const std::domain_error& e) {if(error_size)std::snprintf(error,error_size,"%s",e.what());return 2;}
    catch(const std::exception& e) {if(error_size)std::snprintf(error,error_size,"%s",e.what());return 3;}
}
extern "C" TPMSHX_THERMAL_API const char* TPMSHX_THERMAL_CALL test_full_2d_json(void* handle) {
    return static_cast<Handle*>(handle)->result.c_str();
}
extern "C" TPMSHX_THERMAL_API void TPMSHX_THERMAL_CALL test_full_2d_destroy(void* handle) {
    delete static_cast<Handle*>(handle);
}
