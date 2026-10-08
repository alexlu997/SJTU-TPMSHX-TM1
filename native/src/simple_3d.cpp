#include "tpmshx/simple_3d.hpp"
#include "tpmshx/simple_momentum.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace tpmshx {
namespace {
template <typename T> ArrayView<const T> read(ArrayView<T> a) { return {a.data,a.size}; }
SimpleFacesView<const double> velocities(Simple3DStateView s) { return {read(s.u),read(s.v),read(s.w)}; }
SimpleFacesView<double> mutable_velocities(Simple3DStateView s) { return {s.u,s.v,s.w}; }
SimpleFacesView<const double> corrections(Simple3DStateView s) { return {read(s.d_u),read(s.d_v),read(s.d_w)}; }
template <typename T> void extent(ArrayView<T> a, std::size_t n, const char* name) {
    if (a.size != n || (n && !a.data)) throw std::invalid_argument(std::string("invalid SIMPLE 3D extent: ")+name);
}
template <typename T> bool finite(ArrayView<T> a) {
    for (std::size_t n=0;n<a.size;++n) if (!std::isfinite(a[n])) return false;
    return true;
}
void positive(ArrayView<const double> a,const char* name,bool zero=false) {
    for (std::size_t n=0;n<a.size;++n)
        if (!std::isfinite(a[n]) || (zero ? a[n]<0. : a[n]<=0.))
            throw std::invalid_argument(std::string("invalid SIMPLE 3D coefficient: ")+name);
}
void fraction(ArrayView<const double> a,const char* name) {
    for (std::size_t n=0;n<a.size;++n) if (!std::isfinite(a[n]) || a[n]<0. || a[n]>1.)
        throw std::invalid_argument(std::string("invalid SIMPLE 3D fraction: ")+name);
}
bool state_finite(const Simple3DMaterialView& m,Simple3DStateView s) {
    return finite(s.u)&&finite(s.v)&&finite(s.w)&&finite(s.pressure)&&finite(s.density)&&finite(m.temperature);
}
void validate_grid(const GridView& g) {
    const auto limit=static_cast<std::size_t>(std::numeric_limits<int>::max());
    if (!g.nx||!g.ny||!g.nz||g.nx>limit/g.ny||g.nx*g.ny>limit/g.nz)
        throw std::invalid_argument("SIMPLE 3D requires a nonempty 32-bit cell grid");
    extent(g.dx,g.nx,"dx");extent(g.dy,g.ny,"dy");extent(g.dz,g.nz,"dz");
    positive(g.dx,"dx");positive(g.dy,"dy");positive(g.dz,"dz");
}
bool overlap(ArrayView<const double> a,ArrayView<const double> b) {
    const auto x=reinterpret_cast<std::uintptr_t>(a.data),y=reinterpret_cast<std::uintptr_t>(b.data);
    return a.size&&b.size&&(x<=y ? y-x<a.size*sizeof(double) : x-y<b.size*sizeof(double));
}
void validate(const GridView& g,const Simple3DMaterialView& m,const Simple3DBoundaryView& b,Simple3DStateView s) {
    validate_grid(g);const auto n=g.nx*g.ny*g.nz;
    extent(m.epsilon,n,"epsilon");extent(m.viscosity,n,"viscosity");extent(m.effective_viscosity,n,"effective_viscosity");
    extent(m.permeability,n,"permeability");extent(m.forchheimer,n,"forchheimer");extent(m.temperature,n,"temperature");
    extent(s.u,(g.nx+1)*g.ny*g.nz,"u");extent(s.v,g.nx*(g.ny+1)*g.nz,"v");extent(s.w,g.nx*g.ny*(g.nz+1),"w");
    extent(s.d_u,s.u.size,"d_u");extent(s.d_v,s.v.size,"d_v");extent(s.d_w,s.w.size,"d_w");
    extent(s.pressure,n,"pressure");extent(s.pressure_correction,n,"pressure_correction");extent(s.density,n,"density");
    extent(s.inlet_velocity,g.nx*g.nz,"inlet_velocity");
    extent(b.outlet_u_fraction,(g.nx+1)*g.nz,"outlet_u_fraction");extent(b.outlet_w_fraction,g.nx*(g.nz+1),"outlet_w_fraction");
    positive(m.epsilon,"epsilon");fraction(m.epsilon,"epsilon");positive(m.viscosity,"viscosity");
    positive(m.effective_viscosity,"effective_viscosity");positive(m.permeability,"permeability");positive(m.forchheimer,"forchheimer",true);
    fraction(b.outlet_u_fraction,"outlet_u_fraction");fraction(b.outlet_w_fraction,"outlet_w_fraction");
    if (!finite(s.inlet_velocity)) throw std::invalid_argument("nonfinite SIMPLE inlet velocity");
    const ArrayView<const double> outputs[]={read(s.u),read(s.v),read(s.w),read(s.pressure),read(s.pressure_correction),
        read(s.d_u),read(s.d_v),read(s.d_w),read(s.density),read(s.inlet_velocity)};
    const ArrayView<const double> inputs[]={g.dx,g.dy,g.dz,m.epsilon,m.viscosity,m.effective_viscosity,m.permeability,
        m.forchheimer,m.temperature,b.outlet_u_fraction,b.outlet_w_fraction};
    for (std::size_t i=0;i<10;++i) {
        for (std::size_t j=0;j<i;++j) if (overlap(outputs[i],outputs[j])) throw std::invalid_argument("SIMPLE mutable arrays overlap");
        for (auto input:inputs) if (overlap(outputs[i],input)) throw std::invalid_argument("SIMPLE mutable state overlaps an input");
    }
}
void validate_open(const GridView& g,ArrayView<const unsigned char> open) {
    extent(open,g.nx*g.nz,"outlet_open");
    for (std::size_t i=0;i<open.size;++i) if (open[i]>1) throw std::invalid_argument("invalid SIMPLE outlet support");
}
void validate_order(bool sou,Simple3DOrdering order) {
    if ((order!=Simple3DOrdering::natural&&order!=Simple3DOrdering::red_black)||(sou&&order==Simple3DOrdering::red_black))
        throw std::invalid_argument("SOU requires natural ordering; unknown ordering is invalid");
}
using detail::sou_axis;
using detail::sou_bound;
// Keep the reference JIT's explicit operation ordering. A few ULPs in the
// converged velocity field can alter the coupled thermal stopping iteration.
// Both strip orientations use the same harmonic resistance, with the fused
// product on the corresponding side of the shared face.
double diffusion_conductance_left(double a,double b,double dl,double dr) {
    return a<=0. || b<=0.?0.:a*b/std::fma(dr,a,dl*b);
}
double diffusion_conductance_right(double a,double b,double dl,double dr) {
    return a<=0. || b<=0.?0.:a*b/std::fma(dl,b,dr*a);
}
struct Transport { double de,dw,dn,ds,dt,db,fe,fw,fn,fs,ft,fb; };
struct Equation { double diagonal,rhs,compensation,predictor_diagonal; };
struct Kernel {
    const GridView& g;const Simple3DMaterialView& m;const Simple3DBoundaryView& b;Simple3DStateView s;
    const int nx,ny,nz;const bool sou,use_eps;
    Kernel(const GridView& grid,const Simple3DMaterialView& material,const Simple3DBoundaryView& boundary,Simple3DStateView state,bool second)
        :g(grid),m(material),b(boundary),s(state),nx(static_cast<int>(g.nx)),ny(static_cast<int>(g.ny)),nz(static_cast<int>(g.nz)),sou(second),
         use_eps(*std::min_element(m.epsilon.data,m.epsilon.data+m.epsilon.size)!=*std::max_element(m.epsilon.data,m.epsilon.data+m.epsilon.size)) {}
    std::size_t c(int i,int j,int k) const { return (static_cast<std::size_t>(i)*g.ny+static_cast<std::size_t>(j))*g.nz+static_cast<std::size_t>(k); }
    std::size_t vi(int i,int j,int k) const { return (static_cast<std::size_t>(i)*(g.ny+1)+static_cast<std::size_t>(j))*g.nz+static_cast<std::size_t>(k); }
    std::size_t wi(int i,int j,int k) const { return (static_cast<std::size_t>(i)*g.ny+static_cast<std::size_t>(j))*(g.nz+1)+static_cast<std::size_t>(k); }
    double u(int i,int j,int k) const { return s.u[c(i,j,k)]; }
    double v(int i,int j,int k) const { return s.v[vi(i,j,k)]; }
    double w(int i,int j,int k) const { return s.w[wi(i,j,k)]; }
    double ep(int i,int j,int k) const { return m.epsilon[c(i,j,k)]; }
    double rho(int i,int j,int k) const { return s.density[c(i,j,k)]; }
    double ratio(int i,int j,int k,double ec) const { const auto e=ep(i,j,k);return !use_eps||e==ec?1.:e/ec; }
    double mu(int i,int j,int k,double ec) const { return m.effective_viscosity[c(i,j,k)]*ratio(i,j,k,ec); }
    double sx(int i,int j,int k,double ec) const {
        if(i==0||i==nx)return 0.;return std::fma(rho(i,j,k),ratio(i,j,k,ec),rho(i-1,j,k)*ratio(i-1,j,k,ec));
    }
    double sy(int i,int j,int k,double ec) const {
        const int lo=std::max(j-1,0),hi=std::min(j,ny-1);
        return std::fma(rho(i,hi,k),ratio(i,hi,k,ec),rho(i,lo,k)*ratio(i,lo,k,ec));
    }
    double sz(int i,int j,int k,double ec) const {
        if(k==0||k==nz)return 0.;return std::fma(rho(i,j,k),ratio(i,j,k,ec),rho(i,j,k-1)*ratio(i,j,k-1,ec));
    }
    double mx(int i,int j,int k,double ec) const {
        if (i==0||i==nx)return 0.;return (.5*u(i,j,k))*sx(i,j,k,ec);
    }
    double mz(int i,int j,int k,double ec) const {
        if (k==0||k==nz)return 0.;return (.5*w(i,j,k))*sz(i,j,k,ec);
    }
    Transport transport_u(int i,int j,int k) const {
        Transport t{};
        const double ec=use_eps?.5*(ep(i-1,j,k)+ep(i,j,k)):1.;
        const double wl=.5*g.dx[i-1],wr=.5*g.dx[i];
        t.de=mu(i,j,k,ec)*(g.dy[j]*g.dz[k])/g.dx[i];
        t.dw=mu(i-1,j,k,ec)*(g.dy[j]*g.dz[k])/g.dx[i-1];
        t.fe=((mx(i,j,k,ec)+mx(i+1,j,k,ec))*(.5*(g.dy[j]*g.dz[k])));
        t.fw=((mx(i,j,k,ec)+mx(i-1,j,k,ec))*(.5*(g.dy[j]*g.dz[k])));
        if (j>0) t.ds=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i,j-1,k,ec),.5*g.dy[j],.5*g.dy[j-1]),wl*diffusion_conductance_left(mu(i-1,j,k,ec),mu(i-1,j-1,k,ec),.5*g.dy[j],.5*g.dy[j-1]))*g.dz[k];
        else {
            t.ds=2.*(wl*mu(i-1,j,k,ec)+wr*mu(i,j,k,ec))*g.dz[k]/g.dy[j];
        }
        t.fs=(.5*std::fma(wr*v(i,j,k),sy(i,j,k,ec),(wl*v(i-1,j,k))*sy(i-1,j,k,ec)))*g.dz[k];
        if (j<ny-1) t.dn=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i,j+1,k,ec),.5*g.dy[j],.5*g.dy[j+1]),wl*diffusion_conductance_left(mu(i-1,j,k,ec),mu(i-1,j+1,k,ec),.5*g.dy[j],.5*g.dy[j+1]))*g.dz[k];
        else {
            const double boundary_n=2.*(wl*mu(i-1,j,k,ec)+wr*mu(i,j,k,ec))*g.dz[k];
            t.dn=std::fma(-b.outlet_u_fraction[static_cast<std::size_t>(i)*g.nz+static_cast<std::size_t>(k)],boundary_n,boundary_n)/g.dy[j];
        }
        t.fn=(.5*std::fma(wr*v(i,j+1,k),sy(i,j+1,k,ec),(wl*v(i-1,j+1,k))*sy(i-1,j+1,k,ec)))*g.dz[k];
        if (k>0) t.db=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i,j,k-1,ec),.5*g.dz[k],.5*g.dz[k-1]),wl*diffusion_conductance_left(mu(i-1,j,k,ec),mu(i-1,j,k-1,ec),.5*g.dz[k],.5*g.dz[k-1]))*g.dy[j];
        else {
            t.db=2.*(wl*mu(i-1,j,k,ec)+wr*mu(i,j,k,ec))*g.dy[j]/g.dz[k];
        }
        t.fb=std::fma(wr,mz(i,j,k,ec),((.5*wl)*w(i-1,j,k))*sz(i-1,j,k,ec))*g.dy[j];
        if (k<nz-1) t.dt=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i,j,k+1,ec),.5*g.dz[k],.5*g.dz[k+1]),wl*diffusion_conductance_left(mu(i-1,j,k,ec),mu(i-1,j,k+1,ec),.5*g.dz[k],.5*g.dz[k+1]))*g.dy[j];
        else {
            t.dt=2.*(wl*mu(i-1,j,k,ec)+wr*mu(i,j,k,ec))*g.dy[j]/g.dz[k];
        }
        t.ft=std::fma(wr,mz(i,j,k+1,ec),((.5*wl)*w(i-1,j,k+1))*sz(i-1,j,k+1,ec))*g.dy[j];
        return t;
    }
    Transport transport_v(int i,int j,int k) const {
        Transport t{};
        const double ec=use_eps?.5*(ep(i,j-1,k)+ep(i,j,k)):1.;
        const double wl=.5*g.dy[j-1],wr=.5*g.dy[j];
        if (i>0) t.dw=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i-1,j,k,ec),.5*g.dx[i],.5*g.dx[i-1]),wl*diffusion_conductance_left(mu(i,j-1,k,ec),mu(i-1,j-1,k,ec),.5*g.dx[i],.5*g.dx[i-1]))*g.dz[k];
        else {
            t.dw=2.*(wl*mu(i,j-1,k,ec)+wr*mu(i,j,k,ec))*g.dz[k]/g.dx[i];
        }
        t.fw=std::fma(wr,mx(i,j,k,ec),((.5*wl)*u(i,j-1,k))*sx(i,j-1,k,ec))*g.dz[k];
        if (i<nx-1) t.de=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i+1,j,k,ec),.5*g.dx[i],.5*g.dx[i+1]),wl*diffusion_conductance_left(mu(i,j-1,k,ec),mu(i+1,j-1,k,ec),.5*g.dx[i],.5*g.dx[i+1]))*g.dz[k];
        else {
            t.de=2.*(wl*mu(i,j-1,k,ec)+wr*mu(i,j,k,ec))*g.dz[k]/g.dx[i];
        }
        t.fe=std::fma(wr,mx(i+1,j,k,ec),((.5*wl)*u(i+1,j-1,k))*sx(i+1,j-1,k,ec))*g.dz[k];
        t.dn=mu(i,j,k,ec)*(g.dx[i]*g.dz[k])/g.dy[j];
        t.ds=mu(i,j-1,k,ec)*(g.dx[i]*g.dz[k])/g.dy[j-1];
        t.fn=(std::fma(v(i,j+1,k),sy(i,j+1,k,ec),v(i,j,k)*sy(i,j,k,ec))*(.25*(g.dx[i]*g.dz[k])));
        t.fs=(std::fma(v(i,j-1,k),sy(i,j-1,k,ec),v(i,j,k)*sy(i,j,k,ec))*(.25*(g.dx[i]*g.dz[k])));
        if (k>0) t.db=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i,j,k-1,ec),.5*g.dz[k],.5*g.dz[k-1]),wl*diffusion_conductance_left(mu(i,j-1,k,ec),mu(i,j-1,k-1,ec),.5*g.dz[k],.5*g.dz[k-1]))*g.dx[i];
        else {
            t.db=2.*(wl*mu(i,j-1,k,ec)+wr*mu(i,j,k,ec))*g.dx[i]/g.dz[k];
        }
        t.fb=std::fma(wr,mz(i,j,k,ec),((.5*wl)*w(i,j-1,k))*sz(i,j-1,k,ec))*g.dx[i];
        if (k<nz-1) t.dt=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i,j,k+1,ec),.5*g.dz[k],.5*g.dz[k+1]),wl*diffusion_conductance_left(mu(i,j-1,k,ec),mu(i,j-1,k+1,ec),.5*g.dz[k],.5*g.dz[k+1]))*g.dx[i];
        else {
            t.dt=2.*(wl*mu(i,j-1,k,ec)+wr*mu(i,j,k,ec))*g.dx[i]/g.dz[k];
        }
        t.ft=std::fma(wr,mz(i,j,k+1,ec),((.5*wl)*w(i,j-1,k+1))*sz(i,j-1,k+1,ec))*g.dx[i];
        return t;
    }
    Transport transport_w(int i,int j,int k) const {
        Transport t{};
        const double ec=use_eps?.5*(ep(i,j,k-1)+ep(i,j,k)):1.;
        const double wl=.5*g.dz[k-1],wr=.5*g.dz[k];
        if (i>0) t.dw=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i-1,j,k,ec),.5*g.dx[i],.5*g.dx[i-1]),wl*diffusion_conductance_left(mu(i,j,k-1,ec),mu(i-1,j,k-1,ec),.5*g.dx[i],.5*g.dx[i-1]))*g.dy[j];
        else {
            t.dw=2.*(wl*mu(i,j,k-1,ec)+wr*mu(i,j,k,ec))*g.dy[j]/g.dx[i];
        }
        t.fw=std::fma(wr,mx(i,j,k,ec),((.5*wl)*u(i,j,k-1))*sx(i,j,k-1,ec))*g.dy[j];
        if (i<nx-1) t.de=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i+1,j,k,ec),.5*g.dx[i],.5*g.dx[i+1]),wl*diffusion_conductance_left(mu(i,j,k-1,ec),mu(i+1,j,k-1,ec),.5*g.dx[i],.5*g.dx[i+1]))*g.dy[j];
        else {
            t.de=2.*(wl*mu(i,j,k-1,ec)+wr*mu(i,j,k,ec))*g.dy[j]/g.dx[i];
        }
        t.fe=std::fma(wr,mx(i+1,j,k,ec),((.5*wl)*u(i+1,j,k-1))*sx(i+1,j,k-1,ec))*g.dy[j];
        if (j>0) t.ds=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i,j-1,k,ec),.5*g.dy[j],.5*g.dy[j-1]),wl*diffusion_conductance_left(mu(i,j,k-1,ec),mu(i,j-1,k-1,ec),.5*g.dy[j],.5*g.dy[j-1]))*g.dx[i];
        else {
            t.ds=2.*(wl*mu(i,j,k-1,ec)+wr*mu(i,j,k,ec))*g.dx[i]/g.dy[j];
        }
        t.fs=(.5*std::fma(wr*v(i,j,k),sy(i,j,k,ec),(wl*v(i,j,k-1))*sy(i,j,k-1,ec)))*g.dx[i];
        if (j<ny-1) t.dn=std::fma(wr,diffusion_conductance_right(mu(i,j,k,ec),mu(i,j+1,k,ec),.5*g.dy[j],.5*g.dy[j+1]),wl*diffusion_conductance_left(mu(i,j,k-1,ec),mu(i,j+1,k-1,ec),.5*g.dy[j],.5*g.dy[j+1]))*g.dx[i];
        else {
            const double boundary_n=2.*(wl*mu(i,j,k-1,ec)+wr*mu(i,j,k,ec))*g.dx[i];
            t.dn=std::fma(-b.outlet_w_fraction[static_cast<std::size_t>(i)*(g.nz+1)+static_cast<std::size_t>(k)],boundary_n,boundary_n)/g.dy[j];
        }
        t.fn=(.5*std::fma(wr*v(i,j+1,k),sy(i,j+1,k,ec),(wl*v(i,j+1,k-1))*sy(i,j+1,k-1,ec)))*g.dx[i];
        t.dt=mu(i,j,k,ec)*(g.dx[i]*g.dy[j])/g.dz[k];
        t.db=mu(i,j,k-1,ec)*(g.dx[i]*g.dy[j])/g.dz[k-1];
        t.ft=((mz(i,j,k,ec)+mz(i,j,k+1,ec))*(.5*(g.dx[i]*g.dy[j])));
        t.fb=((mz(i,j,k,ec)+mz(i,j,k-1,ec))*(.5*(g.dx[i]*g.dy[j])));
        return t;
    }
    static double row_rhs(const Transport& t,double e,double w,double n,double south,double top,double bottom,double dp,double area) {
        double rhs=(t.de+std::max(-t.fe,0.))*e;
        rhs=std::fma(t.dw+std::max(t.fw,0.),w,rhs);
        rhs=std::fma(t.dn+std::max(-t.fn,0.),n,rhs);
        rhs=std::fma(t.ds+std::max(t.fs,0.),south,rhs);
        rhs=std::fma(t.dt+std::max(-t.ft,0.),top,rhs);
        rhs=std::fma(t.db+std::max(t.fb,0.),bottom,rhs);
        return std::fma(dp,area,rhs);
    }
    static double row_rhs_v(const Transport& t,double e,double w,double n,double south,double top,double bottom,double dp,double area) {
        double rhs=(t.dn+std::max(-t.fn,0.))*n;
        rhs=std::fma(t.ds+std::max(t.fs,0.),south,rhs);
        rhs=std::fma(t.de+std::max(-t.fe,0.),e,rhs);
        rhs=std::fma(t.dw+std::max(t.fw,0.),w,rhs);
        rhs=std::fma(t.dt+std::max(-t.ft,0.),top,rhs);
        rhs=std::fma(t.db+std::max(t.fb,0.),bottom,rhs);
        return std::fma(dp,area,rhs);
    }
    Equation equation_u(int i,int j,int k,bool predictor) const {
        const auto t=transport_u(i,j,k);
        const double va=.25*((v(i-1,j,k)+v(i,j,k))+(v(i-1,j+1,k)+v(i,j+1,k)));
        const double wa=.25*((w(i-1,j,k)+w(i,j,k))+(w(i-1,j,k+1)+w(i,j,k+1)));
        const double speed=std::sqrt(std::fma(wa,wa,std::fma(u(i,j,k),u(i,j,k),va*va)));
        const double rl=.5*(rho(i-1,j,k)+rho(i,j,k)), ml=.5*(m.viscosity[c(i-1,j,k)]+m.viscosity[c(i,j,k)]);
        const double permeability=.5*(m.permeability[c(i-1,j,k)]+m.permeability[c(i,j,k)]), cf=.5*(m.forchheimer[c(i-1,j,k)]+m.forchheimer[c(i,j,k)]);
        const double volume=(.5*(g.dx[i-1]+g.dx[i]))*g.dy[j]*g.dz[k];
        const double drag=(speed<1e-10?ml/permeability:std::fma(rl*cf,speed,ml/permeability))*volume;
        const double base=((((((std::max(t.fe,0.)+t.de)+(t.dw+std::max(-t.fw,0.)))+std::max(t.fn,0.))+t.ds)+std::max(-t.fs,0.))+t.dn)+(((t.dt+std::max(t.ft,0.))+t.db)+std::max(-t.fb,0.));
        Equation e{base+drag,row_rhs(t,i+1<nx?u(i+1,j,k):0.,u(i-1,j,k),j<ny-1?u(i,j+1,k):0.,j>0?u(i,j-1,k):0.,k<nz-1?u(i,j,k+1):0.,k>0?u(i,j,k-1):0.,s.pressure[c(i-1,j,k)]-s.pressure[c(i,j,k)],g.dy[j]*g.dz[k]),0.,0.};
        if (sou) {
            e.rhs+=sou_axis(u(std::max(i-2,0),j,k),u(std::max(i-1,0),j,k),u(i,j,k),u(std::min(i+1,nx),j,k),u(std::min(i+2,nx),j,k),
                i>2,i>1 && i+1<nx,i+2<=nx,i>1,t.fw,t.fe,g.dx,i,true)
                +sou_axis(u(i,std::max(j-2,0),k),u(i,std::max(j-1,0),k),u(i,j,k),u(i,std::min(j+1,ny-1),k),u(i,std::min(j+2,ny-1),k),
                j>1,j>0 && j<ny-1,j<ny-2,j>0 && j<ny-1,t.fs,t.fn,g.dy,j,false)
                +sou_axis(u(i,j,std::max(k-2,0)),u(i,j,std::max(k-1,0)),u(i,j,k),u(i,j,std::min(k+1,nz-1)),u(i,j,std::min(k+2,nz-1)),
                k>1,k>0 && k<nz-1,k<nz-2,k>0 && k<nz-1,t.fb,t.ft,g.dz,k,false);
        }
        if (predictor) {
            e.compensation=std::max(((t.fw+t.fs)-((t.fe+t.fn)+t.ft))+t.fb,0.);
            if (sou) e.compensation+=sou_bound(u(std::max(i-1,0),j,k),u(i,j,k),u(std::min(i+1,nx),j,k),
                i>1,i>1 && i+1<nx,t.fw,t.fe,g.dx,i,true)
                +sou_bound(u(i,std::max(j-1,0),k),u(i,j,k),u(i,std::min(j+1,ny-1),k),
                j>0 && j<ny-1,j>0 && j<ny-1,t.fs,t.fn,g.dy,j,false)
                +sou_bound(u(i,j,std::max(k-1,0)),u(i,j,k),u(i,j,std::min(k+1,nz-1)),
                k>0 && k<nz-1,k>0 && k<nz-1,t.fb,t.ft,g.dz,k,false);
        }
        e.predictor_diagonal=(base+e.compensation)+drag;
        return e;
    }
    Equation equation_v(int i,int j,int k,bool predictor) const {
        const auto t=transport_v(i,j,k);
        const double ua=.25*((u(i,j-1,k)+u(i+1,j-1,k))+(u(i,j,k)+u(i+1,j,k)));
        const double wa=.25*((w(i,j-1,k)+w(i,j,k))+(w(i,j-1,k+1)+w(i,j,k+1)));
        const double speed=std::sqrt(std::fma(wa,wa,std::fma(v(i,j,k),v(i,j,k),ua*ua)));
        const double rl=.5*(rho(i,j-1,k)+rho(i,j,k)), ml=.5*(m.viscosity[c(i,j-1,k)]+m.viscosity[c(i,j,k)]);
        const double permeability=m.permeability[c(i,j,k)], cf=m.forchheimer[c(i,j,k)];
        const double volume=g.dx[i]*(.5*(g.dy[j-1]+g.dy[j]))*g.dz[k];
        const double drag=(speed<1e-10?ml/permeability:std::fma(rl*cf,speed,ml/permeability))*volume;
        const double base=(((std::max(t.fe,0.)+t.de)+(t.dw+std::max(-t.fw,0.)))+std::max(t.ft,0.)+std::max(-t.fb,0.))+((((t.dn+std::max(t.fn,0.))+t.ds)+std::max(-t.fs,0.))+t.dt+t.db);
        Equation e{base+drag,row_rhs_v(t,i<nx-1?v(i+1,j,k):0.,i>0?v(i-1,j,k):0.,v(i,j+1,k),v(i,j-1,k),k<nz-1?v(i,j,k+1):0.,k>0?v(i,j,k-1):0.,s.pressure[c(i,j-1,k)]-s.pressure[c(i,j,k)],g.dx[i]*g.dz[k]),0.,0.};
        if (sou) {
            e.rhs+=sou_axis(v(std::max(i-2,0),j,k),v(std::max(i-1,0),j,k),v(i,j,k),v(std::min(i+1,nx-1),j,k),v(std::min(i+2,nx-1),j,k),
                i>1,i>0 && i<nx-1,i<nx-2,i>0 && i<nx-1,t.fw,t.fe,g.dx,i,false)
                +sou_axis(v(i,std::max(j-2,0),k),v(i,std::max(j-1,0),k),v(i,j,k),v(i,std::min(j+1,ny),k),v(i,std::min(j+2,ny),k),
                j>2,j>1,j+2<=ny,j>1,t.fs,t.fn,g.dy,j,true)
                +sou_axis(v(i,j,std::max(k-2,0)),v(i,j,std::max(k-1,0)),v(i,j,k),v(i,j,std::min(k+1,nz-1)),v(i,j,std::min(k+2,nz-1)),
                k>1,k>0 && k<nz-1,k<nz-2,k>0 && k<nz-1,t.fb,t.ft,g.dz,k,false);
        }
        if (predictor) {
            e.compensation=std::max(((t.fw+t.fs)-((t.fe+t.fn)+t.ft))+t.fb,0.);
            if (sou) e.compensation+=sou_bound(v(std::max(i-1,0),j,k),v(i,j,k),v(std::min(i+1,nx-1),j,k),
                i>0 && i<nx-1,i>0 && i<nx-1,t.fw,t.fe,g.dx,i,false)
                +sou_bound(v(i,std::max(j-1,0),k),v(i,j,k),v(i,std::min(j+1,ny),k),
                j>1,j>1,t.fs,t.fn,g.dy,j,true)
                +sou_bound(v(i,j,std::max(k-1,0)),v(i,j,k),v(i,j,std::min(k+1,nz-1)),
                k>0 && k<nz-1,k>0 && k<nz-1,t.fb,t.ft,g.dz,k,false);
        }
        e.predictor_diagonal=base+(drag+e.compensation);
        return e;
    }
    Equation equation_w(int i,int j,int k,bool predictor) const {
        const auto t=transport_w(i,j,k);
        const double ua=.25*((u(i,j,k-1)+u(i+1,j,k-1))+(u(i,j,k)+u(i+1,j,k)));
        const double va=.25*((v(i,j,k-1)+v(i,j+1,k-1))+(v(i,j,k)+v(i,j+1,k)));
        const double speed=std::sqrt(std::fma(va,va,std::fma(w(i,j,k),w(i,j,k),ua*ua)));
        const double rl=.5*(rho(i,j,k-1)+rho(i,j,k)), ml=.5*(m.viscosity[c(i,j,k-1)]+m.viscosity[c(i,j,k)]);
        const double permeability=m.permeability[c(i,j,k)], cf=m.forchheimer[c(i,j,k)];
        const double volume=g.dx[i]*g.dy[j]*(.5*(g.dz[k-1]+g.dz[k]));
        const double drag=(speed<1e-10?ml/permeability:std::fma(rl*cf,speed,ml/permeability))*volume;
        const double base=((((std::max(t.fe,0.)+t.de)+(t.dw+std::max(-t.fw,0.)))+t.dn)+(((std::max(t.fn,0.)+t.ds)+std::max(-t.fs,0.))+t.dt))+((std::max(t.ft,0.)+t.db)+std::max(-t.fb,0.));
        Equation e{base+drag,row_rhs(t,i<nx-1?w(i+1,j,k):0.,i>0?w(i-1,j,k):0.,j<ny-1?w(i,j+1,k):0.,j>0?w(i,j-1,k):0.,w(i,j,k+1),w(i,j,k-1),s.pressure[c(i,j,k-1)]-s.pressure[c(i,j,k)],g.dx[i]*g.dy[j]),0.,0.};
        if (sou) {
            e.rhs+=sou_axis(w(std::max(i-2,0),j,k),w(std::max(i-1,0),j,k),w(i,j,k),w(std::min(i+1,nx-1),j,k),w(std::min(i+2,nx-1),j,k),
                i>1,i>0 && i<nx-1,i<nx-2,i>0 && i<nx-1,t.fw,t.fe,g.dx,i,false)
                +sou_axis(w(i,std::max(j-2,0),k),w(i,std::max(j-1,0),k),w(i,j,k),w(i,std::min(j+1,ny-1),k),w(i,std::min(j+2,ny-1),k),
                j>1,j>0 && j<ny-1,j<ny-2,j>0 && j<ny-1,t.fs,t.fn,g.dy,j,false)
                +sou_axis(w(i,j,std::max(k-2,0)),w(i,j,std::max(k-1,0)),w(i,j,k),w(i,j,std::min(k+1,nz)),w(i,j,std::min(k+2,nz)),
                k>2,k>1,k+2<=nz,k>1,t.fb,t.ft,g.dz,k,true);
        }
        if (predictor) {
            e.compensation=std::max(((t.fw+t.fs)-((t.fe+t.fn)+t.ft))+t.fb,0.);
            if (sou) e.compensation+=sou_bound(w(std::max(i-1,0),j,k),w(i,j,k),w(std::min(i+1,nx-1),j,k),
                i>0 && i<nx-1,i>0 && i<nx-1,t.fw,t.fe,g.dx,i,false)
                +sou_bound(w(i,std::max(j-1,0),k),w(i,j,k),w(i,std::min(j+1,ny-1),k),
                j>0 && j<ny-1,j>0 && j<ny-1,t.fs,t.fn,g.dy,j,false)
                +sou_bound(w(i,j,std::max(k-1,0)),w(i,j,k),w(i,j,std::min(k+1,nz)),
                k>1,k>1,t.fb,t.ft,g.dz,k,true);
        }
        e.predictor_diagonal=base+(drag+e.compensation);
        return e;
    }
    static void update(const Equation& e,double area,double alpha,double& velocity,double& d) {
        const double ap=e.predictor_diagonal;
        double rhs=std::fma(e.compensation,velocity,e.rhs);
        rhs=std::fma(ap,(velocity*(1.-alpha))*(1./alpha),rhs);
        velocity=rhs/(ap*(1./alpha));d=area/ap;
    }
    void predict(ArrayView<const unsigned char> open,double alpha,std::size_t sweeps,Simple3DOrdering order) const {
        const int colors=order==Simple3DOrdering::red_black?2:1;
        for (std::size_t sweep=0;sweep<sweeps;++sweep) for (int color=0;color<colors;++color)
            for (int i=1;i<nx;++i) for (int j=0;j<ny;++j) for (int k=0;k<nz;++k) {
                if (colors==2&&(i+j+k)%2!=color) continue;
                update(equation_u(i,j,k,true),g.dy[j]*g.dz[k],alpha,s.u[c(i,j,k)],s.d_u[c(i,j,k)]);
            }
        for (int j=0;j<ny;++j) for (int k=0;k<nz;++k) { s.u[c(0,j,k)]=0.;s.u[c(nx,j,k)]=0.; }
        for (std::size_t sweep=0;sweep<sweeps;++sweep) for (int color=0;color<colors;++color)
            for (int i=0;i<nx;++i) for (int j=1;j<ny;++j) for (int k=0;k<nz;++k) {
                if (colors==2&&(i+j+k)%2!=color) continue;
                update(equation_v(i,j,k,true),g.dx[i]*g.dz[k],alpha,s.v[vi(i,j,k)],s.d_v[vi(i,j,k)]);
            }
        // Python applies this boundary between the v and w sweeps.
        if (!finite(s.u)||!finite(s.v)||!finite(s.d_u)||!finite(s.d_v)) throw std::domain_error("nonfinite SIMPLE momentum arithmetic");
        apply_simple_y_boundary(3,g,{read(s.inlet_velocity),{},open},mutable_velocities(s),read(s.density),m.epsilon);
        for (std::size_t sweep=0;sweep<sweeps;++sweep) for (int color=0;color<colors;++color)
            for (int i=0;i<nx;++i) for (int j=0;j<ny;++j) for (int k=1;k<nz;++k) {
                if (colors==2&&(i+j+k)%2!=color) continue;
                update(equation_w(i,j,k,true),g.dx[i]*g.dy[j],alpha,s.w[wi(i,j,k)],s.d_w[wi(i,j,k)]);
            }
        for (int i=0;i<nx;++i) for (int j=0;j<ny;++j) { s.w[wi(i,j,0)]=0.;s.w[wi(i,j,nz)]=0.; }
        if (!finite(s.w)||!finite(s.d_w)) throw std::domain_error("nonfinite SIMPLE momentum arithmetic");
    }
    SimpleMomentumResidual residual() const {
        SimpleMomentumResidual r;
        const auto accumulate=[&](int axis,const Equation& e,double velocity) {
            const double lhs=e.diagonal*velocity;
            r.numerator[axis]+=std::abs(lhs-e.rhs);r.denominator[axis]+=.5*(std::abs(lhs)+std::abs(e.rhs));
        };
        for (int i=1;i<nx;++i) for (int j=0;j<ny;++j) for (int k=0;k<nz;++k) accumulate(0,equation_u(i,j,k,false),u(i,j,k));
        for (int i=0;i<nx;++i) for (int j=1;j<ny;++j) for (int k=0;k<nz;++k) accumulate(1,equation_v(i,j,k,false),v(i,j,k));
        for (int i=0;i<nx;++i) for (int j=0;j<ny;++j) for (int k=1;k<nz;++k) accumulate(2,equation_w(i,j,k,false),w(i,j,k));
        normalize_simple_momentum(r,3);return r;
    }
};
void nonfinite_result(Simple3DResult& r) {
    r.stop=SimpleStop::nonfinite;r.converged=false;r.post_closure_certified=false;
    r.legacy_residual=std::numeric_limits<double>::quiet_NaN();
    for (auto* v:{&r.momentum.maximum,&r.mass.local_residual,&r.mass.global_residual,&r.mass.backflow_fraction})
        if (std::isfinite(*v)) *v=std::numeric_limits<double>::quiet_NaN();
}
bool diagnostics_finite(const Simple3DResult& r) {
    return std::isfinite(r.momentum.maximum)&&std::isfinite(r.mass.local_residual)
        &&std::isfinite(r.mass.global_residual)&&std::isfinite(r.mass.backflow_fraction);
}
}

