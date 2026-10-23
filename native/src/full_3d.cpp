#include "tpmshx/full_3d.hpp"
#include "tpmshx/conservative_energy.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "legacy_single_a_temperature.hpp"
#include "model_h_common.hpp"
#include "full_3d_fields.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <memory>
#include <numeric>
#include <stdexcept>
#include <utility>

namespace tpmshx {
namespace {
using Values = std::vector<double>;
using Faces = std::array<Values,3>;
template <typename T> ArrayView<const double> view(const T& x) { return {x.data(),x.size()}; }
ArrayView<double> writable(Values& x) { return {x.data(),x.size()}; }
std::array<ArrayView<const double>,3> views(const Faces& x) {
    return {view(x[0]),view(x[1]),view(x[2])};
}
std::size_t product(std::size_t a,std::size_t b) {
    if (!a || !b || a>std::numeric_limits<std::size_t>::max()/b)
        throw std::invalid_argument("invalid full 3D grid extent");
    return a*b;
}
std::array<std::size_t,3> shape(const GridView& g) { return {g.nx,g.ny,g.nz}; }
std::size_t index(const std::array<std::size_t,3>& n,std::size_t i,std::size_t j,std::size_t k) {
    return (i*n[1]+j)*n[2]+k;
}
std::size_t index(const std::array<std::size_t,3>& n,const std::array<std::size_t,3>& p) {
    return index(n,p[0],p[1],p[2]);
}
void extent(ArrayView<const double> a,std::size_t n,bool positive=false,bool nonnegative=false) {
    if (!a.data || a.size!=n) throw std::invalid_argument("full 3D array extent mismatch");
    for (std::size_t p=0;p<n;++p)
        if (!std::isfinite(a[p]) || (positive && a[p]<=0.) || (nonnegative && a[p]<0.))
            throw std::invalid_argument("invalid full 3D field coefficient");
}
bool finite(const Values& v) {
    return std::all_of(v.begin(),v.end(),[](double x){return std::isfinite(x);});
}
double sum(ArrayView<const double> v) { return std::accumulate(v.data,v.data+v.size,0.); }
double average(const Values& v) { return std::accumulate(v.begin(),v.end(),0.)/v.size(); }
double cell_average(const GridView& g,const Values& field) {
    double numerator=0.,denominator=0.; const auto n=shape(g);
    for(std::size_t i=0;i<g.nx;++i) for(std::size_t j=0;j<g.ny;++j) for(std::size_t k=0;k<g.nz;++k) {
        const double volume=g.dx[i]*g.dy[j]*g.dz[k];
        numerator+=field[index(n,i,j,k)]*volume; denominator+=volume;
    }
    return numerator/denominator;
}
GridView grid(const Full3DFlowState& s) {
    return {s.widths[0].size(),s.widths[1].size(),s.widths[2].size(),
            view(s.widths[0]),view(s.widths[1]),view(s.widths[2])};
}
Faces empty_faces(const GridView& g) {
    return {Values((g.nx+1)*g.ny*g.nz),Values(g.nx*(g.ny+1)*g.nz),Values(g.nx*g.ny*(g.nz+1))};
}
Values to_solver(const GridView& real,const Full3DSide& side,ArrayView<const double> field) {
    const auto rn=shape(real);
    const std::array<std::size_t,3> sn{rn[side.solver_axes[0]],rn[side.solver_axes[1]],rn[side.solver_axes[2]]};
    Values out(field.size);
    for(std::size_t i=0;i<sn[0];++i) for(std::size_t j=0;j<sn[1];++j) for(std::size_t k=0;k<sn[2];++k) {
        std::array<std::size_t,3> p{};
        p[side.solver_axes[0]]=i; p[side.solver_axes[1]]=(side.direction%2 ? sn[1]-1-j:j);
        p[side.solver_axes[2]]=k;
        out[index(sn,i,j,k)]=field[index(rn,p)];
    }
    return out;
}
Values to_real(const GridView& real,const Full3DSide& side,ArrayView<const double> field,
               int staggered_axis=-1,double sign=1.) {
    auto rn=shape(real);
    if(staggered_axis>=0) ++rn[side.solver_axes[static_cast<std::size_t>(staggered_axis)]];
    const std::array<std::size_t,3> sn{rn[side.solver_axes[0]],rn[side.solver_axes[1]],rn[side.solver_axes[2]]};
    Values out(field.size);
    for(std::size_t i=0;i<sn[0];++i) for(std::size_t j=0;j<sn[1];++j) for(std::size_t k=0;k<sn[2];++k) {
        std::array<std::size_t,3> p{};
        p[side.solver_axes[0]]=i; p[side.solver_axes[1]]=(side.direction%2 ? sn[1]-1-j:j);
        p[side.solver_axes[2]]=k;
        out[index(rn,p)]=sign*field[index(sn,i,j,k)];
    }
    return out;
}
}  // namespace

namespace detail {
void update_real(const GridView& real,const Full3DSide& side,Full3DFlowState& state) {
    const auto g=grid(state); const auto sn=shape(g); const std::size_t count=g.nx*g.ny*g.nz;
    const Values* components[]{&state.u,&state.v,&state.w};
    for(std::size_t d=0;d<3;++d) {
        const double sign=(d==1 && side.direction%2) ? -1.:1.;
        const auto real_axis=static_cast<std::size_t>(side.solver_axes[d]);
        state.face_velocity_real[real_axis]=to_real(real,side,view(*components[d]),static_cast<int>(d),sign);
        Values cc(count); auto fs=sn; ++fs[d];
        for(std::size_t i=0;i<g.nx;++i) for(std::size_t j=0;j<g.ny;++j) for(std::size_t k=0;k<g.nz;++k) {
            std::array<std::size_t,3> p{i,j,k},next=p; ++next[d];
            cc[index(sn,p)]=.5*((*components[d])[index(fs,p)]+(*components[d])[index(fs,next)]);
        }
        state.velocity_real[real_axis]=to_real(real,side,view(cc),-1,sign);
    }
    Values absolute=state.pressure;
    for(double& p:absolute) p+=state.pressure_reference;
    state.pressure_real=to_real(real,side,view(absolute));
    state.density_real=to_real(real,side,view(state.density));
}
}  // namespace detail

namespace {
using detail::update_real;
Values multiply(ArrayView<const double> a,ArrayView<const double> b) {
    Values out(a.size); for(std::size_t p=0;p<a.size;++p) out[p]=a[p]*b[p]; return out;
}
Faces mass_faces(const GridView& g,const Faces& velocity,ArrayView<const double> epsilon,
                 const Values& rho) {
    auto out=empty_faces(g); const auto coefficient=multiply(epsilon,view(rho));
    simple_face_mass_flux(3,g,{view(velocity[0]),view(velocity[1]),view(velocity[2])},view(coefficient),
        {writable(out[0]),writable(out[1]),writable(out[2])});
    return out;
}
// Enumerate a physical boundary in its native transverse C order. No mask is
// multiplied here: SIMPLE's face-average velocity already contains open area.
template<typename F> void boundary(const GridView& g,int axis,bool high,F operation) {
    const auto n=shape(g); auto fn=n; ++fn[axis];
    const std::array<ArrayView<const double>,3> widths{g.dx,g.dy,g.dz};
    std::array<int,2> cross{}; int next=0;
    for(int d=0;d<3;++d) if(d!=axis) cross[next++]=d;
    std::size_t face_index=0;
    for(std::size_t i=0;i<n[cross[0]];++i) for(std::size_t j=0;j<n[cross[1]];++j) {
        std::array<std::size_t,3> cell{},face{};
        cell[cross[0]]=face[cross[0]]=i; cell[cross[1]]=face[cross[1]]=j;
        cell[axis]=high?n[axis]-1:0; face[axis]=high?n[axis]:0;
        operation(face_index++,index(n,cell),index(fn,face),widths[cross[0]][i]*widths[cross[1]][j]);
    }
}
Values inlet_capacity(const GridView& g,int direction,const Faces& velocity,
                      ArrayView<const double> epsilon,const Values& rho,double cp) {
    const int axis=direction/2; const bool reverse=direction%2;
    Values result(rho.size()/shape(g)[axis]);
    boundary(g,axis,reverse,[&](std::size_t q,std::size_t p,std::size_t f,double area) {
        result[q]=epsilon[p]*rho[p]*cp*velocity[axis][f]*area*(reverse?-1.:1.);
    });
    return result;
}
}  // namespace

namespace detail {
void balance_outflow(const GridView& g,int direction,Faces& velocity,const Values& coefficient) {
    const int axis=direction/2; const bool reverse=direction%2; double low=0.,high=0.;
    boundary(g,axis,false,[&](std::size_t,std::size_t p,std::size_t f,double area) {
        low+=coefficient[p]*velocity[axis][f]*area;
    });
    boundary(g,axis,true,[&](std::size_t,std::size_t p,std::size_t f,double area) {
        high+=coefficient[p]*velocity[axis][f]*area;
    });
    const double inlet=reverse?high:low,outlet=reverse?low:high;
    if(std::abs(outlet)<1e-12*(std::abs(inlet)+1e-30)) return;
    const double scale=inlet/outlet;
    if(!std::isfinite(scale) || scale<=0.) return;
    boundary(g,axis,!reverse,[&](std::size_t,std::size_t,std::size_t f,double) { velocity[axis][f]*=scale; });
}
}  // namespace detail

namespace {
using detail::balance_outflow;
std::optional<PressurePortState> inlet_state(const Full3DSide& side,const Full3DFlowState& state) {
    if(side.fluid!=Fluid::air) return std::nullopt;
    return inlet_pressure_state(grid(state),view(state.pressure),view(state.inlet_opening),
        view(state.outlet_opening),state.pressure_reference,side.inlet_pressure);
}
void anchor(const Full3DSide& side,Full3DFlowState& state) {
    if(side.fluid==Fluid::air) return;
    const auto measured=inlet_pressure_state(grid(state),view(state.pressure),view(state.inlet_opening),
        view(state.outlet_opening),0.,side.inlet_pressure);
    state.pressure_reference=side.inlet_pressure-measured.realized_Pa;
}
struct Cancelled {};
void cancel(const Full3DControl& c) { if(c.cancel && c.cancel(c.context)) throw Cancelled{}; }

bool strict_model_h(const Full3DInput& in) {
    return in.geometry.asymmetric || (in.a.fluid==Fluid::water && in.b.fluid==Fluid::water);
}

Full3DThermalMode thermal_mode(const Full3DInput& in,const Full3DControl& c) {
    if(in.solve_b && (uses_co2_eos(in.a.fluid) || uses_co2_eos(in.b.fluid)))return Full3DThermalMode::true_h;
    if(in.geometry.grid.nz>1 && c.variable_rho_cp && in.solve_b && c.conservative)
        return Full3DThermalMode::model_h;
    return Full3DThermalMode::temperature;
}

void validate(const Full3DInput& in,const Full3DControl& c) {
    const auto& x=in.geometry; const auto& g=x.grid; const auto n=product(product(g.nx,g.ny),g.nz);
    extent(g.dx,g.nx,true);extent(g.dy,g.ny,true);extent(g.dz,g.nz,true);
    for(auto a:{x.epsilon,x.epsilon_a,x.epsilon_b}) {
        extent(a,n,true); for(std::size_t p=0;p<n;++p) if(a[p]>=1.)
            throw std::invalid_argument("full 3D porosity must be below one");
    }
    for(std::size_t p=0;p<n;++p) if(std::abs(x.epsilon_a[p]+x.epsilon_b[p]-x.epsilon[p])>1e-9)
        throw std::invalid_argument("full 3D side porosities must partition total porosity");
    if(!x.asymmetric) for(std::size_t p=0;p<n;++p)
        if(x.epsilon_a[p]!=.5*x.epsilon[p] || x.epsilon_b[p]!=.5*x.epsilon[p])
            throw std::invalid_argument("symmetric full 3D geometry requires exactly half porosity per side");
    for(auto a:{x.permeability,x.cell_length,x.area_density,x.hydraulic_diameter}) extent(a,n,true);
    extent(x.forchheimer,n,false,true);extent(x.solid_conductivity,n,false,true);
    for(auto source:in.sources) if(source.size) extent(source,n);
    for(const auto* side:{&in.a,&in.b}) {
        const auto& s=*side;
        if(side==&in.b && !in.solve_b) {
            if(!std::isfinite(s.inlet_temperature) || s.inlet_temperature<=0.
               || !std::isfinite(s.inlet_pressure) || s.inlet_pressure<=0.)
                throw std::invalid_argument("invalid prescribed B inlet state");
            continue;
        }
        if(s.direction<0 || s.direction>5 || s.solver_axes[1]!=s.direction/2)
            throw std::invalid_argument("full 3D direction disagrees with prepared axes");
        auto axes=s.solver_axes;std::sort(axes.begin(),axes.end());
        if(axes!=std::array<int,3>{0,1,2}) throw std::invalid_argument("invalid full 3D prepared axes");
        for(double v:{s.inlet_temperature,s.inlet_pressure,s.permeability_scale,s.forchheimer_scale,
                      s.sco2_nusselt_multiplier,x.reference_cell_length,x.reference_hydraulic_diameter})
            if(!std::isfinite(v) || v<=0.) throw std::invalid_argument("invalid full 3D scalar input");
        if(!std::isfinite(s.inlet_velocity) || !std::isfinite(s.dispersion))
            throw std::invalid_argument("nonfinite full 3D flow or dispersion input");
        const auto counts=shape(g);const auto np=counts[s.solver_axes[0]]*counts[s.solver_axes[2]];
        for(auto a:{s.inlet_opening,s.outlet_opening}) {
            extent(a,np,false,true); if(std::any_of(a.data,a.data+a.size,[](double v){return v>1.;}))
                throw std::invalid_argument("full 3D geometric opening exceeds one");
        }
    }
    model_h_common::validate_iteration_overrides(c.model_h_iterations);
    if(c.model_h_iterations.active()) {
        const auto mode=thermal_mode(in,c);
        const bool integral=mode==Full3DThermalMode::model_h || (mode==Full3DThermalMode::temperature
            && (g.nz==1 || (!c.conservative && c.force_cell_centered))
            && !uses_co2_eos(in.a.fluid) && (!in.solve_b || !uses_co2_eos(in.b.fluid)));
        if(!integral)throw std::invalid_argument("model-h iteration controls require an integral h(T) route");
    }
    if(!c.enthalpy.cpu_threads)throw std::invalid_argument("CPU thread count must be positive");
    if(!c.max_outer || !c.initial_simple_iterations || !c.warm_simple_iterations || !c.thermal_iterations
       || !std::isfinite(c.outer_temperature_tolerance) || c.outer_temperature_tolerance<=0.
       || !std::isfinite(c.thermal_relaxation) || c.thermal_relaxation<=0. || c.thermal_relaxation>1.)
        throw std::invalid_argument("invalid full 3D iteration controls");
    if(c.envelope_mode<0 || c.envelope_mode>2 || c.roughness_mode<0 || c.roughness_mode>2)
        throw std::invalid_argument("invalid full 3D resolved mode");
    for(const auto tolerance:{c.enthalpy.coupled_energy_tolerance,c.enthalpy.equation_energy_tolerance})
        if(!tolerance || !std::isfinite(*tolerance) || *tolerance<=0.)
            throw std::invalid_argument("full 3D requires finite positive true-h coupled and equation gates");
    if(c.enthalpy.algorithm!=EnthalpyAlgorithm::temperature_sou)
        throw std::invalid_argument("retired or unknown full 3D energy algorithm; use T-SOU");
    if(in.solve_b && (uses_co2_eos(in.a.fluid) || uses_co2_eos(in.b.fluid))) {
        for(auto source:in.sources)
            if(source.size && std::any_of(source.data,source.data+source.size,[](double x){return x!=0.;}))
                throw std::invalid_argument("full 3D true-h energy does not support physical sources");
        if(!c.enthalpy.max_iterations || !std::isfinite(c.enthalpy.omega)
           || c.enthalpy.omega<=0. || c.enthalpy.omega>1.
           || !std::isfinite(c.enthalpy.temperature_update_tolerance) || c.enthalpy.temperature_update_tolerance<=0.)
            throw std::invalid_argument("invalid full 3D energy controls");
        if(c.enthalpy.require_enthalpy_update_on_temperature
           && (!std::isfinite(c.enthalpy.update_tolerance) || c.enthalpy.update_tolerance<=0.))
            throw std::invalid_argument("full 3D T energy h-update tolerance must be finite and positive");
    }
    // These existing options are implemented in subsequent qualified slices;
    // failing before state initialization prevents a silent substitute solve.
    if(g.nz==1) {
        if(c.thermal_relaxation!=.7 || in.a.direction>3 || (in.solve_b && in.b.direction>3))
            throw std::invalid_argument("Nz=1 uses the original 2D thermal direction and relaxation contract");
        if(std::any_of(in.sources.begin(),in.sources.end(),[](auto x){return x.size>0;}))
            throw std::invalid_argument("Nz=1 thermal delegate has no MMS source hooks");
    }
    if(c.coarse_bootstrap && !c.coarse_iterations)
        throw std::invalid_argument("coarse bootstrap requires a positive iteration cap");
}

const char* energy_port_error(const GridView& g,const Full3DSide& side,const Faces& mass) {
    const auto counts=shape(g);
    const char* error=nullptr;
    for(int axis=0;axis<3;++axis) for(bool high:{false,true})
        boundary(g,axis,high,[&](std::size_t,std::size_t p,std::size_t f,double) {
            if(error || mass[axis][f]==0.) return;
            if(axis!=side.direction/2) {
                error="candidate energy mass crosses a non-port boundary";return;
            }
            const std::array<std::size_t,3> coord{p/(g.ny*g.nz),(p/g.nz)%g.ny,p%g.nz};
            const auto q=coord[side.solver_axes[0]]*counts[side.solver_axes[2]]+coord[side.solver_axes[2]];
            const bool inlet=high==static_cast<bool>(side.direction%2);
            if((inlet?side.inlet_opening:side.outlet_opening)[q]==0.)
                error="candidate energy mass crosses a closed port face";
            if(!inlet && (high?mass[axis][f]:-mass[axis][f])<0.)
                error="candidate energy has exterior inflow without a defined inlet state";
        });
    return error;
}

Simple3DMaterialView material(const Full3DFlowState& s) {
    return {view(s.epsilon),view(s.viscosity),view(s.effective_viscosity),
        view(s.permeability),view(s.forchheimer),view(s.temperature)};
}
Simple3DBoundaryView ports(const Full3DFlowState& s) {
    return {view(s.outlet_u_fraction),view(s.outlet_w_fraction)};
}
Simple3DStateView flow_view(Full3DFlowState& s) {
    return {writable(s.u),writable(s.v),writable(s.w),writable(s.pressure),writable(s.pressure_correction),
        writable(s.d_u),writable(s.d_v),writable(s.d_w),writable(s.density),writable(s.inlet_velocity)};
}
Values block_average(const Values& values,const std::array<std::size_t,3>& n) {
    const std::array<std::size_t,3> c{n[0]/2,n[1]/2,n[2]/2}; Values out(c[0]*c[1]*c[2]);
    for(std::size_t i=0;i<c[0];++i) for(std::size_t j=0;j<c[1];++j) for(std::size_t k=0;k<c[2];++k) {
        double value=0.;
        for(std::size_t x=0;x<2;++x) for(std::size_t y=0;y<2;++y) for(std::size_t z=0;z<2;++z)
            value+=values[index(n,2*i+x,2*j+y,2*k+z)];
        out[index(c,i,j,k)]=value/8.;
    }
    return out;
}
// scipy.ndimage.zoom(order=1, mode='nearest', grid_mode=False): points are
// aligned at the first and last samples, including staggered endpoints.
Values prolong(const Values& v,const std::array<std::size_t,3>& n,const std::array<std::size_t,3>& target) {
    Values out(target[0]*target[1]*target[2]);
    for(std::size_t i=0;i<target[0];++i) for(std::size_t j=0;j<target[1];++j) for(std::size_t k=0;k<target[2];++k) {
        const std::array<std::size_t,3> p{i,j,k};std::array<std::size_t,3> lower{},upper{};std::array<double,3> fraction{};
        for(std::size_t d=0;d<3;++d) {
            const double coordinate=target[d]>1?double(p[d])*double(n[d]-1)/double(target[d]-1):0.;
            lower[d]=static_cast<std::size_t>(std::floor(coordinate));upper[d]=std::min(lower[d]+1,n[d]-1);
            fraction[d]=coordinate-double(lower[d]);
        }
        double value=0.;
        for(std::size_t x=0;x<2;++x) for(std::size_t y=0;y<2;++y) for(std::size_t z=0;z<2;++z)
            value+=v[index(n,x?upper[0]:lower[0],y?upper[1]:lower[1],z?upper[2]:lower[2])]
                *(x?fraction[0]:1.-fraction[0])*(y?fraction[1]:1.-fraction[1])*(z?fraction[2]:1.-fraction[2]);
        out[index(target,p)]=value;
    }
    return out;
}
Values open_intersections(const Values& fine,const Values& coarse,double lo,double hi) {
    Values f(fine.size()+1),c(coarse.size()+1),out(fine.size()*coarse.size());
    std::partial_sum(fine.begin(),fine.end(),f.begin()+1);std::partial_sum(coarse.begin(),coarse.end(),c.begin()+1);
    for(std::size_t i=0;i<coarse.size();++i) for(std::size_t j=0;j<fine.size();++j)
        out[i*fine.size()+j]=std::max(std::min({c[i+1],f[j+1],hi})-std::max({c[i],f[j],lo}),0.);
    return out;
}
void bootstrap(const Full3DSide& a,Full3DFlowState& fine,Simple3DSolver& solver,
               const Simple3DControl& parent,std::size_t iterations,
               Full3DFlowState::BootstrapTrace& trace,std::size_t depth=1) {
    Full3DFlowState::Bootstrap info;const auto fg=grid(fine);const auto fn=shape(fg);
    const std::array<std::size_t,3> cn{fg.nx/2,fg.ny/2,fg.nz/2};info.shape=cn;
    const auto level_index=trace.levels.size();trace.levels.emplace_back();
    trace.levels[level_index].depth=depth;trace.levels[level_index].fine_shape=fn;
    trace.levels[level_index].coarse_shape=cn;trace.levels[level_index].iteration_cap=iterations;
    if(*std::min_element(cn.begin(),cn.end())<bootstrap_min_coarse_axis) {
        info.reason="coarse-too-small";trace.levels[level_index].stop=info.reason;
        if(depth==1)trace.decision=info.reason;fine.bootstrap=info;return;
    }
    try {
        Full3DFlowState c;const auto count=cn[0]*cn[1]*cn[2];
        for(std::size_t d=0;d<3;++d)c.widths[d].assign(cn[d],sum(view(fine.widths[d]))/cn[d]);
        const auto cg=grid(c);c.permeability=block_average(fine.permeability,fn);c.forchheimer=block_average(fine.forchheimer,fn);
        const double eps_mean=average(fine.epsilon);double variance=0.;
        for(double v:fine.epsilon)variance+=(v-eps_mean)*(v-eps_mean);
        c.epsilon=std::sqrt(variance/fine.epsilon.size())>1e-12?block_average(fine.epsilon,fn):Values(count,fine.epsilon[0]);
        const double rho=average(fine.density),mu=fine.viscosity[0];
        c.density.assign(count,rho);c.temperature.assign(count,a.inlet_temperature);c.viscosity.assign(count,mu);
        c.effective_viscosity.resize(count);for(std::size_t p=0;p<count;++p)c.effective_viscosity[p]=mu/c.epsilon[p];
        auto faces=empty_faces(cg);c.u=std::move(faces[0]);c.v=std::move(faces[1]);c.w=std::move(faces[2]);
        c.d_u.assign(c.u.size(),0.);c.d_v.assign(c.v.size(),0.);c.d_w.assign(c.w.size(),0.);
        c.pressure.assign(count,0.);c.pressure_correction.assign(count,0.);
        const auto xi=port_overlap_1d(cg.dx,a.inlet_rectangle[0],a.inlet_rectangle[1]);
        const auto zi=port_overlap_1d(cg.dz,a.inlet_rectangle[2],a.inlet_rectangle[3]);
        const auto xo=port_overlap_1d(cg.dx,a.outlet_rectangle[0],a.outlet_rectangle[1]);
        const auto zo=port_overlap_1d(cg.dz,a.outlet_rectangle[2],a.outlet_rectangle[3]);
        const auto xu=port_overlap_1d(cg.dx,a.outlet_rectangle[0],a.outlet_rectangle[1],true);
        const auto zw=port_overlap_1d(cg.dz,a.outlet_rectangle[2],a.outlet_rectangle[3],true);
        c.inlet_opening.resize(cg.nx*cg.nz);c.outlet_opening.resize(cg.nx*cg.nz);
        c.outlet_u_fraction.resize((cg.nx+1)*cg.nz);c.outlet_w_fraction.resize(cg.nx*(cg.nz+1));
        std::vector<unsigned char> opened(cg.nx*cg.nz);
        for(std::size_t i=0;i<cg.nx;++i) for(std::size_t k=0;k<cg.nz;++k) {
            const auto p=i*cg.nz+k;c.inlet_opening[p]=xi[i]*zi[k];c.outlet_opening[p]=xo[i]*zo[k];opened[p]=c.outlet_opening[p]>0.;
        }
        for(std::size_t i=0;i<=cg.nx;++i) for(std::size_t k=0;k<cg.nz;++k)c.outlet_u_fraction[i*cg.nz+k]=xu[i]*zo[k];
        for(std::size_t i=0;i<cg.nx;++i) for(std::size_t k=0;k<=cg.nz;++k)c.outlet_w_fraction[i*(cg.nz+1)+k]=xo[i]*zw[k];
        const auto ox=open_intersections(fine.widths[0],c.widths[0],a.inlet_rectangle[0],a.inlet_rectangle[1]);
        const auto oz=open_intersections(fine.widths[2],c.widths[2],a.inlet_rectangle[2],a.inlet_rectangle[3]);
        Values mass_open(fg.nx*fg.nz);
        for(std::size_t i=0;i<fg.nx;++i) for(std::size_t k=0;k<fg.nz;++k) {
            const auto p=i*fg.nz+k;mass_open[p]=fine.inlet_opening[p]>0.?
                fine.fixed_inlet_massflux[p]*fine.epsilon[i*fg.ny*fg.nz+k]/fine.inlet_opening[p]:0.;
        }
        c.inlet_velocity.resize(cg.nx*cg.nz);c.fixed_inlet_massflux.resize(cg.nx*cg.nz);
        for(std::size_t i=0;i<cg.nx;++i) for(std::size_t k=0;k<cg.nz;++k) {
            double mass=0.;
            for(std::size_t z=0;z<fg.nz;++z) {double integrated=0.;
                for(std::size_t x=0;x<fg.nx;++x)integrated+=ox[i*fg.nx+x]*mass_open[x*fg.nz+z];
                mass+=integrated*oz[k*fg.nz+z];}
            const auto p=i*cg.nz+k;c.inlet_velocity[p]=mass/(cg.dx[i]*cg.dz[k]*rho*c.epsilon[i*cg.ny*cg.nz+k]);
            c.fixed_inlet_massflux[p]=c.inlet_velocity[p]*rho;c.v[i*(cg.ny+1)*cg.nz+k]=c.inlet_velocity[p];
        }
        Simple3DSolver coarse(cg,{opened.data(),opened.size()});
        auto controls=Full3DControl{}.simple;controls.max_iterations=iterations;
        controls.alpha_velocity=parent.alpha_velocity;controls.alpha_pressure=parent.alpha_pressure;controls.alpha_density=parent.alpha_density;
        controls.ideal_gas=parent.ideal_gas;controls.gas_constant=parent.gas_constant;controls.pressure_reference_absolute=parent.pressure_reference_absolute;
        controls.adaptive_pressure_tolerance=parent.adaptive_pressure_tolerance;controls.cancel=parent.cancel;controls.context=parent.context;
        controls.ordering=count>=200000?Simple3DOrdering::red_black:Simple3DOrdering::natural;
        if(controls.ideal_gas && controls.massflux_inlet)coarse.capture_massflux_target(view(c.fixed_inlet_massflux));
        trace.levels[level_index].child_selected=count>bootstrap_auto_cell_threshold;
        if(count>bootstrap_auto_cell_threshold)bootstrap(a,c,coarse,controls,bootstrap_recursive_iterations,trace,depth+1);
        try {c.last=coarse.solve(material(c),ports(c),flow_view(c),controls);}
        catch(...) {
            trace.levels[level_index].charged_iterations=coarse.charged_iterations();
            trace.levels[level_index].solve_started=coarse.charged_iterations()>0;throw;
        }
        auto& level=trace.levels[level_index];
        level.charged_iterations=c.last.iterations;level.converged=c.last.converged;
        level.solve_started=level.charged_iterations>0;
        const char* stops[]{"ongoing","tol","stall","max_iter","nonfinite","cancelled","pressure_failure","post_closure"};
        level.stop=stops[static_cast<unsigned>(c.last.stop)];
        if(c.last.stop==SimpleStop::cancelled)throw Cancelled{};
        if(c.last.stop==SimpleStop::pressure_failure)throw std::runtime_error(c.last.linear.detail);
        Values pin(fg.nx*fg.nz);
        for(std::size_t i=0;i<fg.nx;++i) for(std::size_t k=0;k<fg.nz;++k)pin[i*fg.nz+k]=fine.pressure[(i*fg.ny+fg.ny-1)*fg.nz+k];
        for(std::size_t d=0;d<3;++d) {auto from=cn,to=fn;++from[d];++to[d];
            Values* dest[]{&fine.u,&fine.v,&fine.w};const Values* source[]{&c.u,&c.v,&c.w};*dest[d]=prolong(*source[d],from,to);}
        fine.pressure=prolong(c.pressure,cn,fn);
        if(finite(fine.u)&&finite(fine.v)&&finite(fine.w)&&finite(fine.pressure)&&finite(fine.density)) {
            for(std::size_t i=0;i<fg.nx;++i) for(std::size_t k=0;k<fg.nz;++k) {
                const auto p=i*fg.nz+k;
                if(fine.outlet_opening[p]>0.)fine.pressure[(i*fg.ny+fg.ny-1)*fg.nz+k]=pin[p];
                fine.v[i*(fg.ny+1)*fg.nz+k]=fine.inlet_velocity[p];
            }
            solver.refresh_after_seed(material(fine),ports(fine),flow_view(fine),parent);
        }
        info.applied=true;info.converged=c.last.converged;info.iterations=c.last.iterations;
        level.applied=true;
        if(!coarse.history().legacy.empty())info.residual=coarse.history().legacy.back();
    } catch(const Cancelled&) {
        trace.levels[level_index].stop="cancelled";if(depth==1)trace.decision="cancelled";throw;
    } catch(const std::exception& error) {
        info.reason="exception:"+std::string(error.what());
        if(trace.levels[level_index].stop=="not-started")trace.levels[level_index].stop="error";
    }
    if(depth==1)trace.decision=info.applied?"applied":"error";
    fine.bootstrap=std::move(info);
}

struct Runtime {
    const Full3DInput& input; const Full3DControl& control;
    const Full3DThermalMode mode;
    const std::array<SidePhysics,2> physics;
    const bool cell_centered,legacy_single_sco2;
    Full3DResult result;
    PropertyEvaluator props;
    EnthalpyEOS eos;
    StaggeredTemperatureDriver thermal;
    std::array<std::unique_ptr<Simple3DSolver>,2> simple;
    std::array<FluidProperties,2> inlet;
    std::array<double,2> drag_k{},drag_cf{},mass_flux{},dispersion{},hv_ratio{1.,1.};
    std::array<Values,2> conductivity,rho_cp,hv;
    std::array<Values,2> transport_temperature;
    std::array<std::vector<FluidProperties>,2> transport_values;
    std::array<Values,3> temperature,previous;
    std::optional<Full3DThermalRunState> pending;
    std::unique_ptr<ModelHRun2D> model_h_2d;
    std::unique_ptr<ModelHRun3D> model_h_3d;
    std::unique_ptr<LegacyTemperatureRun> legacy;
    std::unique_ptr<EnthalpyRun> enthalpy;
    std::array<std::array<Values,2>,2> planar_mass;
    std::array<Values,2> legacy_capacity;
    Values zero_velocity;
    double unit_depth=1.;
    const Full3DSide& side(std::size_t s) const { return s?input.b:input.a; }
    ArrayView<const double> epsilon(std::size_t s) const { return s?input.geometry.epsilon_b:input.geometry.epsilon_a; }
    bool active(std::size_t s) const { return !s || input.solve_b; }
    explicit Runtime(const Full3DInput& i,const Full3DControl& c):input(i),control(c),
        mode(thermal_mode(i,c)),physics(resolve_full_3d_physics(i,c)),
        cell_centered(mode==Full3DThermalMode::temperature
            && (i.geometry.grid.nz==1 || (!c.conservative && c.force_cell_centered))),
        legacy_single_sco2(!i.solve_b && i.a.fluid==Fluid::sco2) {
        const auto physical=shape(i.geometry.grid);
        for(std::size_t s=0;s<2;++s) if(s==0||i.solve_b) {
            auto& trace=result.flow[s].bootstrap_trace;trace.available=true;
            trace.selected=c.coarse_bootstrap;trace.coarse_iteration_cap=c.coarse_iterations;
            trace.policy=c.coarse_bootstrap?"explicit_on":"explicit_off";
            trace.decision=c.coarse_bootstrap?"not-started":"disabled";
            for(std::size_t d=0;d<3;++d)trace.fine_shape[d]=physical[side(s).solver_axes[d]];
        }
    }

