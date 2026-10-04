#include "tpmshx/full_2d.hpp"
#include "tpmshx/conservative_energy.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "tpmshx/refinement_2d.hpp"
#include "contiguous_sum.hpp"
#include "model_h_common.hpp"

#include <exception>
#include <numeric>
#include <thread>

namespace tpmshx {
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
const char* fluid_name(Fluid fluid) { return fluid==Fluid::air?"air":fluid==Fluid::water?"water":"sco2"; }
void temperature_ranges(std::vector<RangeObservation>& ledger,Fluid fluid,std::size_t side,
                        const char* source,const char* stage,const char* layout,
                        const std::vector<std::size_t>& shape,ArrayView<const double> temperature,
                        std::initializer_list<const char*> properties) {
    if (fluid==Fluid::sco2) return; // sCO2 state bounds are fail-loud, not empirical fit warnings.
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
        fluid==Fluid::water?data::water_nu_re_range:data::sco2_nu_re_range;
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
        if (s.direction<0 || s.direction>3 || (s.fluid!=Fluid::air && s.fluid!=Fluid::water && s.fluid!=Fluid::sco2))
            throw std::invalid_argument("invalid full2D side direction/fluid");
        if (p.thermal_mode==Full2DThermalMode::model_h && (s.fluid==Fluid::sco2 || p.asymmetric))
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
    if (!c.outer_iterations || !c.thermal_iterations || !c.thermal_chunk)
        throw std::invalid_argument("full2D budgets must be positive");
    for (double value:{c.outer_temperature_tolerance,c.outer_density_tolerance,c.outer_relaxation,
                       c.thermal_q_tolerance,c.enthalpy_update_tolerance})
        if (!std::isfinite(value) || value<=0) throw std::invalid_argument("invalid full2D tolerance/relaxation");
    if (c.outer_relaxation>1) throw std::invalid_argument("full2D outer relaxation exceeds one");
    switch(c.enthalpy_algorithm) {
        case EnthalpyAlgorithm::legacy_h_fou: break;
        case EnthalpyAlgorithm::temperature_fou:
        case EnthalpyAlgorithm::temperature_sou:
            if(p.thermal_mode!=Full2DThermalMode::true_h || c.thermal_red_black)
                throw std::invalid_argument("candidate full2D energy requires the existing true-h route without red-black energy");
            if(!std::isfinite(c.temperature_update_tolerance) || c.temperature_update_tolerance<=0.)
                throw std::invalid_argument("invalid candidate full2D temperature update tolerance");
            break;
        default: throw std::invalid_argument("unknown full2D energy algorithm");
    }
}

void check_energy_ports(const GridView& g,const Full2DSide& side,
                        const Vector& mass_x,const Vector& mass_y) {
    for(int axis=0;axis<2;++axis) for(bool high:{false,true}) {
        const auto count=axis==0?g.ny:g.nx;
        for(std::size_t q=0;q<count;++q) {
            const double mass=axis==0?mass_x[(high?g.nx*g.ny:0)+q]
                :mass_y[q*(g.ny+1)+(high?g.ny:0)];
            if(mass==0.) continue;
            if(axis!=side.direction/2)
                throw std::invalid_argument("candidate energy mass crosses a non-port boundary");
            const bool inlet=high==static_cast<bool>(side.direction%2);
            if((inlet?side.inlet_geometry:side.outlet_geometry)[q]==0.)
                throw std::invalid_argument("candidate energy mass crosses a closed port face");
        }
    }
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

Full2DFlow solve_flow(const Full2DProblem& p,const Full2DControl& c,std::size_t side,
                     std::size_t outer,const Full2DResult& current,const FluidProperties& inlet) {
    const auto& g=p.grid; const auto& s=p.sides[side]; const auto& old=current.flow[side];
    const std::size_t count=g.nx*g.ny;
    Full2DFlow f;
    const auto cross=s.direction<2?g.dy:g.dx,stream=s.direction<2?g.dx:g.dy;
    f.dx.assign(cross.data,cross.data+cross.size); f.dy.assign(stream.data,stream.data+stream.size);
    if (s.direction%2) std::reverse(f.dy.begin(),f.dy.end());
    const double depth=1.; const GridView fg{cross.size,stream.size,1,view(f.dx),view(f.dy),{&depth,1}};
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
    std::vector<unsigned char> open(cross.size);
    for (std::size_t a=0;a<cross.size;++a) {
        open[a]=s.outlet_geometry[a]>0.;
        f.v[a*(stream.size+1)]=f.inlet_velocity[a]*s.inlet_profile[a];
        f.v[a*(stream.size+1)+stream.size]=open[a]?f.v[a*(stream.size+1)+stream.size-1]:0.;
    }
    Vector permeability(count),forchheimer(count);
    for (std::size_t a=0;a<cross.size;++a) for (std::size_t b=0;b<stream.size;++b) {
        const auto k=a*stream.size+b;
        permeability[k]=s.permeability.size?s.permeability[k]:s.row_permeability[b];
        forchheimer[k]=s.forchheimer.size?s.forchheimer[k]:s.row_forchheimer[b];
    }
    const Simple2DMaterialView material{view(f.epsilon),view(f.viscosity),view(f.effective_viscosity),
        view(permeability),view(forchheimer),view(f.temperature)};
    const Simple2DBoundaryView boundary{s.inlet_profile,s.outlet_u_fraction,s.inlet_velocity,f.taper_flux_scale,inlet.rho};
    const Simple2DStateView state{writable(f.u),writable(f.v),writable(f.pressure),writable(f.pressure_correction),
        writable(f.d_u),writable(f.d_v),writable(f.density),writable(f.inlet_velocity)};
    auto flow_control=c.flow; flow_control.pressure_reference_absolute=f.reference_pressure;
    flow_control.ideal_gas=s.fluid==Fluid::air;
    FlowCallback callback{c,side}; flow_control.cancel=flow_cancel; flow_control.progress=flow_progress;
    flow_control.context=&callback;
    Simple2DSolver solver(fg,{open.data(),open.size()});
    f.result=solver.solve(material,boundary,state,flow_control); f.history=solver.history();
    f.massflux_target=solver.massflux_target();
    if (f.result.stop==SimpleStop::cancelled) return f;
    if (s.fluid==Fluid::air)
        f.pressure_state=inlet_pressure_state(fg,view(f.pressure),s.inlet_geometry,s.outlet_geometry,
                                             f.reference_pressure,s.inlet_pressure);
    build_physical_evidence(p,side,f);
    return f;
}

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

void prepare_thermal(const Full2DProblem& p,const Full2DControl& c,Full2DResult& r,
                     PropertyEvaluator& properties,const std::array<FluidProperties,2>& inlet) {
    const auto& g=p.grid; const std::size_t n=g.nx*g.ny;
    auto& t=r.thermal;
    t.solid_conductivity.assign(p.solid_conductivity.data,p.solid_conductivity.data+n);
    for (std::size_t side=0;side<2;++side) {
        const auto& s=p.sides[side]; const auto& f=r.flow[side];
        const double split=side==0?p.split_a:1.-p.split_a;
        t.hv[side].resize(n); t.conductivity[side].resize(n);
        t.pressure[side]=f.absolute_pressure; t.mass_x[side]=f.mass_x; t.mass_y[side]=f.mass_y;
        t.rho_cp[side]=r.rho_cp[side];
        if (p.thermal_mode==Full2DThermalMode::temperature)
            t.inlet_capacity[side]=capacity_at_inlet(g,s.direction,t,side,inlet[side].cp);
        double mean_rho=average(view(r.density[side]),g);
        double mean_mu=r.iterations?average(view(r.viscosity[side]),g):s.initial_viscosity;
        auto reference=inlet[side];
        double reference_temperature=s.inlet_temperature;
        if (p.thermal_mode==Full2DThermalMode::true_h && s.fluid!=Fluid::sco2) {
            Vector rho(n),mu(n),pin(n,s.inlet_pressure);
            actual_water(properties,s.fluid,view(t.temperature[side]),view(pin),"2D h_v property refresh",side);
            for (std::size_t k=0;k<n;++k) {
                const auto prop=properties.transport(s.fluid,t.temperature[side][k],s.inlet_pressure);
                rho[k]=prop.rho; mu[k]=prop.mu;
            }
            mean_rho=average(view(rho),g); mean_mu=average(view(mu),g);
            reference_temperature=average(view(t.temperature[side]),g);
            reference=properties.transport(s.fluid,reference_temperature,s.inlet_pressure);
            temperature_ranges(r.range_observations,s.fluid,side,"property","main-hv","real-cell(x,y)",
                {g.nx,g.ny},view(t.temperature[side]),{"density","viscosity"});
            temperature_ranges(r.range_observations,s.fluid,side,"property","main-hv","real-cell(x,y)",
                {},{&reference_temperature,1},{"conductivity"});
        } else if (p.thermal_mode!=Full2DThermalMode::true_h) {
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
                return area*std::max(nu,data::nu_laminar_floor)/dh;
            };
            const double denominator=reduced(s.reference_area_density,s.reference_hydraulic_diameter,"asym-reference-scalar");
            ratio=denominator>0?reduced(s.side_area_density,s.side_hydraulic_diameter,"asym-side-scalar")/denominator:1.;
        }
        auto raw_re=nu_range(p,side,true,"main-hv","real-cell(x,y)",{g.nx,g.ny});
        auto source_re=nu_range(p,side,false,"main-hv","real-cell(x,y)",{g.nx,g.ny});
        auto& observation=r.nu_observations[side];
        if (p.thermal_mode==Full2DThermalMode::true_h && s.fluid==Fluid::sco2) {
            observation=NuObservation{}; observation.available=true; observation.cells=n; observation.pressure=s.inlet_pressure;
            observation.raw_min=observation.re_min=observation.pr_min=observation.temperature_min=std::numeric_limits<double>::infinity();
            observation.raw_max=observation.re_max=observation.pr_max=observation.temperature_max=-std::numeric_limits<double>::infinity();
        }
        for (std::size_t k=0;k<n;++k) {
            const double speed=std::sqrt(f.uc[k]*f.uc[k]+f.vc[k]*f.vc[k]);
            double re,pr,conductivity;
            if (p.thermal_mode==Full2DThermalMode::true_h && s.fluid==Fluid::sco2) {
                const auto props=properties.transport(s.fluid,t.temperature[side][k],s.inlet_pressure);
                re=props.rho*std::abs(speed)*p.hydraulic_diameter[k]/std::max(props.mu,1e-30);
                pr=props.cp*props.mu/std::max(props.k,1e-30); conductivity=props.k;
            } else {
                re=mean_rho*(std::abs(speed)+1e-12)*p.hydraulic_diameter[k]/mean_mu;
                pr=reference.pr; conductivity=reference.k;
            }
            const double nu=fluid_nusselt_ratio(s.fluid,p.topology,std::max(re,1.),pr,
                                               p.nu_geometry_ratio[k],p.sco2_nu_multiplier);
            observe_range_value(raw_re,re,k); observe_range_value(source_re,std::max(re,1.),k);
            if (observation.available) {
                observation.floor_cells+=nu<data::nu_laminar_floor;
                observation.raw_min=std::min(observation.raw_min,nu); observation.raw_max=std::max(observation.raw_max,nu);
                observation.re_min=std::min(observation.re_min,re); observation.re_max=std::max(observation.re_max,re);
                observation.pr_min=std::min(observation.pr_min,pr); observation.pr_max=std::max(observation.pr_max,pr);
                observation.temperature_min=std::min(observation.temperature_min,t.temperature[side][k]);
                observation.temperature_max=std::max(observation.temperature_max,t.temperature[side][k]);
            }
            t.hv[side][k]=p.area_density[k]*std::max(nu,data::nu_laminar_floor)*conductivity/p.hydraulic_diameter[k];
            if (p.asymmetric) t.hv[side][k]*=ratio;
            t.conductivity[side][k]=p.fluid_conductivity[side][k]*(p.asymmetric?2.*split:1.);
        }
        merge_range_observation(r.range_observations,std::move(raw_re));
        if (s.fluid!=Fluid::air) temperature_ranges(r.range_observations,s.fluid,side,"property","main-hv","real-cell(x,y)",
            {},{&reference_temperature,1},{"viscosity","conductivity","cp"});
        merge_range_observation(r.range_observations,std::move(source_re));
        if (p.thermal_mode==Full2DThermalMode::temperature)
            temperature_ranges(r.range_observations,s.fluid,side,"property","main-inlet","scalar",{},
                               {&s.inlet_temperature,1},{"cp"});
    }
    (void)c;
}

void solve_thermal(const Full2DProblem& p,const Full2DControl& c,Full2DResult& r) {
    auto& t=r.thermal;
    const auto& g=p.grid; const std::size_t n=g.nx*g.ny;
    const TemperatureStateView fields{writable(t.temperature[0]),writable(t.temperature[1]),writable(t.temperature[2])};
    const auto boundary=[&](std::size_t side) {
        return TemperatureBoundary{p.sides[side].direction,p.sides[side].inlet_temperature,{},p.sides[side].inlet_geometry,{}};
    };
    if (p.thermal_mode==Full2DThermalMode::model_h) {
        const auto fluid=[&](std::size_t side) {
            return ModelHFluid2D{p.sides[side].fluid,view(t.conductivity[side]),view(t.hv[side]),
                                view(t.mass_x[side]),view(t.mass_y[side]),boundary(side)};
        };
        const ModelHControl2D control{c.thermal_iterations,c.thermal_chunk,c.thermal_q_tolerance,
            true,true,c.thermal_red_black && n>30000,c.cancel,nullptr,c.context};
        t.result=solve_model_h_2d(g,fluid(0),fluid(1),p.solid_conductivity,fields,control);
    } else if (p.thermal_mode==Full2DThermalMode::true_h) {
        std::array<Vector,2> eps; Vector z(n*2,0.);
        for (std::size_t side=0;side<2;++side) {
            eps[side].resize(n);
            const double split=side==0?p.split_a:1.-p.split_a;
            for (std::size_t k=0;k<n;++k) eps[side][k]=p.total_porosity[k]*split;
            if(c.enthalpy_algorithm!=EnthalpyAlgorithm::legacy_h_fou)
                check_energy_ports(g,p.sides[side],t.mass_x[side],t.mass_y[side]);
        }
        const auto fluid=[&](std::size_t side) {
            return EnthalpySideView{p.sides[side].fluid,p.sides[side].inlet_temperature,p.sides[side].inlet_pressure,
                view(t.pressure[side]),view(eps[side]),view(t.hv[side]),view(t.mass_x[side]),view(t.mass_y[side]),view(z),p.sides[side].direction};
        };
        t.h_a.resize(n); t.h_b.resize(n);
        const EnthalpyStateView state{writable(t.h_a),writable(t.h_b),fields.a,fields.b,fields.solid,true,true,true};
        EnthalpyControl control{c.thermal_iterations,3,.6,c.enthalpy_update_tolerance,.001,.001,
            c.table_directory,c.cancel,c.context};
        control.algorithm=c.enthalpy_algorithm;
        control.temperature_update_tolerance=c.temperature_update_tolerance;
        if(control.algorithm!=EnthalpyAlgorithm::legacy_h_fou) {
            control.sweeps=5;
            control.omega=control.algorithm==EnthalpyAlgorithm::temperature_sou?.2:.6;
        }
        t.result=solve_enthalpy(g,fluid(0),fluid(1),p.solid_conductivity,state,control);
        const auto& solved=std::get<EnthalpyResult>(t.result);
        if(solved.stop!=EnthalpyStop::cancelled && solved.algorithm!=EnthalpyAlgorithm::legacy_h_fou) {
            EnthalpyEOS eos;
            for(std::size_t side=0;side<2;++side) {
                auto& actual=t.actual_conductivity[side];actual.resize(n);
                for(std::size_t k=0;k<n;++k)
                    actual[k]=eps[side][k]*eos.conductivity(p.sides[side].fluid,t.temperature[side][k],t.pressure[side][k]);
                t.enthalpy_boundary_power[side]=enthalpy_boundary_power(g,view(side==0?t.h_a:t.h_b),
                    {view(t.mass_x[side]),view(t.mass_y[side]),view(z)},solved.inlet_enthalpy[side],
                    solved.algorithm==EnthalpyAlgorithm::temperature_sou);
            }
        }
    } else {
        std::array<Vector,2> eps;
        for (std::size_t side=0;side<2;++side) {
            eps[side].resize(n);
            const double split=side==0?p.split_a:1.-p.split_a;
            for (std::size_t k=0;k<n;++k) eps[side][k]=p.total_porosity[k]*split;
        }
        const auto fluid=[&](std::size_t side) {
            auto bc=boundary(side); bc.capacity_flux=view(t.inlet_capacity[side]);
            return TemperatureFluidView{view(t.conductivity[side]),view(t.hv[side]),view(eps[side]),
                view(t.rho_cp[side]),view(r.flow[side].uc),view(r.flow[side].vc),{},bc};
        };
        const TemperatureControl control{c.thermal_iterations,c.thermal_chunk,c.thermal_q_tolerance,
            .7,1.,1.,true,false,c.cancel,nullptr,c.context};
        t.result=solve_temperature(TemperatureScheme::cell_centered_2d,g,fluid(0),fluid(1),
                                   p.solid_conductivity,fields,control,{},c.thermal_red_black && n>30000);
    }
}
} // namespace