void simple_3d_predictor(const GridView& g,ArrayView<const unsigned char> open,const Simple3DMaterialView& m,
    const Simple3DBoundaryView& b,Simple3DStateView s,double alpha,std::size_t sweeps,bool sou,Simple3DOrdering order) {
    validate(g,m,b,s);validate_open(g,open);validate_order(sou,order);
    if (!std::isfinite(alpha)||alpha<=0.||alpha>1.) throw std::invalid_argument("invalid SIMPLE velocity relaxation");
    if (!state_finite(m,s)) throw std::invalid_argument("nonfinite SIMPLE predictor input");
    positive(read(s.density),"density");positive(m.temperature,"temperature");
    Kernel(g,m,b,s,sou).predict(open,alpha,sweeps,order);
}
SimpleMomentumResidual simple_3d_momentum_residual(const GridView& g,const Simple3DMaterialView& m,
    const Simple3DBoundaryView& b,Simple3DStateView s,bool sou) {
    validate(g,m,b,s);return Kernel(g,m,b,s,sou).residual();
}

struct Simple3DSolver::Impl {
    std::vector<double> dx,dy,dz,old_rho_eps,fresh_rho_eps,target;
    std::vector<unsigned char> outlet,all_cells;
    GridView grid;SimplePressureAssembly assembly;PressureCandidate pressure;SimpleHistory history;
    std::size_t pressure_clip_hits=0,charged_iterations=0;
    Impl(const GridView& g,ArrayView<const unsigned char> open)
        :dx(g.dx.data,g.dx.data+g.dx.size),dy(g.dy.data,g.dy.data+g.dy.size),dz(g.dz.data,g.dz.data+g.dz.size),
         old_rho_eps(g.nx*g.ny*g.nz),fresh_rho_eps(old_rho_eps.size()),outlet(open.data,open.data+open.size),all_cells(old_rho_eps.size(),0),
         grid{g.nx,g.ny,g.nz,{dx.data(),dx.size()},{dy.data(),dy.size()},{dz.data(),dz.size()}},assembly(3,grid,{outlet.data(),outlet.size()}) {}
    ArrayView<const unsigned char> opening() const { return {outlet.data(),outlet.size()}; }
    ArrayView<const unsigned char> excluded(bool final) const {
        const auto& v=final?all_cells:assembly.cell_kind();return {v.data(),v.size()};
    }
    void rho_eps(std::vector<double>& out,const Simple3DMaterialView& m,Simple3DStateView s) const {
        for (std::size_t n=0;n<out.size();++n) out[n]=s.density[n]*m.epsilon[n];
    }
    void inlet(Simple3DStateView s) const {
        for (std::size_t i=0;i<grid.nx;++i) for (std::size_t k=0;k<grid.nz;++k)
            s.inlet_velocity[i*grid.nz+k]=target[i*grid.nz+k]/std::max(s.density[i*grid.ny*grid.nz+k],1e-9);
    }
    void density(const Simple3DMaterialView& m,Simple3DStateView s,const Simple3DControl& control) {
        for (std::size_t n=0;n<s.pressure.size;++n) {
            double absolute=s.pressure[n]+control.pressure_reference_absolute;
            const bool clipped=absolute<1e3||absolute>10e6;absolute=std::clamp(absolute,1e3,10e6);
            if (clipped) { ++pressure_clip_hits;s.pressure[n]=absolute-control.pressure_reference_absolute; }
            const double density=absolute/(control.gas_constant*m.temperature[n]);
            s.density[n]=control.alpha_density*density+(1.-control.alpha_density)*s.density[n];
        }
        if (control.massflux_inlet) inlet(s);
    }
};
Simple3DSolver::Simple3DSolver(const GridView& g,ArrayView<const unsigned char> open) {
    validate_grid(g);validate_open(g,open);impl_=std::make_unique<Impl>(g,open);
}
Simple3DSolver::~Simple3DSolver()=default;
const SimpleHistory& Simple3DSolver::history() const { return impl_->history; }
const std::vector<double>& Simple3DSolver::massflux_target() const { return impl_->target; }
void Simple3DSolver::capture_massflux_target(ArrayView<const double> target) {
    if (!impl_->target.empty() || !impl_->history.legacy.empty())
        throw std::invalid_argument("SIMPLE inlet target was already captured or solved");
    if (!target.data || target.size!=impl_->grid.nx*impl_->grid.nz)
        throw std::invalid_argument("SIMPLE inlet target extent mismatch");
    for (std::size_t p=0;p<target.size;++p)
        if (!std::isfinite(target[p])) throw std::invalid_argument("nonfinite SIMPLE inlet target");
    impl_->target.assign(target.data,target.data+target.size);
}
bool Simple3DSolver::refresh_after_seed(const Simple3DMaterialView& m,const Simple3DBoundaryView& b,
    Simple3DStateView s,const Simple3DControl& control) {
    auto& impl=*impl_;const auto& g=impl.grid;validate(g,m,b,s);
    if (!std::isfinite(control.alpha_density) || control.alpha_density<=0. || control.alpha_density>1.
        || !std::isfinite(control.pressure_reference_absolute) || control.pressure_reference_absolute<=0.
        || !std::isfinite(control.gas_constant) || control.gas_constant<=0.)
        throw std::invalid_argument("invalid SIMPLE seed density controls");
    if (control.ideal_gas && control.massflux_inlet && impl.target.empty())
        throw std::invalid_argument("capture original inlet target before bootstrap density refresh");
    if (!state_finite(m,s)) return false;
    if (control.ideal_gas) impl.density(m,s,control);
    if (!state_finite(m,s)) return false;
    const SimpleBoundaryView boundary{read(s.inlet_velocity),{},impl.opening()};
    apply_simple_y_boundary(3,g,boundary,mutable_velocities(s),read(s.density),m.epsilon);
    return state_finite(m,s);
}
Simple3DResult Simple3DSolver::solve(const Simple3DMaterialView& m,const Simple3DBoundaryView& b,
    Simple3DStateView s,const Simple3DControl& control) {
    auto& impl=*impl_;impl.charged_iterations=0;
    const auto& g=impl.grid;validate(g,m,b,s);validate_order(control.second_order_upwind,control.ordering);
    if (!control.max_iterations||!control.inner_sweeps||!control.pressure_rebuild_every)
        throw std::invalid_argument("SIMPLE iteration and pressure rebuild budgets must be positive");
    for (double alpha:{control.alpha_velocity,control.alpha_pressure,control.alpha_density})
        if (!std::isfinite(alpha)||alpha<=0.||alpha>1.) throw std::invalid_argument("invalid SIMPLE relaxation");
    if (!std::isfinite(control.pressure_reference_absolute)||control.pressure_reference_absolute<=0.
        ||!std::isfinite(control.gas_constant)||control.gas_constant<=0.
        ||!std::isfinite(control.pressure_diagonal_drift)||control.pressure_diagonal_drift<0.)
        throw std::invalid_argument("invalid SIMPLE pressure/density controls");
    SimpleF2Monitor monitor(velocities(s),control.convergence,10);Simple3DResult result;
    result.pressure_clip_hits=impl.pressure_clip_hits;
    if (!state_finite(m,s)) { nonfinite_result(result);return result; }
    positive(read(s.density),"density");positive(m.temperature,"temperature");
    if (control.cancel&&control.cancel(control.context)) { result.stop=SimpleStop::cancelled;return result; }
    if (control.ideal_gas&&control.massflux_inlet&&impl.target.empty()) {
        impl.target.resize(g.nx*g.nz);
        for (std::size_t i=0;i<g.nx;++i) for (std::size_t k=0;k<g.nz;++k)
            impl.target[i*g.nz+k]=s.inlet_velocity[i*g.nz+k]*s.density[i*g.ny*g.nz+k];
    }
    Kernel kernel(g,m,b,s,control.second_order_upwind);
    const SimpleBoundaryView boundary{read(s.inlet_velocity),{},impl.opening()};
    const auto audit=[&](bool final) {
        impl.rho_eps(impl.fresh_rho_eps,m,s);
        return simple_mass_audit(3,g,velocities(s),{impl.fresh_rho_eps.data(),impl.fresh_rho_eps.size()},impl.excluded(final));
    };
    const auto finish=[&](SimpleStop reason) {
        try { apply_simple_y_boundary(3,g,boundary,mutable_velocities(s),read(s.density),m.epsilon); }
        catch (const std::domain_error&) { nonfinite_result(result);return; }
        if (!state_finite(m,s)) { nonfinite_result(result);return; }
        result.mass=audit(true);result.momentum=kernel.residual();result.post_closure_measured=true;
        if (!diagnostics_finite(result)) { nonfinite_result(result);return; }
        result.post_closure_certified=monitor.gates_hold(result.momentum.maximum,result.mass);
        result.stop=reason==SimpleStop::tol&&!result.post_closure_certified?SimpleStop::post_closure:reason;
        result.converged=result.stop==SimpleStop::tol;
        if (result.stop==SimpleStop::post_closure) ++result.post_closure_rejections;
    };
    for (std::size_t it=1;it<=control.max_iterations;++it) {
        if (control.cancel&&control.cancel(control.context)) { result.stop=SimpleStop::cancelled;result.converged=false;return result; }
        result.iterations=it;impl.charged_iterations=it;impl.rho_eps(impl.old_rho_eps,m,s);
        try { kernel.predict(impl.opening(),control.alpha_velocity,control.inner_sweeps,control.ordering); }
        catch (const std::domain_error&) { nonfinite_result(result);return result; }
        if (!state_finite(m,s)) { nonfinite_result(result);return result; }
        const PressureSystem* system;
        try { system=&impl.assembly.assemble(g,velocities(s),corrections(s),{impl.old_rho_eps.data(),impl.old_rho_eps.size()}); }
        catch (const std::domain_error&) { nonfinite_result(result);return result; }
        PressureControl linear;linear.dimension=3;
        linear.relative_tolerance=control.adaptive_pressure_tolerance
            ?std::clamp(.05*(impl.history.legacy.empty()?1.:impl.history.legacy.back()),1e-7,1e-3):1e-5;
        linear.force_rebuild=it%control.pressure_rebuild_every==0;
        linear.diagonal_drift_threshold=control.pressure_diagonal_drift;
        result.linear=impl.pressure.solve(*system,linear);
        if (!result.linear.success) { result.stop=SimpleStop::pressure_failure;return result; }
        std::copy(result.linear.x.begin(),result.linear.x.end(),s.pressure_correction.data);result.linear.x.clear();
        try { correct_simple_pressure(3,g,boundary,s.pressure,read(s.pressure_correction),mutable_velocities(s),
            corrections(s),read(s.density),m.epsilon,control.alpha_pressure); }
        catch (const std::domain_error&) { nonfinite_result(result);return result; }
        if (control.ideal_gas) {
            if (!state_finite(m,s)) { nonfinite_result(result);return result; }
            impl.density(m,s,control);
        }
        result.pressure_clip_hits=impl.pressure_clip_hits;
        if (!state_finite(m,s)) { nonfinite_result(result);return result; }
        const auto legacy=simple_legacy_mass_residual(3,g,velocities(s),{impl.old_rho_eps.data(),impl.old_rho_eps.size()});
        result.legacy_residual=legacy.residual;result.legacy_reference=legacy.reference;
        impl.history.legacy.push_back(result.legacy_residual);
        if (control.progress&&(it==1||it%50==0)) control.progress(control.context,it,result.legacy_residual);
        const double delta=monitor.velocity_delta(velocities(s));
        const bool eval=monitor.should_evaluate_momentum(it,delta)||control.track_momentum;
        if (eval) { result.momentum=kernel.residual();if (control.track_momentum) impl.history.momentum.push_back({it,result.momentum}); }
        result.mass=audit(false);impl.history.local_mass.push_back(result.mass.local_residual);impl.history.global_mass.push_back(result.mass.global_residual);
        if (!std::isfinite(result.legacy_residual)||!std::isfinite(delta)||!std::isfinite(result.mass.local_residual)
            ||!std::isfinite(result.mass.global_residual)||!std::isfinite(result.mass.backflow_fraction)) { nonfinite_result(result);return result; }
        if (eval) {
            const auto reason=monitor.submit(it,result.momentum.maximum,result.mass,delta);
            if (reason==SimpleStop::nonfinite) { nonfinite_result(result);return result; }
            if (reason!=SimpleStop::ongoing) {
                finish(reason);
                if (result.stop!=SimpleStop::post_closure||it==control.max_iterations) return result;
                monitor.reset_confirmation();
            }
        }
    }
    finish(SimpleStop::max_iterations);return result;
}
std::size_t Simple3DSolver::charged_iterations() const {return impl_->charged_iterations;}
}  // namespace tpmshx
