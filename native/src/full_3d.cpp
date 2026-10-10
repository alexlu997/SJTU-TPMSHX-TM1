#include "tpmshx/full_3d.hpp"
#include "tpmshx/conservative_energy.hpp"
#include "tpmshx/model_coefficients.hpp"
#include "legacy_single_a_temperature.hpp"

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
    if(!c.max_outer || !c.initial_simple_iterations || !c.warm_simple_iterations || !c.thermal_iterations
       || !std::isfinite(c.outer_temperature_tolerance) || c.outer_temperature_tolerance<=0.
       || !std::isfinite(c.thermal_relaxation) || c.thermal_relaxation<=0. || c.thermal_relaxation>1.)
        throw std::invalid_argument("invalid full 3D iteration controls");
    if(c.envelope_mode<0 || c.envelope_mode>2 || c.roughness_mode<0 || c.roughness_mode>2)
        throw std::invalid_argument("invalid full 3D resolved mode");
    for(const auto tolerance:{c.enthalpy.coupled_energy_tolerance,c.enthalpy.equation_energy_tolerance})
        if(!tolerance || !std::isfinite(*tolerance) || *tolerance<=0.)
            throw std::invalid_argument("full 3D requires finite positive true-h coupled and equation gates");
    switch(c.enthalpy.algorithm) {
        case EnthalpyAlgorithm::legacy_h_fou: break;
        case EnthalpyAlgorithm::temperature_fou:
        case EnthalpyAlgorithm::temperature_sou:
            if(!in.solve_b || (!uses_co2_eos(in.a.fluid) && !uses_co2_eos(in.b.fluid)))
                throw std::invalid_argument("candidate full 3D energy currently requires the existing two-sided true-h route");
            if(!c.conservative || !c.variable_rho_cp || c.red_black_energy
               || in.a.dispersion!=0. || in.b.dispersion!=0.)
                throw std::invalid_argument("unsupported candidate full 3D energy boundary, property or acceleration option");
            for(auto source:in.sources)
                if(source.size && std::any_of(source.data,source.data+source.size,[](double x){return x!=0.;}))
                    throw std::invalid_argument("candidate full 3D energy does not support physical sources");
            if(!c.enthalpy.max_iterations || !c.enthalpy.sweeps || !std::isfinite(c.enthalpy.omega)
               || c.enthalpy.omega<=0. || c.enthalpy.omega>1.
               || !std::isfinite(c.enthalpy.temperature_update_tolerance) || c.enthalpy.temperature_update_tolerance<=0.)
                throw std::invalid_argument("invalid candidate full 3D energy controls");
            if(c.enthalpy.require_enthalpy_update_on_temperature
               && (!std::isfinite(c.enthalpy.update_tolerance) || c.enthalpy.update_tolerance<=0.))
                throw std::invalid_argument("full 3D T energy h-update tolerance must be finite and positive");
            break;
        default: throw std::invalid_argument("unknown full 3D energy algorithm");
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

void check_energy_ports(const GridView& g,const Full3DSide& side,const Faces& mass) {
    const auto counts=shape(g);
    for(int axis=0;axis<3;++axis) for(bool high:{false,true})
        boundary(g,axis,high,[&](std::size_t,std::size_t p,std::size_t f,double) {
            if(mass[axis][f]==0.) return;
            if(axis!=side.direction/2)
                throw std::invalid_argument("candidate energy mass crosses a non-port boundary");
            const std::array<std::size_t,3> coord{p/(g.ny*g.nz),(p/g.nz)%g.ny,p%g.nz};
            const auto q=coord[side.solver_axes[0]]*counts[side.solver_axes[2]]+coord[side.solver_axes[2]];
            const bool inlet=high==static_cast<bool>(side.direction%2);
            if((inlet?side.inlet_opening:side.outlet_opening)[q]==0.)
                throw std::invalid_argument("candidate energy mass crosses a closed port face");
        });
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
    Full3DResult result;
    PropertyEvaluator props;
    EnthalpyEOS eos;
    StaggeredTemperatureDriver thermal;
    std::array<std::unique_ptr<Simple3DSolver>,2> simple;
    std::array<std::unique_ptr<OuterAnderson>,2> anderson;
    std::array<FluidProperties,2> inlet;
    std::array<double,2> drag_k{},drag_cf{},mass_flux{},dispersion{},hv_ratio{1.,1.};
    std::array<Values,2> conductivity,rho_cp,hv;
    std::array<Values,3> temperature,previous;
    const Full3DSide& side(std::size_t s) const { return s?input.b:input.a; }
    ArrayView<const double> epsilon(std::size_t s) const { return s?input.geometry.epsilon_b:input.geometry.epsilon_a; }
    bool active(std::size_t s) const { return !s || input.solve_b; }
    explicit Runtime(const Full3DInput& i,const Full3DControl& c):input(i),control(c) {
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
    void solve_flow(std::size_t s,std::size_t cap,const std::string& stage);
    void check_water(const std::array<Values,3>& t,const std::array<Values,2>& pressure);
    void heat_transfer(std::size_t s,bool warm);
    Full3DThermalEvidence prepare(bool warm);
    Full3DOuterRecord solve_thermal(std::size_t outer,Full3DThermalEvidence& evidence);
    void refresh_flow(std::size_t s,std::size_t outer,const std::optional<PressurePortState>& pressure);
    void refresh_thermal_properties();
    void post(std::size_t outer);
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

void Runtime::solve_flow(std::size_t s,std::size_t cap,const std::string& stage) {
    auto& v=result.flow[s];const auto& a=side(s);auto c=control.simple;
    c.max_iterations=cap;c.ideal_gas=a.fluid==Fluid::air;c.pressure_reference_absolute=v.pressure_reference;
    c.cancel=control.cancel;c.context=control.context;
    if(control.coarse_bootstrap && simple[s]->history().legacy.empty() && !v.bootstrap) {
        if(c.ideal_gas && c.massflux_inlet)simple[s]->capture_massflux_target(view(v.fixed_inlet_massflux));
        bootstrap(a,v,*simple[s],c,control.coarse_iterations,v.bootstrap_trace);
    }
    v.last=simple[s]->solve({view(v.epsilon),view(v.viscosity),view(v.effective_viscosity),
                            view(v.permeability),view(v.forchheimer),view(v.temperature)},
        {view(v.outlet_u_fraction),view(v.outlet_w_fraction)},
        {writable(v.u),writable(v.v),writable(v.w),writable(v.pressure),writable(v.pressure_correction),
         writable(v.d_u),writable(v.d_v),writable(v.d_w),writable(v.density),writable(v.inlet_velocity)},c);
    if(v.last.stop==SimpleStop::cancelled) throw Cancelled{};
    if(v.last.stop==SimpleStop::pressure_failure) throw std::runtime_error("full 3D SIMPLE pressure solve failed: "+v.last.linear.detail);
    anchor(a,v);v.history=simple[s]->history();
    if(!v.last.converged) {
        const char* reasons[]{"ongoing","tol","stall","max_iter","nonfinite","cancelled","pressure_failure","post_closure"};
        result.simple_failures.push_back(std::string(s?"B@":"A@")+stage+"["+reasons[static_cast<unsigned>(v.last.stop)]+"]");
    }
    update_real(input.geometry.grid,a,v);v.inlet_pressure=inlet_state(a,v);
}

void Runtime::initialize() {
    const auto& g=input.geometry.grid;const auto n=g.nx*g.ny*g.nz;
    for(std::size_t s=0;s<2;++s) {
        const auto& a=side(s);inlet[s]=props.evaluate(a.fluid,a.inlet_temperature,a.inlet_pressure);
        if(active(s)) initialize_side(s);
        if(control.outer_anderson && active(s)) anderson[s]=std::make_unique<OuterAnderson>(
            static_cast<int>(control.anderson_history),control.anderson_trust,static_cast<int>(control.anderson_patience));
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
    solve_flow(0,control.initial_simple_iterations,"init");
    if(input.solve_b) solve_flow(1,control.initial_simple_iterations,"init");
    bulk_ranges();
    temperature[0].assign(n,input.a.inlet_temperature);temperature[1].assign(n,input.b.inlet_temperature);
    temperature[2].assign(n,control.initial_solid_temperature.value_or(.5*(input.a.inlet_temperature+input.b.inlet_temperature)));
}

void Runtime::check_water(const std::array<Values,3>& t,const std::array<Values,2>& pressure) {
    for(std::size_t s=0;s<2;++s) if(side(s).fluid==Fluid::water)
        for(std::size_t p=0;p<t[s].size();++p)
            props.check_water(t[s][p],active(s)?pressure[s][p]:side(s).inlet_pressure);
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
    if(uses_co2_eos(a.fluid) && warm) {
        observation={};observation.available=true;observation.cells=hv[s].size();observation.pressure=a.inlet_pressure;
        observation.raw_min=observation.re_min=observation.pr_min=observation.temperature_min=std::numeric_limits<double>::infinity();
        observation.raw_max=observation.re_max=observation.pr_max=observation.temperature_max=-std::numeric_limits<double>::infinity();
    }
    for(std::size_t p=0;p<hv[s].size();++p) {
        auto property=inlet[s];
        if(uses_co2_eos(a.fluid) && warm) property=props.transport(a.fluid,temperature[s][p],a.inlet_pressure);
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

Full3DThermalEvidence Runtime::prepare(bool warm) {
    Full3DThermalEvidence e;const auto& geo=input.geometry;const auto& g=geo.grid;
    const bool true_h=input.solve_b && (uses_co2_eos(input.a.fluid) || uses_co2_eos(input.b.fluid));
    const bool model_h=g.nz>1 && control.variable_rho_cp && input.solve_b && control.conservative && !geo.asymmetric
        && ((input.a.fluid==Fluid::air && (input.b.fluid==Fluid::air || input.b.fluid==Fluid::water))
            || (input.a.fluid==Fluid::water && input.b.fluid==Fluid::air));
    e.mode=true_h?Full3DThermalMode::true_h:(model_h?Full3DThermalMode::model_h:Full3DThermalMode::temperature);
    const bool cc=e.mode==Full3DThermalMode::temperature
        &&(g.nz==1||(!control.conservative&&control.force_cell_centered));
    const bool legacy_single_sco2=!input.solve_b && input.a.fluid==Fluid::sco2;
    if(cc && legacy_single_sco2)
        e.temperature_algorithm="legacy_frozen_cp_single_a_cc_v1";
    if(!true_h && warm)temperature_ranges("main","real-cell(x,y,z)-warm");
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
        if(cc) {
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

Full3DOuterRecord Runtime::solve_thermal(std::size_t outer,Full3DThermalEvidence& e) {
    const auto& geo=input.geometry;const auto& g=geo.grid;
    const bool true_h=e.mode==Full3DThermalMode::true_h,model_h=e.mode==Full3DThermalMode::model_h;
    const bool startup=model_h && (input.a.fluid==Fluid::water || input.b.fluid==Fluid::water) && outer==0;
    std::array<TemperatureBoundary,2> bc;
    for(std::size_t s=0;s<2;++s) bc[s]={active(s)?side(s).direction:3,side(s).inlet_temperature,{},
        active(s)?side(s).inlet_opening:ArrayView<const double>{},view(e.inlet_capacity[s])};
    Full3DOuterRecord record;record.outer_index=outer;e.outer_index=outer;
    std::size_t budget=true_h?2:(startup?std::min<std::size_t>(control.thermal_iterations,250):control.thermal_iterations);
    std::size_t remaining=control.thermal_iterations;
    const auto initial=temperature;
    while(true) {
        auto state=TemperatureStateView{writable(temperature[0]),writable(temperature[1]),writable(temperature[2])};
        if(model_h) {
            auto ba=bc[0],bb=bc[1];ba.capacity_flux={};bb.capacity_flux={};
            ModelHControl3D mc{budget,250,1e-4,control.thermal_relaxation,
                control.refined_port_energy?1.:control.thermal_relaxation,control.thermal_relaxation,
                true,control.refined_port_energy,control.red_black_energy,control.cancel,nullptr,control.context};
            e.model_h=solve_model_h_3d(g,
                {input.a.fluid,view(conductivity[0]),view(hv[0]),view(e.mass[0][0]),view(e.mass[0][1]),view(e.mass[0][2]),ba,input.sources[0]},
                {input.b.fluid,view(conductivity[1]),view(hv[1]),view(e.mass[1][0]),view(e.mass[1][1]),view(e.mass[1][2]),bb,input.sources[1]},
                geo.solid_conductivity,input.sources[2],state,mc);
            const auto& r=*e.model_h;
            if(r.stop==TemperatureStop::cancelled) throw Cancelled{};
            record.thermal_converged=r.stop==TemperatureStop::converged;record.thermal_iterations=r.iterations;record.thermal_residual=r.residual;
        } else {
            TemperatureControl tc{budget,250,1e-4,control.thermal_relaxation,control.thermal_relaxation,
                control.thermal_relaxation,true,true,control.cancel,nullptr,control.context};
            TemperatureResult r;
            if(g.nz>1 && (control.conservative || !control.force_cell_centered)) {
                e.staggered=thermal.solve(g,
                    {view(conductivity[0]),view(hv[0]),epsilon(0),view(rho_cp[0]),views(e.face_velocity[0]),bc[0],input.sources[0]},
                    {view(conductivity[1]),view(hv[1]),epsilon(1),view(rho_cp[1]),views(e.face_velocity[1]),bc[1],input.sources[1]},
                    geo.solid_conductivity,state,tc,control.conservative,control.red_black_energy,
                    input.solve_b?ArrayView<const double>{}:view(initial[1]),input.sources[2]);
                r=e.staggered->iteration;
            } else {
                if(std::any_of(input.sources.begin(),input.sources.end(),[](auto source){
                    return source.size && std::any_of(source.data,source.data+source.size,[](double x){return x!=0.;});}))
                    throw std::invalid_argument("nonzero 3D MMS sources require staggered velocities");
                const bool legacy_single_sco2=!input.solve_b && input.a.fluid==Fluid::sco2;
                if(true_h || legacy_single_sco2) {
                    // Retain the G4 CC rows for true-h warm-up and single-A
                    // sCO2, with frozen outer properties and no h(T) ledger.
                    // Only true-h receives the two-sweep warm-up cap; its
                    // enthalpy driver then enforces the selected physical gates.
                    const auto& va=result.flow[0].velocity_real;
                    const Values zero_velocity(input.solve_b?0:temperature[0].size());
                    const auto vb=input.solve_b?views(result.flow[1].velocity_real)
                        :std::array<ArrayView<const double>,3>{view(zero_velocity),view(zero_velocity),view(zero_velocity)};
                    auto capacity=e.inlet_capacity;
                    if(g.nz==1) {
                        tc.chunk_iterations=500;tc.q_relative_tolerance=2e-8;
                        tc.alpha_a=.7;tc.alpha_solid=1.;tc.alpha_b=1.;tc.second_order_b=false;
                        for(std::size_t s=0;s<2;++s) {
                            for(double& value:capacity[s]) value/=sum(g.dz);
                            bc[s].capacity_flux=view(capacity[s]);
                        }
                    }
                    r=solve_legacy_single_a_temperature(g.nz==1?TemperatureScheme::cell_centered_2d:TemperatureScheme::cell_centered_3d,g,
                        {view(conductivity[0]),view(hv[0]),epsilon(0),view(rho_cp[0]),view(va[0]),view(va[1]),view(va[2]),bc[0]},
                        {view(conductivity[1]),view(hv[1]),epsilon(1),view(rho_cp[1]),vb[0],vb[1],vb[2],bc[1]},
                        geo.solid_conductivity,state,tc,input.solve_b?ArrayView<const double>{}:view(initial[1]));
                } else {
                    auto ba=bc[0],bb=bc[1];ba.capacity_flux={};bb.capacity_flux={};
                    const auto prescribed=input.solve_b?ArrayView<const double>{}:view(initial[1]);
                    PhysicalHeatLedger audit;bool audit_available=false;
                    if(g.nz==1) {
                        for(std::size_t s=0;s<2;++s)
                            if(active(s)&&std::any_of(e.mass[s][2].begin(),e.mass[s][2].end(),[](double value){return value!=0.;}))
                                throw std::invalid_argument("Nz=1 model enthalpy requires zero mass on both z boundaries");
                        const double depth=sum(g.dz),unit_depth=1.;
                        const GridView planar{g.nx,g.ny,1,g.dx,g.dy,{&unit_depth,1}};
                        std::array<std::array<Values,2>,2> mass;
                        for(std::size_t s=0;s<2;++s) for(std::size_t axis=0;axis<2;++axis) {
                            mass[s][axis]=e.mass[s][axis];
                            for(double& value:mass[s][axis]) value/=depth;
                        }
                        ModelHControl2D mc{budget,500,2e-8,true,false,false,control.cancel,nullptr,control.context};
                        mc.second_order_b=false;mc.strict_energy_balance=true;
                        const auto solved=solve_model_h_2d(planar,
                            {input.a.fluid,view(conductivity[0]),view(hv[0]),view(mass[0][0]),view(mass[0][1]),ba},
                            {input.b.fluid,view(conductivity[1]),view(hv[1]),view(mass[1][0]),view(mass[1][1]),bb},
                            geo.solid_conductivity,state,mc,prescribed,&audit);
                        r={solved.stop,solved.iterations,solved.residual,solved.q_b};
                        audit_available=solved.physical_audit_available;
                        e.temperature_algorithm="model_h_tface_sou_fou_strict_v3";
                        if(audit_available) {
                            for(auto& phase:audit.advective_out) for(auto& plane:phase) for(double& v:plane) v*=depth;
                            for(auto& phase:audit.diffusive_out) for(auto& plane:phase) for(double& v:plane) v*=depth;
                            for(auto& phase:audit.residual) for(double& v:phase) v*=depth;
                            for(double& v:audit.source_integral) v*=depth;
                            audit.prescribed_b_power*=depth;
                        }
                    } else {
                        ModelHControl3D mc{budget,250,1e-4,control.thermal_relaxation,
                            control.thermal_relaxation,control.thermal_relaxation,
                            true,false,false,control.cancel,nullptr,control.context};
                        mc.strict_energy_balance=true;
                        const auto solved=solve_model_h_3d(g,
                            {input.a.fluid,view(conductivity[0]),view(hv[0]),view(e.mass[0][0]),view(e.mass[0][1]),view(e.mass[0][2]),ba,{}},
                            {input.b.fluid,view(conductivity[1]),view(hv[1]),view(e.mass[1][0]),view(e.mass[1][1]),view(e.mass[1][2]),bb,{}},
                            geo.solid_conductivity,{},state,mc,prescribed,&audit);
                        r={solved.stop,solved.iterations,solved.residual,solved.q_b};
                        audit_available=solved.physical_audit_available;
                        e.temperature_algorithm="model_h_tface_sou_sou_strict_v3";
                    }
                    if(audit_available) e.temperature_audit=std::move(audit);
                }
            }
            if(r.stop==TemperatureStop::cancelled) throw Cancelled{};
            record.thermal_converged=r.stop==TemperatureStop::converged;record.thermal_iterations=r.iterations;record.thermal_residual=r.residual;
        }
        try {
            if(!true_h) check_water(temperature,e.pressure);
            for(const auto& t:temperature) if(!finite(t)) throw std::domain_error("nonfinite full 3D thermal return");
        } catch(const WaterStateError& error) {
            if(!startup || budget<=1 || !std::all_of(temperature.begin(),temperature.end(),finite)) throw;
            remaining-=std::min(remaining,record.thermal_iterations);
            if(!remaining) throw;
            record.rejected_startup_iterations.push_back(record.thermal_iterations);
            record.rejected_startup_reasons.push_back(error.what());
            budget=std::min(budget/2,remaining);temperature=initial;continue;
        }
        if(startup) {
            remaining-=std::min(remaining,record.thermal_iterations);
            record.startup_total_iterations=control.thermal_iterations-remaining;
        }
        break;
    }
    if(!true_h)temperature_ranges("main","real-cell(x,y,z)-return");
    if(true_h) {
        for(std::size_t s=0;s<2;++s) {
            auto faces=e.face_velocity[s];
            balance_outflow(g,side(s).direction,faces,multiply(epsilon(s),view(result.flow[s].density_real)));
            const auto projected=thermal.project_capacity_faces(g,epsilon(s),view(result.flow[s].density_real),views(faces));
            e.mass[s]=mass_faces(g,projected.velocity,epsilon(s),result.flow[s].density_real);
            if(control.enthalpy.algorithm!=EnthalpyAlgorithm::legacy_h_fou)
                check_energy_ports(g,side(s),e.mass[s]);
            e.enthalpy[s].resize(temperature[s].size());
        }
        auto c=control.enthalpy;c.cancel=control.cancel;c.context=control.context;
        e.true_h=solve_enthalpy(g,
            {input.a.fluid,input.a.inlet_temperature,input.a.inlet_pressure,view(e.pressure[0]),epsilon(0),view(hv[0]),view(e.mass[0][0]),view(e.mass[0][1]),view(e.mass[0][2]),input.a.direction},
            {input.b.fluid,input.b.inlet_temperature,input.b.inlet_pressure,view(e.pressure[1]),epsilon(1),view(hv[1]),view(e.mass[1][0]),view(e.mass[1][1]),view(e.mass[1][2]),input.b.direction},
            geo.solid_conductivity,{writable(e.enthalpy[0]),writable(e.enthalpy[1]),writable(temperature[0]),writable(temperature[1]),writable(temperature[2]),true,true,true},c);
        const auto& r=*e.true_h;if(r.stop==EnthalpyStop::cancelled) throw Cancelled{};
        record.thermal_converged=r.stop==EnthalpyStop::converged;record.thermal_iterations=r.iterations;record.thermal_residual=r.residual;
        check_water(temperature,e.pressure);
        for(const auto& t:temperature) if(!finite(t)) throw std::domain_error("nonfinite full 3D true-h return");
        if(r.algorithm!=EnthalpyAlgorithm::legacy_h_fou) {
            for(std::size_t s=0;s<2;++s) {
                auto& actual=e.actual_conductivity[s];actual.resize(temperature[s].size());
                for(std::size_t p=0;p<actual.size();++p)
                    actual[p]=epsilon(s)[p]*eos.conductivity(side(s).fluid,temperature[s][p],e.pressure[s][p]);
                e.enthalpy_boundary_power[s]=enthalpy_boundary_power(g,view(e.enthalpy[s]),views(e.mass[s]),
                    r.inlet_enthalpy[s],r.algorithm==EnthalpyAlgorithm::temperature_sou);
            }
        }
    }
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
    return record;
}

void Runtime::refresh_flow(std::size_t s,std::size_t outer,const std::optional<PressurePortState>& pressure) {
    const auto& a=side(s);auto& flow=result.flow[s];const auto& g=input.geometry.grid;
    const bool air=a.fluid==Fluid::air;
    const bool local_sco2=s==0 && a.fluid==Fluid::sco2 && control.sco2_local_pressure_a;
    auto next_temperature=to_solver(g,a,view(temperature[s]));
    const auto local_grid=grid(flow);
    property_ranges(s,"property","property-refresh","solver-cell(cross1,stream,cross2)",
        {local_grid.nx,local_grid.ny,local_grid.nz},view(next_temperature),air?2:3);
    const auto previous_mu=outer && anderson[s]?flow.viscosity:Values{};
    Values rho_new(flow.density.size()),mu_new(flow.viscosity.size());
    for(std::size_t p=0;p<rho_new.size();++p) {
        const double absolute=flow.pressure_reference+flow.pressure[p];
        const auto property=props.transport(a.fluid,next_temperature[p],local_sco2?absolute:a.inlet_pressure);
        rho_new[p]=air?absolute/(model_coefficients::envelope_r_air*next_temperature[p]):property.rho;
        mu_new[p]=property.mu;
    }
    // Original A setter runs before the selected-property update; original B
    // setter runs after it and overwrites air mu again. Preserve that ordering.
    if(s==0) {
        flow.temperature=next_temperature;
        if(air) flow.viscosity=mu_new;
    }
    if(outer && anderson[s]) {
        auto selected=anderson[s]->step({view(flow.density),view(previous_mu)},{view(rho_new),view(mu_new)},.6);
        flow.density=std::move(selected.blocks[0]);flow.viscosity=std::move(selected.blocks[1]);
    } else {
        for(std::size_t p=0;p<rho_new.size();++p) {
            flow.density[p]=outer ? .6*rho_new[p]+.4*flow.density[p]:rho_new[p];
            flow.viscosity[p]=outer ? .6*mu_new[p]+.4*flow.viscosity[p]:mu_new[p];
        }
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
            const double drag=mu*mass_flux[s]/std::max(drag_k[s],1e-16)+drag_cf[s]*mass_flux[s]*mass_flux[s];
            flow.pressure_reference=pressure_initial_reference(predict_outlet_p_sq(a.inlet_pressure,mean,drag,sum(sg.dy)),
                                                               a.inlet_pressure,flow.pressure_iterations);
        }
    } else if(s==0) {
        const double mean=cell_average(g,temperature[s]);
        property_ranges(s,"property","property-refresh","mean",{},{&mean,1},2);
        if(a.fluid==Fluid::water) props.check_water(mean,a.inlet_pressure);
        const double mu=props.transport(a.fluid,mean,a.inlet_pressure).mu;
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
        if(air && !(outer && anderson[s])) {
            flow.viscosity=std::move(mu_new);
            for(std::size_t p=0;p<flow.viscosity.size();++p) flow.effective_viscosity[p]=flow.viscosity[p]/flow.epsilon[p];
        }
    }
    solve_flow(s,control.warm_simple_iterations,"outer"+std::to_string(outer));
}

void Runtime::refresh_thermal_properties() {
    const auto& g=input.geometry.grid;
    for(std::size_t s=0;s<2;++s) {
        const auto& a=side(s);
        unsigned mask=4;
        if(s==0 || !(control.variable_rho_cp && a.fluid==Fluid::air && active(s)))mask|=8;
        if((s==0 && !control.variable_rho_cp) || (s==1 && !(control.variable_rho_cp && a.fluid==Fluid::air && active(s))))mask|=1;
        property_ranges(s,"property","property-refresh","real-cell(x,y,z)",{g.nx,g.ny,g.nz},view(temperature[s]),mask);
        for(std::size_t p=0;p<temperature[s].size();++p) {
            const auto property=props.transport(a.fluid,temperature[s][p],a.inlet_pressure);
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

void Runtime::post(std::size_t outer) {
    const std::array<std::optional<PressurePortState>,2> pressure{
        inlet_state(input.a,result.flow[0]),input.solve_b?inlet_state(input.b,result.flow[1]):std::nullopt};
    const std::array<Values,2> absolute{result.flow[0].pressure_real,result.flow[1].pressure_real};
    check_water(temperature,absolute);
    refresh_flow(0,outer,pressure[0]);
    refresh_thermal_properties();
    if(input.solve_b) refresh_flow(1,outer,pressure[1]);
}

void Runtime::finish() {
    const auto& g=input.geometry.grid;
    const bool true_h_pair=uses_co2_eos(input.a.fluid) || uses_co2_eos(input.b.fluid);
    const bool candidate=result.thermal.true_h
        && result.thermal.true_h->algorithm!=EnthalpyAlgorithm::legacy_h_fou;
    if(!true_h_pair)temperature_ranges("final","real-cell(x,y,z)");
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
        if(anderson[s]) result.anderson[s]=anderson[s]->stats();
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
                const double h=eos.bracket_enthalpy(a.fluid,local_temperature[out],pressure);
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
        if(candidate || result.thermal.temperature_audit) {
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
            if(evidence.temperature_audit) {
                double q=0.;
                for(const auto& plane:evidence.temperature_audit->advective_out[s])
                    for(double value:plane) q-=value;
                result.duty[s]=evidence.temperature_audit->boundary_complete?std::abs(q)
                    :std::numeric_limits<double>::quiet_NaN();
            } else result.duty[s]=std::abs(s==0?evidence.true_h->q_a:evidence.true_h->q_b);
        } else if(true_h_pair) {
            eos.validate(a.fluid,a.inlet_temperature,a.inlet_pressure,"3D final inlet enthalpy");
            const double hin=eos.bracket_enthalpy(a.fluid,a.inlet_temperature,a.inlet_pressure);
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

Full3DResult solve_full_3d(const Full3DInput& input,const Full3DControl& control) {
    validate(input,control);
    Runtime runtime(input,control);
    try {
        cancel(control);runtime.initialize();
        for(std::size_t outer=0;outer<control.max_outer;++outer) {
            cancel(control);
            if(control.outer_iteration)control.outer_iteration(control.context,outer+1,control.max_outer);
            if(control.progress) control.progress(control.context,10.+80.*static_cast<double>(outer)/control.max_outer);
            auto evidence=runtime.prepare(outer>0 || control.initial_solid_temperature.has_value());
            auto record=runtime.solve_thermal(outer,evidence);
            // Detach the completed thermal state before either post update.
            runtime.result.thermal=std::move(evidence);
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
                runtime.result.outer_ok=true;runtime.result.stop=Full3DStop::converged;break;
            }
            // Preserve the original final capped post, including its later
            // pressure reference and fields. Thermal evidence is already owned.
            runtime.post(outer);
        }
        runtime.result.post_after_last_thermal=!runtime.result.outer_ok;
        runtime.finish();cancel(control);
        if(control.progress) control.progress(control.context,100.);
    } catch(const Cancelled&) {
        runtime.result.stop=Full3DStop::cancelled;runtime.result.converged=false;
        for(auto& flow:runtime.result.flow)
            if(flow.bootstrap_trace.available && flow.bootstrap_trace.decision=="not-started")
                flow.bootstrap_trace.decision="cancelled";
    }
    return std::move(runtime.result);
}

}  // namespace tpmshx
