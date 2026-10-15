#include "tpmshx/full_2d.hpp"
#include "tpmshx/conservative_energy.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "tpmshx/refinement_2d.hpp"
#include "contiguous_sum.hpp"
#include "model_h_common.hpp"

#include <exception>
#include <condition_variable>
#include <mutex>
#include <numeric>
#include <thread>

namespace tpmshx {
std::array<SidePhysics,2> resolve_full_2d_physics(const Full2DProblem& p) {
    const bool eos=p.thermal_mode==Full2DThermalMode::true_h;
    std::array<SidePhysics,2> selected;
    for(std::size_t side=0;side<2;++side) {
        const auto fluid=p.sides[side].fluid;
        selected[side]={fluid,eos?EnergyRelation::eos_h_TP:EnergyRelation::integral_cp_T,
            eos?ConductivitySource::local_eos:ConductivitySource::prepared,
            !eos?HeatTransferSampling::outer_mean_inlet_reference:
                uses_co2_eos(fluid)?HeatTransferSampling::thermal_local_at_inlet_pressure:
                    HeatTransferSampling::thermal_mean_at_inlet_pressure};
    }
    return selected;
}

namespace {
using Vector=std::vector<double>;
using model_h_common::view;
using detail::contiguous_sum;
namespace data=model_coefficients;
ArrayView<double> writable(Vector& x) { return {x.data(),x.size()}; }
double sum(ArrayView<const double> x) { return std::accumulate(x.data,x.data+x.size,0.); }
// cell_average uses contiguous reductions for its weights and final axis.
double average(ArrayView<const double> values,const GridView& g) {
    Vector weighted(g.ny); const double sx=contiguous_sum(g.dx),sy=contiguous_sum(g.dy);
    for (std::size_t j=0;j<g.ny;++j) {
        double column=0.;
        for (std::size_t i=0;i<g.nx;++i) column+=values[i*g.ny+j]*g.dx[i];
        weighted[j]=(column/sx)*g.dy[j];
    }
    return contiguous_sum(view(weighted))/sy;
}
double maximum(ArrayView<const double> x) { return *std::max_element(x.data,x.data+x.size); }
double minimum(ArrayView<const double> x) { return *std::min_element(x.data,x.data+x.size); }
const char* fluid_name(Fluid fluid) { return fluid==Fluid::air?"air":fluid==Fluid::water?"water":fluid==Fluid::co2?"co2":"sco2"; }
void temperature_ranges(std::vector<RangeObservation>& ledger,Fluid fluid,std::size_t side,
                        const char* source,const char* stage,const char* layout,
                        const std::vector<std::size_t>& shape,ArrayView<const double> temperature,
                        std::initializer_list<const char*> properties) {
    if (uses_co2_eos(fluid)) return; // sCO2 state bounds are fail-loud, not empirical fit warnings.
    for (const auto* property:properties) {
        if (fluid==Fluid::air && std::string(property)=="density") continue;
        const auto bounds=fluid==Fluid::water?data::water_temperature_range:
            std::string(property)=="cp"?data::air_cp_temperature_range:data::air_temperature_range;
        observe_range(ledger,{source,std::string(fluid_name(fluid))+"_"+property,"",stage,layout,side,shape,bounds},temperature);
    }
}
void temperature_state(std::vector<RangeObservation>& ledger,Fluid fluid,std::size_t side,
                       const char* stage,const GridView& grid,ArrayView<const double> temperature) {
    temperature_ranges(ledger,fluid,side,"property_state",stage,"real-cell(x,y)",{grid.nx,grid.ny},temperature,
                       {"density","viscosity","conductivity","cp"});
}
RangeObservation nu_range(const Full2DProblem& p,std::size_t side,bool raw,const char* stage,
                          const char* layout,std::vector<std::size_t> shape) {
    const auto fluid=p.sides[side].fluid;
    const auto bounds=fluid==Fluid::air?data::air_nu_re_range:
        fluid==Fluid::water?data::water_nu_re_range:
        fluid==Fluid::co2?data::co2_nu_re_range:data::sco2_nu_re_range;
    return {raw?"nu_raw":"nu",fluid_name(fluid),p.topology==Topology::diamond?"Diamond":"Gyroid",
            stage,layout,side,std::move(shape),bounds};
}
std::size_t flow_index(std::size_t i,std::size_t j,const GridView& g,int direction) {
    if (direction<2) return j*g.nx+(direction==0?i:g.nx-1-i);
    return i*g.ny+(direction==2?j:g.ny-1-j);
}
Vector to_flow(ArrayView<const double> real,const GridView& g,int direction) {
    Vector result(real.size);
    for (std::size_t i=0;i<g.nx;++i) for (std::size_t j=0;j<g.ny;++j)
        result[flow_index(i,j,g,direction)]=real[i*g.ny+j];
    return result;
}
Vector to_real(ArrayView<const double> field,const GridView& g,int direction) {
    Vector result(field.size);
    for (std::size_t i=0;i<g.nx;++i) for (std::size_t j=0;j<g.ny;++j)
        result[i*g.ny+j]=field[flow_index(i,j,g,direction)];
    return result;
}
void actual_water(PropertyEvaluator& props,Fluid fluid,ArrayView<const double> temperature,
                  ArrayView<const double> pressure,const char* where,std::size_t side) {
    if (fluid!=Fluid::water) return;
    for (std::size_t p=0;p<temperature.size;++p) {
        try { props.check_water(temperature[p],pressure[p]); }
        catch (const WaterStateError& e) {
            throw WaterStateError(std::string(where)+" "+(side==0?"A":"B")+" cell="+std::to_string(p)+": "+e.what());
        }
    }
}
bool cancelled(const Full2DControl& c) { return c.cancel && c.cancel(c.context); }
struct FlowCallback { const Full2DControl& control; std::size_t side; };
bool flow_cancel(void* raw) { return cancelled(static_cast<FlowCallback*>(raw)->control); }
void flow_progress(void* raw,std::size_t it,double residual) {
    const auto& x=*static_cast<FlowCallback*>(raw);
    if (x.control.residual) x.control.residual(x.control.context,x.side,it,residual);
}
void validate(const Full2DProblem& p,const Full2DControl& c) {
    const auto& g=p.grid;
    const auto count=model_h_common::product(g.nx,g.ny);
    if (g.nz!=1 || g.dz.size!=1 || !g.dz.data || g.dz[0]!=1.)
        throw std::invalid_argument("full2D requires unit depth");
    model_h_common::coefficient(g.dx,g.nx,true); model_h_common::coefficient(g.dy,g.ny,true);
    for (auto x:{p.solid_conductivity,p.total_porosity,p.area_density,p.hydraulic_diameter,p.cell_length,p.nu_geometry_ratio})
        model_h_common::coefficient(x,count,true);
    for (auto x:p.fluid_conductivity) model_h_common::coefficient(x,count);
    if (!p.spatial_geometry) for (auto x:{p.fluid_conductivity[0],p.fluid_conductivity[1],
                                         p.solid_conductivity,p.total_porosity})
        if (!std::all_of(x.data,x.data+x.size,[&](double value){return value==x[0];}))
            throw std::invalid_argument("uniform full2D prepared coefficients must be constant");
    if (p.topology!=Topology::diamond && p.topology!=Topology::gyroid)
        throw std::invalid_argument("invalid full2D topology");
    if (p.thermal_mode!=Full2DThermalMode::temperature && p.thermal_mode!=Full2DThermalMode::model_h
        && p.thermal_mode!=Full2DThermalMode::true_h) throw std::invalid_argument("invalid full2D thermal mode");
    if (!std::isfinite(p.split_a) || p.split_a<=0 || p.split_a>=1
        || !std::isfinite(p.sco2_nu_multiplier) || p.sco2_nu_multiplier<=0
        || !std::isfinite(p.reference_cell_length) || p.reference_cell_length<=0
        || !std::isfinite(p.reference_porosity) || p.reference_porosity<=0 || p.reference_porosity>=1)
        throw std::invalid_argument("invalid full2D geometry split or closure controls");
    if (!p.asymmetric && p.split_a!=.5) throw std::invalid_argument("symmetric full2D requires half void per side");
    if (p.initial_solid_temperature && (!std::isfinite(*p.initial_solid_temperature) || *p.initial_solid_temperature<=0))
        throw std::invalid_argument("invalid full2D solid seed");
    for (std::size_t side=0;side<2;++side) {
        const auto& s=p.sides[side];
        if (s.direction<0 || s.direction>3 || (s.fluid!=Fluid::air && s.fluid!=Fluid::water && !uses_co2_eos(s.fluid)))
            throw std::invalid_argument("invalid full2D side direction/fluid");
        if (p.thermal_mode==Full2DThermalMode::model_h && (uses_co2_eos(s.fluid) || p.asymmetric))
            throw std::invalid_argument("full2D model-h requires symmetric air/water");
        for (double value:{s.inlet_temperature,s.inlet_pressure,s.initial_viscosity,s.seed_permeability})
            if (!std::isfinite(value) || value<=0) throw std::invalid_argument("invalid full2D inlet/seed");
        if (!std::isfinite(s.inlet_velocity) || !std::isfinite(s.seed_forchheimer) || s.seed_forchheimer<0)
            throw std::invalid_argument("invalid full2D inlet velocity/drag");
        const std::size_t cross=s.direction<2?g.ny:g.nx,stream=s.direction<2?g.nx:g.ny;
        model_h_common::coefficient(s.row_permeability,stream,true);
        model_h_common::coefficient(s.row_forchheimer,stream);
        if (s.permeability.size || s.forchheimer.size) {
            model_h_common::coefficient(s.permeability,count,true);
            model_h_common::coefficient(s.forchheimer,count);
        }
        for (auto x:{s.inlet_geometry,s.outlet_geometry,s.inlet_profile,s.outlet_profile}) {
            model_h_common::coefficient(x,cross);
            for (std::size_t j=0;j<x.size;++j) if (x[j]>1.) throw std::invalid_argument("full2D opening exceeds one");
        }
        model_h_common::coefficient(s.outlet_u_fraction,cross+1);
        for (std::size_t j=0;j<s.outlet_u_fraction.size;++j)
            if (s.outlet_u_fraction[j]>1.) throw std::invalid_argument("full2D outlet face opening exceeds one");
        if (sum(s.inlet_geometry)<=0 || sum(s.outlet_geometry)<=0 || sum(s.inlet_profile)<=0)
            throw std::invalid_argument("full2D requires open inlet and outlet");
        const auto widths=s.direction<2?g.dy:g.dx;
        const auto inlet=port_fractions_1d(widths,s.inlet_lo,s.inlet_hi,s.uniform_inlet);
        const auto outlet=port_fractions_1d(widths,s.outlet_lo,s.outlet_hi);
        const auto same_port=[&](ArrayView<const double> supplied,const Vector& expected,const char* name) {
            for (std::size_t j=0;j<expected.size();++j)
                if (std::abs(supplied[j]-expected[j])>1e-15+1e-12*std::abs(expected[j]))
                    throw std::invalid_argument(std::string("full2D ")+(side==0?"A ":"B ")+name+
                        " disagrees with its grid and port geometry");
        };
        same_port(s.inlet_geometry,inlet.first,"inlet_geometry");
        same_port(s.inlet_profile,inlet.second,"inlet_profile");
        same_port(s.outlet_geometry,outlet.first,"outlet_geometry");
        same_port(s.outlet_profile,outlet.second,"outlet_profile");
        same_port(s.outlet_u_fraction,port_overlap_1d(widths,s.outlet_lo,s.outlet_hi,true),"outlet_u_fraction");
        if (p.asymmetric) for (double value:{s.side_area_density,s.side_hydraulic_diameter,
                                             s.reference_area_density,s.reference_hydraulic_diameter})
            if (!std::isfinite(value) || value<=0) throw std::invalid_argument("invalid offset-side geometry");
    }
    model_h_common::validate_iteration_overrides(c.model_h_iterations);
    if(c.model_h_iterations.active() && (p.thermal_mode==Full2DThermalMode::true_h
        || uses_co2_eos(p.sides[0].fluid) || uses_co2_eos(p.sides[1].fluid)))
        throw std::invalid_argument("model-h iteration controls require an integral h(T) route");
    if (!c.outer_iterations || !c.thermal_iterations || !c.thermal_chunk)
        throw std::invalid_argument("full2D budgets must be positive");
    for (double value:{c.outer_temperature_tolerance,c.outer_density_tolerance,c.outer_relaxation,
                       c.thermal_q_tolerance,c.enthalpy.update_tolerance})
        if (!std::isfinite(value) || value<=0) throw std::invalid_argument("invalid full2D tolerance/relaxation");
    if (c.outer_relaxation>1) throw std::invalid_argument("full2D outer relaxation exceeds one");
    switch(c.enthalpy.algorithm) {
        case EnthalpyAlgorithm::legacy_h_fou: break;
        case EnthalpyAlgorithm::temperature_fou:
        case EnthalpyAlgorithm::temperature_sou:
            if(p.thermal_mode!=Full2DThermalMode::true_h || c.thermal_red_black)
                throw std::invalid_argument("candidate full2D energy requires the existing true-h route without red-black energy");
            if(!std::isfinite(c.enthalpy.temperature_update_tolerance) || c.enthalpy.temperature_update_tolerance<=0.)
                throw std::invalid_argument("invalid candidate full2D temperature update tolerance");
            break;
        default: throw std::invalid_argument("unknown full2D energy algorithm");
    }
}

const char* energy_port_error(const GridView& g,const Full2DSide& side,
                        const Vector& mass_x,const Vector& mass_y) {
    for(int axis=0;axis<2;++axis) for(bool high:{false,true}) {
        const auto count=axis==0?g.ny:g.nx;
        for(std::size_t q=0;q<count;++q) {
            const double mass=axis==0?mass_x[(high?g.nx*g.ny:0)+q]
                :mass_y[q*(g.ny+1)+(high?g.ny:0)];
            if(mass==0.) continue;
            if(axis!=side.direction/2)
                return "candidate energy mass crosses a non-port boundary";
            const bool inlet=high==static_cast<bool>(side.direction%2);
            if((inlet?side.inlet_geometry:side.outlet_geometry)[q]==0.)
                return "candidate energy mass crosses a closed port face";
            if (!inlet && (high?mass:-mass)<0.)
                return "candidate energy has exterior inflow without a defined inlet state";
        }
    }
    return nullptr;
}

void build_physical_evidence(const Full2DProblem& p,std::size_t side,Full2DFlow& f) {
    const auto& g=p.grid; const auto& s=p.sides[side]; const auto direction=s.direction;
    const std::size_t cross=f.dx.size(),stream=f.dy.size(),count=g.nx*g.ny;
    Vector main(count),transverse(count);
    for (std::size_t a=0;a<cross;++a) for (std::size_t b=0;b<stream;++b) {
        main[a*stream+b]=.5*(f.v[a*(stream+1)+b]+f.v[a*(stream+1)+b+1]);
        transverse[a*stream+b]=.5*(f.u[a*stream+b]+f.u[(a+1)*stream+b]);
    }
    f.uc=to_real(view(direction<2?main:transverse),g,direction);
    f.vc=to_real(view(direction<2?transverse:main),g,direction);
    if (direction%2) for (double& x:direction<2?f.uc:f.vc) x=-x;
    f.absolute_pressure=to_real(view(f.pressure),g,direction);
    double shift=f.reference_pressure;
    if (s.fluid!=Fluid::air) {
        const double depth=1.; const GridView flow_grid{cross,stream,1,view(f.dx),view(f.dy),{&depth,1}};
        const auto state=inlet_pressure_state(flow_grid,view(f.pressure),s.inlet_geometry,s.outlet_geometry,0.,s.inlet_pressure);
        shift=s.inlet_pressure-state.realized_Pa;
    }
    for (double& x:f.absolute_pressure) x+=shift;
    const auto rho=to_real(view(f.density),g,direction);
    const double split=side==0?p.split_a:1.-p.split_a;
    Vector rho_eps(count);
    for (std::size_t k=0;k<count;++k) rho_eps[k]=rho[k]*(p.total_porosity[k]*split);
    f.mass_x.resize((g.nx+1)*g.ny); f.mass_y.resize(g.nx*(g.ny+1));
    for (std::size_t i=0;i<=g.nx;++i) for (std::size_t j=0;j<g.ny;++j) {
        double velocity;
        if (direction<2) velocity=f.v[j*(g.nx+1)+(direction==0?i:g.nx-i)]*(direction==0?1.:-1.);
        else velocity=f.u[i*g.ny+(direction==2?j:g.ny-1-j)];
        const double coefficient=i==0?rho_eps[j]:(i==g.nx?rho_eps[(i-1)*g.ny+j]
            :.5*(rho_eps[(i-1)*g.ny+j]+rho_eps[i*g.ny+j]));
        f.mass_x[i*g.ny+j]=coefficient*velocity*g.dy[j];
    }
    for (std::size_t i=0;i<g.nx;++i) for (std::size_t j=0;j<=g.ny;++j) {
        double velocity;
        if (direction<2) velocity=f.u[j*g.nx+(direction==0?i:g.nx-1-i)];
        else velocity=f.v[i*(g.ny+1)+(direction==2?j:g.ny-j)]*(direction==2?1.:-1.);
        const double coefficient=j==0?rho_eps[i*g.ny]:(j==g.ny?rho_eps[i*g.ny+j-1]
            :.5*(rho_eps[i*g.ny+j-1]+rho_eps[i*g.ny+j]));
        f.mass_y[i*(g.ny+1)+j]=coefficient*velocity*g.dx[i];
    }
}

Full2DFlow prepare_flow(const Full2DProblem& p,const Full2DControl& c,std::size_t side,
                       std::size_t outer,const Full2DResult& current) {
    const auto& g=p.grid; const auto& s=p.sides[side]; const auto& old=current.flow[side];
    const std::size_t count=g.nx*g.ny;
    Full2DFlow f;
    const auto sample_index=static_cast<std::int64_t>(outer);
    const char* sampled_temperature=outer?"previous_thermal_return":"inlet";
    record_property_samples(f.property_sampling,side,sample_index,"flow",
        s.fluid==Fluid::air?"ideal_gas":"outer_property_state",sampled_temperature,
        s.fluid==Fluid::air?"current_SIMPLE_absolute":outer?"previous_thermal_absolute":"inlet",
        s.fluid==Fluid::air?"local_evaluation":"copy_density",{"density"});
    record_property_samples(f.property_sampling,side,sample_index,"flow",
        s.fluid==Fluid::air?"model_resource":"outer_property_state",sampled_temperature,
        s.fluid==Fluid::air||!outer?"inlet":"previous_thermal_absolute",
        s.fluid==Fluid::air?"local_evaluation":"copy_viscosity",{"viscosity"});
    const auto cross=s.direction<2?g.dy:g.dx,stream=s.direction<2?g.dx:g.dy;
    f.dx.assign(cross.data,cross.data+cross.size); f.dy.assign(stream.data,stream.data+stream.size);
    if (s.direction%2) std::reverse(f.dy.begin(),f.dy.end());
    f.density=to_flow(view(current.density[side]),g,s.direction);
    f.viscosity=to_flow(view(current.viscosity[side]),g,s.direction);
    f.temperature=outer?to_flow(view(current.thermal.temperature[side]),g,s.direction):Vector(count,s.inlet_temperature);
    f.epsilon=to_flow(p.total_porosity,g,s.direction); f.effective_viscosity.resize(count);
    PropertyEvaluator local;
    for (std::size_t k=0;k<count;++k) {
        if (s.fluid==Fluid::air) f.viscosity[k]=local.transport(Fluid::air,f.temperature[k],s.inlet_pressure).mu;
        f.effective_viscosity[k]=f.viscosity[k]/f.epsilon[k];
    }
    const bool shooting=s.fluid==Fluid::air && c.pressure_shooting && old.pressure_state.has_value();
    if (shooting) f.pressure_iterations=old.pressure_iterations;
    f.reference_pressure=s.inlet_pressure;
    if (s.fluid==Fluid::air) {
        if (shooting) f.reference_pressure=pressure_shooting_reference(*old.pressure_state,f.pressure_iterations);
        else {
            const double rho=s.inlet_pressure/(c.flow.gas_constant*s.inlet_temperature),mass=rho*std::abs(s.inlet_velocity);
            const double mu=outer?average(view(current.viscosity[side]),g):s.initial_viscosity;
            const double length=sum(stream);
            double drag=mu*mass/std::max(s.seed_permeability,1e-16)+s.seed_forchheimer*mass*mass;
            double estimate=predict_outlet_p_sq(s.inlet_pressure,s.inlet_temperature,drag,length);
            f.reference_pressure=pressure_initial_reference(estimate,s.inlet_pressure,f.pressure_iterations);
            if (maximum(s.row_permeability)!=minimum(s.row_permeability)
                || maximum(s.row_forchheimer)!=minimum(s.row_forchheimer)) {
                drag=0.;
                for (std::size_t b=0;b<stream.size;++b)
                    drag+=mu*mass/std::max(s.row_permeability[b],1e-16)+s.row_forchheimer[b]*mass*mass;
                drag/=static_cast<double>(stream.size);
                estimate=predict_outlet_p_sq(s.inlet_pressure,s.inlet_temperature,drag,length);
                f.pressure_iterations.clear();
                f.reference_pressure=pressure_initial_reference(estimate,s.inlet_pressure,f.pressure_iterations);
            }
        }
    }
    // Preserve np.sum's reduction of the tapered inlet products; a last-bit
    // change here changes the prescribed mass target before the first sweep.
    f.taper_flux_scale=1.; bool differs=false;
    Vector geometry_weights(cross.size),profile_weights(cross.size);
    for (std::size_t a=0;a<cross.size;++a) {
        differs=differs || s.inlet_profile[a]!=s.inlet_geometry[a];
        geometry_weights[a]=s.inlet_geometry[a]*cross[a];
        profile_weights[a]=s.inlet_profile[a]*cross[a];
    }
    const double geometry=contiguous_sum(view(geometry_weights)),profile=contiguous_sum(view(profile_weights));
    if (differs && profile>1e-30 && geometry>0.) f.taper_flux_scale=geometry/profile;
    f.u.assign((cross.size+1)*stream.size,0.); f.v.assign(cross.size*(stream.size+1),0.);
    f.pressure.assign(count,0.); f.pressure_correction.assign(count,0.);
    f.d_u.assign(f.u.size(),0.); f.d_v.assign(f.v.size(),0.);
    f.inlet_velocity.assign(cross.size,s.inlet_velocity*f.taper_flux_scale);
    for (std::size_t a=0;a<cross.size;++a) {
        f.v[a*(stream.size+1)]=f.inlet_velocity[a]*s.inlet_profile[a];
        f.v[a*(stream.size+1)+stream.size]=s.outlet_geometry[a]>0.?f.v[a*(stream.size+1)+stream.size-1]:0.;
    }
    return f;
}

struct FlowRun {
    const Full2DProblem& p;
    FlowCallback callback;
    Full2DFlow flow;
    Vector permeability,forchheimer;
    std::unique_ptr<Simple2DSolver> solver;
    FlowRun(const Full2DProblem& problem,const Full2DControl& control,std::size_t side,
            const Full2DResult& current,const FluidProperties& inlet,const Full2DFlowRunState* saved)
        :p(problem),callback{control,side},flow(saved?saved->flow:prepare_flow(p,control,side,current.iterations,current)) {
        if(saved && !saved->iteration)return;
        auto& f=flow;const auto& s=p.sides[side];
        const auto cross=f.dx.size(),stream=f.dy.size();
        permeability.resize(cross*stream);forchheimer.resize(cross*stream);
        for(std::size_t a=0;a<cross;++a)for(std::size_t b=0;b<stream;++b) {
            const auto k=a*stream+b;
            permeability[k]=s.permeability.size?s.permeability[k]:s.row_permeability[b];
            forchheimer[k]=s.forchheimer.size?s.forchheimer[k]:s.row_forchheimer[b];
        }
        std::vector<unsigned char> open(cross);
        for(std::size_t a=0;a<cross;++a)open[a]=s.outlet_geometry[a]>0.;
        const double depth=1.;const GridView grid{cross,stream,1,view(f.dx),view(f.dy),{&depth,1}};
        solver=std::make_unique<Simple2DSolver>(grid,ArrayView<const unsigned char>{open.data(),open.size()});
        const Simple2DMaterialView material{view(f.epsilon),view(f.viscosity),view(f.effective_viscosity),
            view(permeability),view(forchheimer),view(f.temperature)};
        const Simple2DBoundaryView boundary{s.inlet_profile,s.outlet_u_fraction,s.inlet_velocity,f.taper_flux_scale,inlet.rho};
        const Simple2DStateView fields{writable(f.u),writable(f.v),writable(f.pressure),writable(f.pressure_correction),
            writable(f.d_u),writable(f.d_v),writable(f.density),writable(f.inlet_velocity)};
        auto settings=control.flow;settings.pressure_reference_absolute=f.reference_pressure;
        settings.ideal_gas=s.fluid==Fluid::air;settings.cancel=flow_cancel;settings.progress=flow_progress;
        settings.context=&callback;settings.accelerate_fixed_density=!settings.ideal_gas;
        if(saved) {
            auto state=*saved->iteration;
            for(const auto& field:state.fields)if(!field.empty())
                throw std::invalid_argument("full 2D flow state repeats its physical fields");
            state.fields={f.u,f.v,f.pressure,f.pressure_correction,f.d_u,f.d_v,f.density,f.inlet_velocity};
            solver->restore_active(material,boundary,fields,settings,state);
        } else solver->start(material,boundary,fields,settings);
        finish();
    }
    void finish() {
        if(!solver || solver->phase()==SimplePhase::active)return;
        auto& f=flow;const auto side=callback.side;const auto& s=p.sides[side];
        f.result=solver->take_result();f.history=solver->history();f.massflux_target=solver->massflux_target();
        solver.reset();
        if(f.result.stop==SimpleStop::cancelled)return;
        const double depth=1.;const GridView grid{f.dx.size(),f.dy.size(),1,view(f.dx),view(f.dy),{&depth,1}};
        if(s.fluid==Fluid::air)
            f.pressure_state=inlet_pressure_state(grid,view(f.pressure),s.inlet_geometry,s.outlet_geometry,
                                                 f.reference_pressure,s.inlet_pressure);
        build_physical_evidence(p,side,f);
    }
    void advance(bool complete) {
        do {if(solver) {solver->advance();finish();}}while(complete && solver);
    }
    Full2DFlowRunState snapshot() const {
        Full2DFlowRunState state{flow,{}};
        if(solver) {state.iteration=solver->snapshot_active();state.iteration->fields={};}
        return state;
    }
};

// Keep both workers for the call. Ordinary solves have no per-step barrier.
struct FlowPair {
    std::array<std::unique_ptr<FlowRun>,2> sides;
    std::array<std::thread,2> workers;
    std::array<std::exception_ptr,2> errors;
    std::mutex mutex;
    std::condition_variable work,joined;
    std::size_t generation=0,finished=0;
    bool complete=false,shutdown=false;
    FlowPair(const Full2DProblem& p,const Full2DControl& c,const Full2DResult& r,
             const std::array<FluidProperties,2>& inlet,const std::array<Full2DFlowRunState,2>* saved=nullptr) {
        for(std::size_t side=0;side<2;++side)
            sides[side]=std::make_unique<FlowRun>(p,c,side,r,inlet[side],saved?&(*saved)[side]:nullptr);
        try {
            for(std::size_t side=0;side<2;++side)workers[side]=std::thread([this,side] {
                std::size_t seen=0;
                std::unique_lock<std::mutex> lock(mutex);
                for(;;) {
                    work.wait(lock,[&] {return shutdown || generation!=seen;});
                    if(shutdown)return;
                    seen=generation;const bool drain=complete;lock.unlock();
                    std::exception_ptr error;
                    try {sides[side]->advance(drain);}catch(...) {error=std::current_exception();}
                    lock.lock();errors[side]=error;++finished;joined.notify_one();
                }
            });
        } catch(...) {stop();throw;}
    }
    ~FlowPair() {stop();}
    void stop() {
        {std::lock_guard<std::mutex> lock(mutex);shutdown=true;}
        work.notify_all();for(auto& worker:workers)if(worker.joinable())worker.join();
    }
    void advance(bool drain) {
        std::unique_lock<std::mutex> lock(mutex);
        finished=0;complete=drain;errors={};++generation;work.notify_all();
        joined.wait(lock,[&] {return finished==2;});
        for(const auto& error:errors)if(error)std::rethrow_exception(error);
    }
    bool done() const {return !sides[0]->solver && !sides[1]->solver;}
    bool cancelled() const {
        return sides[0]->flow.result.stop==SimpleStop::cancelled || sides[1]->flow.result.stop==SimpleStop::cancelled;
    }
    std::array<Full2DFlow,2> take_result() {
        stop();return {std::move(sides[0]->flow),std::move(sides[1]->flow)};
    }
    std::array<Full2DFlowRunState,2> snapshot() const {return {sides[0]->snapshot(),sides[1]->snapshot()};}
};

bool thermal_converged(const Full2DThermalState& t) {
    return std::visit([](const auto& r) { return static_cast<int>(r.stop)==0; },t.result);
}
std::size_t thermal_iterations(const Full2DThermalState& t) {
    return std::visit([](const auto& r) { return r.iterations; },t.result);
}
bool thermal_cancelled(const Full2DThermalState& t) {
    if (const auto* h=std::get_if<EnthalpyResult>(&t.result)) return h->stop==EnthalpyStop::cancelled;
    return std::visit([](const auto& r) { return static_cast<int>(r.stop)==2; },t.result);
}

Vector capacity_at_inlet(const GridView& g,int direction,const Full2DThermalState& t,
                         std::size_t side,double cp) {
    const std::size_t cross=direction<2?g.ny:g.nx;
    Vector capacity(cross);
    for (std::size_t k=0;k<cross;++k) {
        const double mass=direction==0?t.mass_x[side][k]:
            direction==1?-t.mass_x[side][g.nx*g.ny+k]:
            direction==2?t.mass_y[side][k*(g.ny+1)]:-t.mass_y[side][k*(g.ny+1)+g.ny];
        capacity[k]=mass*cp;
    }
    return capacity;
}

void prepare_thermal(const Full2DProblem& p,const std::array<SidePhysics,2>& physics,Full2DResult& r,
                     PropertyEvaluator& properties,const std::array<FluidProperties,2>& inlet) {
    const auto& g=p.grid; const std::size_t n=g.nx*g.ny;
    auto& t=r.thermal;
    t.property_sampling.clear();
    const auto outer=static_cast<std::int64_t>(r.iterations);
    t.solid_conductivity.assign(p.solid_conductivity.data,p.solid_conductivity.data+n);
    for (std::size_t side=0;side<2;++side) {
        const auto& s=p.sides[side]; const auto& f=r.flow[side];
        const auto& selected=physics[side];
        const double split=side==0?p.split_a:1.-p.split_a;
        t.hv[side].resize(n); t.conductivity[side].resize(n);
        t.pressure[side]=f.absolute_pressure; t.mass_x[side]=f.mass_x; t.mass_y[side]=f.mass_y;
        t.rho_cp[side]=r.rho_cp[side];
        if (p.thermal_mode==Full2DThermalMode::temperature) {
            t.inlet_capacity[side]=capacity_at_inlet(g,s.direction,t,side,inlet[side].cp);
            t.temperature_cp_coefficients[side]=model_h_common::coefficients(s.fluid);
        }
        double mean_rho=average(view(r.density[side]),g);
        double mean_mu=r.iterations?average(view(r.viscosity[side]),g):s.initial_viscosity;
        const char* provider=selected.transport_provider();
        const char* lagged=r.iterations?"previous_thermal_return":"inlet";
        if (selected.eos_energy()) {
            record_property_samples(t.property_sampling,side,outer,"thermal_hv",provider,lagged,"inlet",
                selected.local_heat_transfer()?"local_evaluation":"volume_mean_after_evaluation",{"density","viscosity"});
            record_property_samples(t.property_sampling,side,outer,"thermal_hv",provider,lagged,"inlet",
                selected.local_heat_transfer()?"local_evaluation":"evaluation_at_volume_mean_temperature",{"conductivity","Pr"});
        } else {
            record_property_samples(t.property_sampling,side,outer,"thermal_hv","outer_property_state",lagged,
                r.iterations?"previous_thermal_absolute":"inlet","volume_mean",{"density","viscosity"});
            record_property_samples(t.property_sampling,side,outer,"thermal_hv",provider,"inlet","inlet",
                "scalar_evaluation",{"conductivity","Pr"});
        }
        if (selected.conductivity==ConductivitySource::prepared)
            record_property_samples(t.property_sampling,side,outer,"thermal","prepared_property_state","inlet","inlet",
                p.asymmetric?"copy_with_side_porosity_ratio":"copy",{"conductivity"});
        if (p.asymmetric)
            record_property_samples(t.property_sampling,side,outer,"thermal_hv_ratio",provider,"inlet","inlet",
                "scalar_evaluation",{"density","viscosity","Pr"});
        auto reference=inlet[side];
        double reference_temperature=s.inlet_temperature;
        if (selected.heat_transfer==HeatTransferSampling::thermal_mean_at_inlet_pressure) {
            Vector rho(n),mu(n),pin(n,s.inlet_pressure);
            actual_water(properties,s.fluid,view(t.temperature[side]),view(pin),"2D h_v property refresh",side);
            for (std::size_t k=0;k<n;++k) {
                const auto prop=properties.transport(selected.transport_fluid,t.temperature[side][k],s.inlet_pressure);
                rho[k]=prop.rho; mu[k]=prop.mu;
            }
            mean_rho=average(view(rho),g); mean_mu=average(view(mu),g);
            reference_temperature=average(view(t.temperature[side]),g);
            reference=properties.transport(selected.transport_fluid,reference_temperature,s.inlet_pressure);
            temperature_ranges(r.range_observations,s.fluid,side,"property","main-hv","real-cell(x,y)",
                {g.nx,g.ny},view(t.temperature[side]),{"density","viscosity"});
            temperature_ranges(r.range_observations,s.fluid,side,"property","main-hv","real-cell(x,y)",
                {},{&reference_temperature,1},{"conductivity"});
        } else if (!selected.eos_energy()) {
            temperature_ranges(r.range_observations,s.fluid,side,"property","main-hv","scalar",{},
                {&s.inlet_temperature,1},{"conductivity"});
        }
        double ratio=1.;
        if (p.asymmetric) {
            temperature_ranges(r.range_observations,s.fluid,side,"property","asym-ratio","scalar",{},
                {&s.inlet_temperature,1},{"density","viscosity"});
            const auto reduced=[&](double area,double diameter,const char* layout) {
                const double dh=std::max(diameter,1e-12);
                const double re=inlet[side].rho*std::abs(s.inlet_velocity)*dh/std::max(inlet[side].mu,1e-30);
                const double nu=fluid_nusselt(s.fluid,p.topology,std::max(re,1.),inlet[side].pr,
                    p.reference_cell_length,dh,p.sco2_nu_multiplier);
                auto raw=nu_range(p,side,true,"asym-ratio",layout,{}),source=nu_range(p,side,false,"asym-ratio",layout,{});
                observe_range_value(raw,re,0); observe_range_value(source,std::max(re,1.),0);
                merge_range_observation(r.range_observations,std::move(raw));
                if (s.fluid!=Fluid::air) temperature_ranges(r.range_observations,s.fluid,side,"property","asym-ratio",layout,
                    {},{&s.inlet_temperature,1},{"viscosity","conductivity","cp"});
                merge_range_observation(r.range_observations,std::move(source));
                return area*std::max(nu,nusselt_floor(s.fluid))/dh;
            };
            const double denominator=reduced(s.reference_area_density,s.reference_hydraulic_diameter,"asym-reference-scalar");
            ratio=denominator>0?reduced(s.side_area_density,s.side_hydraulic_diameter,"asym-side-scalar")/denominator:1.;
        }
        auto raw_re=nu_range(p,side,true,"main-hv","real-cell(x,y)",{g.nx,g.ny});
        auto source_re=nu_range(p,side,false,"main-hv","real-cell(x,y)",{g.nx,g.ny});
        auto pr_range=source_re; pr_range.view="nu_pr"; pr_range.bounds=data::co2_nu_pr_range;
        auto& observation=r.nu_observations[side];
        if (selected.local_heat_transfer()) {
            observation=NuObservation{}; observation.available=true; observation.cells=n; observation.pressure=s.inlet_pressure;
            observation.raw_min=observation.re_min=observation.pr_min=observation.temperature_min=std::numeric_limits<double>::infinity();
            observation.raw_max=observation.re_max=observation.pr_max=observation.temperature_max=-std::numeric_limits<double>::infinity();
        }
        for (std::size_t k=0;k<n;++k) {
            const double speed=std::sqrt(f.uc[k]*f.uc[k]+f.vc[k]*f.vc[k]);
            double re,pr,conductivity;
            if (selected.local_heat_transfer()) {
                const auto props=properties.transport(selected.transport_fluid,t.temperature[side][k],s.inlet_pressure);
                re=props.rho*std::abs(speed)*p.hydraulic_diameter[k]/std::max(props.mu,1e-30);
                pr=props.cp*props.mu/std::max(props.k,1e-30); conductivity=props.k;
            } else {
                re=mean_rho*(std::abs(speed)+1e-12)*p.hydraulic_diameter[k]/mean_mu;
                pr=reference.pr; conductivity=reference.k;
            }
            const double nu=fluid_nusselt_ratio(s.fluid,p.topology,std::max(re,1.),pr,
                                               p.nu_geometry_ratio[k],p.sco2_nu_multiplier);
            observe_range_value(raw_re,re,k); observe_range_value(source_re,std::max(re,1.),k);
            if (s.fluid==Fluid::co2) observe_range_value(pr_range,pr,k);
            if (observation.available) {
                observation.floor_cells+=nu<nusselt_floor(s.fluid);
                observation.raw_min=std::min(observation.raw_min,nu); observation.raw_max=std::max(observation.raw_max,nu);
                observation.re_min=std::min(observation.re_min,re); observation.re_max=std::max(observation.re_max,re);
                observation.pr_min=std::min(observation.pr_min,pr); observation.pr_max=std::max(observation.pr_max,pr);
                observation.temperature_min=std::min(observation.temperature_min,t.temperature[side][k]);
                observation.temperature_max=std::max(observation.temperature_max,t.temperature[side][k]);
            }
            t.hv[side][k]=p.area_density[k]*std::max(nu,nusselt_floor(s.fluid))*conductivity/p.hydraulic_diameter[k];
            if (p.asymmetric) t.hv[side][k]*=ratio;
            t.conductivity[side][k]=p.fluid_conductivity[side][k]*(p.asymmetric?2.*split:1.);
        }
        merge_range_observation(r.range_observations,std::move(raw_re));
        if (s.fluid!=Fluid::air) temperature_ranges(r.range_observations,s.fluid,side,"property","main-hv","real-cell(x,y)",
            {},{&reference_temperature,1},{"viscosity","conductivity","cp"});
        merge_range_observation(r.range_observations,std::move(source_re));
        if (s.fluid==Fluid::co2) merge_range_observation(r.range_observations,std::move(pr_range));
        if (p.thermal_mode==Full2DThermalMode::temperature)
            temperature_ranges(r.range_observations,s.fluid,side,"property","main-inlet","scalar",{},
                               {&s.inlet_temperature,1},{"cp"});
    }
}

struct ThermalRun {
    const Full2DProblem& p;
    Full2DThermalState& t;
    std::array<Vector,2> epsilon;
    Vector z;
    PhysicalHeatLedger audit;
    std::unique_ptr<ModelHRun2D> model_h;
    std::unique_ptr<EnthalpyRun> enthalpy;
    ThermalRun(const Full2DProblem& problem,const std::array<SidePhysics,2>& physics,
               const Full2DControl& c,Full2DThermalState& thermal,std::size_t outer,const char* stage,
               const Full2DThermalRunState* saved=nullptr):p(problem),t(thermal) {
        const auto& g=p.grid;const std::size_t n=g.nx*g.ny;
        const auto budget=c.model_h_iterations.max_iterations?c.model_h_iterations.max_iterations:c.thermal_iterations;
        if(!saved) {
            t.physical_audit.reset();t.model_h_iterations.reset();
            for(std::size_t side=0;side<2;++side)
                record_property_samples(t.property_sampling,side,static_cast<std::int64_t>(outer),stage,
                    physics[side].eos_energy()?"HEOS":"model_resource","current_thermal_iterate",
                    physics[side].eos_energy()?"last_thermal_input_absolute":nullptr,
                    physics[side].eos_energy()?"local_evaluation":"integral_cp_T",{"energy_relation"});
            if(physics[0].conductivity==ConductivitySource::local_eos)
                for(std::size_t side=0;side<2;++side)
                    record_property_samples(t.property_sampling,side,static_cast<std::int64_t>(outer),stage,
                        "HEOS","current_thermal_iterate","last_thermal_input_absolute","local_evaluation",{"conductivity"});
        }
        const TemperatureStateView fields{writable(t.temperature[0]),writable(t.temperature[1]),writable(t.temperature[2])};
        if(physics[0].eos_energy()) {
            if(saved && (!saved->enthalpy || saved->model_h || t.model_h_iterations))
                throw std::invalid_argument("full 2D continuation requires its EOS energy owner");
            z.assign(n*2,0.);
            for(std::size_t side=0;side<2;++side) {
                epsilon[side].resize(n);const double split=side==0?p.split_a:1.-p.split_a;
                for(std::size_t k=0;k<n;++k)epsilon[side][k]=p.total_porosity[k]*split;
                if(c.enthalpy.algorithm!=EnthalpyAlgorithm::legacy_h_fou)
                    if(const auto* error=energy_port_error(g,p.sides[side],t.mass_x[side],t.mass_y[side]))
                        throw std::invalid_argument(error);
            }
            const auto fluid=[&](std::size_t side) {
                return EnthalpySideView{p.sides[side].fluid,p.sides[side].inlet_temperature,p.sides[side].inlet_pressure,
                    view(t.pressure[side]),view(epsilon[side]),view(t.hv[side]),view(t.mass_x[side]),view(t.mass_y[side]),view(z),p.sides[side].direction};
            };
            if(!saved) {t.h_a.resize(n);t.h_b.resize(n);}
            const EnthalpyStateView fields_h{writable(t.h_a),writable(t.h_b),fields.a,fields.b,fields.solid,true,true,true};
            auto control=c.enthalpy;control.cancel=c.cancel;control.context=c.context;
            if(saved) {
                auto state=*saved->enthalpy;
                for(const auto& field:state.fields)if(!field.empty())
                    throw std::invalid_argument("full 2D EOS state repeats its physical fields");
                state.fields={t.h_a,t.h_b,t.temperature[0],t.temperature[1],t.temperature[2]};
                enthalpy=std::make_unique<EnthalpyRun>(g,fluid(0),fluid(1),p.solid_conductivity,fields_h,control,state,&audit);
            } else enthalpy=std::make_unique<EnthalpyRun>(g,fluid(0),fluid(1),p.solid_conductivity,fields_h,control,&audit);
        } else {
            if(saved && (!saved->model_h || saved->enthalpy || !t.model_h_iterations))
                throw std::invalid_argument("full 2D continuation requires its model energy owner");
            const auto fluid=[&](std::size_t side) {
                const TemperatureBoundary boundary{p.sides[side].direction,p.sides[side].inlet_temperature,{},p.sides[side].inlet_geometry,{}};
                return ModelHFluid2D{physics[side].transport_fluid,view(t.conductivity[side]),view(t.hv[side]),
                                    view(t.mass_x[side]),view(t.mass_y[side]),boundary};
            };
            ModelHControl2D control{budget,c.thermal_chunk,c.thermal_q_tolerance,
                true,true,c.thermal_red_black && n>30000,c.cancel,nullptr,c.context};
            if(p.thermal_mode==Full2DThermalMode::temperature) {
                control.second_order_b=false;control.strict_energy_balance=true;
            }
            const auto settings=model_h_common::apply_iteration_tolerances(control,c.model_h_iterations);
            if(saved) {
                const auto& stored=*t.model_h_iterations;
                if(stored.max_iterations!=settings.max_iterations || stored.chunk_iterations!=settings.chunk_iterations
                    || stored.temperature_tolerance!=settings.temperature_tolerance
                    || stored.q_relative_tolerance!=settings.q_relative_tolerance
                    || stored.total_iteration_budget!=settings.total_iteration_budget)
                    throw std::invalid_argument("full 2D energy state differs from its iteration controls");
                auto state=*saved->model_h;
                for(const auto& field:state.iteration.temperature)if(!field.empty())
                    throw std::invalid_argument("full 2D model energy state repeats its physical fields");
                state.iteration.temperature=t.temperature;
                model_h=std::make_unique<ModelHRun2D>(g,fluid(0),fluid(1),p.solid_conductivity,fields,control,state,ArrayView<const double>{},&audit);
            } else {
                t.model_h_iterations=settings;
                model_h=std::make_unique<ModelHRun2D>(g,fluid(0),fluid(1),p.solid_conductivity,fields,control,ArrayView<const double>{},&audit);
            }
        }
        finish();
    }
    void finish() {
        if(model_h && model_h->phase()!=ModelHPhase::active) {
            auto solved=model_h->take_result();model_h.reset();
            if(solved.physical_audit_available)t.physical_audit=std::move(audit);
            if(p.thermal_mode==Full2DThermalMode::model_h)t.result=std::move(solved);
            else {
                t.result=TemperatureResult{solved.stop,solved.iterations,solved.residual,solved.q_b};
                t.temperature_algorithm="model_h_tface_sou_fou_strict_v3";
            }
        }
        if(enthalpy && enthalpy->phase()!=EnthalpyPhase::active) {
            t.result=enthalpy->take_result();enthalpy.reset();
            const auto& solved=std::get<EnthalpyResult>(t.result);const auto& g=p.grid;
            if(solved.stop!=EnthalpyStop::cancelled && solved.final_audit && solved.final_audit->fluid_equations_computed) {
                for(std::size_t side=0;side<2;++side)
                    audit.boundary_complete=audit.boundary_complete && !energy_port_error(g,p.sides[side],t.mass_x[side],t.mass_y[side]);
                t.physical_audit=std::move(audit);
            }
            if(solved.stop!=EnthalpyStop::cancelled && solved.algorithm!=EnthalpyAlgorithm::legacy_h_fou) {
                EnthalpyEOS eos;
                for(std::size_t side=0;side<2;++side) {
                    auto& actual=t.actual_conductivity[side];actual.resize(g.nx*g.ny);
                    for(std::size_t k=0;k<actual.size();++k)
                        actual[k]=epsilon[side][k]*eos.conductivity(p.sides[side].fluid,t.temperature[side][k],t.pressure[side][k]);
                    t.enthalpy_boundary_power[side]=enthalpy_boundary_power(g,view(side==0?t.h_a:t.h_b),
                        {view(t.mass_x[side]),view(t.mass_y[side]),view(z)},solved.inlet_enthalpy[side],
                        solved.algorithm==EnthalpyAlgorithm::temperature_sou);
                }
            }
        }
    }
    bool done() const {return !model_h && !enthalpy;}
    void advance() {
        if(model_h)model_h->advance();else if(enthalpy)enthalpy->advance();
        finish();
    }
    Full2DThermalRunState snapshot() const {
        Full2DThermalRunState saved;
        if(model_h) {saved.model_h=model_h->snapshot();saved.model_h->iteration.temperature={};}
        if(enthalpy) {saved.enthalpy=enthalpy->snapshot();saved.enthalpy->fields={};}
        return saved;
    }
};

} // namespace

namespace {
struct Runtime {
    const Full2DProblem& p;
    const Full2DControl& c;
    const std::array<SidePhysics,2> physics;
    Full2DResult result;
    PropertyEvaluator properties;
    std::array<FluidProperties,2> inlet{};
    std::array<Vector,3> previous;
    std::optional<Full2DProblem> fine_problem;
    std::array<Vector,2> fine_opening;
    double unit_depth=1.;
    std::unique_ptr<FlowPair> flow;
    std::unique_ptr<ThermalRun> thermal;
    Runtime(const Full2DProblem& problem,const Full2DControl& control)
        :p(problem),c(control),physics(resolve_full_2d_physics(problem)) {}
    void initialize();
    void begin_flow();
    void finish_flow();
    void finish_thermal();
    void bind_refinement();
    Full2DControl refinement_control() const;
    void begin_refinement();
    void finish_refinement();
    void finish_coarse();
    void finish();
};

void Runtime::initialize() {
    const auto& g=p.grid;const std::size_t n=g.nx*g.ny;
    for (std::size_t side=0;side<2;++side) {
        const auto& s=p.sides[side]; inlet[side]=properties.evaluate(s.fluid,s.inlet_temperature,s.inlet_pressure);
        temperature_ranges(result.range_observations,s.fluid,side,"property","inlet","scalar",{},
                           {&s.inlet_temperature,1},{"density","cp"});
        record_property_samples(result.property_sampling,side,-1,"initialize",
            uses_co2_eos(s.fluid)?"HEOS":"model_resource","inlet","inlet","scalar_evaluation",{"density","rho_cp"});
        record_property_samples(result.property_sampling,side,-1,"initialize","prepared_property_state",
            "inlet","inlet","copy",{"viscosity"});
        result.density[side].assign(n,inlet[side].rho);
        result.viscosity[side].assign(n,s.initial_viscosity);
        result.rho_cp[side].assign(n,inlet[side].rho*inlet[side].cp);
        result.thermal.temperature[side].assign(n,s.inlet_temperature);
    }
    result.thermal.temperature[2].assign(n,p.initial_solid_temperature.value_or(
        .5*(p.sides[0].inlet_temperature+p.sides[1].inlet_temperature)));
}

void Runtime::begin_flow() {
    if(cancelled(c)) {result.cancelled=true;return;}
    if(c.progress)c.progress(c.context,result.iterations,c.outer_iterations);
    flow=std::make_unique<FlowPair>(p,c,result,inlet);
}

void Runtime::finish_flow() {
    const auto& g=p.grid;const auto outer=result.iterations;
    result.flow=flow->take_result();flow.reset();
    if(cancelled(c) || result.flow[0].result.stop==SimpleStop::cancelled || result.flow[1].result.stop==SimpleStop::cancelled) {
        result.cancelled=true;return;
    }
    for (std::size_t side=0;side<2;++side)
        actual_water(properties,p.sides[side].fluid,view(result.thermal.temperature[side]),
                     view(result.flow[side].absolute_pressure),"2D SIMPLE return",side);
    for (std::size_t side=0;side<2;++side) {
        const auto& f=result.flow[side];
        if (p.sides[side].fluid==Fluid::air)
            temperature_ranges(result.range_observations,Fluid::air,side,"property","main","solver-cell(perp,stream)",
                {f.dx.size(),f.dy.size()},view(f.temperature),{"viscosity"});
    }
    prepare_thermal(p,physics,result,properties,inlet);
    if (p.thermal_mode!=Full2DThermalMode::true_h && (outer || p.initial_solid_temperature))
        for (std::size_t side=0;side<2;++side)
            temperature_state(result.range_observations,p.sides[side].fluid,side,"main-warm",g,
                              view(result.thermal.temperature[side]));
    thermal=std::make_unique<ThermalRun>(p,physics,c,result.thermal,outer,"thermal");
}

void Runtime::finish_thermal() {
    thermal.reset();
    const auto& g=p.grid;const std::size_t n=g.nx*g.ny,outer=result.iterations;
    if (thermal_cancelled(result.thermal)) { result.cancelled=true; return; }
    if (p.thermal_mode!=Full2DThermalMode::true_h)
        for (std::size_t side=0;side<2;++side)
            temperature_state(result.range_observations,p.sides[side].fluid,side,"main-return",g,
                              view(result.thermal.temperature[side]));
    for (std::size_t side=0;side<2;++side)
        actual_water(properties,p.sides[side].fluid,view(result.thermal.temperature[side]),
                     view(result.flow[side].absolute_pressure),"2D energy return",side);
    for (const auto& field:result.thermal.temperature) model_h_common::check(view(field),n);
    std::array<Vector,2> density,rho_cp;
    Full2DOuterRecord record{}; record.iteration=outer; record.thermal_iterations=thermal_iterations(result.thermal);
    record.model_h_iterations=result.thermal.model_h_iterations;
    record.thermal_converged=thermal_converged(result.thermal);
    if(const auto* solved=std::get_if<EnthalpyResult>(&result.thermal.result)) {
        record.enthalpy_algorithm=solved->algorithm;
        record.thermal_temperature_update=solved->temperature_update;
        record.thermal_picard_relaxation=solved->picard_relaxation;
    }
    bool stable=outer>0;
    for (std::size_t side=0;side<2;++side) {
        density[side].resize(n); rho_cp[side].resize(n);
        record_property_samples(result.property_sampling,side,static_cast<std::int64_t>(outer),"property_refresh",
            uses_co2_eos(p.sides[side].fluid)?"HEOS":"model_resource","current_thermal_return",
            "last_thermal_input_absolute","local_evaluation",{"density","rho_cp","viscosity"});
        temperature_ranges(result.range_observations,p.sides[side].fluid,side,"property","property-refresh","real-cell(x,y)",
            {g.nx,g.ny},view(result.thermal.temperature[side]),{"density","cp","viscosity"});
        double numerator=0.,denominator=0.;
        const auto& f=result.flow[side];
        for (std::size_t k=0;k<n;++k) {
            const auto prop=properties.transport(p.sides[side].fluid,result.thermal.temperature[side][k],f.absolute_pressure[k]);
            density[side][k]=prop.rho; rho_cp[side][k]=prop.rho*prop.cp; result.viscosity[side][k]=prop.mu;
            const double weight=std::sqrt(f.uc[k]*f.uc[k]+f.vc[k]*f.vc[k])+1e-12;
            numerator+=std::abs((prop.rho-result.density[side][k])/result.density[side][k])*weight;
            denominator+=weight;
        }
        record.relative_density_change[side]=numerator/denominator;
        stable=stable && record.relative_density_change[side]<c.outer_density_tolerance;
        stable=stable && (!f.pressure_state || f.pressure_state->passed);
    }
    for (std::size_t side=0;side<3;++side) {
        double delta=outer?0.:std::numeric_limits<double>::infinity();
        if (outer) for (std::size_t k=0;k<n;++k)
            delta=std::max(delta,std::abs(result.thermal.temperature[side][k]-previous[side][k]));
        record.temperature_change[side]=delta; stable=stable && delta<c.outer_temperature_tolerance;
        previous[side]=result.thermal.temperature[side];
    }
    record.outer_converged=stable && record.thermal_converged;
    result.outer_history.push_back(record); result.iterations=outer+1;
    if (record.outer_converged) { result.outer_converged=true; return; }
    for (std::size_t side=0;side<2;++side)
        record_property_samples(result.property_sampling,side,static_cast<std::int64_t>(outer),"property_post",
            "outer_property_state","current_thermal_return","last_thermal_input_absolute",
            "outer_relaxation",{"density","rho_cp"});
    // Original post runs even after the last capped thermal call.
    for (std::size_t side=0;side<2;++side) for (std::size_t k=0;k<n;++k) {
        result.density[side][k]=c.outer_relaxation*density[side][k]+(1.-c.outer_relaxation)*result.density[side][k];
        result.rho_cp[side][k]=c.outer_relaxation*rho_cp[side][k]+(1.-c.outer_relaxation)*result.rho_cp[side][k];
    }
}

void Runtime::finish_coarse() {
    const auto& g=p.grid;const std::size_t n=g.nx*g.ny;
    result.post_after_last_thermal=!result.outer_converged;
    if (cancelled(c)) { result.cancelled=true; return; }
    for (std::size_t side=0;side<2;++side) {
        const auto& s=p.sides[side]; const auto& f=result.flow[side];
        if (p.thermal_mode!=Full2DThermalMode::true_h)
            temperature_state(result.range_observations,s.fluid,side,"final",g,view(result.thermal.temperature[side]));
        actual_water(properties,s.fluid,view(result.thermal.temperature[side]),view(f.absolute_pressure),"2D final state",side);
        result.envelope[side]={true,{}};
        if (s.fluid==Fluid::air) {
            Vector speed(n);
            for (std::size_t k=0;k<n;++k) speed[k]=std::sqrt(f.uc[k]*f.uc[k]+f.vc[k]*f.vc[k]);
            result.envelope[side]=gate_solution(minimum(view(f.absolute_pressure)),maximum(view(speed)),s.inlet_temperature,
                c.envelope_mode,side==0?"2D-A":"2D-B",1.,mach_field_max(view(speed),view(result.thermal.temperature[side])));
        }
    }
}
} // namespace

namespace {
std::size_t boundary_cell(const GridView& g,int direction,std::size_t cross,bool outlet) {
    const bool high=(direction%2==0)==outlet;
    return direction<2?(high?g.nx-1:0)*g.ny+cross:cross*g.ny+(high?g.ny-1:0);
}
double solid_duty(const GridView& g,const Full2DThermalState& t) {
    double q=0.;
    for (std::size_t i=0;i<g.nx;++i) for (std::size_t j=0;j<g.ny;++j) {
        const auto k=i*g.ny+j;
        q+=t.hv[1][k]*(t.temperature[2][k]-t.temperature[1][k])*(g.dx[i]*g.dy[j]);
    }
    return q;
}
double temperature_duty(const Full2DThermalState& thermal,std::size_t side) {
    if(!thermal.physical_audit) throw std::logic_error("full2D temperature duty requires its thermal ledger");
    if(!thermal.physical_audit->boundary_complete) return std::numeric_limits<double>::quiet_NaN();
    double q=0.;
    for(const auto& plane:thermal.physical_audit->advective_out[side])
        for(double value:plane) q-=value;
    return q;
}
void Runtime::begin_refinement() {
    auto& r=result;
    r.refined.emplace(); auto& fine=*r.refined;
    const auto& g=p.grid;
    fine.dx=split_refinement_cells(g.dx); fine.dy=split_refinement_cells(g.dy);
    const GridView fg{fine.dx.size(),fine.dy.size(),1,view(fine.dx),view(fine.dy),{&unit_depth,1}};
    const auto interpolate=[&](ArrayView<const double> field) {
        return refine_cell_field_2d(g.dx,g.dy,fg.dx,fg.dy,field);
    };
    const auto geometry=[&](ArrayView<const double> field) {
        return p.spatial_geometry?interpolate(field):Vector(fg.nx*fg.ny,field[0]);
    };
    fine.epsilon=geometry(p.total_porosity);
    fine.thermal.solid_conductivity=geometry(view(r.thermal.solid_conductivity));
    for (std::size_t side=0;side<2;++side) {
        const auto& s=p.sides[side]; const auto cross=s.direction<2?fg.dy:fg.dx;
        fine.inlet_profile[side]=port_fractions_1d(cross,s.inlet_lo,s.inlet_hi,s.uniform_inlet).second;
        fine.outlet_profile[side]=port_fractions_1d(cross,s.outlet_lo,s.outlet_hi).second;
        fine.thermal.temperature[side]=interpolate(view(r.thermal.temperature[side]));
        temperature_state(r.range_observations,s.fluid,side,"richardson-warm",fg,view(fine.thermal.temperature[side]));
        // Python retains scalar rho*cp only for the first main solve; later
        // outer passes own fields. Preserve that source shape in the ledger.
        if (r.iterations==1)
            temperature_ranges(r.range_observations,s.fluid,side,"property","richardson-inlet","scalar",{},
                               {&s.inlet_temperature,1},{"density","cp"});
        if (p.thermal_mode==Full2DThermalMode::temperature)
            temperature_ranges(r.range_observations,s.fluid,side,"property","richardson-inlet","scalar",{},
                               {&s.inlet_temperature,1},{"cp"});
        record_property_samples(fine.thermal.property_sampling,side,static_cast<std::int64_t>((r.iterations-1)),
            "refined_thermal","coarse_thermal_input",nullptr,nullptr,"interpolate",{"hv","rho_cp","pressure"});
        record_property_samples(fine.thermal.property_sampling,side,static_cast<std::int64_t>((r.iterations-1)),
            "refined_thermal","prepared_property_state","inlet","inlet",
            p.spatial_geometry?"interpolate":"broadcast",{"conductivity"});
        fine.thermal.hv[side]=interpolate(view(r.thermal.hv[side]));
        fine.thermal.rho_cp[side]=interpolate(view(r.thermal.rho_cp[side]));
        fine.thermal.conductivity[side]=geometry(p.thermal_mode==Full2DThermalMode::model_h
            ?view(r.thermal.conductivity[side]):p.fluid_conductivity[side]);
        if (p.thermal_mode==Full2DThermalMode::temperature && p.asymmetric)
            for (double& value:fine.thermal.conductivity[side]) value*=2.*(side==0?p.split_a:1.-p.split_a);
        fine.thermal.pressure[side]=interpolate(view(r.thermal.pressure[side]));
        fine.uc[side]=interpolate(view(r.flow[side].uc));
        fine.vc[side]=interpolate(view(r.flow[side].vc));
        actual_water(properties,s.fluid,view(r.thermal.temperature[side]),view(r.thermal.pressure[side]),
                     "Richardson coarse",side);
        actual_water(properties,s.fluid,view(fine.thermal.temperature[side]),view(fine.thermal.pressure[side]),
                     "Richardson warm start",side);
        if (p.thermal_mode==Full2DThermalMode::model_h || p.thermal_mode==Full2DThermalMode::temperature) {
            auto faces=prolong_mass_faces_2d({view(r.thermal.mass_x[side]),view(r.thermal.mass_y[side])},
                                            g.dx,g.dy,fg.dx,fg.dy);
            fine.thermal.mass_x[side]=std::move(faces[0]); fine.thermal.mass_y[side]=std::move(faces[1]);
        }
        if(p.thermal_mode==Full2DThermalMode::temperature) {
            const auto coarse=s.direction<2?g.dy:g.dx;
            fine.thermal.inlet_capacity[side]=refine_inlet_capacity(coarse,cross,view(r.thermal.inlet_capacity[side]));
            fine.thermal.temperature_cp_coefficients[side]=model_h_common::coefficients(s.fluid);
        }
    }
    fine.thermal.temperature[2]=interpolate(view(r.thermal.temperature[2]));
    bind_refinement();
    thermal=std::make_unique<ThermalRun>(*fine_problem,physics,refinement_control(),fine.thermal,r.iterations-1,"refined_thermal");
}

Full2DControl Runtime::refinement_control() const {
    auto control=c;control.thermal_iterations=p.thermal_mode==Full2DThermalMode::model_h?12000:5000;
    control.thermal_chunk=500;control.thermal_q_tolerance=.001;
    return control;
}

void Runtime::bind_refinement() {
    auto& fine=*result.refined;
    fine_problem=p;auto& fp=*fine_problem;
    fp.grid={fine.dx.size(),fine.dy.size(),1,view(fine.dx),view(fine.dy),{&unit_depth,1}};
    fp.total_porosity=view(fine.epsilon);fp.solid_conductivity=view(fine.thermal.solid_conductivity);
    for(std::size_t side=0;side<2;++side) {
        const auto& spec=p.sides[side];const auto widths=spec.direction<2?fp.grid.dy:fp.grid.dx;
        fine_opening[side]=port_fractions_1d(widths,spec.inlet_lo,spec.inlet_hi,spec.uniform_inlet).first;
        fp.sides[side].inlet_geometry=view(fine_opening[side]);
    }
}

void Runtime::finish_refinement() {
    thermal.reset();auto& r=result;auto& fine=*r.refined;
    const auto& g=p.grid;const auto& fg=fine_problem->grid;
    if(thermal_cancelled(fine.thermal)) {r.cancelled=true;return;}
    for (std::size_t side=0;side<2;++side) {
        temperature_state(r.range_observations,p.sides[side].fluid,side,"richardson-return",fg,view(fine.thermal.temperature[side]));
        actual_water(properties,p.sides[side].fluid,view(fine.thermal.temperature[side]),view(fine.thermal.pressure[side]),
                     "Richardson return",side);
    }
    for (const auto& field:fine.thermal.temperature) model_h_common::check(view(field),fg.nx*fg.ny);
    fine.accepted=thermal_converged(fine.thermal);
    if (p.thermal_mode==Full2DThermalMode::model_h) {
        auto& main=std::get<ModelHResult2D>(r.thermal.result).audit;
        auto& refined=std::get<ModelHResult2D>(fine.thermal.result).audit;
        main.passed=main.passed && r.outer_converged;
        refined.passed=refined.passed && r.outer_converged && !r.post_after_last_thermal;
        fine.accepted=fine.accepted && main.passed && refined.passed;
    }
    const auto nan=std::numeric_limits<double>::quiet_NaN();
    for (std::size_t side=0;side<2;++side) {
        if (p.thermal_mode==Full2DThermalMode::model_h) {
            r.duty[side]=std::get<ModelHResult2D>(r.thermal.result).audit.sides[side].q_advective;
            fine.duty[side]=fine.accepted?std::get<ModelHResult2D>(fine.thermal.result).audit.sides[side].q_advective:nan;
        } else {
            r.duty[side]=temperature_duty(r.thermal,side);
            fine.duty[side]=fine.accepted?temperature_duty(fine.thermal,side):nan;
        }
        fine.extrapolated_duty[side]=(4.*std::abs(fine.duty[side])-std::abs(r.duty[side]))/3.;
    }
    fine.extrapolated=fine.accepted && std::isfinite(fine.extrapolated_duty[0]) && std::isfinite(fine.extrapolated_duty[1]);
    if (!fine.extrapolated) for (std::size_t side=0;side<2;++side) fine.extrapolated_duty[side]=std::abs(r.duty[side]);
    r.q_total=nan;
    for (double q:fine.extrapolated_duty) if (std::isfinite(q)) r.q_total=std::isfinite(r.q_total)?std::max(r.q_total,q):q;
    const double user_max=std::max(std::abs(r.duty[0]),std::abs(r.duty[1]));
    const double fine_max=std::max(std::abs(fine.duty[0]),std::abs(fine.duty[1]));
    fine.warning=(std::isfinite(fine_max) && std::abs(user_max-fine_max)/std::max(user_max,1e-12)>.10)
        || !std::isfinite(fine.duty[0]) || !std::isfinite(fine.duty[1]);
    r.q_solid=solid_duty(g,r.thermal);
    if (fine.accepted) r.q_solid=(4.*solid_duty(fg,fine.thermal)-r.q_solid)/3.;
    if (!fine.extrapolated) { fine.warning=true; r.q_solid=solid_duty(g,r.thermal); }
}
} // namespace

namespace {
void Runtime::finish() {
    auto& r=result;
    if (p.thermal_mode==Full2DThermalMode::true_h) {
        const auto& h=std::get<EnthalpyResult>(r.thermal.result);
        r.duty={h.q_a,h.q_b}; r.q_total=std::abs(h.q_a); r.q_solid=std::abs(h.q_b);
    }
    if (r.cancelled) return;
    r.simple_ok=true; r.envelope_ok=true;
    for (std::size_t side=0;side<2;++side) {
        const auto& f=r.flow[side]; const auto& s=p.sides[side];
        const bool candidate=c.enthalpy.algorithm!=EnthalpyAlgorithm::legacy_h_fou || (!r.thermal.temperature_algorithm.empty() && r.thermal.physical_audit.has_value());
        const auto& mass_x=candidate?r.thermal.mass_x[side]:f.mass_x;
        const auto& mass_y=candidate?r.thermal.mass_y[side]:f.mass_y;
        r.simple_ok=r.simple_ok && f.result.converged;
        r.envelope_ok=r.envelope_ok && r.envelope[side].valid;
        double in=0.,out=0.,in_weights=sum(s.inlet_profile),out_weights=sum(s.outlet_profile);
        for (std::size_t k=0;k<f.dx.size();++k) {
            in+=f.pressure[k*f.dy.size()]*s.inlet_profile[k];
            out+=f.pressure[(k+1)*f.dy.size()-1]*s.outlet_profile[k];
        }
        const auto row_mean=[&](bool outlet) {
            double value=0.;
            for (std::size_t k=0;k<f.dx.size();++k) value+=f.pressure[k*f.dy.size()+(outlet?f.dy.size()-1:0)];
            return value/static_cast<double>(f.dx.size());
        };
        r.pressure_drop[side]=(in_weights>1e-12?in/in_weights:row_mean(false))
            -(out_weights>1e-12?out/out_weights:row_mean(true));
        double mass=0.,heat=0.;
        for (std::size_t k=0;k<s.outlet_geometry.size;++k) {
            const int d=s.direction;
            const double outward=d==0?mass_x[p.grid.nx*p.grid.ny+k]:d==1?-mass_x[k]:
                d==2?mass_y[k*(p.grid.ny+1)+p.grid.ny]:-mass_y[k*(p.grid.ny+1)];
            if (s.outlet_geometry[k]>0.) {
                const double w=std::max(outward,0.); mass+=w;
                if (w>0.) heat+=w*r.thermal.temperature[side][boundary_cell(p.grid,d,k,true)];
            }
        }
        if (!std::isfinite(mass) || mass<=0.) throw std::domain_error("2D outlet temperature requires finite positive outward mass flow");
        r.outlet_temperature[side]=heat/mass;
        if (!std::isfinite(r.outlet_temperature[side])) throw std::domain_error("2D outlet temperature is non-finite");
        r.inlet_mass[side]=std::numeric_limits<double>::quiet_NaN();
        if (p.thermal_mode==Full2DThermalMode::model_h)
            r.inlet_mass[side]=std::get<ModelHResult2D>(r.thermal.result).audit.sides[side].mass_in;
        else if (p.thermal_mode==Full2DThermalMode::true_h || (!r.thermal.temperature_algorithm.empty() && r.thermal.physical_audit)) {
            r.inlet_mass[side]=0.; const auto& g=p.grid;
            for (std::size_t j=0;j<g.ny;++j) r.inlet_mass[side]+=std::max(mass_x[j],0.);
            for (std::size_t j=0;j<g.ny;++j) r.inlet_mass[side]+=std::max(-mass_x[g.nx*g.ny+j],0.);
            for (std::size_t i=0;i<g.nx;++i) r.inlet_mass[side]+=std::max(mass_y[i*(g.ny+1)],0.);
            for (std::size_t i=0;i<g.nx;++i) r.inlet_mass[side]+=std::max(-mass_y[i*(g.ny+1)+g.ny],0.);
        }
    }
    r.energy_imbalance=std::abs(r.duty[0]+r.duty[1])/(std::abs(r.duty[0])+std::abs(r.duty[1])+1e-30);
    r.thermal_ok=thermal_converged(r.thermal);
    r.pair_balance_ok=p.thermal_mode!=Full2DThermalMode::true_h || r.energy_imbalance<.05;
    r.model_balance_ok=p.thermal_mode!=Full2DThermalMode::model_h ||
        (std::get<ModelHResult2D>(r.thermal.result).audit.passed && std::get<ModelHResult2D>(r.refined->thermal.result).audit.passed);
    r.converged=r.outer_converged && r.simple_ok && r.thermal_ok && r.envelope_ok && r.pair_balance_ok && r.model_balance_ok
        && (!r.refined || (thermal_converged(r.refined->thermal) && r.refined->extrapolated));
}
} // namespace

struct Full2DRun::Impl {
    Full2DProblem input;
    Full2DControl control;
    Runtime runtime;
    Full2DPhase phase=Full2DPhase::created;
    bool result_taken=false,boundary=true;
    Impl(const Full2DProblem& p,const Full2DControl& c):input(p),control(c),runtime(input,control) {}
};

Full2DRun::Full2DRun(const Full2DProblem& input,const Full2DControl& control) {
    validate(input,control);impl_=std::make_unique<Impl>(input,control);
}
Full2DRun::~Full2DRun()=default;
Full2DPhase Full2DRun::phase() const {return impl_->phase;}

Full2DPhase Full2DRun::advance() {
    advance_impl(true);
    while(impl_->phase==Full2DPhase::flow_boundary || impl_->phase==Full2DPhase::thermal_boundary
        || impl_->phase==Full2DPhase::refinement_boundary)advance_impl(true);
    return impl_->phase;
}

Full2DPhase Full2DRun::advance_step() {return advance_impl(false);}

Full2DPhase Full2DRun::advance_impl(bool complete_flow) {
    if(!impl_->boundary)throw std::logic_error("unfinished full 2D step cannot advance");
    if(impl_->phase==Full2DPhase::completed || impl_->phase==Full2DPhase::cancelled)return impl_->phase;
    if(impl_->phase==Full2DPhase::failed)throw std::logic_error("full 2D failed run cannot advance");
    auto& runtime=impl_->runtime;
    impl_->boundary=false;
    try {
        const auto end_thermal=[&] {
            runtime.finish_thermal();impl_->phase=Full2DPhase::outer_boundary;
            if(!runtime.result.cancelled && (runtime.result.outer_converged
                || runtime.result.iterations==impl_->control.outer_iterations)) {
                runtime.finish_coarse();impl_->phase=Full2DPhase::ready_to_finish;
            }
        };
        const auto end_refinement=[&] {
            runtime.finish_refinement();runtime.finish();impl_->phase=Full2DPhase::completed;
        };
        if(impl_->phase==Full2DPhase::created) {
            runtime.initialize();impl_->phase=Full2DPhase::outer_boundary;
        } else if(impl_->phase==Full2DPhase::ready_to_finish) {
            if(impl_->input.thermal_mode==Full2DThermalMode::true_h) {
                runtime.finish();impl_->phase=Full2DPhase::completed;
            } else {
                runtime.begin_refinement();impl_->phase=Full2DPhase::refinement_boundary;
                if(runtime.thermal->done())end_refinement();
            }
        } else if(impl_->phase==Full2DPhase::outer_boundary) {
            runtime.begin_flow();impl_->phase=Full2DPhase::flow_boundary;
        } else if(impl_->phase==Full2DPhase::flow_boundary) {
            runtime.flow->advance(complete_flow);
            if(runtime.flow->done()) {
                runtime.finish_flow();impl_->phase=Full2DPhase::thermal_boundary;
                if(!runtime.result.cancelled && runtime.thermal->done())end_thermal();
            } else if(runtime.flow->cancelled())runtime.result.cancelled=true;
        } else if(impl_->phase==Full2DPhase::thermal_boundary) {
            runtime.thermal->advance();if(runtime.thermal->done())end_thermal();
        } else if(impl_->phase==Full2DPhase::refinement_boundary) {
            runtime.thermal->advance();if(runtime.thermal->done())end_refinement();
        }
        if(runtime.result.cancelled) {
            runtime.flow.reset();runtime.thermal.reset();impl_->phase=Full2DPhase::cancelled;
        }
        impl_->boundary=true;
    } catch(...) {
        runtime.flow.reset();runtime.thermal.reset();impl_->phase=Full2DPhase::failed;throw;
    }
    return impl_->phase;
}

namespace {
bool saved_boundary(Full2DPhase phase) {
    return phase==Full2DPhase::outer_boundary || phase==Full2DPhase::ready_to_finish
        || phase==Full2DPhase::flow_boundary || phase==Full2DPhase::thermal_boundary
        || phase==Full2DPhase::refinement_boundary;
}
void validate_continuation(const Full2DProblem& p,const Full2DControl& c,const Full2DRunState& state) {
    const auto& r=state.result;const auto& g=p.grid;
    const auto outer=r.outer_history.size(),n=g.nx*g.ny;
    const bool flow_active=state.phase==Full2DPhase::flow_boundary;
    const bool thermal_active=state.phase==Full2DPhase::thermal_boundary;
    const bool refinement=state.phase==Full2DPhase::refinement_boundary;
    const bool ready=state.phase==Full2DPhase::ready_to_finish || refinement;
    if(!saved_boundary(state.phase) || outer>c.outer_iterations
        || r.iterations!=outer || r.cancelled || r.converged
        || r.refined.has_value()!=refinement || state.flow.has_value()!=flow_active
        || state.thermal.has_value()!=(thermal_active || refinement)
        || (refinement && p.thermal_mode==Full2DThermalMode::true_h)
        || (!ready && (r.outer_converged || outer==c.outer_iterations))
        || (ready && (!outer || (!r.outer_converged && outer!=c.outer_iterations)))
        || r.post_after_last_thermal!=(ready && !r.outer_converged))
        throw std::invalid_argument("invalid full 2D continuation position");
    const bool converged=outer && r.outer_history.back().outer_converged;
    if(r.outer_converged!=converged || (converged && !r.outer_history.back().thermal_converged))
        throw std::invalid_argument("full 2D continuation exit differs from its history");
    for(std::size_t i=0;i<outer;++i)
        if(r.outer_history[i].iteration!=i || (i+1<outer && r.outer_history[i].outer_converged))
            throw std::invalid_argument("invalid full 2D continuation history");
    const auto check=[&](const Vector& values,std::size_t size,bool positive=false) {
        if(values.size()!=size || !std::all_of(values.begin(),values.end(),[&](double value) {
            return std::isfinite(value) && (!positive || value>0.);
        }))throw std::invalid_argument("invalid full 2D continuation field");
    };
    const auto check_flow=[&](const Full2DFlow& f,std::size_t side,bool complete) {
        const auto direction=p.sides[side].direction;
        const auto cross=direction<2?g.dy:g.dx,stream=direction<2?g.dx:g.dy;
        check(f.dx,cross.size,true);check(f.dy,stream.size,true);
        for(std::size_t i=0;i<cross.size;++i)if(f.dx[i]!=cross[i])
            throw std::invalid_argument("full 2D continuation grid differs from input");
        for(std::size_t j=0;j<stream.size;++j)if(f.dy[j]!=stream[direction%2?stream.size-1-j:j])
            throw std::invalid_argument("full 2D continuation grid differs from input");
        if(f.epsilon!=to_flow(p.total_porosity,g,direction))
            throw std::invalid_argument("full 2D continuation geometry differs from input");
        for(const auto* field:{&f.density,&f.viscosity,&f.effective_viscosity,&f.temperature})check(*field,n,true);
        for(const auto* field:{&f.pressure,&f.pressure_correction})check(*field,n);
        for(const auto* field:{&f.u,&f.d_u})check(*field,(cross.size+1)*stream.size);
        for(const auto* field:{&f.v,&f.d_v})check(*field,cross.size*(stream.size+1));
        check(f.inlet_velocity,cross.size);check(f.absolute_pressure,complete?n:0,true);
        check(f.uc,complete?n:0);check(f.vc,complete?n:0);
        check(f.mass_x,complete?(g.nx+1)*g.ny:0);check(f.mass_y,complete?g.nx*(g.ny+1):0);
        if(!(f.reference_pressure>0.) || !std::isfinite(f.reference_pressure)
            || !(f.taper_flux_scale>0.) || !std::isfinite(f.taper_flux_scale)
            || (complete && (f.result.stop==SimpleStop::ongoing || f.result.stop==SimpleStop::cancelled
                || f.result.iterations>c.flow.max_iterations))
            || (!complete && (f.pressure_state || f.massflux_target || !f.history.legacy.empty()
                || !f.history.local_mass.empty() || !f.history.global_mass.empty() || !f.history.momentum.empty())))
            throw std::invalid_argument("invalid full 2D continuation flow reference or position");
    };
    const auto check_thermal=[&](const Full2DThermalState& t,const GridView& grid,bool active) {
        const auto count=grid.nx*grid.ny;
        for(const auto& temperature:t.temperature)check(temperature,count,true);
        for(std::size_t side=0;side<2;++side) {
            const auto cross=p.sides[side].direction<2?grid.ny:grid.nx;
            check(t.hv[side],count);check(t.conductivity[side],count);
            check(t.pressure[side],count,true);check(t.rho_cp[side],count,true);
            check(t.mass_x[side],(grid.nx+1)*grid.ny);check(t.mass_y[side],grid.nx*(grid.ny+1));
            check(t.inlet_capacity[side],p.thermal_mode==Full2DThermalMode::temperature?cross:0);
            if(!t.actual_conductivity[side].empty())check(t.actual_conductivity[side],count,true);
        }
        check(t.solid_conductivity,count);
        check(t.h_a,p.thermal_mode==Full2DThermalMode::true_h?count:0);
        check(t.h_b,p.thermal_mode==Full2DThermalMode::true_h?count:0);
        if(active) {
            if(t.physical_audit)throw std::invalid_argument("unfinished full 2D energy state has a final audit");
            return;
        }
        if(t.result.index()!=static_cast<std::size_t>(p.thermal_mode)
            || (p.thermal_mode==Full2DThermalMode::temperature
                ?t.temperature_algorithm!="model_h_tface_sou_fou_strict_v3":!t.temperature_algorithm.empty()))
            throw std::invalid_argument("full 2D continuation energy relation differs from its input");
        if(const auto* h=std::get_if<EnthalpyResult>(&t.result))
            if(h->algorithm!=c.enthalpy.algorithm)
                throw std::invalid_argument("full 2D continuation energy method differs from its input");
        if(const auto* h=std::get_if<ModelHResult2D>(&t.result)) {
            check(h->last_a,count);check(h->last_b,count);
            if(h->audit_available) {
                check(h->audit.solid_residual,count);
                for(const auto& side:h->audit.sides) {
                    check(side.residual,count);check(side.linearization_defect,count);
                    check(side.h_faces[0],(grid.nx+1)*grid.ny);check(side.h_faces[1],grid.nx*(grid.ny+1));
                    for(std::size_t face=0;face<4;++face) {
                        const auto size=face<2?grid.ny:grid.nx;
                        check(side.boundary_mass_out[face],size);check(side.boundary_h_out[face],size);
                    }
                }
            }
        }
        if(t.physical_audit) {
            const auto& ledger=*t.physical_audit;
            const std::size_t sizes[]{grid.ny,grid.ny,grid.nx,grid.nx,count,count};
            for(std::size_t phase=0;phase<3;++phase) {
                check(ledger.residual[phase],count);
                for(std::size_t face=0;face<6;++face) {
                    check(ledger.advective_out[phase][face],sizes[face]);
                    check(ledger.diffusive_out[phase][face],sizes[face]);
                }
            }
        }
    };
    for(std::size_t field=0;field<3;++field) {
        check(r.thermal.temperature[field],n,true);check(state.previous[field],outer?n:0,true);
        if(outer && !thermal_active && state.previous[field]!=r.thermal.temperature[field])
            throw std::invalid_argument("full 2D continuation comparison field differs from its thermal state");
    }
    for(std::size_t side=0;side<2;++side) {
        for(const auto* field:{&r.density[side],&r.viscosity[side],&r.rho_cp[side]})check(*field,n,true);
        const auto& inlet=state.inlet[side];
        for(double value:{inlet.rho,inlet.mu,inlet.k,inlet.cp,inlet.pr})
            if(!(value>0.) || !std::isfinite(value))throw std::invalid_argument("invalid full 2D continuation property");
        if(outer || thermal_active)check_flow(r.flow[side],side,true);
        if(thermal_active && (r.thermal.pressure[side]!=r.flow[side].absolute_pressure
            || r.thermal.mass_x[side]!=r.flow[side].mass_x || r.thermal.mass_y[side]!=r.flow[side].mass_y
            || r.thermal.rho_cp[side]!=r.rho_cp[side]))
            throw std::invalid_argument("full 2D continuation thermal input differs from the current state");
        if(state.flow) {
            const auto& run=(*state.flow)[side];check_flow(run.flow,side,!run.iteration);
            if(run.iteration)for(const auto& field:run.iteration->fields)check(field,0);
        }
    }
    if(outer || thermal_active)check_thermal(r.thermal,g,thermal_active);
    if(outer && !thermal_active && (r.outer_history.back().thermal_iterations!=thermal_iterations(r.thermal)
        || r.outer_history.back().thermal_converged!=thermal_converged(r.thermal)))
        throw std::invalid_argument("full 2D continuation thermal history differs from its evidence");
    if(state.thermal) {
        const auto& run=*state.thermal;
        const bool eos=p.thermal_mode==Full2DThermalMode::true_h;
        if(run.enthalpy.has_value()!=eos || run.model_h.has_value()==eos)
            throw std::invalid_argument("invalid full 2D continuation thermal owner");
        if(run.enthalpy)for(const auto& field:run.enthalpy->fields)check(field,0);
        if(run.model_h)for(const auto& field:run.model_h->iteration.temperature)check(field,0);
    }
    if(refinement) {
        const auto& fine=*r.refined;const double depth=1.;
        if(fine.dx!=split_refinement_cells(g.dx) || fine.dy!=split_refinement_cells(g.dy)
            || fine.accepted || fine.extrapolated)
            throw std::invalid_argument("invalid full 2D continuation refined grid or position");
        const GridView grid{fine.dx.size(),fine.dy.size(),1,view(fine.dx),view(fine.dy),{&depth,1}};
        check(fine.epsilon,grid.nx*grid.ny,true);check_thermal(fine.thermal,grid,true);
        for(std::size_t side=0;side<2;++side) {
            check(fine.uc[side],grid.nx*grid.ny);check(fine.vc[side],grid.nx*grid.ny);
            const auto& spec=p.sides[side];const auto widths=spec.direction<2?grid.dy:grid.dx;
            if(fine.inlet_profile[side]!=port_fractions_1d(widths,spec.inlet_lo,spec.inlet_hi,spec.uniform_inlet).second
                || fine.outlet_profile[side]!=port_fractions_1d(widths,spec.outlet_lo,spec.outlet_hi).second)
                throw std::invalid_argument("full 2D continuation refined ports differ from input");
        }
    }
}

} // namespace

Full2DRun::Full2DRun(const Full2DProblem& input,const Full2DControl& control,const Full2DRunState& state)
    :Full2DRun(input,control) {
    validate_continuation(input,control,state);
    auto& r=impl_->runtime;r.result=state.result;r.inlet=state.inlet;r.previous=state.previous;
    impl_->phase=state.phase;
    if(state.flow)r.flow=std::make_unique<FlowPair>(impl_->input,impl_->control,r.result,r.inlet,&*state.flow);
    if(state.thermal) {
        if(state.phase==Full2DPhase::refinement_boundary) {
            r.bind_refinement();
            r.thermal=std::make_unique<ThermalRun>(*r.fine_problem,r.physics,r.refinement_control(),
                r.result.refined->thermal,r.result.iterations-1,"refined_thermal",&*state.thermal);
        } else r.thermal=std::make_unique<ThermalRun>(impl_->input,r.physics,impl_->control,
            r.result.thermal,r.result.iterations,"thermal",&*state.thermal);
    }
}

Full2DRunState Full2DRun::snapshot() const {
    if(!impl_->boundary || !saved_boundary(impl_->phase))
        throw std::logic_error("full 2D snapshot requires a completed iteration boundary");
    const auto& runtime=impl_->runtime;
    Full2DRunState state{impl_->phase,runtime.result,runtime.inlet,runtime.previous,{},{}};
    if(runtime.flow)state.flow=runtime.flow->snapshot();
    if(runtime.thermal)state.thermal=runtime.thermal->snapshot();
    validate_continuation(impl_->input,impl_->control,state);
    return state;
}

Full2DResult Full2DRun::take_result() {
    if(!impl_->boundary || impl_->result_taken || (impl_->phase!=Full2DPhase::completed && impl_->phase!=Full2DPhase::cancelled))
        throw std::logic_error("full 2D result is not available");
    impl_->result_taken=true;return std::move(impl_->runtime.result);
}

Full2DResult solve_full_2d_coarse(const Full2DProblem& p,const Full2DControl& c) {
    Full2DRun run(p,c);
    while(run.phase()==Full2DPhase::created || run.phase()==Full2DPhase::outer_boundary)run.advance();
    if(run.phase()==Full2DPhase::cancelled)return run.take_result();
    run.impl_->phase=Full2DPhase::completed;
    return run.take_result();
}

Full2DResult solve_full_2d(const Full2DProblem& p,const Full2DControl& c) {
    Full2DRun run(p,c);
    while(run.phase()!=Full2DPhase::completed && run.phase()!=Full2DPhase::cancelled)run.advance();
    return run.take_result();
}

} // namespace tpmshx