Full2DResult solve_full_2d_coarse(const Full2DProblem& p,const Full2DControl& c) {
    validate(p,c); const auto& g=p.grid; const std::size_t n=g.nx*g.ny;
    Full2DResult result; PropertyEvaluator properties;
    std::array<FluidProperties,2> inlet;
    for (std::size_t side=0;side<2;++side) {
        const auto& s=p.sides[side]; inlet[side]=properties.evaluate(s.fluid,s.inlet_temperature,s.inlet_pressure);
        temperature_ranges(result.range_observations,s.fluid,side,"property","inlet","scalar",{},
                           {&s.inlet_temperature,1},{"density","cp"});
        result.density[side].assign(n,inlet[side].rho);
        result.viscosity[side].assign(n,s.initial_viscosity);
        result.rho_cp[side].assign(n,inlet[side].rho*inlet[side].cp);
        result.thermal.temperature[side].assign(n,s.inlet_temperature);
    }
    result.thermal.temperature[2].assign(n,p.initial_solid_temperature.value_or(
        .5*(p.sides[0].inlet_temperature+p.sides[1].inlet_temperature)));
    std::array<Vector,3> previous;
    for (std::size_t outer=0;outer<c.outer_iterations;++outer) {
        if (cancelled(c)) { result.cancelled=true; return result; }
        if (c.progress) c.progress(c.context,outer,c.outer_iterations);
        std::array<Full2DFlow,2> next; std::array<std::exception_ptr,2> errors;
        const auto flow=[&](std::size_t side) {
            try { next[side]=solve_flow(p,c,side,outer,result,inlet[side]); }
            catch (...) { errors[side]=std::current_exception(); }
        };
        std::thread a(flow,0);
        try { std::thread b(flow,1); a.join(); b.join(); }
        catch (...) { if (a.joinable()) a.join(); throw; }
        for (auto& error:errors) if (error) std::rethrow_exception(error);
        result.flow=std::move(next);
        if (cancelled(c) || result.flow[0].result.stop==SimpleStop::cancelled || result.flow[1].result.stop==SimpleStop::cancelled) {
            result.cancelled=true; return result;
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
        prepare_thermal(p,c,result,properties,inlet);
        if (p.thermal_mode!=Full2DThermalMode::true_h && (outer || p.initial_solid_temperature))
            for (std::size_t side=0;side<2;++side)
                temperature_state(result.range_observations,p.sides[side].fluid,side,"main-warm",g,
                                  view(result.thermal.temperature[side]));
        solve_thermal(p,c,result);
        if (thermal_cancelled(result.thermal)) { result.cancelled=true; return result; }
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
        record.thermal_converged=thermal_converged(result.thermal);
        if(const auto* solved=std::get_if<EnthalpyResult>(&result.thermal.result)) {
            record.enthalpy_algorithm=solved->algorithm;
            record.thermal_temperature_update=solved->temperature_update;
            record.thermal_picard_relaxation=solved->picard_relaxation;
        }
        bool stable=outer>0;
        for (std::size_t side=0;side<2;++side) {
            density[side].resize(n); rho_cp[side].resize(n);
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
        if (record.outer_converged) { result.outer_converged=true; break; }
        // Original post runs even after the last capped thermal call.
        for (std::size_t side=0;side<2;++side) for (std::size_t k=0;k<n;++k) {
            result.density[side][k]=c.outer_relaxation*density[side][k]+(1.-c.outer_relaxation)*result.density[side][k];
            result.rho_cp[side][k]=c.outer_relaxation*rho_cp[side][k]+(1.-c.outer_relaxation)*result.rho_cp[side][k];
        }
    }
    result.post_after_last_thermal=!result.outer_converged;
    if (cancelled(c)) { result.cancelled=true; return result; }
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
    return result;
}

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
double temperature_duty(const GridView& g,int direction,double inlet_temperature,
                        ArrayView<const double> temperature,ArrayView<const double> uc,
                        ArrayView<const double> vc,ArrayView<const double> rho_cp,
                        ArrayView<const double> epsilon,double split,
                        ArrayView<const double> inlet_profile,ArrayView<const double> outlet_profile) {
    const auto widths=direction<2?g.dy:g.dx,velocity=direction<2?uc:vc;
    double in_weight=0.,out_weight=0.,in_heat=0.,out_heat=0.,out_mean=0.;
    for (std::size_t k=0;k<widths.size;++k) {
        const auto in=boundary_cell(g,direction,k,false),out=boundary_cell(g,direction,k,true);
        const double wi=(epsilon[in]*split)*rho_cp[in]*std::abs(velocity[in])*widths[k]*inlet_profile[k];
        const double wo=(epsilon[out]*split)*rho_cp[out]*std::abs(velocity[out])*widths[k]*outlet_profile[k];
        in_weight+=wi; out_weight+=wo; in_heat+=wi*inlet_temperature; out_heat+=wo*temperature[out];
        out_mean+=temperature[out];
    }
    if (in_weight<1e-30) return 0.;
    const double outlet=out_weight>1e-30?out_heat/out_weight:out_mean/static_cast<double>(widths.size);
    return in_weight*(in_heat/in_weight-outlet);
}
void refine_thermal(const Full2DProblem& p,const Full2DControl& c,Full2DResult& r,
                    PropertyEvaluator& properties) {
    r.refined.emplace(); auto& fine=*r.refined;
    const auto& g=p.grid;
    fine.dx=split_refinement_cells(g.dx); fine.dy=split_refinement_cells(g.dy);
    const double depth=1.;
    const GridView fg{fine.dx.size(),fine.dy.size(),1,view(fine.dx),view(fine.dy),{&depth,1}};
    const auto interpolate=[&](ArrayView<const double> field) {
        return refine_cell_field_2d(g.dx,g.dy,fg.dx,fg.dy,field);
    };
    const auto geometry=[&](ArrayView<const double> field) {
        return p.spatial_geometry?interpolate(field):Vector(fg.nx*fg.ny,field[0]);
    };
    fine.epsilon=geometry(p.total_porosity);
    auto fp=p; fp.grid=fg; fp.total_porosity=view(fine.epsilon);
    Full2DResult fr;
    fr.thermal.solid_conductivity=geometry(view(r.thermal.solid_conductivity));
    fp.solid_conductivity=view(fr.thermal.solid_conductivity);
    std::array<Vector,2> opening;
    for (std::size_t side=0;side<2;++side) {
        const auto& s=p.sides[side]; const auto cross=s.direction<2?fg.dy:fg.dx;
        auto inlet=port_fractions_1d(cross,s.inlet_lo,s.inlet_hi,s.uniform_inlet);
        opening[side]=std::move(inlet.first); fine.inlet_profile[side]=std::move(inlet.second);
        fine.outlet_profile[side]=port_fractions_1d(cross,s.outlet_lo,s.outlet_hi).second;
        fp.sides[side].inlet_geometry=view(opening[side]);
        fr.thermal.temperature[side]=interpolate(view(r.thermal.temperature[side]));
        temperature_state(r.range_observations,s.fluid,side,"richardson-warm",fg,view(fr.thermal.temperature[side]));
        // Python retains scalar rho*cp only for the first main solve; later
        // outer passes own fields. Preserve that source shape in the ledger.
        if (r.iterations==1)
            temperature_ranges(r.range_observations,s.fluid,side,"property","richardson-inlet","scalar",{},
                               {&s.inlet_temperature,1},{"density","cp"});
        if (p.thermal_mode==Full2DThermalMode::temperature)
            temperature_ranges(r.range_observations,s.fluid,side,"property","richardson-inlet","scalar",{},
                               {&s.inlet_temperature,1},{"cp"});
        fr.thermal.hv[side]=interpolate(view(r.thermal.hv[side]));
        fr.thermal.rho_cp[side]=interpolate(view(r.thermal.rho_cp[side]));
        fr.thermal.conductivity[side]=geometry(p.thermal_mode==Full2DThermalMode::model_h
            ?view(r.thermal.conductivity[side]):p.fluid_conductivity[side]);
        if (p.thermal_mode==Full2DThermalMode::temperature && p.asymmetric)
            for (double& value:fr.thermal.conductivity[side]) value*=2.*(side==0?p.split_a:1.-p.split_a);
        fr.thermal.pressure[side]=interpolate(view(r.thermal.pressure[side]));
        fr.flow[side].uc=interpolate(view(r.flow[side].uc));
        fr.flow[side].vc=interpolate(view(r.flow[side].vc));
        actual_water(properties,s.fluid,view(r.thermal.temperature[side]),view(r.thermal.pressure[side]),
                     "Richardson coarse",side);
        actual_water(properties,s.fluid,view(fr.thermal.temperature[side]),view(fr.thermal.pressure[side]),
                     "Richardson warm start",side);
        if (p.thermal_mode==Full2DThermalMode::model_h) {
            auto faces=prolong_mass_faces_2d({view(r.thermal.mass_x[side]),view(r.thermal.mass_y[side])},
                                            g.dx,g.dy,fg.dx,fg.dy);
            fr.thermal.mass_x[side]=std::move(faces[0]); fr.thermal.mass_y[side]=std::move(faces[1]);
        } else {
            const auto coarse=s.direction<2?g.dy:g.dx;
            fr.thermal.inlet_capacity[side]=refine_inlet_capacity(coarse,cross,view(r.thermal.inlet_capacity[side]));
        }
    }
    fr.thermal.temperature[2]=interpolate(view(r.thermal.temperature[2]));
    auto fc=c; fc.thermal_iterations=p.thermal_mode==Full2DThermalMode::model_h?12000:5000;
    fc.thermal_chunk=500; fc.thermal_q_tolerance=.001;
    solve_thermal(fp,fc,fr);
    if (thermal_cancelled(fr.thermal)) { r.cancelled=true; fine.thermal=std::move(fr.thermal); return; }
    for (std::size_t side=0;side<2;++side) {
        temperature_state(r.range_observations,p.sides[side].fluid,side,"richardson-return",fg,view(fr.thermal.temperature[side]));
        actual_water(properties,p.sides[side].fluid,view(fr.thermal.temperature[side]),view(fr.thermal.pressure[side]),
                     "Richardson return",side);
        fine.uc[side]=std::move(fr.flow[side].uc); fine.vc[side]=std::move(fr.flow[side].vc);
    }
    for (const auto& field:fr.thermal.temperature) model_h_common::check(view(field),fg.nx*fg.ny);
    fine.thermal=std::move(fr.thermal);
    fine.accepted=thermal_converged(fine.thermal);
    if (p.thermal_mode==Full2DThermalMode::model_h) {
        auto& main=std::get<ModelHResult2D>(r.thermal.result).audit;
        auto& refined=std::get<ModelHResult2D>(fine.thermal.result).audit;
        main.passed=main.passed && r.outer_converged;
        refined.passed=refined.passed && r.outer_converged && !r.post_after_last_thermal;
        fine.accepted=fine.accepted && main.passed && refined.passed;
    }
    const auto nan=std::numeric_limits<double>::quiet_NaN();
    const Vector coarse_epsilon(g.nx*g.ny,p.reference_porosity);
    for (std::size_t side=0;side<2;++side) {
        const auto& s=p.sides[side]; const double split=side==0?p.split_a:1.-p.split_a;
        if (p.thermal_mode==Full2DThermalMode::model_h) {
            r.duty[side]=std::get<ModelHResult2D>(r.thermal.result).audit.sides[side].q_advective;
            fine.duty[side]=fine.accepted?std::get<ModelHResult2D>(fine.thermal.result).audit.sides[side].q_advective:nan;
        } else {
            r.duty[side]=temperature_duty(g,s.direction,s.inlet_temperature,view(r.thermal.temperature[side]),
                view(r.flow[side].uc),view(r.flow[side].vc),view(r.thermal.rho_cp[side]),view(coarse_epsilon),split,
                s.inlet_profile,s.outlet_profile);
            fine.duty[side]=fine.accepted?temperature_duty(fg,s.direction,s.inlet_temperature,
                view(fine.thermal.temperature[side]),view(fine.uc[side]),view(fine.vc[side]),
                view(fine.thermal.rho_cp[side]),view(fine.epsilon),split,
                view(fine.inlet_profile[side]),view(fine.outlet_profile[side])):nan;
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
    // Original temperature-only fallback: finite outlet-cell mean and physical
    // inlet capacity. Model-h never substitutes a mean-field duty.
    if (!std::isfinite(r.q_total) && p.thermal_mode==Full2DThermalMode::temperature) {
        for (std::size_t side=0;side<2;++side) {
            const auto& s=p.sides[side]; const std::size_t count=s.direction<2?g.ny:g.nx;
            double mean=0.; std::size_t finite=0;
            for (std::size_t k=0;k<count;++k) {
                const double t=r.thermal.temperature[side][boundary_cell(g,s.direction,k,true)];
                if (std::isfinite(t)) { mean+=t; ++finite; }
            }
            mean=finite?mean/static_cast<double>(finite):s.inlet_temperature;
            const auto props=properties.evaluate(s.fluid,s.inlet_temperature,s.inlet_pressure);
            temperature_ranges(r.range_observations,s.fluid,side,"property","fallback-inlet","scalar",{},
                               {&s.inlet_temperature,1},{"density","cp"});
            const double mass=props.rho*std::abs(s.inlet_velocity)*(s.inlet_hi-s.inlet_lo)
                *p.reference_porosity*(side==0?p.split_a:1.-p.split_a);
            const double q=mass*props.cp*std::abs(s.inlet_temperature-mean);
            if (std::isfinite(q)) r.q_total=std::isfinite(r.q_total)?std::max(r.q_total,q):q;
        }
    }
}
} // namespace

Full2DResult solve_full_2d(const Full2DProblem& p,const Full2DControl& c) {
    auto r=solve_full_2d_coarse(p,c);
    if (r.cancelled) return r;
    PropertyEvaluator properties;
    if (p.thermal_mode==Full2DThermalMode::true_h) {
        const auto& h=std::get<EnthalpyResult>(r.thermal.result);
        r.duty={h.q_a,h.q_b}; r.q_total=std::abs(h.q_a); r.q_solid=std::abs(h.q_b);
    } else refine_thermal(p,c,r,properties);
    if (r.cancelled) return r;
    r.simple_ok=true; r.envelope_ok=true;
    for (std::size_t side=0;side<2;++side) {
        const auto& f=r.flow[side]; const auto& s=p.sides[side];
        const bool candidate=c.enthalpy_algorithm!=EnthalpyAlgorithm::legacy_h_fou;
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
        else if (p.thermal_mode==Full2DThermalMode::true_h) {
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
    return r;
}
} // namespace tpmshx