    void initialize();
    void initialize_side(std::size_t s);
    void start_flow(std::size_t s,std::size_t cap,const Simple3DRunState* saved=nullptr);
    bool advance_flow(std::size_t s,const std::string& stage);
    void check_water(const std::array<Values,3>& t,const std::array<Values,2>& pressure);
    const FluidProperties& inlet_transport(std::size_t s,std::size_t p);
    void heat_transfer(std::size_t s,bool warm);
    Full3DThermalEvidence prepare(bool warm,std::size_t outer);
    void begin_thermal(std::size_t outer);
    void start_thermal(const Full3DThermalRunState* saved=nullptr);
    void start_enthalpy(const EnthalpyRunState* saved=nullptr);
    bool advance_thermal();
    void finish_thermal();
    void refresh_flow(std::size_t s,std::size_t outer,const std::optional<PressurePortState>& pressure);
    void refresh_thermal_properties(std::size_t outer);

    void finish();
    void property_ranges(std::size_t s,const char* source,const char* stage,const char* layout,
                         const std::vector<std::size_t>& dims,ArrayView<const double> values,unsigned mask);
    void temperature_ranges(const char* stage,const char* layout);
    RangeObservation nu_range(std::size_t s,const char* source,const char* stage,const char* layout,
                              std::vector<std::size_t> dims) const;
    void bulk_ranges();
};

void Runtime::property_ranges(std::size_t s,const char* source,const char* stage,const char* layout,
                             const std::vector<std::size_t>& dims,ArrayView<const double> values,unsigned mask) {
    const auto fluid=side(s).fluid;if(uses_co2_eos(fluid))return;
    const char* names[]{"density","viscosity","conductivity","cp"};
    for(unsigned bit=0;bit<4;++bit) if((mask&(1u<<bit)) && (fluid==Fluid::water || bit!=0)) {
        RangeObservation r;r.view=source;r.model=std::string(fluid==Fluid::air?"air_":"water_")+names[bit];
        r.side=s;r.stage=stage;r.layout=layout;r.shape=dims;
        r.bounds=fluid==Fluid::water?model_coefficients::water_temperature_range:
            (bit==3?model_coefficients::air_cp_temperature_range:model_coefficients::air_temperature_range);
        observe_range(result.range_observations,std::move(r),values);
    }
}

void Runtime::temperature_ranges(const char* stage,const char* layout) {
    const auto& g=input.geometry.grid;
    for(std::size_t s=0;s<2;++s) property_ranges(s,"property_state",stage,layout,{g.nx,g.ny,g.nz},view(temperature[s]),15);
}

RangeObservation Runtime::nu_range(std::size_t s,const char* source,const char* stage,const char* layout,
                                   std::vector<std::size_t> dims) const {
    const auto fluid=side(s).fluid;RangeObservation r;r.view=source;
    r.model=fluid==Fluid::air?"air":(fluid==Fluid::water?"water":fluid==Fluid::co2?"co2":"sco2");
    r.topology=input.topology==Topology::diamond?"Diamond":"Gyroid";r.side=s;r.stage=stage;r.layout=layout;r.shape=std::move(dims);
    r.bounds=fluid==Fluid::air?model_coefficients::air_nu_re_range:
        (fluid==Fluid::water?model_coefficients::water_nu_re_range:
         fluid==Fluid::co2?model_coefficients::co2_nu_re_range:model_coefficients::sco2_nu_re_range);
    return r;
}

void Runtime::bulk_ranges() {
    const auto& g=input.geometry.grid;const auto& geo=input.geometry;
    for(std::size_t s=0;s<2;++s) if(active(s) && side(s).fluid!=Fluid::air) {
        const auto& a=side(s);
        property_ranges(s,"property","inlet","scalar-hv-property",{},{&a.inlet_temperature,1},15);
        auto raw=nu_range(s,"nu_raw","inlet",geo.spatial?"real-cell(x,y,z)-bulk-Re":"scalar-hv-bulk",
                          geo.spatial?std::vector<std::size_t>{g.nx,g.ny,g.nz}:std::vector<std::size_t>{});
        auto source=nu_range(s,"nu","inlet",geo.spatial?"scalar-zoned-call":"scalar-hv-bulk",{});
        for(std::size_t p=0;p<(geo.spatial?g.nx*g.ny*g.nz:1);++p) {
            const double re=inlet[s].rho*std::max(std::abs(a.inlet_velocity),0.)*std::max(geo.hydraulic_diameter[p],1e-12)
                /std::max(inlet[s].mu,1e-30);
            observe_range_value(raw,re,p);auto one=source;observe_range_value(one,std::max(re,1.),0);
            merge_range_observation(result.range_observations,std::move(one));
        }
        merge_range_observation(result.range_observations,std::move(raw));
    }
}

void Runtime::initialize_side(std::size_t s) {
    const auto& a=side(s);auto& state=result.flow[s];const auto& geo=input.geometry;const auto& g=geo.grid;
    const std::array<ArrayView<const double>,3> widths{g.dx,g.dy,g.dz};
    for(std::size_t d=0;d<3;++d) {
        const auto w=widths[static_cast<std::size_t>(a.solver_axes[d])];
        state.widths[d]=Values(w.data,w.data+w.size);
        if(d==1 && a.direction%2) std::reverse(state.widths[d].begin(),state.widths[d].end());
    }
    const auto sg=grid(state);const auto n=sg.nx*sg.ny*sg.nz;
    state.epsilon=to_solver(g,a,geo.epsilon);
    state.permeability=to_solver(g,a,geo.permeability);state.forchheimer=to_solver(g,a,geo.forchheimer);
    for(double& value:state.permeability) value*=a.permeability_scale;
    for(double& value:state.forchheimer) value*=a.forchheimer_scale;
    // Uniform preparation retains scalar drag coefficients for its 1D pressure
    // seed. Summing repeated copies would introduce a grid-dependent roundoff.
    drag_k[s]=geo.spatial?average(state.permeability):state.permeability[0];
    drag_cf[s]=geo.spatial?average(state.forchheimer):state.forchheimer[0];
    state.inlet_opening=Values(a.inlet_opening.data,a.inlet_opening.data+a.inlet_opening.size);
    state.outlet_opening=Values(a.outlet_opening.data,a.outlet_opening.data+a.outlet_opening.size);
    const auto xi=port_overlap_1d(sg.dx,a.inlet_rectangle[0],a.inlet_rectangle[1]);
    const auto zi=port_overlap_1d(sg.dz,a.inlet_rectangle[2],a.inlet_rectangle[3]);
    const auto xo=port_overlap_1d(sg.dx,a.outlet_rectangle[0],a.outlet_rectangle[1]);
    const auto zo=port_overlap_1d(sg.dz,a.outlet_rectangle[2],a.outlet_rectangle[3]);
    const auto xu=port_overlap_1d(sg.dx,a.outlet_rectangle[0],a.outlet_rectangle[1],true);
    const auto zw=port_overlap_1d(sg.dz,a.outlet_rectangle[2],a.outlet_rectangle[3],true);
    std::vector<unsigned char> opened(state.outlet_opening.size());
    state.outlet_u_fraction.resize((sg.nx+1)*sg.nz);state.outlet_w_fraction.resize(sg.nx*(sg.nz+1));
    for(std::size_t i=0;i<sg.nx;++i) for(std::size_t k=0;k<sg.nz;++k) {
        const auto p=i*sg.nz+k;
        if(std::abs(state.inlet_opening[p]-xi[i]*zi[k])>1e-15+1e-12*std::abs(xi[i]*zi[k])
           || std::abs(state.outlet_opening[p]-xo[i]*zo[k])>1e-15+1e-12*std::abs(xo[i]*zo[k]))
            throw std::invalid_argument("prepared full 3D openings disagree with rectangles");
        opened[p]=state.outlet_opening[p]>0.;
    }
    for(std::size_t i=0;i<=sg.nx;++i) for(std::size_t k=0;k<sg.nz;++k) state.outlet_u_fraction[i*sg.nz+k]=xu[i]*zo[k];
    for(std::size_t i=0;i<sg.nx;++i) for(std::size_t k=0;k<=sg.nz;++k) state.outlet_w_fraction[i*(sg.nz+1)+k]=xo[i]*zw[k];
    state.temperature.assign(n,a.inlet_temperature);state.density.assign(n,inlet[s].rho);
    state.viscosity.assign(n,inlet[s].mu);state.effective_viscosity.resize(n);
    for(std::size_t p=0;p<n;++p) state.effective_viscosity[p]=state.viscosity[p]/state.epsilon[p];
    auto faces=empty_faces(sg);state.u=std::move(faces[0]);state.v=std::move(faces[1]);state.w=std::move(faces[2]);
    state.d_u.assign(state.u.size(),0.);state.d_v.assign(state.v.size(),0.);state.d_w.assign(state.w.size(),0.);
    state.pressure.assign(n,0.);state.pressure_correction.assign(n,0.);
    state.inlet_velocity.resize(sg.nx*sg.nz);state.fixed_inlet_massflux.resize(sg.nx*sg.nz);
    for(std::size_t i=0;i<sg.nx;++i) for(std::size_t k=0;k<sg.nz;++k) {
        const auto p=i*sg.nz+k;state.inlet_velocity[p]=state.inlet_opening[p]*a.inlet_velocity;
        state.fixed_inlet_massflux[p]=state.inlet_velocity[p]*inlet[s].rho;
        state.v[i*(sg.ny+1)*sg.nz+k]=state.inlet_velocity[p];
    }
    mass_flux[s]=inlet[s].rho*a.inlet_velocity;
    const double drag=inlet[s].mu*mass_flux[s]/std::max(drag_k[s],1e-16)+drag_cf[s]*mass_flux[s]*mass_flux[s];
    if(a.fluid==Fluid::air)
        state.pressure_reference=pressure_initial_reference(predict_outlet_p_sq(a.inlet_pressure,a.inlet_temperature,drag,sum(sg.dy)),
                                                           a.inlet_pressure,state.pressure_iterations);
    else state.pressure_reference=std::max(a.inlet_pressure-drag*sum(sg.dy)/inlet[s].rho,1e4);
    simple[s]=std::make_unique<Simple3DSolver>(sg,ArrayView<const unsigned char>{opened.data(),opened.size()});
}

void Runtime::start_flow(std::size_t s,std::size_t cap,const Simple3DRunState* saved) {
    auto& v=result.flow[s];const auto& a=side(s);auto c=control.simple;
    c.max_iterations=cap;c.ideal_gas=a.fluid==Fluid::air;c.pressure_reference_absolute=v.pressure_reference;
    c.cancel=control.cancel;c.context=control.context;
    if(!saved && control.coarse_bootstrap && simple[s]->history().legacy.empty() && !v.bootstrap) {
        if(c.ideal_gas && c.massflux_inlet)simple[s]->capture_massflux_target(view(v.fixed_inlet_massflux));
        bootstrap(a,v,*simple[s],c,control.coarse_iterations,v.bootstrap_trace);
    }
    const Simple3DMaterialView material{view(v.epsilon),view(v.viscosity),view(v.effective_viscosity),
        view(v.permeability),view(v.forchheimer),view(v.temperature)};
    const Simple3DBoundaryView boundary{view(v.outlet_u_fraction),view(v.outlet_w_fraction)};
    const Simple3DStateView fields{writable(v.u),writable(v.v),writable(v.w),writable(v.pressure),writable(v.pressure_correction),
        writable(v.d_u),writable(v.d_v),writable(v.d_w),writable(v.density),writable(v.inlet_velocity)};
    if(saved)simple[s]->restore_active(material,boundary,fields,c,*saved);
    else simple[s]->start(material,boundary,fields,c);
    if(simple[s]->phase()==SimplePhase::cancelled)throw Cancelled{};
}

bool Runtime::advance_flow(std::size_t s,const std::string& stage) {
    if(simple[s]->phase()==SimplePhase::active && simple[s]->advance()==SimplePhase::active)return false;
    auto& v=result.flow[s];const auto& a=side(s);v.last=simple[s]->take_result();
    if(v.last.stop==SimpleStop::cancelled) throw Cancelled{};
    if(v.last.stop==SimpleStop::pressure_failure) throw std::runtime_error("full 3D SIMPLE pressure solve failed: "+v.last.linear.detail);
    anchor(a,v);v.history=simple[s]->history();
    if(!v.last.converged) {
        const char* reasons[]{"ongoing","tol","stall","max_iter","nonfinite","cancelled","pressure_failure","post_closure"};
        result.simple_failures.push_back(std::string(s?"B@":"A@")+stage+"["+reasons[static_cast<unsigned>(v.last.stop)]+"]");
    }
    update_real(input.geometry.grid,a,v);v.inlet_pressure=inlet_state(a,v);
    return true;
}

void Runtime::initialize() {
    const auto& g=input.geometry.grid;const auto n=g.nx*g.ny*g.nz;
    for(std::size_t s=0;s<2;++s) {
        const auto& a=side(s);inlet[s]=props.evaluate(a.fluid,a.inlet_temperature,a.inlet_pressure);
        if(active(s)) initialize_side(s);
        record_property_samples(result.property_sampling,s,-1,"initialize",
            uses_co2_eos(a.fluid)?"HEOS":"model_resource","inlet","inlet","scalar_evaluation",
            {"density","viscosity","conductivity","rho_cp","dispersion"});
        if(active(s)) {
            record_property_samples(result.flow[s].property_sampling,s,-1,"flow",
                a.fluid==Fluid::air?"ideal_gas":uses_co2_eos(a.fluid)?"HEOS":"model_resource","inlet",
                a.fluid==Fluid::air?"current_SIMPLE_absolute":"inlet",
                a.fluid==Fluid::air?"local_evaluation":"scalar_evaluation",{"density"});
            record_property_samples(result.flow[s].property_sampling,s,-1,"flow",
                uses_co2_eos(a.fluid)?"HEOS":"model_resource","inlet","inlet","scalar_evaluation",{"viscosity"});
        }
        conductivity[s].resize(n);rho_cp[s].assign(n,inlet[s].rho*inlet[s].cp);hv[s].assign(n,0.);
        dispersion[s]=a.dispersion>0.?a.dispersion*inlet[s].rho*inlet[s].cp*std::abs(a.inlet_velocity)*input.geometry.reference_hydraulic_diameter:0.;
        for(std::size_t p=0;p<n;++p) conductivity[s][p]=epsilon(s)[p]*inlet[s].k+dispersion[s];
        if(input.geometry.asymmetric) {
            const auto& z=a.heat_transfer_geometry;
            property_ranges(s,"property","inlet","scalar-hv-property",{},{&a.inlet_temperature,1},a.fluid==Fluid::air?6:15);
            std::size_t geometry_call=0;
            auto coefficient=[&](double area,double diameter) {
                diameter=std::max(diameter,1e-12);
                const double re=inlet[s].rho*std::max(std::abs(a.inlet_velocity),0.)*diameter/std::max(inlet[s].mu,1e-30);
                const char* layout=geometry_call++?"scalar-geometry-side":"scalar-geometry-reference";
                auto raw=nu_range(s,"nu_raw","inlet",layout,{});observe_range_value(raw,re,0);
                merge_range_observation(result.range_observations,std::move(raw));
                auto source=nu_range(s,"nu","inlet",layout,{});observe_range_value(source,std::max(re,1.),0);
                merge_range_observation(result.range_observations,std::move(source));
                const double nu=std::max(fluid_nusselt(a.fluid,input.topology,std::max(re,1.),inlet[s].pr,
                    input.geometry.reference_cell_length,diameter,a.sco2_nusselt_multiplier),nusselt_floor(a.fluid));
                return area*nu/diameter;
            };
            const double reference=coefficient(z[2],z[3]);
            hv_ratio[s]=reference>0.?coefficient(z[0],z[1])/reference:1.;
        }
    }
    temperature[0].assign(n,input.a.inlet_temperature);temperature[1].assign(n,input.b.inlet_temperature);
    temperature[2].assign(n,control.initial_solid_temperature.value_or(.5*(input.a.inlet_temperature+input.b.inlet_temperature)));
}

void Runtime::check_water(const std::array<Values,3>& t,const std::array<Values,2>& pressure) {
    for(std::size_t s=0;s<2;++s) if(side(s).fluid==Fluid::water)
        for(std::size_t p=0;p<t[s].size();++p)
            props.check_water(t[s][p],active(s)?pressure[s][p]:side(s).inlet_pressure);
}

const FluidProperties& Runtime::inlet_transport(std::size_t s,std::size_t p) {
    auto& sampled=transport_temperature[s];auto& values=transport_values[s];
    if(values.empty()) {
        sampled.assign(temperature[s].size(),std::numeric_limits<double>::quiet_NaN());
        values.resize(temperature[s].size());
    }
    // Side, fluid and inlet pressure are fixed for this runtime; restore starts empty.
    if(sampled[p]!=temperature[s][p]) {
        values[p]=props.transport(side(s).fluid,temperature[s][p],side(s).inlet_pressure);
        sampled[p]=temperature[s][p];
    }
    return values[p];
}

void Runtime::heat_transfer(std::size_t s,bool warm) {
    if(!active(s)) return;
    const auto& a=side(s);const auto& geo=input.geometry;const auto& velocity=result.flow[s].velocity_real;
    const auto& g=geo.grid;
    property_ranges(s,"property","main","scalar-hv-property",{},{&a.inlet_temperature,1},a.fluid==Fluid::air?6:15);
    auto raw_range=nu_range(s,"nu_raw","main","real-cell(x,y,z)-hv-speed",{g.nx,g.ny,g.nz});
    auto source_range=nu_range(s,"nu","main","real-cell(x,y,z)-hv-speed",{g.nx,g.ny,g.nz});
    auto pr_range=source_range; pr_range.view="nu_pr"; pr_range.bounds=model_coefficients::co2_nu_pr_range;
    auto& observation=result.nu_observations[s];
    const bool local=physics[s].local_heat_transfer(warm);
    if(local) {
        observation={};observation.available=true;observation.cells=hv[s].size();observation.pressure=a.inlet_pressure;
        observation.raw_min=observation.re_min=observation.pr_min=observation.temperature_min=std::numeric_limits<double>::infinity();
        observation.raw_max=observation.re_max=observation.pr_max=observation.temperature_max=-std::numeric_limits<double>::infinity();
    }
    for(std::size_t p=0;p<hv[s].size();++p) {
        auto property=inlet[s];
        if(local) property=inlet_transport(s,p);
        const double speed=std::abs(std::sqrt(velocity[0][p]*velocity[0][p]+velocity[1][p]*velocity[1][p]
                                           +velocity[2][p]*velocity[2][p]))+1e-12;
        const double re=property.rho*speed*geo.hydraulic_diameter[p]/property.mu;
        observe_range_value(raw_range,re,p);observe_range_value(source_range,std::max(re,1.),p);
        if(a.fluid==Fluid::co2)observe_range_value(pr_range,property.pr,p);
        const double raw_nu=fluid_nusselt(a.fluid,input.topology,std::max(re,1.),property.pr,
            geo.cell_length[p],geo.hydraulic_diameter[p],a.sco2_nusselt_multiplier);
        const double nu=std::max(raw_nu,nusselt_floor(a.fluid));
        if(observation.available) {
            observation.floor_cells+=raw_nu<nusselt_floor(a.fluid);
            observation.raw_min=std::min(observation.raw_min,raw_nu);observation.raw_max=std::max(observation.raw_max,raw_nu);
            observation.re_min=std::min(observation.re_min,re);observation.re_max=std::max(observation.re_max,re);
            observation.pr_min=std::min(observation.pr_min,property.pr);observation.pr_max=std::max(observation.pr_max,property.pr);
            observation.temperature_min=std::min(observation.temperature_min,temperature[s][p]);
            observation.temperature_max=std::max(observation.temperature_max,temperature[s][p]);
        }
        double value=geo.area_density[p]*(nu*property.k/geo.hydraulic_diameter[p]);
        if(a.fluid==Fluid::air) {
            const double re_in=inlet[s].rho*std::abs(a.inlet_velocity)*geo.reference_hydraulic_diameter/std::max(inlet[s].mu,1e-12);
            value*=nu_extra_roughness_factor(re_in,static_cast<RoughnessMode>(control.roughness_mode),
                                           control.roughness_height,geo.reference_hydraulic_diameter);
        }
        hv[s][p]=value*hv_ratio[s];
    }
    merge_range_observation(result.range_observations,std::move(raw_range));
    merge_range_observation(result.range_observations,std::move(source_range));
    if(a.fluid==Fluid::co2)merge_range_observation(result.range_observations,std::move(pr_range));
}

Full3DThermalEvidence Runtime::prepare(bool warm,std::size_t outer) {
    Full3DThermalEvidence e;const auto& geo=input.geometry;const auto& g=geo.grid;
    e.mode=mode;
    const bool true_h=mode==Full3DThermalMode::true_h,model_h=mode==Full3DThermalMode::model_h;
    const bool cc=cell_centered;
    if(cc && legacy_single_sco2)
        e.temperature_algorithm="legacy_frozen_cp_single_a_cc_v1";
    if(warm)temperature_ranges("main","real-cell(x,y,z)-warm");
    for(std::size_t s=0;s<2;++s) if(active(s)) e.pressure[s]=result.flow[s].pressure_real;
    if(!true_h) check_water(temperature,e.pressure);
    for(const auto& t:temperature) if(!finite(t)) throw std::domain_error("nonfinite full 3D thermal warm start");
    for(std::size_t s=0;s<2;++s) {
        heat_transfer(s,warm);e.hv[s]=hv[s];e.conductivity[s]=conductivity[s];
        if(!active(s)) {
            e.face_velocity[s]=empty_faces(g);e.rho_cp[s]=rho_cp[s];
            if(cc) {
                e.mass[s]=empty_faces(g);
                e.temperature_cp_coefficients[s].fill(std::numeric_limits<double>::quiet_NaN());
            }
            continue;
        }
        const auto& a=side(s);const auto& flow=result.flow[s];e.face_velocity[s]=flow.face_velocity_real;
        const auto sample_index=static_cast<std::int64_t>(outer);
        const char* provider=physics[s].transport_provider();
        record_property_samples(e.property_sampling,s,sample_index,"thermal_hv",provider,
            physics[s].local_heat_transfer(warm)?"previous_thermal_or_seed":"inlet","inlet",
            physics[s].local_heat_transfer(warm)?"local_evaluation":"scalar_evaluation",{"density","viscosity","conductivity","Pr"});
        record_property_samples(e.property_sampling,s,sample_index,true_h?"thermal_warmup":"thermal",
            "outer_property_state",outer?"previous_thermal_return":"inlet","inlet","copy",{"conductivity"});
        if(control.variable_rho_cp && a.fluid==Fluid::air)
            record_property_samples(e.property_sampling,s,sample_index,true_h?"thermal_warmup":"thermal",
                "model_resource",warm?"previous_thermal_or_seed":"inlet","inlet",
                "current_SIMPLE_density_times_cp",{"rho_cp"});
        else if(!model_h && (!cc || legacy_single_sco2 || true_h))
            record_property_samples(e.property_sampling,s,sample_index,true_h?"thermal_warmup":"thermal",
                "outer_property_state",outer?"previous_thermal_return":"inlet","inlet","copy",{"rho_cp"});
        if(physics[s].energy==EnergyRelation::integral_cp_T)
            record_property_samples(e.property_sampling,s,sample_index,"thermal","model_resource",
                "current_thermal_iterate",nullptr,"integral_cp_T",{"energy_relation"});
        else if(!true_h)
            record_property_samples(e.property_sampling,s,sample_index,"thermal","outer_property_state",
                outer?"previous_thermal_return":"inlet",nullptr,"frozen_capacity_temperature",{"energy_relation"});
        if(model_h||cc) e.mass[s]=mass_faces(g,e.face_velocity[s],epsilon(s),flow.density_real);
        e.inlet_capacity[s]=inlet_capacity(g,a.direction,e.face_velocity[s],epsilon(s),flow.density_real,inlet[s].cp);
        if(control.variable_rho_cp && a.fluid==Fluid::air)
            for(std::size_t p=0;p<rho_cp[s].size();++p) {
                const double sampled_cp=props.transport(a.fluid,warm?temperature[s][p]:a.inlet_temperature,a.inlet_pressure).cp;
                rho_cp[s][p]=flow.density_real[p]*sampled_cp;
            }
        if(control.variable_rho_cp && a.fluid==Fluid::air)
            property_ranges(s,"property","property-refresh","real-cell(x,y,z)-thermal-cp",
                warm?std::vector<std::size_t>{g.nx,g.ny,g.nz}:std::vector<std::size_t>{},
                warm?view(temperature[s]):ArrayView<const double>{&a.inlet_temperature,1},8);
        e.rho_cp[s]=rho_cp[s];
        if(cc || model_h) {
            if(legacy_single_sco2) e.temperature_cp_coefficients[s].fill(std::numeric_limits<double>::quiet_NaN());
            else if(a.fluid==Fluid::air) e.temperature_cp_coefficients[s]=model_coefficients::model_h_air;
            else if(a.fluid==Fluid::water) e.temperature_cp_coefficients[s]=model_coefficients::model_h_water;
            else throw std::invalid_argument("full CC model enthalpy requires air or water on solved sides");
        }
        if(!model_h && (!cc || legacy_single_sco2) && control.conservative && control.strict_mass_balance
           && (a.fluid!=Fluid::air || control.variable_rho_cp))
            balance_outflow(g,a.direction,e.face_velocity[s],multiply(epsilon(s),view(rho_cp[s])));
    }
    return e;
}

void Runtime::begin_thermal(std::size_t outer) {
    pending.emplace();auto& run=*pending;
    run.evidence=prepare(outer>0 || control.initial_solid_temperature.has_value(),outer);
    run.record.outer_index=outer;run.evidence.outer_index=outer;
    run.initial=temperature;
    run.remaining=control.model_h_iterations.max_iterations
        ?control.model_h_iterations.max_iterations:control.thermal_iterations;
    const bool startup=mode==Full3DThermalMode::model_h
        && (input.a.fluid==Fluid::water || input.b.fluid==Fluid::water) && outer==0;
    run.budget=mode==Full3DThermalMode::true_h?2:(startup?std::min<std::size_t>(run.remaining,250):run.remaining);
    start_thermal();
}

void Runtime::start_thermal(const Full3DThermalRunState* saved) {
    auto& run=*pending;auto& e=run.evidence;const auto& g=input.geometry.grid;
    const auto& geo=input.geometry;const bool true_h=mode==Full3DThermalMode::true_h;
    if(saved && saved->enthalpy) {start_enthalpy(&*saved->enthalpy);return;}
    const auto total=control.model_h_iterations.max_iterations
        ?control.model_h_iterations.max_iterations:control.thermal_iterations;
    std::array<TemperatureBoundary,2> bc;
    for(std::size_t s=0;s<2;++s)bc[s]={active(s)?side(s).direction:3,side(s).inlet_temperature,{},
        active(s)?side(s).inlet_opening:ArrayView<const double>{},view(e.inlet_capacity[s])};
    const TemperatureStateView fields{writable(temperature[0]),writable(temperature[1]),writable(temperature[2])};
    const auto prescribed=input.solve_b?ArrayView<const double>{}:view(run.initial[1]);
    if(mode==Full3DThermalMode::model_h) {
        auto ba=bc[0],bb=bc[1];ba.capacity_flux={};bb.capacity_flux={};
        ModelHControl3D mc{run.budget,250,1e-4,control.thermal_relaxation,
            control.refined_port_energy?1.:control.thermal_relaxation,control.thermal_relaxation,
            true,control.refined_port_energy,control.red_black_energy,control.cancel,nullptr,control.context};
        mc.cpu_threads=control.enthalpy.cpu_threads;
        mc.strict_energy_balance=strict_model_h(input);
        const auto settings=model_h_common::apply_iteration_tolerances(mc,control.model_h_iterations,total);
        if(!saved)run.record.model_h_iterations.push_back(settings);
        const ModelHFluid3D a{input.a.fluid,view(conductivity[0]),view(hv[0]),view(e.mass[0][0]),view(e.mass[0][1]),view(e.mass[0][2]),ba,input.sources[0]};
        const ModelHFluid3D b{input.b.fluid,view(conductivity[1]),view(hv[1]),view(e.mass[1][0]),view(e.mass[1][1]),view(e.mass[1][2]),bb,input.sources[1]};
        auto* audit=&e.physical_audit.emplace();
        if(saved) {
            auto state=*saved->model_h_3d;state.iteration.temperature=temperature;
            model_h_3d=std::make_unique<ModelHRun3D>(g,a,b,geo.solid_conductivity,input.sources[2],fields,mc,state,ArrayView<const double>{},audit);
        } else model_h_3d=std::make_unique<ModelHRun3D>(g,a,b,geo.solid_conductivity,input.sources[2],fields,mc,ArrayView<const double>{},audit);
    } else {
        TemperatureControl tc{run.budget,250,1e-4,control.thermal_relaxation,control.thermal_relaxation,
            control.thermal_relaxation,true,true,control.cancel,nullptr,control.context};
        if(g.nz>1 && (control.conservative || !control.force_cell_centered)) {
            const StaggeredTemperatureFluid a{view(conductivity[0]),view(hv[0]),epsilon(0),view(rho_cp[0]),views(e.face_velocity[0]),bc[0],input.sources[0]};
            const StaggeredTemperatureFluid b{view(conductivity[1]),view(hv[1]),epsilon(1),view(rho_cp[1]),views(e.face_velocity[1]),bc[1],input.sources[1]};
            auto* audit=control.conservative && !true_h?&e.physical_audit.emplace():nullptr;
            if(saved) {
                auto state=*saved->staggered;state.iteration.temperature=temperature;
                thermal.restore_active(g,a,b,geo.solid_conductivity,fields,tc,control.conservative,
                    control.red_black_energy,state,prescribed,input.sources[2],true_h,audit);
            } else thermal.start(g,a,b,geo.solid_conductivity,fields,tc,control.conservative,
                control.red_black_energy,prescribed,input.sources[2],true_h,audit);
        } else {
            if(std::any_of(input.sources.begin(),input.sources.end(),[](auto source){
                return source.size && std::any_of(source.data,source.data+source.size,[](double x){return x!=0.;});}))
                throw std::invalid_argument("nonzero 3D MMS sources require staggered velocities");
            if(true_h || legacy_single_sco2) {
                const auto& va=result.flow[0].velocity_real;
                zero_velocity.assign(input.solve_b?0:temperature[0].size(),0.);
                const auto vb=input.solve_b?views(result.flow[1].velocity_real)
                    :std::array<ArrayView<const double>,3>{view(zero_velocity),view(zero_velocity),view(zero_velocity)};
                legacy_capacity=e.inlet_capacity;
                if(g.nz==1) {
                    tc.chunk_iterations=500;tc.q_relative_tolerance=2e-8;
                    tc.alpha_a=.7;tc.alpha_solid=1.;tc.alpha_b=1.;tc.second_order_b=false;
                    for(std::size_t s=0;s<2;++s) {
                        for(double& value:legacy_capacity[s])value/=sum(g.dz);
                        bc[s].capacity_flux=view(legacy_capacity[s]);
                    }
                }
                const auto scheme=g.nz==1?TemperatureScheme::cell_centered_2d:TemperatureScheme::cell_centered_3d;
                const TemperatureFluidView a{view(conductivity[0]),view(hv[0]),epsilon(0),view(rho_cp[0]),view(va[0]),view(va[1]),view(va[2]),bc[0]};
                const TemperatureFluidView b{view(conductivity[1]),view(hv[1]),epsilon(1),view(rho_cp[1]),vb[0],vb[1],vb[2],bc[1]};
                if(saved) {
                    auto state=*saved->legacy;state.temperature=temperature;
                    legacy=std::make_unique<LegacyTemperatureRun>(scheme,g,a,b,geo.solid_conductivity,fields,tc,state,prescribed);
                } else legacy=std::make_unique<LegacyTemperatureRun>(scheme,g,a,b,geo.solid_conductivity,fields,tc,prescribed);
            } else {
                auto ba=bc[0],bb=bc[1];ba.capacity_flux={};bb.capacity_flux={};
                auto* audit=&e.physical_audit.emplace();
                if(g.nz==1) {
                    for(std::size_t s=0;s<2;++s)
                        if(active(s)&&std::any_of(e.mass[s][2].begin(),e.mass[s][2].end(),[](double value){return value!=0.;}))
                            throw std::invalid_argument("Nz=1 model enthalpy requires zero mass on both z boundaries");
                    const double depth=sum(g.dz);
                    const GridView planar{g.nx,g.ny,1,g.dx,g.dy,{&unit_depth,1}};
                    for(std::size_t s=0;s<2;++s)for(std::size_t axis=0;axis<2;++axis) {
                        planar_mass[s][axis]=e.mass[s][axis];
                        for(double& value:planar_mass[s][axis])value/=depth;
                    }
                    ModelHControl2D mc{run.budget,500,2e-8,true,false,false,control.cancel,nullptr,control.context};
                    mc.second_order_b=false;mc.strict_energy_balance=true;
                    const auto settings=model_h_common::apply_iteration_tolerances(mc,control.model_h_iterations,total);
                    if(!saved)run.record.model_h_iterations.push_back(settings);
                    const ModelHFluid2D a{input.a.fluid,view(conductivity[0]),view(hv[0]),view(planar_mass[0][0]),view(planar_mass[0][1]),ba};
                    const ModelHFluid2D b{input.b.fluid,view(conductivity[1]),view(hv[1]),view(planar_mass[1][0]),view(planar_mass[1][1]),bb};
                    if(saved) {
                        auto state=*saved->model_h_2d;state.iteration.temperature=temperature;
                        model_h_2d=std::make_unique<ModelHRun2D>(planar,a,b,geo.solid_conductivity,fields,mc,state,prescribed,audit);
                    } else model_h_2d=std::make_unique<ModelHRun2D>(planar,a,b,geo.solid_conductivity,fields,mc,prescribed,audit);
                } else {
                    ModelHControl3D mc{run.budget,250,1e-4,control.thermal_relaxation,
                        control.thermal_relaxation,control.thermal_relaxation,true,false,false,control.cancel,nullptr,control.context};
                    mc.cpu_threads=control.enthalpy.cpu_threads;
                    mc.strict_energy_balance=true;
                    const auto settings=model_h_common::apply_iteration_tolerances(mc,control.model_h_iterations,total);
                    if(!saved)run.record.model_h_iterations.push_back(settings);
                    const ModelHFluid3D a{input.a.fluid,view(conductivity[0]),view(hv[0]),view(e.mass[0][0]),view(e.mass[0][1]),view(e.mass[0][2]),ba,{}};
                    const ModelHFluid3D b{input.b.fluid,view(conductivity[1]),view(hv[1]),view(e.mass[1][0]),view(e.mass[1][1]),view(e.mass[1][2]),bb,{}};
                    if(saved) {
                        auto state=*saved->model_h_3d;state.iteration.temperature=temperature;
                        model_h_3d=std::make_unique<ModelHRun3D>(g,a,b,geo.solid_conductivity,ArrayView<const double>{},fields,mc,state,prescribed,audit);
                    } else model_h_3d=std::make_unique<ModelHRun3D>(g,a,b,geo.solid_conductivity,ArrayView<const double>{},fields,mc,prescribed,audit);
                }
            }
        }
    }
    if((model_h_3d && model_h_3d->phase()==ModelHPhase::cancelled)
       || (model_h_2d && model_h_2d->phase()==ModelHPhase::cancelled)
       || (!model_h_3d && !model_h_2d && !legacy && thermal.phase()==TemperaturePhase::cancelled))throw Cancelled{};
}

void Runtime::start_enthalpy(const EnthalpyRunState* saved) {
    auto& run=*pending;auto& e=run.evidence;const auto& g=input.geometry.grid;
    if(!saved) {
        for(std::size_t s=0;s<2;++s) {
            auto faces=e.face_velocity[s];
            balance_outflow(g,side(s).direction,faces,multiply(epsilon(s),view(result.flow[s].density_real)));
            const auto projected=thermal.project_capacity_faces(g,epsilon(s),view(result.flow[s].density_real),views(faces));
            e.mass[s]=mass_faces(g,projected.velocity,epsilon(s),result.flow[s].density_real);
            if(const auto* error=energy_port_error(g,side(s),e.mass[s]))throw std::invalid_argument(error);
            e.enthalpy[s].resize(temperature[s].size());
        }
        for(std::size_t s=0;s<2;++s) {
            record_property_samples(e.property_sampling,s,static_cast<std::int64_t>(run.record.outer_index),"thermal",
                physics[s].eos_energy()?"HEOS":"model_resource","current_thermal_iterate",
                physics[s].eos_energy()?"last_thermal_input_absolute":nullptr,
                physics[s].eos_energy()?"local_evaluation":"integral_cp_T",{"energy_relation"});
            if(physics[s].conductivity==ConductivitySource::local_eos)
                record_property_samples(e.property_sampling,s,static_cast<std::int64_t>(run.record.outer_index),"thermal","HEOS",
                    "current_thermal_iterate","last_thermal_input_absolute","local_evaluation",{"conductivity"});
            else record_property_samples(e.property_sampling,s,static_cast<std::int64_t>(run.record.outer_index),"thermal",
                "outer_property_state",run.record.outer_index?"previous_thermal_return":"inlet","inlet","copy",{"conductivity"});
        }
    }
    auto c=control.enthalpy;c.cancel=control.cancel;c.context=control.context;
    c.reference_independent_update=true;
    const EnthalpySideView a{input.a.fluid,input.a.inlet_temperature,input.a.inlet_pressure,view(e.pressure[0]),epsilon(0),view(hv[0]),view(e.mass[0][0]),view(e.mass[0][1]),view(e.mass[0][2]),input.a.direction,
        physics[0].energy,physics[0].conductivity,
        physics[0].conductivity==ConductivitySource::local_eos?ArrayView<const double>{}:view(e.conductivity[0])};
    const EnthalpySideView b{input.b.fluid,input.b.inlet_temperature,input.b.inlet_pressure,view(e.pressure[1]),epsilon(1),view(hv[1]),view(e.mass[1][0]),view(e.mass[1][1]),view(e.mass[1][2]),input.b.direction,
        physics[1].energy,physics[1].conductivity,
        physics[1].conductivity==ConductivitySource::local_eos?ArrayView<const double>{}:view(e.conductivity[1])};
    const EnthalpyStateView fields{writable(e.enthalpy[0]),writable(e.enthalpy[1]),writable(temperature[0]),writable(temperature[1]),writable(temperature[2]),true,true,true};
    auto* audit=&e.physical_audit.emplace();
    if(saved) {
        auto state=*saved;state.fields={e.enthalpy[0],e.enthalpy[1],temperature[0],temperature[1],temperature[2]};
        enthalpy=std::make_unique<EnthalpyRun>(g,a,b,input.geometry.solid_conductivity,fields,c,state,audit);
    } else enthalpy=std::make_unique<EnthalpyRun>(g,a,b,input.geometry.solid_conductivity,fields,c,audit);
    if(enthalpy->phase()==EnthalpyPhase::cancelled)throw Cancelled{};
}

bool Runtime::advance_thermal() {
    auto& run=*pending;auto& e=run.evidence;auto& record=run.record;const auto& g=input.geometry.grid;
    const bool true_h=mode==Full3DThermalMode::true_h;
    if(enthalpy) {
        if(enthalpy->phase()==EnthalpyPhase::active && enthalpy->advance()==EnthalpyPhase::active)return false;
        e.true_h=enthalpy->take_result(&e.actual_conductivity);enthalpy.reset();
        const auto& r=*e.true_h;if(r.stop==EnthalpyStop::cancelled)throw Cancelled{};
        if(!r.final_audit || !r.final_audit->fluid_equations_computed)e.physical_audit.reset();
        if(e.physical_audit)for(std::size_t s=0;s<2;++s)
            e.physical_audit->boundary_complete=e.physical_audit->boundary_complete && !energy_port_error(g,side(s),e.mass[s]);
        record.thermal_converged=r.stop==EnthalpyStop::converged;record.thermal_iterations=r.iterations;record.thermal_residual=r.residual;
        check_water(temperature,e.pressure);
        for(const auto& t:temperature)if(!finite(t))throw std::domain_error("nonfinite full 3D true-h return");
        temperature_ranges("main","real-cell(x,y,z)-return");
        for(std::size_t s=0;s<2;++s) {
            e.enthalpy_boundary_power[s]=enthalpy_boundary_power(g,view(e.enthalpy[s]),views(e.mass[s]),
                r.inlet_enthalpy[s],true);
        }
        finish_thermal();return true;
    }
    TemperatureResult solved{};
    if(model_h_3d) {
        if(model_h_3d->phase()==ModelHPhase::active && model_h_3d->advance()==ModelHPhase::active)return false;
        auto value=model_h_3d->take_result();model_h_3d.reset();
        solved={value.stop,value.iterations,value.residual,value.q_b};
        if(!value.physical_audit_available)e.physical_audit.reset();
        if(mode==Full3DThermalMode::model_h) {
            if(strict_model_h(input))e.temperature_algorithm="model_h_tface_sou_sou_strict_v3";
            e.model_h=std::move(value);
        } else e.temperature_algorithm="model_h_tface_sou_sou_strict_v3";
    } else if(model_h_2d) {
        if(model_h_2d->phase()==ModelHPhase::active && model_h_2d->advance()==ModelHPhase::active)return false;
        const auto value=model_h_2d->take_result();model_h_2d.reset();
        solved={value.stop,value.iterations,value.residual,value.q_b};
        if(!value.physical_audit_available)e.physical_audit.reset();
        e.temperature_algorithm="model_h_tface_sou_fou_strict_v3";
        if(e.physical_audit) {
            auto& audit=*e.physical_audit;const double depth=sum(g.dz);
            for(auto& phase:audit.advective_out)for(auto& plane:phase)for(double& v:plane)v*=depth;
            for(auto& phase:audit.diffusive_out)for(auto& plane:phase)for(double& v:plane)v*=depth;
            for(auto& phase:audit.residual)for(double& v:phase)v*=depth;
            for(double& v:audit.source_integral)v*=depth;
            audit.prescribed_b_power*=depth;
        }
    } else if(legacy) {
        if(legacy->phase()==TemperaturePhase::active && legacy->advance()==TemperaturePhase::active)return false;
        solved=legacy->take_result();legacy.reset();
    } else {
        if(thermal.phase()==TemperaturePhase::active && thermal.advance()==TemperaturePhase::active)return false;
        e.staggered=thermal.take_result();solved=e.staggered->iteration;
    }
    if(solved.stop==TemperatureStop::cancelled)throw Cancelled{};
    record.thermal_converged=solved.stop==TemperatureStop::converged;
    record.thermal_iterations=solved.iterations;record.thermal_residual=solved.residual;
    const bool startup=mode==Full3DThermalMode::model_h
        && (input.a.fluid==Fluid::water || input.b.fluid==Fluid::water) && record.outer_index==0;
    try {
        if(!true_h)check_water(temperature,e.pressure);
        for(const auto& t:temperature)if(!finite(t))throw std::domain_error("nonfinite full 3D thermal return");
    } catch(const WaterStateError& error) {
        if(!startup || run.budget<=1 || !std::all_of(temperature.begin(),temperature.end(),finite))throw;
        run.remaining-=std::min(run.remaining,record.thermal_iterations);
        if(!run.remaining)throw;
        record.rejected_startup_iterations.push_back(record.thermal_iterations);
        record.rejected_startup_reasons.push_back(error.what());
        run.budget=std::min(run.budget/2,run.remaining);temperature=run.initial;
        start_thermal();return false;
    }
    if(startup) {
        run.remaining-=std::min(run.remaining,record.thermal_iterations);
        const auto total=control.model_h_iterations.max_iterations
            ?control.model_h_iterations.max_iterations:control.thermal_iterations;
        record.startup_total_iterations=total-run.remaining;
    }
    temperature_ranges("main","real-cell(x,y,z)-return");
    if(true_h) {start_enthalpy();return false;}
    finish_thermal();return true;
}

void Runtime::finish_thermal() {
    auto& e=pending->evidence;auto& record=pending->record;
    e.temperature=temperature;
    if(e.model_h) {
        record.model_h=e.model_h;auto& audit=record.model_h->audit;
        Values{}.swap(audit.solid_residual);
        for(auto& s:audit.sides) {
            Values{}.swap(s.residual);Values{}.swap(s.inlet_diffusion);
            for(auto& b:s.boundaries)Values{}.swap(b.enthalpy_faces);
        }
    }
    record.true_h=e.true_h;
    for(std::size_t s=0;s<2;++s)if(active(s)) {
        record.pressure_reference[s]=result.flow[s].pressure_reference;
        record.pressure_range[s]={*std::min_element(e.pressure[s].begin(),e.pressure[s].end()),
                                  *std::max_element(e.pressure[s].begin(),e.pressure[s].end())};
    }
}

void Runtime::refresh_flow(std::size_t s,std::size_t outer,const std::optional<PressurePortState>& pressure) {
    const auto& a=side(s);auto& flow=result.flow[s];const auto& g=input.geometry.grid;
    const bool air=a.fluid==Fluid::air;
    const bool local_sco2=s==0 && a.fluid==Fluid::sco2 && control.sco2_local_pressure_a;
    flow.property_sampling.clear();
    const auto sample_index=static_cast<std::int64_t>(outer);
    const char* provider=uses_co2_eos(a.fluid)?"HEOS":"model_resource";
    record_property_samples(flow.property_sampling,s,sample_index,"flow_post",air?"ideal_gas":provider,
        "current_thermal_return",air?"current_SIMPLE_absolute":local_sco2?"previous_SIMPLE_absolute":"inlet",
        air?"local_evaluation":outer?"relax_0.6":"local_evaluation",{"density"});
    record_property_samples(flow.property_sampling,s,sample_index,"flow_post",provider,
        "current_thermal_return",local_sco2?"previous_SIMPLE_absolute":"inlet",
        outer&&!air?"relax_0.6":"local_evaluation",{"viscosity"});
    auto next_temperature=to_solver(g,a,view(temperature[s]));
    const auto local_grid=grid(flow);
    property_ranges(s,"property","property-refresh","solver-cell(cross1,stream,cross2)",
        {local_grid.nx,local_grid.ny,local_grid.nz},view(next_temperature),air?2:3);
    Values rho_new(flow.density.size()),mu_new(flow.viscosity.size());
    const auto physical_shape=shape(g);
    for(std::size_t p=0;p<rho_new.size();++p) {
        const double absolute=flow.pressure_reference+flow.pressure[p];
        FluidProperties property;
        if(local_sco2) property=props.transport(a.fluid,next_temperature[p],absolute);
        else {
            std::array<std::size_t,3> cell{};
            const auto stream=(p/local_grid.nz)%local_grid.ny;
            cell[a.solver_axes[0]]=p/(local_grid.ny*local_grid.nz);
            cell[a.solver_axes[1]]=a.direction%2?local_grid.ny-1-stream:stream;
            cell[a.solver_axes[2]]=p%local_grid.nz;
            property=inlet_transport(s,index(physical_shape,cell));
        }
        rho_new[p]=air?absolute/(model_coefficients::envelope_r_air*next_temperature[p]):property.rho;
        mu_new[p]=property.mu;
    }
    // Keep A's temperature update before the property blend and B's update after it.
    if(s==0) {
        flow.temperature=next_temperature;
        if(air) flow.viscosity=mu_new;
    }
    for(std::size_t p=0;p<rho_new.size();++p) {
        flow.density[p]=outer ? .6*rho_new[p]+.4*flow.density[p]:rho_new[p];
        flow.viscosity[p]=outer ? .6*mu_new[p]+.4*flow.viscosity[p]:mu_new[p];
    }
    for(std::size_t p=0;p<flow.viscosity.size();++p) flow.effective_viscosity[p]=flow.viscosity[p]/flow.epsilon[p];
    const auto sg=grid(flow);
    if(!air) for(std::size_t i=0;i<sg.nx;++i) for(std::size_t k=0;k<sg.nz;++k) {
        const auto face=i*sg.nz+k;
        flow.inlet_velocity[face]=flow.fixed_inlet_massflux[face]/std::max(flow.density[(i*sg.ny)*sg.nz+k],1e-9);
    }
    if(air) {
        if(control.pressure_shooting) flow.pressure_reference=pressure_shooting_reference(*pressure,flow.pressure_iterations);
        else {
            const double mean=cell_average(g,temperature[s]);
            property_ranges(s,"property","property-refresh","mean",{},{&mean,1},2);
            const double mu=props.transport(a.fluid,mean,a.inlet_pressure).mu;
            record_property_samples(flow.property_sampling,s,sample_index,"pressure_seed",provider,
                "volume_mean_current_thermal_return","inlet","scalar_evaluation",{"viscosity"});
            const double drag=mu*mass_flux[s]/std::max(drag_k[s],1e-16)+drag_cf[s]*mass_flux[s]*mass_flux[s];
            flow.pressure_reference=pressure_initial_reference(predict_outlet_p_sq(a.inlet_pressure,mean,drag,sum(sg.dy)),
                                                               a.inlet_pressure,flow.pressure_iterations);
        }
    } else if(s==0) {
        const double mean=cell_average(g,temperature[s]);
        property_ranges(s,"property","property-refresh","mean",{},{&mean,1},2);
        if(a.fluid==Fluid::water) props.check_water(mean,a.inlet_pressure);
        const double mu=props.transport(a.fluid,mean,a.inlet_pressure).mu;
        record_property_samples(flow.property_sampling,s,sample_index,"pressure_seed",provider,
                "volume_mean_current_thermal_return","inlet","scalar_evaluation",{"viscosity"});
        const double drag=mu*mass_flux[s]/std::max(drag_k[s],1e-16)+drag_cf[s]*mass_flux[s]*mass_flux[s];
        if(local_sco2) {
            const double rho=std::max(cell_average(sg,flow.density),1e-9);
            const double outlet=a.inlet_pressure-drag*sum(sg.dy)/rho;
            if(outlet<=model_coefficients::pressure_floor_pa) {
                const std::string message="A-side local-pressure sCO2 property experiment has an inadmissible 1D D-F pressure seed; this approximation does not establish physical choking";
                if(control.envelope_mode==0) throw ChokedFlowError(message);
                if(control.envelope_mode==1) result.warnings.push_back(message);
            }
            flow.pressure_reference=std::max(outlet,model_coefficients::pressure_floor_pa);
        } else flow.pressure_reference=std::max(a.inlet_pressure-drag*sum(sg.dy)/inlet[s].rho,1e4);
    }
    if(s==1) {
        flow.temperature=std::move(next_temperature);
        if(air) {
            flow.viscosity=std::move(mu_new);
            for(std::size_t p=0;p<flow.viscosity.size();++p) flow.effective_viscosity[p]=flow.viscosity[p]/flow.epsilon[p];
        }
    }
    start_flow(s,control.warm_simple_iterations);
}

void Runtime::refresh_thermal_properties(std::size_t outer) {
    const auto& g=input.geometry.grid;
    for(std::size_t s=0;s<2;++s) {
        const auto& a=side(s);
        record_property_samples(result.property_sampling,s,static_cast<std::int64_t>(outer),"property_post",
            uses_co2_eos(a.fluid)?"HEOS":"model_resource","current_thermal_return","inlet",
            "side_porosity_times_k_plus_inlet_dispersion",{"conductivity"});
        if(!(control.variable_rho_cp && a.fluid==Fluid::air && active(s)))
            record_property_samples(result.property_sampling,s,static_cast<std::int64_t>(outer),"property_post",
                uses_co2_eos(a.fluid)?"HEOS":"model_resource","current_thermal_return","inlet",
                s==0&&control.variable_rho_cp?"current_SIMPLE_density_times_cp":"local_rho_times_cp",{"rho_cp"});
        unsigned mask=4;
        if(s==0 || !(control.variable_rho_cp && a.fluid==Fluid::air && active(s)))mask|=8;
        if((s==0 && !control.variable_rho_cp) || (s==1 && !(control.variable_rho_cp && a.fluid==Fluid::air && active(s))))mask|=1;
        property_ranges(s,"property","property-refresh","real-cell(x,y,z)",{g.nx,g.ny,g.nz},view(temperature[s]),mask);
        for(std::size_t p=0;p<temperature[s].size();++p) {
            const auto property=inlet_transport(s,p);
            conductivity[s][p]=epsilon(s)[p]*property.k+dispersion[s];
            // A consumes its freshly completed relaxed SIMPLE density. B's
            // non-air branch samples unrelaxed inlet-pressure properties here,
            // before B's subsequent flow update. Air refreshes before thermal.
            if(s==0 && control.variable_rho_cp && a.fluid!=Fluid::air) {
                rho_cp[s][p]=result.flow[s].density_real[p]*property.cp;
            } else if(!(control.variable_rho_cp && a.fluid==Fluid::air && active(s))) {
                rho_cp[s][p]=property.rho*property.cp;
            }
        }
    }
}


void Runtime::finish() {
    const auto& g=input.geometry.grid;
    const bool true_h_pair=uses_co2_eos(input.a.fluid) || uses_co2_eos(input.b.fluid);
    const bool candidate=result.thermal.true_h.has_value();
    if(!true_h_pair || mode==Full3DThermalMode::true_h)
        temperature_ranges("final","real-cell(x,y,z)");
    result.finite_fields=std::all_of(temperature.begin(),temperature.end(),finite);
    result.simple_ok=true;result.envelope_ok=true;
    const auto n=shape(g);
    for(std::size_t i=0;i<g.nx;++i) for(std::size_t j=0;j<g.ny;++j) for(std::size_t k=0;k<g.nz;++k) {
        const std::array<std::size_t,3> cell{i,j,k};const auto p=index(n,cell);const double vol=g.dx[i]*g.dy[j]*g.dz[k];
        for(std::size_t s=0;s<2;++s) {
            const double exchange=((candidate?result.thermal.hv[s][p]:hv[s][p])
                *(temperature[2][p]-temperature[s][p]))*vol;
            result.solid_exchange[s]+=exchange;
            if(active(s) && cell[side(s).direction/2]>0 && cell[side(s).direction/2]+1<n[side(s).direction/2])
                result.interior_exchange[s]+=exchange;
        }
    }
    result.energy_imbalance=std::abs(result.solid_exchange[0]+result.solid_exchange[1])
        /(std::abs(result.solid_exchange[0])+std::abs(result.solid_exchange[1])+1e-30);
    result.interior_duty=result.interior_exchange[1]!=0.? .5*(std::abs(result.interior_exchange[0])+std::abs(result.interior_exchange[1]))
        :std::abs(result.interior_exchange[0]);
    result.interior_imbalance=std::abs(std::abs(result.interior_exchange[0])-std::abs(result.interior_exchange[1]))
        /std::max({std::abs(result.interior_exchange[0]),std::abs(result.interior_exchange[1]),1e-30});
    for(std::size_t s=0;s<2;++s) {
        if(!active(s)) {
            result.outlet_temperature[s]=std::numeric_limits<double>::quiet_NaN();
            result.inlet_mass[s]=std::numeric_limits<double>::quiet_NaN();continue;
        }
        const auto& a=side(s);auto& f=result.flow[s];const auto sg=grid(f);
        // Kept capacity routes report EOS duty separately from their thermal update.
        const auto reporting_energy=mode==Full3DThermalMode::true_h
            ?physics[s].energy:EnergyRelation::eos_h_TP;
        for(std::size_t p=0;p<temperature[s].size();++p) {
            if(a.fluid==Fluid::water) props.check_water(temperature[s][p],f.pressure_real[p]);
            else if(uses_co2_eos(a.fluid)) eos.validate(a.fluid,temperature[s][p],f.pressure_real[p],"3D final report state");
        }
        f.inlet_pressure=inlet_state(a,f);
        const auto port=inlet_pressure_state(sg,view(f.pressure),view(f.inlet_opening),view(f.outlet_opening),f.pressure_reference,a.inlet_pressure);
        result.pressure_drop[s]=port.realized_Pa-port.outlet_Pa;
        const auto local_temperature=to_solver(g,a,view(temperature[s]));
        const auto eps=to_solver(g,a,epsilon(s));
        double mass_in=0.,mass_out=0.,signed_in=0.,signed_out=0.,weighted_t=0.,weighted_h=0.,plain_t=0.,plain_h=0.;
        for(std::size_t i=0;i<sg.nx;++i) for(std::size_t k=0;k<sg.nz;++k) {
            const auto in=(i*sg.ny)*sg.nz+k,out=(i*sg.ny+sg.ny-1)*sg.nz+k;
            const auto vin=i*(sg.ny+1)*sg.nz+k,vout=(i*(sg.ny+1)+sg.ny)*sg.nz+k;
            const double area=sg.dx[i]*sg.dz[k];
            const double m_in=f.density[in]*f.v[vin]*area,m_out=f.density[out]*f.v[vout]*area;
            signed_in+=m_in*eps[in];signed_out+=m_out*eps[out];
            result.physical_mass_in[s]+=std::abs(m_in);result.physical_mass_out[s]+=std::abs(m_out);
            mass_in+=((f.density[in]*std::abs(f.v[vin]))*area)*eps[in];
            const double weight=((f.density[out]*std::abs(f.v[vout]))*area)*eps[out];
            mass_out+=weight;weighted_t+=local_temperature[out]*weight;plain_t+=local_temperature[out];
            if(true_h_pair && !candidate) {
                const double pressure=f.pressure_reference+f.pressure[out];
                eos.validate(a.fluid,local_temperature[out],pressure,"3D final outlet enthalpy");
                const double h=eos.bracket_enthalpy(a.fluid,local_temperature[out],pressure,reporting_energy);
                weighted_h+=h*weight;plain_h+=h;
            }
        }
        result.inlet_mass[s]=mass_in;
        result.mass_imbalance[s]=std::abs(signed_in-signed_out)/(std::abs(signed_in)+1e-30);
        result.outlet_temperature[s]=mass_out<1e-30?plain_t/(sg.nx*sg.nz):weighted_t/mass_out;
        if(!true_h_pair) {
            Values outlet(sg.nx*sg.nz);
            for(std::size_t i=0;i<sg.nx;++i) for(std::size_t k=0;k<sg.nz;++k)
                outlet[i*sg.nz+k]=local_temperature[(i*sg.ny+sg.ny-1)*sg.nz+k];
            property_ranges(s,"property_state","final","outlet-cell-face(real-transverse-axes)",
                {sg.nx,sg.nz},view(outlet),15);
        }
        if(candidate || (result.thermal.temperature_algorithm && result.thermal.physical_audit)) {
            const auto& evidence=result.thermal;
            const int axis=a.direction/2;const bool reverse=a.direction%2;
            double thermal_in=0.,thermal_out=0.,thermal_temperature=0.;
            boundary(g,axis,reverse,[&](std::size_t,std::size_t,std::size_t f,double) {
                thermal_in+=std::max((reverse?-1.:1.)*evidence.mass[s][axis][f],0.);
            });
            boundary(g,axis,!reverse,[&](std::size_t,std::size_t p,std::size_t f,double) {
                const double weight=std::max((reverse?-1.:1.)*evidence.mass[s][axis][f],0.);
                thermal_out+=weight;thermal_temperature+=weight*evidence.temperature[s][p];
            });
            result.inlet_mass[s]=thermal_in;
            result.outlet_temperature[s]=thermal_out>0.?thermal_temperature/thermal_out
                :std::numeric_limits<double>::quiet_NaN();
            if(evidence.temperature_algorithm && evidence.physical_audit) {
                double q=0.;
                for(const auto& plane:evidence.physical_audit->advective_out[s])
                    for(double value:plane) q-=value;
                result.duty[s]=evidence.physical_audit->boundary_complete?std::abs(q)
                    :std::numeric_limits<double>::quiet_NaN();
            } else result.duty[s]=std::abs(s==0?evidence.true_h->q_a:evidence.true_h->q_b);
        } else if(true_h_pair) {
            eos.validate(a.fluid,a.inlet_temperature,a.inlet_pressure,"3D final inlet enthalpy");
            const double hin=eos.bracket_enthalpy(a.fluid,a.inlet_temperature,a.inlet_pressure,reporting_energy);
            const double hout=mass_out<1e-30?plain_h/(sg.nx*sg.nz):weighted_h/mass_out;
            result.duty[s]=std::abs(mass_in*(hin-hout));
        } else result.duty[s]=std::abs(mass_in*inlet[s].cp*(a.inlet_temperature-result.outlet_temperature[s]));
        if(result.thermal.model_h) {
            const auto& audit=result.thermal.model_h->audit.sides[s];
            result.duty[s]=audit.boundary_complete && std::isfinite(audit.advective_in)?std::abs(audit.advective_in):std::numeric_limits<double>::quiet_NaN();
        }
        auto& speed=f.speed_real;speed.resize(f.density.size());
        for(std::size_t p=0;p<speed.size();++p)
            speed[p]=std::sqrt(f.velocity_real[0][p]*f.velocity_real[0][p]+f.velocity_real[1][p]*f.velocity_real[1][p]
                              +f.velocity_real[2][p]*f.velocity_real[2][p]);
        result.finite_fields=result.finite_fields && finite(speed);
        result.simple_ok=result.simple_ok && f.last.stop==SimpleStop::tol;
        result.minimum_pressure[s]=*std::min_element(f.pressure_real.begin(),f.pressure_real.end());
        if(a.fluid==Fluid::air) {
            result.maximum_mach[s]=mach_field_max(view(speed),view(temperature[s]));
            const auto envelope=gate_solution(result.minimum_pressure[s],*std::max_element(speed.begin(),speed.end()),
                a.inlet_temperature,control.envelope_mode==0?"raise":(control.envelope_mode==1?"warn":"off"),
                s?"3D-B":"3D-A",1.,result.maximum_mach[s]);
            result.envelope_ok=result.envelope_ok && envelope.valid;
            for(const auto& why:envelope.reasons) result.envelope_reasons.push_back(std::string(s?"[B] ":"[A] ")+why);
        }
    }
    if(input.solve_b && true_h_pair && result.duty[0]>1. && result.duty[1]>1.)
        result.enthalpy_imbalance=std::abs(result.duty[0]-result.duty[1])/std::max(result.duty[0],result.duty[1]);
    result.thermal_ok=!result.outer.empty() && result.outer.back().thermal_converged;
    result.converged=result.simple_ok && result.thermal_ok && result.outer_ok && result.finite_fields && result.envelope_ok;
    result.final_conductivity=std::move(conductivity);result.final_rho_cp=std::move(rho_cp);
    for(std::size_t s=0;s<2;++s)result.inlet_cp[s]=inlet[s].cp;
}

}  // namespace

std::array<SidePhysics,2> resolve_full_3d_physics(const Full3DInput& input,const Full3DControl& control) {
    const auto mode=thermal_mode(input,control);
    const bool cc=mode==Full3DThermalMode::temperature
        && (input.geometry.grid.nz==1 || (!control.conservative && control.force_cell_centered));
    const bool single_sco2=!input.solve_b && input.a.fluid==Fluid::sco2;
    const auto relation=mode==Full3DThermalMode::true_h?EnergyRelation::eos_h_TP:
        (mode==Full3DThermalMode::model_h || (cc && !single_sco2))?
            EnergyRelation::integral_cp_T:EnergyRelation::capacity_temperature;
    std::array<SidePhysics,2> selected;
    for(std::size_t side=0;side<2;++side) {
        const auto fluid=side?input.b.fluid:input.a.fluid;
        if(side && !input.solve_b) {
            selected[side]={fluid,EnergyRelation::prescribed_temperature,
                ConductivitySource::prescribed,HeatTransferSampling::prescribed};
            continue;
        }
        const auto energy=relation==EnergyRelation::eos_h_TP && !uses_co2_eos(fluid)
            ?EnergyRelation::integral_cp_T:relation;
        selected[side]={fluid,energy,
            energy==EnergyRelation::eos_h_TP?ConductivitySource::local_eos:ConductivitySource::outer_transport,
            uses_co2_eos(fluid)?HeatTransferSampling::inlet_then_thermal_local_at_inlet_pressure:
                HeatTransferSampling::inlet};
    }
    return selected;
}

struct Full3DRun::Impl {
    Full3DInput input;
    Full3DControl control;
    Runtime runtime;
    Full3DPhase phase=Full3DPhase::created;
    bool result_taken=false,boundary=true;
    Impl(const Full3DInput& i,const Full3DControl& c):input(i),control(c),runtime(input,control) {}
};

Full3DRun::Full3DRun(const Full3DInput& input,const Full3DControl& control) {
    validate(input,control);impl_=std::make_unique<Impl>(input,control);
}
Full3DRun::~Full3DRun()=default;
Full3DPhase Full3DRun::phase() const {return impl_->phase;}

namespace {
std::optional<std::size_t> active_flow(Full3DPhase phase) {
    if(phase==Full3DPhase::initial_flow_a || phase==Full3DPhase::post_flow_a)return 0;
    if(phase==Full3DPhase::initial_flow_b || phase==Full3DPhase::post_flow_b)return 1;
    return std::nullopt;
}
bool initial_flow(Full3DPhase phase) {
    return phase==Full3DPhase::initial_flow_a || phase==Full3DPhase::initial_flow_b;
}
bool saved_boundary(Full3DPhase phase) {
    return phase==Full3DPhase::outer_boundary || phase==Full3DPhase::ready_to_finish
        || phase==Full3DPhase::thermal_boundary || active_flow(phase).has_value();
}
} // namespace

Full3DPhase Full3DRun::advance() {
    do {advance_step();}while(impl_->phase>=Full3DPhase::initial_flow_a);
    return impl_->phase;
}

Full3DPhase Full3DRun::advance_step() {
    auto& runtime=impl_->runtime;const auto& input=impl_->input;const auto& control=impl_->control;
    if(!impl_->boundary)throw std::logic_error("unfinished full 3D step cannot advance");
    if(impl_->phase==Full3DPhase::completed || impl_->phase==Full3DPhase::cancelled)return impl_->phase;
    if(impl_->phase==Full3DPhase::failed)throw std::logic_error("full 3D failed run cannot advance");
    impl_->boundary=false;
    try {
        const auto step=[&] {
            if(impl_->phase==Full3DPhase::created) {
                cancel(control);runtime.initialize();runtime.start_flow(0,control.initial_simple_iterations);
                impl_->phase=Full3DPhase::initial_flow_a;return;
            }
            if(impl_->phase==Full3DPhase::ready_to_finish) {
                runtime.result.post_after_last_thermal=!runtime.result.outer_ok;
                runtime.finish();cancel(control);
                if(control.progress)control.progress(control.context,100.);
                impl_->phase=Full3DPhase::completed;return;
            }
            if(const auto side=active_flow(impl_->phase)) {
                const bool initial=initial_flow(impl_->phase);
                const auto outer=runtime.result.outer.size();
                if(!runtime.advance_flow(*side,initial?"init":"outer"+std::to_string(outer-1)))return;
                if(*side==0) {
                    if(initial) {
                        if(input.solve_b) {
                            runtime.start_flow(1,control.initial_simple_iterations);
                            impl_->phase=Full3DPhase::initial_flow_b;return;
                        }
                    } else {
                        runtime.refresh_thermal_properties(outer-1);
                        if(input.solve_b) {
                            runtime.refresh_flow(1,outer-1,runtime.result.outer.back().inlet_pressure[1]);
                            impl_->phase=Full3DPhase::post_flow_b;return;
                        }
                    }
                }
                if(initial)runtime.bulk_ranges();
                impl_->phase=!initial && outer==control.max_outer?Full3DPhase::ready_to_finish:Full3DPhase::outer_boundary;
                return;
            }
            const auto outer=runtime.result.outer.size();
            if(impl_->phase==Full3DPhase::outer_boundary) {
                cancel(control);
                if(control.outer_iteration)control.outer_iteration(control.context,outer+1,control.max_outer);
                if(control.progress)control.progress(control.context,10.+80.*static_cast<double>(outer)/control.max_outer);
                runtime.begin_thermal(outer);impl_->phase=Full3DPhase::thermal_boundary;return;
            }
            if(!runtime.advance_thermal())return;
            auto record=std::move(runtime.pending->record);
            runtime.result.thermal=std::move(runtime.pending->evidence);runtime.pending.reset();
            cancel(control);
            bool temperature_ok=outer>0;
            for(std::size_t field=0;field<3;++field) {
                double delta=outer?0.:std::numeric_limits<double>::infinity();
                if(outer) for(std::size_t p=0;p<runtime.temperature[field].size();++p)
                    delta=std::max(delta,std::abs(runtime.temperature[field][p]-runtime.previous[field][p]));
                record.temperature_change[field]=delta;
                temperature_ok=temperature_ok && delta<control.outer_temperature_tolerance;
                runtime.previous[field]=runtime.temperature[field];
            }
            record.inlet_pressure={inlet_state(input.a,runtime.result.flow[0]),
                input.solve_b?inlet_state(input.b,runtime.result.flow[1]):std::nullopt};
            const bool pressure_ok=std::all_of(record.inlet_pressure.begin(),record.inlet_pressure.end(),
                [](const auto& p){return !p || p->passed;});
            record.coupling_converged=temperature_ok && pressure_ok;
            runtime.result.outer.push_back(record);
            if(record.coupling_converged && record.thermal_converged) {
                runtime.result.outer_ok=true;runtime.result.stop=Full3DStop::converged;
                impl_->phase=Full3DPhase::ready_to_finish;return;
            }
            const std::array<Values,2> absolute{runtime.result.flow[0].pressure_real,runtime.result.flow[1].pressure_real};
            runtime.check_water(runtime.temperature,absolute);
            runtime.refresh_flow(0,outer,record.inlet_pressure[0]);
            impl_->phase=Full3DPhase::post_flow_a;
        };
        step();impl_->boundary=true;
    } catch(const Cancelled&) {
        runtime.result.stop=Full3DStop::cancelled;runtime.result.converged=false;
        for(auto& flow:runtime.result.flow)
            if(flow.bootstrap_trace.available && flow.bootstrap_trace.decision=="not-started")flow.bootstrap_trace.decision="cancelled";
        impl_->phase=Full3DPhase::cancelled;impl_->boundary=true;
    } catch(...) {impl_->phase=Full3DPhase::failed;throw;}
    return impl_->phase;
}

namespace {
void validate_continuation(const Full3DInput& input,const Full3DControl& control,const Full3DRunState& state) {
    const auto outer=state.result.outer.size();const auto& g=input.geometry.grid;
    const auto n=g.nx*g.ny*g.nz;
    const auto flow_side=active_flow(state.phase);
    const bool initial=initial_flow(state.phase),thermal_active=state.phase==Full3DPhase::thermal_boundary;
    const bool post=flow_side.has_value() && !initial;
    if(!saved_boundary(state.phase) || outer>control.max_outer
       || ((state.phase==Full3DPhase::outer_boundary || thermal_active) && outer==control.max_outer)
       || (initial && outer) || (post && !outer) || (flow_side==1 && !input.solve_b)
       || (state.phase==Full3DPhase::ready_to_finish && !state.result.outer_ok && outer!=control.max_outer)
       || (state.result.outer_ok && state.phase!=Full3DPhase::ready_to_finish)
       || state.flow_convergence.has_value()!=flow_side.has_value()
       || state.flow_iteration.has_value()!=flow_side.has_value() || state.thermal.has_value()!=thermal_active)
        throw std::invalid_argument("invalid full 3D continuation position");
    const bool completed=outer && state.result.outer.back().coupling_converged
        && state.result.outer.back().thermal_converged;
    if(state.result.outer_ok!=completed
       || state.result.stop!=(completed?Full3DStop::converged:Full3DStop::iteration_limit))
        throw std::invalid_argument("full 3D continuation exit differs from its history");
    for(std::size_t i=0;i<outer;++i) if(state.result.outer[i].outer_index!=i)
        throw std::invalid_argument("invalid full 3D continuation history");
    auto check=[&](const Values& values,std::size_t size,bool positive=false) {
        if(values.size()!=size || !finite(values) || (positive && !std::all_of(values.begin(),values.end(),[](double v){return v>0.;})))
            throw std::invalid_argument("invalid full 3D continuation field");
    };
    for(std::size_t field=0;field<3;++field) {
        check(state.temperature[field],n,true);check(state.previous[field],outer?n:0,true);
    }
    for(std::size_t side=0;side<2;++side) {
        check(state.conductivity[side],n,true);check(state.rho_cp[side],n,true);check(state.hv[side],n);
        const auto& inlet=state.inlet[side];
        for(double value:{inlet.rho,inlet.mu,inlet.k,inlet.cp,inlet.pr,state.hv_ratio[side]})
            if(!(value>0.) || !std::isfinite(value))throw std::invalid_argument("invalid full 3D continuation property");
        for(double value:{state.drag_k[side],state.drag_cf[side],state.mass_flux[side],state.dispersion[side]})
            if(value<0. || !std::isfinite(value))throw std::invalid_argument("invalid full 3D continuation coefficient");
        const bool active=side==0||input.solve_b;
        if(state.simple[side].has_value()!=active)
            throw std::invalid_argument("invalid full 3D continuation owner");
        if(!active)continue;
        const auto& flow=state.result.flow[side];const auto& a=side?input.b:input.a;
        const std::array<ArrayView<const double>,3> widths{g.dx,g.dy,g.dz};
        for(std::size_t d=0;d<3;++d) {
            const auto expected=widths[a.solver_axes[d]];
            check(flow.widths[d],expected.size,true);
            for(std::size_t j=0;j<expected.size;++j)
                if(flow.widths[d][j]!=expected[d==1 && a.direction%2?expected.size-1-j:j])
                    throw std::invalid_argument("full 3D continuation grid differs from input");
        }
        const auto sg=grid(flow);
        const auto& geo=input.geometry;
        auto expected_k=to_solver(g,a,geo.permeability),expected_cf=to_solver(g,a,geo.forchheimer);
        for(auto& value:expected_k)value*=a.permeability_scale;
        for(auto& value:expected_cf)value*=a.forchheimer_scale;
        if(flow.epsilon!=to_solver(g,a,geo.epsilon) || flow.permeability!=expected_k || flow.forchheimer!=expected_cf
           || flow.inlet_opening!=Values(a.inlet_opening.data,a.inlet_opening.data+a.inlet_opening.size)
           || flow.outlet_opening!=Values(a.outlet_opening.data,a.outlet_opening.data+a.outlet_opening.size))
            throw std::invalid_argument("full 3D continuation geometry differs from input");
        if(!(flow.pressure_reference>0.) || !std::isfinite(flow.pressure_reference))
            throw std::invalid_argument("invalid full 3D continuation pressure reference");
        for(const auto* v:{&flow.epsilon,&flow.permeability,&flow.temperature,&flow.viscosity,&flow.effective_viscosity,&flow.density})check(*v,n,true);
        for(const auto* v:{&flow.forchheimer,&flow.pressure,&flow.pressure_correction})check(*v,n);
        const bool have_real=!initial || (state.phase==Full3DPhase::initial_flow_b && side==0);
        check(flow.pressure_real,have_real?n:0);check(flow.density_real,have_real?n:0);
        const std::array<std::size_t,3> faces{(sg.nx+1)*sg.ny*sg.nz,sg.nx*(sg.ny+1)*sg.nz,sg.nx*sg.ny*(sg.nz+1)};
        for(std::size_t d=0;d<3;++d) {
            const Values* velocity[]{&flow.u,&flow.v,&flow.w};const Values* diagonal[]{&flow.d_u,&flow.d_v,&flow.d_w};
            check(*velocity[d],faces[d]);check(*diagonal[d],faces[d]);
            check(flow.velocity_real[d],have_real?n:0);
            const std::array<std::size_t,3> physical_faces{(g.nx+1)*g.ny*g.nz,g.nx*(g.ny+1)*g.nz,g.nx*g.ny*(g.nz+1)};
            check(flow.face_velocity_real[d],have_real?physical_faces[d]:0);
        }
        for(const auto* v:{&flow.inlet_velocity,&flow.inlet_opening,&flow.outlet_opening,&flow.fixed_inlet_massflux})check(*v,sg.nx*sg.nz);
        check(flow.outlet_u_fraction,(sg.nx+1)*sg.nz);check(flow.outlet_w_fraction,sg.nx*(sg.nz+1));
    }
    if(state.thermal) {
        const auto& run=*state.thermal;const auto& e=run.evidence;const auto& record=run.record;
        const auto mode=thermal_mode(input,control);const bool eos=mode==Full3DThermalMode::true_h;
        const bool staggered=g.nz>1 && (control.conservative || !control.force_cell_centered);
        const bool legacy=!staggered && (eos || (!input.solve_b && input.a.fluid==Fluid::sco2));
        const bool model=mode==Full3DThermalMode::model_h;
        const auto owners=run.model_h_2d.has_value()+run.model_h_3d.has_value()+run.staggered.has_value()
            +run.legacy.has_value()+run.enthalpy.has_value();
        if(owners!=1 || e.outer_index!=outer || record.outer_index!=outer || e.mode!=mode
           || (run.enthalpy && !eos) || (run.legacy && !legacy)
           || (run.staggered && (model || !staggered))
           || (run.model_h_2d && (eos || legacy || g.nz!=1))
           || (run.model_h_3d && !(model || (!eos && !staggered && !legacy && g.nz>1)))
           || record.rejected_startup_iterations.size()!=record.rejected_startup_reasons.size())
            throw std::invalid_argument("invalid full 3D continuation thermal owner");
        const auto total=control.model_h_iterations.max_iterations
            ?control.model_h_iterations.max_iterations:control.thermal_iterations;
        const bool startup=model && (input.a.fluid==Fluid::water || input.b.fluid==Fluid::water) && outer==0;
        auto remaining=total,budget=eos?std::size_t{2}:(startup?std::min<std::size_t>(total,250):total);
        const bool integral=run.model_h_2d.has_value() || run.model_h_3d.has_value();
        if(record.model_h_iterations.size()!=(integral?record.rejected_startup_iterations.size()+1:0))
            throw std::invalid_argument("invalid full 3D continuation thermal call history");
        for(std::size_t attempt=0;attempt<record.model_h_iterations.size();++attempt) {
            const auto& settings=record.model_h_iterations[attempt];
            const auto chunk=g.nz==1?500u:250u;
            const double tolerance=control.model_h_iterations.temperature_tolerance
                ?control.model_h_iterations.temperature_tolerance:.01;
            const double q_tolerance=control.model_h_iterations.q_relative_tolerance
                ?control.model_h_iterations.q_relative_tolerance:g.nz==1?2e-8:1e-4;
            ModelHControl3D acceleration{};
            acceleration.strict_energy_balance=model?strict_model_h(input):g.nz>1;
            if(settings.accelerate!=(model && control.refined_port_energy)
               || settings.acceleration_sweeps!=model_h_common::acceleration_block(acceleration)
               || settings.acceleration_history!=model_h_common::acceleration_history(acceleration)
               || settings.max_iterations!=budget || settings.chunk_iterations!=chunk
               || settings.temperature_tolerance!=tolerance || settings.q_relative_tolerance!=q_tolerance
               || settings.total_iteration_budget!=total)
                throw std::invalid_argument("full 3D continuation thermal settings differ from input");
            if(attempt==record.rejected_startup_iterations.size())break;
            const auto charged=record.rejected_startup_iterations[attempt];
            if(!startup || budget<=1 || !charged || charged>budget || charged>=remaining)
                throw std::invalid_argument("invalid full 3D continuation startup history");
            remaining-=charged;budget=std::min(budget/2,remaining);
        }
        if(!integral && !record.rejected_startup_iterations.empty())
            throw std::invalid_argument("invalid full 3D continuation startup history");
        if(run.remaining!=remaining || run.budget!=budget)
            throw std::invalid_argument("invalid full 3D continuation thermal budget");
        for(std::size_t field=0;field<3;++field) {
            check(run.initial[field],n,true);check(e.temperature[field],0);
            if(outer && run.initial[field]!=state.previous[field])
                throw std::invalid_argument("full 3D continuation thermal start differs from the previous state");
            if(!outer) {
                const double expected=field==0?input.a.inlet_temperature:field==1?input.b.inlet_temperature
                    :control.initial_solid_temperature.value_or(.5*(input.a.inlet_temperature+input.b.inlet_temperature));
                if(!std::all_of(run.initial[field].begin(),run.initial[field].end(),[&](double value){return value==expected;}))
                    throw std::invalid_argument("full 3D continuation initial temperature differs from input");
            }
        }
        const std::array<std::size_t,3> faces{(g.nx+1)*g.ny*g.nz,g.nx*(g.ny+1)*g.nz,g.nx*g.ny*(g.nz+1)};
        for(std::size_t side=0;side<2;++side) {
            if(e.pressure[side]!=state.result.flow[side].pressure_real || e.hv[side]!=state.hv[side]
               || e.conductivity[side]!=state.conductivity[side] || e.rho_cp[side]!=state.rho_cp[side])
                throw std::invalid_argument("full 3D continuation thermal input differs from the current state");
            for(std::size_t d=0;d<3;++d) {
                check(e.face_velocity[side][d],faces[d]);
                check(e.mass[side][d],model || (mode==Full3DThermalMode::temperature && !staggered) || run.enthalpy?faces[d]:0);
            }
            check(e.enthalpy[side],run.enthalpy?n:0);
            const auto direction=side?input.b.direction:input.a.direction;
            const auto patch=direction<2?g.ny*g.nz:direction<4?g.nx*g.nz:g.nx*g.ny;
            check(e.inlet_capacity[side],side==0 || input.solve_b?patch:0);
        }
        const auto empty=[&](const auto& fields) {for(const auto& field:fields)check(field,0);};
        if(run.model_h_2d)empty(run.model_h_2d->iteration.temperature);
        if(run.model_h_3d)empty(run.model_h_3d->iteration.temperature);
        if(run.staggered)empty(run.staggered->iteration.temperature);
        if(run.legacy)empty(run.legacy->temperature);
        if(run.enthalpy)empty(run.enthalpy->fields);
    }

    if(outer) {
        const auto& thermal=state.result.thermal;
        if(thermal.outer_index!=outer-1)throw std::invalid_argument("full 3D thermal evidence has a different continuation position");
        if((thermal.mode==Full3DThermalMode::true_h)!=thermal.true_h.has_value()
           || (thermal.mode==Full3DThermalMode::model_h)!=thermal.model_h.has_value())
            throw std::invalid_argument("full 3D continuation thermal mode differs from its evidence");
        for(const auto& temperature:thermal.temperature)check(temperature,n,true);
        const std::array<std::size_t,3> faces{(g.nx+1)*g.ny*g.nz,g.nx*(g.ny+1)*g.nz,g.nx*g.ny*(g.nz+1)};
        const bool actual_mass=thermal.mode!=Full3DThermalMode::temperature || thermal.temperature_algorithm.has_value();
        for(std::size_t side=0;side<2;++side) {
            check(thermal.hv[side],n);check(thermal.conductivity[side],n,true);check(thermal.rho_cp[side],n,true);
            const bool active=side==0||input.solve_b;check(thermal.pressure[side],active?n:0,true);
            for(std::size_t d=0;d<3;++d) {
                check(thermal.face_velocity[side][d],faces[d]);
                check(thermal.mass[side][d],actual_mass?faces[d]:0);
            }
            check(thermal.enthalpy[side],thermal.true_h?n:0);
            if(!thermal.actual_conductivity[side].empty())check(thermal.actual_conductivity[side],n,true);
        }
    }
}
} // namespace

Full3DRunState Full3DRun::snapshot() const {
    if(!impl_->boundary || !saved_boundary(impl_->phase))
        throw std::logic_error("full 3D snapshot requires a completed iteration boundary");
    const auto& r=impl_->runtime;Full3DRunState state;
    state.phase=impl_->phase;state.result=r.result;state.inlet=r.inlet;
    state.drag_k=r.drag_k;state.drag_cf=r.drag_cf;state.mass_flux=r.mass_flux;
    state.dispersion=r.dispersion;state.hv_ratio=r.hv_ratio;
    state.conductivity=r.conductivity;state.rho_cp=r.rho_cp;state.hv=r.hv;
    state.temperature=r.temperature;state.previous=r.previous;
    const auto flow=active_flow(impl_->phase);
    for(std::size_t side=0;side<2;++side) {
        if(flow==side) {
            auto active=r.simple[side]->snapshot_active();
            state.simple[side]=std::move(active.owner);
            state.flow_convergence=std::move(active.convergence);state.flow_iteration=std::move(active.result);
        } else if(r.simple[side])state.simple[side]=r.simple[side]->snapshot();
    }
    if(r.pending) {
        state.thermal=r.pending;auto& saved=*state.thermal;
        if(r.enthalpy) {saved.enthalpy=r.enthalpy->snapshot();saved.enthalpy->fields={};}
        else if(r.model_h_2d) {saved.model_h_2d=r.model_h_2d->snapshot();saved.model_h_2d->iteration.temperature={};}
        else if(r.model_h_3d) {saved.model_h_3d=r.model_h_3d->snapshot();saved.model_h_3d->iteration.temperature={};}
        else if(r.legacy) {saved.legacy=r.legacy->snapshot();saved.legacy->temperature={};}
        else {saved.staggered=r.thermal.snapshot_active();saved.staggered->iteration.temperature={};}
    }
    validate_continuation(impl_->input,impl_->control,state);
    return state;
}

Full3DRun::Full3DRun(const Full3DInput& input,const Full3DControl& control,const Full3DRunState& state)
    :Full3DRun(input,control) {
    validate_continuation(input,control,state);
    auto& r=impl_->runtime;r.result=state.result;r.inlet=state.inlet;
    r.drag_k=state.drag_k;r.drag_cf=state.drag_cf;r.mass_flux=state.mass_flux;
    r.dispersion=state.dispersion;r.hv_ratio=state.hv_ratio;
    r.conductivity=state.conductivity;r.rho_cp=state.rho_cp;r.hv=state.hv;
    r.temperature=state.temperature;r.previous=state.previous;impl_->phase=state.phase;
    const auto active=active_flow(state.phase);
    for(std::size_t side=0;side<2;++side)if(state.simple[side]) {
        auto& flow=r.result.flow[side];const auto sg=grid(flow);
        std::vector<unsigned char> opened(flow.outlet_opening.size());
        for(std::size_t j=0;j<opened.size();++j)opened[j]=flow.outlet_opening[j]>0.;
        r.simple[side]=std::make_unique<Simple3DSolver>(sg,ArrayView<const unsigned char>{opened.data(),opened.size()});
        if(active==side) {
            Simple3DRunState saved;
            saved.owner=*state.simple[side];saved.convergence=*state.flow_convergence;saved.result=*state.flow_iteration;
            saved.fields={flow.u,flow.v,flow.w,flow.pressure,flow.pressure_correction,flow.d_u,flow.d_v,flow.d_w,flow.density,flow.inlet_velocity};
            r.start_flow(side,initial_flow(state.phase)?control.initial_simple_iterations:control.warm_simple_iterations,&saved);
        } else r.simple[side]->restore(*state.simple[side]);
    }
    if(state.thermal) {
        r.pending=state.thermal;r.start_thermal(&*state.thermal);
        r.pending->model_h_2d.reset();r.pending->model_h_3d.reset();r.pending->staggered.reset();
        r.pending->legacy.reset();r.pending->enthalpy.reset();
    }
}

Full3DResult Full3DRun::take_result() {
    if(!impl_->boundary || (impl_->phase!=Full3DPhase::completed && impl_->phase!=Full3DPhase::cancelled) || impl_->result_taken)
        throw std::logic_error("full 3D result is not available");
    impl_->result_taken=true;return std::move(impl_->runtime.result);
}

Full3DResult solve_full_3d(const Full3DInput& input,const Full3DControl& control) {
    Full3DRun run(input,control);
    while(run.phase()!=Full3DPhase::completed && run.phase()!=Full3DPhase::cancelled)run.advance_step();
    return run.take_result();
}

}  // namespace tpmshx
